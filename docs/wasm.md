# WebAssembly port

Work in progress in [zdiemer/redalert2-recomp](https://github.com/zdiemer/redalert2-recomp).
The browser target compiles the original game's lifted C, using pcrecomp's
Linux Win32 HLE for DirectDraw, sound, dialogs, files and input.
Browser gameplay is not yet verified.

## Build locally

Python 3.10+, Git, CMake and Ninja are required. On Windows the build script
also finds the CMake and Ninja shipped with Visual Studio Community.
The bootstrap downloads Emscripten 6.0.12 and pcrecomp's Linux HLE revision
`12a3480e4691ae43bf0f3d6504f5da414b6e2bc8` into `.deps/`.

```powershell
py -3 tools/wasm/bootstrap.py --game-dir "C:\Program Files\EA Games\Command and Conquer Red Alert II"
py -3 tools/wasm/build.py
py -3 tools/wasm/serve.py --game-dir "C:\Program Files\EA Games\Command and Conquer Red Alert II"
```

Open <http://127.0.0.1:8080/ra2.html> and choose **Use local installation**.
The server binds to localhost and serves only its build directory plus selected
game data. It supplies the COOP/COEP headers required for shared WASM memory.
Alternatively select your game folder in the browser. A TrueType font is
provided by the server (`--font` changes it; Windows defaults to Arial).

For Yuri's Revenge, pass `--target gamemd` to all three commands and
`--build build-wasm` to the server. Each game has its own generated sources
and output directory. No retail files, lifted sources or WASM output are
committed or uploaded; every player builds from their own installation.

## Runtime design and current limits

- WASM code and static data begin at 16 MiB (`GLOBAL_BASE`). The PE loader
  copies the game to its original address, 4 MiB, in the reserved lower range.
  DLL resource images use ordinary allocations.
- The blocking game runs on a pthread, with eight workers available for game
  threads. The browser UI continues to process events. SDL2 presents through
  Emscripten's canvas support; fonts use SDL2_ttf.
- Browser adaptations are generated into the build directory by
  `tools/wasm/prepare_runtime.py`. The dependency checkout is left untouched.
- Bink movies are skipped: the initial build uses the HLE's existing
  no-decoder path. Multiplayer, mod restart, persistent saves and all game
  modes need browser verification. Native UDP is unavailable in a browser.
- The launcher loads selected game assets into memory. It omits movie
  archives and uses a 2 GiB maximum WASM memory.

To pass scripted host arguments, repeat `arg` in the page URL, for example
`?arg=--debuglog&arg=--watchdog&arg=60`. Runtime output appears in the log.
