"""Configure and compile the WebAssembly target using a workspace emsdk."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("game", "gamemd"), default="game")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--opt", default="-O1")
    args = parser.parse_args()
    sdk = Path(os.environ.get("EMSDK", ROOT / ".deps/emsdk"))
    cmake = shutil.which("cmake")
    if not cmake and os.name == "nt":
        candidates = list(Path("C:/Program Files/Microsoft Visual Studio").glob(
            "*/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"))
        cmake = str(candidates[-1]) if candidates else None
    if not cmake:
        parser.error("CMake is required")
    ninja = shutil.which("ninja")
    if not ninja:
        candidate = Path(cmake).parents[2] / "Ninja/ninja.exe"
        ninja = str(candidate) if candidate.exists() else None
    if not ninja:
        parser.error("Ninja is required")
    build = ROOT / ("build-wasm-game" if args.target == "game" else "build-wasm")
    configure = [cmake, "-S", str(ROOT), "-B", str(build), "-G", "Ninja",
                 f"-DCMAKE_MAKE_PROGRAM={ninja}",
                 f"-DCMAKE_TOOLCHAIN_FILE={sdk}/upstream/emscripten/cmake/Modules/Platform/Emscripten.cmake",
                 f"-DPCRECOMP={ROOT}/.deps/pcrecomp", f"-DRA2_TARGET={args.target}",
                 f"-DGEN_OPT={args.opt}", "-DCMAKE_BUILD_TYPE=Release"]
    env = os.environ.copy()
    env["EMSDK"] = str(sdk)
    # emcc uses the SDK's activated .emscripten config and bundled node.
    subprocess.run(configure, check=True, env=env)
    subprocess.run([cmake, "--build", str(build), "-j", str(args.jobs)], check=True, env=env)


if __name__ == "__main__":
    main()
