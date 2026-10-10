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
        target = dest / path.name
        if not target.exists() or target.read_text(encoding="utf-8") != text:
            target.write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("dest", type=Path)
    args = parser.parse_args()
    prepare(args.source, args.dest)
