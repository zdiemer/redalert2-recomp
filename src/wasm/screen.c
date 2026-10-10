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
    hle_screen_title(title);
    fprintf(stderr, "[screen] browser Canvas2D\n");
    return 0;
}

void hle_screen_pump(void) {
    int32_t events[256 * 4];
    int count = MAIN_THREAD_EM_ASM_INT({
        const queue = Module.ra2Input || [];
        const count = Math.min(queue.length, 256);
        for (let i = 0; i < count; i++) HEAP32.set(queue[i], ($0 >> 2) + i*4);
        queue.splice(0, count);
        return count;
    }, events);
    for (int i = 0; i < count; i++) {
        int32_t *e = events + 4*i;
        if (e[0] == 1) hle_input_key(e[1], (uint32_t)e[2], (uint32_t)e[3]);
        else hle_input_mouse((uint32_t)e[1], e[2], e[3]);
    }
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
            canvas.width = w; canvas.height = h; canvas.style.aspectRatio = w + '/' + h;
        }
        canvas.style.cursor = $6 ? 'default' : 'none';
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
    }, px, w, h, pitch, bpp, palette, cursor);
}
