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
        elif path.name == "host_lite.c":
            # sched_yield is a no-op in Emscripten. Give the notified worker
            # time to wake before the current worker takes the mutex again.
            text = text.replace('#include <pthread.h>', '#include <pthread.h>\n#include <unistd.h>')
            text = text.replace('sched_yield();', 'usleep(1000);')
            text = replace(text, 'static __thread mstate g_ms;', '''static __thread mstate g_ms;
static mstate *web_states[64];
static volatile unsigned web_states_count;''')
            text = replace(text, 'g_ms.inited   = 1;', '''g_ms.inited   = 1;
            unsigned index = __sync_fetch_and_add(&web_states_count, 1);
            if (index < 64) web_states[index] = &g_ms;''')
            text += '''
void wasm_machine_report(void) {
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
