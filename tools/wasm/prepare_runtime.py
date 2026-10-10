"""Adapt the pinned Linux HLE in the build tree; never modify the checkout."""
import argparse
from pathlib import Path


def replace(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError(f"Pinned runtime changed: expected one occurrence of {old[:80]!r}")
    return text.replace(old, new)


def prepare(source, dest):
    runtime = source / "runtime/win32hle"
    if not (runtime / "ddraw.c").exists():
        raise RuntimeError("pcrecomp needs the pinned win32hle revision (run bootstrap.py)")
    dest.mkdir(parents=True, exist_ok=True)
    for path in [*runtime.glob("*.c"), *runtime.glob("*.h"),
                 Path(__file__).resolve().parents[2] / "src/wasm/audio.h",
                 source / "runtime/recomp32/recomp_types.h"]:
        text = path.read_text(encoding="utf-8")
        if path.name == "pe_loader.c":
            start = text.index("    void *p = mmap(anywhere")
            end = text.index("    uint32_t base =", start)
            text = text[:start] + '''    /* GLOBAL_BASE leaves this interval unused by the WASM linker. */
    void *p;
    if (anywhere) p = calloc(1, span);
    else {
        if (image_base != 0x00400000u || span > 0x00C00000u) {
            free(file); fprintf(stderr, "[pe] image outside reserved WASM range\\n"); return 1;
        }
        p = (void *)(uintptr_t)image_base;
        memset(p, 0, span);
    }
    if (!p) { free(file); return 1; }
''' + text[end:]
        elif path.name == "recomp_types.h":
            text = replace(text, '#elif defined(__i386__) || defined(__x86_64__)',
                           '''#elif defined(__EMSCRIPTEN__)
#include <emscripten.h>
static inline uint64_t __rdtsc(void) { return (uint64_t)(emscripten_get_now() * 1000000.0); }
#elif defined(__i386__) || defined(__x86_64__)''')
        elif path.name == "gdidc.c":
            start = text.index('    static char path[512];', text.index('static const char *font_file'))
            end = text.index('\n}\nstatic font_t *FONT', start)
            text = text[:start] + '''    (void)face; (void)bold; (void)italic;
    /* The launcher stages the user's font with the private game files. */
    return "/fonts/arial.ttf";''' + text[end:]
        elif path.name == "dsound.c":
            start = text.index('static int audio_open(void) {')
            end = text.index('\n/* the object:', start)
            text = text[:start] + '#include "audio.h"\n' + text[end:]
        elif path.name == "bink.c":
            # MIX entries may share their host file descriptor. Keep each
            # decoder's position and EOF independent of other archive reads.
            text = replace(text, 'int64_t base;', 'int64_t position, length;\n    int64_t base;')
            start = text.index('static int io_read(')
            end = text.index('\nstatic void close_bink(', start)
            text = text[:start] + '''static int io_read(void *opaque, uint8_t *buf, int n) {
    bink_t *b = opaque;
    if (b->position >= b->length) return AVERROR_EOF;
    if (n > b->length-b->position) n = (int)(b->length-b->position);
    ssize_t r = pread(b->fd, buf, (size_t)n, (off_t)(b->base+b->position));
    if (r > 0) b->position += r;
    return r > 0 ? (int)r : AVERROR_EOF;
}
static int64_t io_seek(void *opaque, int64_t off, int whence) {
    bink_t *b = opaque;
    if (whence == AVSEEK_SIZE) return b->length;
    whence &= ~AVSEEK_FORCE;
    if (whence == SEEK_CUR) off += b->position;
    else if (whence == SEEK_END) off += b->length;
    else if (whence != SEEK_SET) return -1;
    if (off < 0) return -1;
    return b->position = off;
}
''' + text[end:]
            text = replace(text, 'b->io = avio_alloc_context', '''uint8_t header[8];
    if (pread(b->fd, header, sizeof header, (off_t)b->base) != sizeof header) {
        g_error = "cannot read movie header"; close_bink(b); RET(0, 2);
    }
    b->length = (int64_t)((uint32_t)header[4] | (uint32_t)header[5]<<8 |
        (uint32_t)header[6]<<16 | (uint32_t)header[7]<<24) + 8;
    b->io = avio_alloc_context''')
            # The RA2 title control still polls after BinkOpen fails. Returning
            # "frame ready" forever traps its catch-up loop in BinkDoFrame.
            # Without a decoder there is never a frame available to present.
            text = replace(text, 'static void k_ret0_1(void) { RET(0, 1); }',
                           'static void k_ret0_1(void) { RET(0, 1); }\n'
                           'static void k_NoFrame(void) { RET(1, 1); }')
            text = replace(text, '{ "_BinkWait@4", k_ret0_1 }',
                           '{ "_BinkWait@4", k_NoFrame }')
            # End-of-movie must stop the guest's frame catch-up loop even
            # when the host was too slow to meet the last frame deadline.
            text = replace(text, 'if (b->paused) RET(1, 1);',
                           'if (!b || b->paused || b->LastFrameNum >= b->Frames) RET(1, 1);')
            text = replace(text, 'AVSEEK_FLAG_BACKWARD | AVSEEK_FLAG_BYTE',
                           'AVSEEK_FLAG_BACKWARD')
            text = replace(text, 'b->done = 0, b->FrameNum = 1;',
                           'b->done = 0, b->FrameNum = 1, b->LastFrameNum = 0;')
            # Low-volume timing makes slow decoding distinguishable from
            # slow presentation, without tracing every guest call/frame.
            text = replace(text, 'uint32_t start_ms, paused_at;',
                           'uint32_t start_ms, paused_at;\n'
                           '    uint32_t decoded, decode_ms, copy_ms;')
            text = replace(text, 'static void close_bink(bink_t *b) {', '''static void movie_timing(bink_t *b) {
    if (b->stream >= 0 && b->decoded)
        fprintf(stderr, "[bink timing] %ux%u/%u frame=%u elapsed=%u decode_ms=%u copy_ms=%u decoded=%u\\n",
            b->Width, b->Height, b->Frames, b->LastFrameNum,
            hle_ticks_ms()-b->start_ms, b->decode_ms, b->copy_ms, b->decoded);
}
static void close_bink(bink_t *b) {
    movie_timing(b);''')
            text = replace(text, 'b->have_frame = decode_frame(b);', '''uint32_t before = hle_ticks_ms();
    b->have_frame = decode_frame(b);
    b->decode_ms += hle_ticks_ms()-before;
    b->decoded++;''')
            text = replace(text, 'b->LastFrameNum = b->FrameNum;', '''b->LastFrameNum = b->FrameNum;
    if (b->decoded % 150 == 0) movie_timing(b);''')
            text = replace(text, 'int w = f->width, h = f->height;',
                           '''uint32_t before = hle_ticks_ms();
    int w = f->width, h = f->height;''')
            text = replace(text, '    RET(0, 7);\n}',
                           '    b->copy_ms += hle_ticks_ms()-before;\n    RET(0, 7);\n}')
        elif path.name == "host_lite.c":
            text = text.replace('#include <pthread.h>', '#include <pthread.h>\n#include <unistd.h>\n#include <emscripten.h>\n#include <emscripten/threading.h>\n#include <stdatomic.h>')
            # These counters are read outside the machine mutex. Volatile
            # does not provide cross-thread synchronization in WebAssembly.
            text = replace(text, 'static volatile int      g_waiters;', 'static _Atomic int      g_waiters;')
            text = replace(text, 'static volatile unsigned g_owner_gen;', 'static _Atomic unsigned g_owner_gen;')
            text = replace(text, '__sync_fetch_and_add(&g_waiters, 1);', 'atomic_fetch_add(&g_waiters, 1);')
            text = replace(text, '__sync_fetch_and_sub(&g_waiters, 1);', 'atomic_fetch_sub(&g_waiters, 1);')
            # Wait for an actual machine handoff, waking as soon as the next
            # owner takes it. Fixed 1 ms sleeps at every contended import
            # unnecessarily throttle the simulation and mouse worker.
            text = replace(text, 'g_owner_gen++;', '''g_owner_gen++;
    emscripten_futex_wake(&g_owner_gen, 0x7FFFFFFF);''')
            text = replace(text,
                           'for (int spins = 0; g_waiters && g_owner_gen == g_block_gen && spins < 1000; spins++) sched_yield();',
                           'for (int spins = 0; g_waiters && g_owner_gen == g_block_gen && spins < 1000; spins++) emscripten_futex_wait(&g_owner_gen, g_block_gen, 1.0);')
            text = replace(text,
                           'for (int spins = 0; g_waiters && g_owner_gen == gen && spins < 1000; spins++) sched_yield();',
                           'for (int spins = 0; g_waiters && g_owner_gen == gen && spins < 1000; spins++) emscripten_futex_wait(&g_owner_gen, gen, 1.0);')
            text = replace(text, 'static __thread mstate g_ms;', '''static __thread mstate g_ms;
static mstate *web_states[64];
static volatile unsigned web_states_count;''')
            text = replace(text, 'g_ms.inited   = 1;', '''g_ms.inited   = 1;
            unsigned index = __sync_fetch_and_add(&web_states_count, 1);
            if (index < 64) web_states[index] = &g_ms;''')
            text = replace(text, 'void hle_block_begin(void) {', '''void hle_block_begin(void) {
    static __thread double last_stack;
    double now_stack = emscripten_get_now();
    if (getenv("HLE_FILETRACE") && now_stack - last_stack > 8000) {
        last_stack = now_stack;
        EM_ASM({ console.log('wait stack guest=' + $0.toString(16) + ' ' + new Error().stack); }, g_cur_func);
    }''')
            text += '''
void wasm_machine_report(void) {
    EM_ASM({ console.log('[machine worker] guest=' + $0.toString(16) + ' import=' + UTF8ToString($1) + ' waiters=' + $2); }, g_cur_func, g_cur_import, g_waiters);
    fprintf(stderr, "[machine] waiters=%d generation=%u\\n", g_waiters, g_owner_gen);
    for (unsigned i = 0; i < web_states_count && i < 64; i++) {
        mstate *state = web_states[i];
        if (state) fprintf(stderr, "[machine] thread=%u depth=%d last=%08X esp=%08X ret=%08X\\n",
            i, state->depth, state->r.cur, state->r.esp, MEM32(state->r.esp));
    }
}
'''
        elif path.name == "kernel32.c":
            text = replace(text, 'static void k_WaitForSingleObject(void) { uint32_t h = A32(0);',
                           '''static void k_WaitForSingleObject(void) { uint32_t h = A32(0);
    static unsigned wait_calls;
    if (getenv("HLE_FILETRACE") && (wait_calls++ < 12 || wait_calls % 1000000 == 0))
        fprintf(stderr, "[wait] handle=%08X timeout=%u guest=%08X thread=%p count=%u\\n",
                h, A32(1), g_cur_func, (void *)pthread_self(), wait_calls);
''')
        target = dest / path.name
        if not target.exists() or target.read_text(encoding="utf-8") != text:
            target.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("dest", type=Path)
    args = parser.parse_args()
    prepare(args.source, args.dest)
