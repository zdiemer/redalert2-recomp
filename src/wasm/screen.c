/* DirectDraw presentation and input on the browser's Canvas2D. All guest
 * and HLE state stays on the machine thread; DOM operations are proxied. */
#include <emscripten.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "win32hle.h"

int (*hle_screen_key_hook)(int, int);
int (*hle_screen_cursor_hook)(void);
void (*hle_screen_frame_hook)(const uint8_t *, int, int, int, int);
int (*hle_screen_compose_hook)(const uint8_t *, int, int, int, uint32_t *);
void (*hle_screen_settings_hook)(const char *, int, int);
static int g_headless;
static uint32_t g_next;

static void warp(int x, int y) {
    MAIN_THREAD_EM_ASM({
        Module.ra2Cursor.x = $0; Module.ra2Cursor.y = $1;
        Module.ra2DrawCursor();
    }, x, y);
}

int hle_screen_scale(const char *name) {
    int smooth = !strcmp(name, "smooth");
    MAIN_THREAD_EM_ASM({ Module.canvas.style.imageRendering = $0 ? 'auto' : 'pixelated'; }, smooth);
    return 1;
}
void hle_screen_bars(int blur) { (void)blur; }
void hle_screen_title(const char *title) {
    MAIN_THREAD_EM_ASM({ document.title = UTF8ToString($0); }, title);
}
int hle_screen_open(const char *title, int fullscreen, int headless) {
    (void)fullscreen;
    g_headless = headless;
    hle_cursor_hook = warp;
    hle_screen_title(title);
    fprintf(stderr, "[screen] browser Canvas2D\n");
    return 0;
}

static void pump_input(void) {
    static int32_t events[1024 * 4];
    static int pending;
    static uint32_t pressed_at[3];
    static int pressed[3], left_reads;
    int count = MAIN_THREAD_EM_ASM_INT({
        const queue = Module.ra2Input || [];
        const count = Math.min(queue.length, $1);
        for (let i = 0; i < count; i++) HEAP32.set(queue[i], ($0 >> 2) + i*4);
        queue.splice(0, count);
        return count;
    }, events + 4*pending, 1024-pending);
    pending += count;
    int consumed = 0;
    for (int i = 0; i < pending; i++) {
        int32_t *e = events + 4*i;
        if (e[0] == 1) hle_input_key(e[1], (uint32_t)e[2], (uint32_t)e[3]);
        else {
            int button = (e[1]-0x201)/3;
            int down = e[1] == 0x201 || e[1] == 0x204 || e[1] == 0x207;
            int up = e[1] == 0x202 || e[1] == 0x205 || e[1] == 0x208;
            uint32_t now = hle_ticks_ms();
            /* RA2 samples button state on its mouse worker. A quick DOM
             * click can arrive entirely between two samples; retain down
             * until the worker has had time to observe it. */
            if (up && pressed[button]) {
                uint32_t age = now-pressed_at[button];
                if (age < 100 || (button == 0 && hle_lbutton_reads-left_reads < 2 && age < 500)) break;
                pressed[button] = 0;
            }
            if (down) {
                pressed[button] = 1; pressed_at[button] = now;
                if (button == 0) left_reads = hle_lbutton_reads;
            }
            hle_input_mouse((uint32_t)e[1], e[2], e[3]);
        }
        consumed++;
    }
    pending -= consumed;
    memmove(events, events + 4*consumed, (size_t)pending * 4 * sizeof *events);
}

void hle_screen_pump(void) {
    pump_input();
    uint32_t now = hle_ticks_ms();
    if (g_headless || (int32_t)(now - g_next) < 0) return;
    g_next = now + 33;
    const uint8_t *px;
    const uint32_t *palette;
    int w, h, pitch, bpp;
    if (!hle_dd_frame(&px, &w, &h, &pitch, &bpp, &palette, NULL)) return;
    if (hle_screen_frame_hook) hle_screen_frame_hook(px, w, h, pitch, bpp);
    int cursor = !hle_screen_cursor_hook || hle_screen_cursor_hook();
    MAIN_THREAD_EM_ASM({
        const canvas = Module.canvas; const w = $1; const h = $2;
        if (canvas.width !== w || canvas.height !== h) {
            canvas.width = w; canvas.height = h;
            Module.ra2Resize();
        }
        canvas.style.cursor = $6 ? 'default' : 'none';
        Module.ra2SystemCursor = $6;
        Module.ra2DrawCursor();
        const ctx = Module.ra2Context || (Module.ra2Context = canvas.getContext('2d', {alpha:false}));
        let frame = Module.ra2Frame;
        if (!frame || frame.width !== w || frame.height !== h) frame = Module.ra2Frame = ctx.createImageData(w, h);
        const out = frame.data; const source = $0; const pitch = $3; const bpp = $4;
        for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
            let r; let g; let b;
            const offset = source + y*pitch + x*(bpp >> 3);
            if (bpp === 16) {
                const p = HEAPU16[offset >> 1];
                r = (p >> 11) * 255/31; g = (p >> 5 & 63) * 255/63; b = (p & 31) * 255/31;
            } else {
                const p = bpp === 8 ? HEAPU32[($5 >> 2) + HEAPU8[offset]] : HEAPU32[offset >> 2];
                r = p >> 16 & 255; g = p >> 8 & 255; b = p & 255;
            }
            const at = (y*w + x)*4;
            out[at] = r; out[at+1] = g; out[at+2] = b; out[at+3] = 255;
        }
        ctx.putImageData(frame, 0, 0);
        document.querySelector('#status').textContent = 'Game running';
        document.querySelector('#status').hidden = true;
    }, px, w, h, pitch, bpp, palette, cursor);
}
