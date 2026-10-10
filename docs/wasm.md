# WebAssembly port

Work in progress in [zdiemer/redalert2-recomp](https://github.com/zdiemer/redalert2-recomp).
The browser target compiles the original game's lifted C, using pcrecomp's
Linux Win32 HLE for DirectDraw, sound, dialogs, files and input.
Red Alert 2 builds and runs a skirmish in Chromium using the
EA installation (23,201 lifted functions, zero errors and zero stubs).
The browser test navigates the menus and deploys the MCV using browser mouse
and keyboard input. The October 10, 2026 Chromium run reached simulation
frame 595, recorded 2,236 non-silent Web Audio buffers, and reported zero
JavaScript errors (60-second skirmish check).
Yuri's Revenge has also lifted successfully (24,944 functions,
zero errors and zero stubs); its WASM build has not yet been tested.

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
  threads. The browser UI continues to process events. A Canvas2D presenter
  displays the existing DirectDraw surfaces; the existing DirectSound mixer
  feeds Web Audio on its own worker. Fonts use SDL2_ttf. SDL's stock browser
  renderer and audio path failed when called from the game worker.
- Browser adaptations are generated into the build directory by
  `tools/wasm/prepare_runtime.py`. The dependency checkout is left untouched.
- Bink movies are skipped: the initial build uses the HLE's existing
  no-decoder path with `BinkWait` reporting no available frame. Returning
  "ready" forever after a failed open traps the animated title's catch-up
  loop and prevents menu input. The movie MIX archives are still required: initialization
  fails without `MOVIES01.MIX`, before the main menu. Multiplayer, mod restart,
  persistent saves and all game modes need browser verification.
- The launcher loads selected game assets into memory (about 1 GiB for RA2)
  and uses a 2 GiB maximum WASM memory. Native UDP is unavailable in a browser.

To pass scripted host arguments, repeat `arg` in the page URL, for example
`?arg=--debuglog&arg=--watchdog&arg=60`. Runtime output appears in the log.
`--filetrace` logs file opens; the watchdog also reports each thread's saved
guest function and stack address. Browser scheduling adapts HLE's fairness
loop to sleep briefly because Emscripten's `sched_yield` does not yield a CPU
time slice.

## Browser validation

Install Playwright with `py -3 -m pip install --target .deps/python playwright`
and install its Chromium browser, or supply an existing one with `--chromium`.
With the server running:

```powershell
py -3 tools/wasm/playtest.py --seconds 45
py -3 tools/wasm/playtest.py --case skirmish --seconds 120
```

The runner saves browser logs, a screenshot and a JSON result in
`work/wasm/<case>/`. The menu check requires dialog `0xE2` and changing frame
checksums. The skirmish check additionally requires the game's own
`Capture_Mouse()` log and an advancing game frame counter. It then uses the
browser's mouse and keyboard on the scaled canvas to deploy the MCV and
requires the game's `Adding event DEPLOY` log. Audio state and non-silent
buffer counts are also recorded. A rendered menu does not pass the skirmish check.
