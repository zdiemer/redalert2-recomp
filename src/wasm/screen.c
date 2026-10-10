/* DirectDraw presentation and input on the browser's Canvas2D. All guest
 * and HLE state stays on the machine thread; DOM operations are proxied. */
#include <emscripten.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "win32hle.h"

int (*hle_screen_key_hook)(int, int);
int (*hle_screen_cursor_hook)(void);
void (*hle_screen_frame_hook)(const uint8_t *, int, int, int, int);
int (*hle_screen_compose_hook)(const uint8_t *, int, int, int, uint32_t *);
void (*hle_screen_settings_hook)(const char *, int, int);
static int g_headless;
static _Atomic int g_presenting;
static uint32_t *g_pixels;
static size_t g_pixels_size;
static uint32_t g_rgb565[65536];
/* One DOM producer and one game-thread consumer. Input polling must never
 * synchronously proxy to the browser: PeekMessage can run thousands of times
 * between frames, starving presentation and audio. Publish complete events
 * with release/acquire ordering before advancing either index. */
static struct {
    _Atomic uint32_t read, write;
    int32_t events[1024 * 4];
} g_input;

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
    for (unsigned p = 0; p < 65536; p++) {
        unsigned r = ((p >> 11)*255+15)/31;
        unsigned g = (((p >> 5)&63)*255+31)/63;
        unsigned b = ((p&31)*255+15)/31;
        g_rgb565[p] = r | (g << 8) | (b << 16) | 0xFF000000u;
    }
    hle_cursor_hook = warp;
    MAIN_THREAD_EM_ASM({ Module.ra2AttachInput($0); }, &g_input);
    hle_screen_title(title);
    fprintf(stderr, "[screen] browser Canvas2D\n");
    return 0;
}

static void pump_input(void) {
    static int32_t events[1024 * 4];
    static int pending;
    static uint32_t pressed_at[3];
    static uint32_t left_changed;
    static int pressed[3], left_reads;
    uint32_t read = atomic_load_explicit(&g_input.read, memory_order_relaxed);
    uint32_t write = atomic_load_explicit(&g_input.write, memory_order_acquire);
    while (read != write && pending < 1024) {
        const int32_t *event = g_input.events + 4*(read++ % 1024);
        /* Keep the newest position between button/key transitions rather
         * than making the guest replay an old trail after a busy frame. */
        if (pending && event[0] == 0 && event[1] == 0x200 &&
            events[4*(pending-1)] == 0 && events[4*(pending-1)+1] == 0x200) pending--;
        memcpy(events + 4*pending++, event, 4*sizeof(int32_t));
    }
    atomic_store_explicit(&g_input.read, read, memory_order_release);
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
                if (age < 100 || (button == 0 && hle_lbutton_reads-left_reads < 2 && now-left_changed < 500)) break;
                pressed[button] = 0;
            }
            if (down) {
                pressed[button] = 1; pressed_at[button] = now;
                if (button == 0) { left_reads = hle_lbutton_reads; left_changed = now; }
            }
            /* A drag's final motion must also be sampled while still down,
             * even if down itself was observed long before release. */
            if (e[1] == 0x200 && pressed[0]) { left_reads = hle_lbutton_reads; left_changed = now; }
            hle_input_mouse((uint32_t)e[1], e[2], e[3]);
        }
        consumed++;
    }
    pending -= consumed;
    memmove(events, events + 4*consumed, (size_t)pending * 4 * sizeof *events);
}

void hle_screen_pump(void) {
    pump_input();
    static unsigned shown_seq;
    static uint32_t last_present;
    uint32_t now = hle_ticks_ms();
    if (g_headless || atomic_load_explicit(&g_presenting, memory_order_acquire)) return;
    const uint8_t *px;
    const uint32_t *palette;
    int w, h, pitch, bpp;
    unsigned seq;
    if (!hle_dd_frame(&px, &w, &h, &pitch, &bpp, &palette, &seq)) return;
    if (seq == shown_seq && now-last_present < 250) return;
    shown_seq = seq; last_present = now;
    if (hle_screen_frame_hook) hle_screen_frame_hook(px, w, h, pitch, bpp);
    int cursor = !hle_screen_cursor_hook || hle_screen_cursor_hook();
    /* The browser consumes a snapshot on its animation frame. Never wait
     * for painting with the guest machine locked, or keep servicing proxy
     * calls so continuously that the browser cannot run its event loop. */
    size_t size = (size_t)w * h * sizeof *g_pixels;
    if (size > g_pixels_size) {
        uint32_t *pixels = realloc(g_pixels, size);
        if (!pixels) return;
        g_pixels = pixels; g_pixels_size = size;
    }
    /* Convert on the worker using a packed lookup instead of millions of
     * JS channel writes on the browser thread. Keep the browser free for
     * pointer events and audio, even at the display's full resolution. */
    for (int y = 0; y < h; y++) {
        const uint8_t *row = px + (size_t)y*pitch;
        uint32_t *out = g_pixels + (size_t)y*w;
        if (bpp == 16) {
            const uint16_t *in = (const uint16_t *)row;
            for (int x = 0; x < w; x++) out[x] = g_rgb565[in[x]];
        } else for (int x = 0; x < w; x++) {
            uint32_t p = bpp == 8 ? (palette ? palette[row[x]] : 0) :
                row[x*(bpp/8)] | (uint32_t)row[x*(bpp/8)+1] << 8 |
                (uint32_t)row[x*(bpp/8)+2] << 16;
            out[x] = (p >> 16 & 255) | (p & 0xFF00) | (p & 255) << 16 | 0xFF000000u;
        }
    }
    atomic_store_explicit(&g_presenting, 1, memory_order_release);
    MAIN_THREAD_ASYNC_EM_ASM({
      requestAnimationFrame(() => {
       try {
        const canvas = Module.canvas; const w = $1; const h = $2;
        if (canvas.width !== w || canvas.height !== h) {
            canvas.width = w; canvas.height = h;
            Module.ra2Resize();
        }
        canvas.style.cursor = $3 ? 'default' : 'none';
        Module.ra2SystemCursor = $3;
        Module.ra2DrawCursor();
        const ctx = Module.ra2Context || (Module.ra2Context = canvas.getContext('2d', {alpha:false}));
        let frame = Module.ra2Frame;
        if (!frame || frame.width !== w || frame.height !== h) frame = Module.ra2Frame = ctx.createImageData(w, h);
        frame.data.set(HEAPU8.subarray($0, $0+w*h*4));
        ctx.putImageData(frame, 0, 0);
        document.querySelector('#status').textContent = 'Game running';
        document.querySelector('#status').hidden = true;
       } finally { Atomics.store(HEAP32, $4 >> 2, 0); }
      });
    }, g_pixels, w, h, cursor, &g_presenting);
}
