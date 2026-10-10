"""Download pinned build tools and lift your own RA2 executable locally."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HLE_REV = "12a3480e4691ae43bf0f3d6504f5da414b6e2bc8"
SDK_VERSION = "6.0.12"


def run(*args, **kwargs):
    subprocess.run([str(a) for a in args], cwd=ROOT, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, required=True)
    parser.add_argument("--target", choices=("game", "gamemd"), default="game")
    args = parser.parse_args()
    exe = args.game_dir / (args.target + ".exe")
    if not exe.is_file():
        parser.error(f"Missing {exe}")
    toolkit = ROOT / ".deps/pcrecomp"
    sdk = ROOT / ".deps/emsdk"
    if not toolkit.exists():
        run("git", "clone", "https://github.com/sp00nznet/pcrecomp.git", toolkit)
        run("git", "-C", toolkit, "checkout", HLE_REV)
    # Naming is optional; the pinned runtime provides the lifter and HLE ABI.
    if not (toolkit / "runtime/win32hle/ddraw.c").exists():
        parser.error(f"{toolkit} lacks the Linux HLE; use revision {HLE_REV}")
    if not sdk.exists():
        run("git", "clone", "https://github.com/emscripten-core/emsdk.git", sdk)
    emsdk = sdk / ("emsdk.bat" if os.name == "nt" else "emsdk")
    run(emsdk, "install", SDK_VERSION)
    run(emsdk, "activate", SDK_VERSION)
    run(sys.executable, "-m", "pip", "install", "pefile", "capstone")
    (ROOT / "game").mkdir(exist_ok=True)
    dest = ROOT / "game" / exe.name
    if not dest.exists() or dest.read_bytes() != exe.read_bytes():
        shutil.copyfile(exe, dest)
    work = ROOT / "work" / ("game" if args.target == "game" else "")
    work.mkdir(parents=True, exist_ok=True)
    run(sys.executable, toolkit / "tools/pe/pe_analyze.py", dest, "--json", work / "pe_analysis.json")
    run(sys.executable, toolkit / "tools/cpp/rtti.py", dest, "-o", work / "rtti.json", "--seeds", work / "rtti_seeds.json")
    if not (work / "functions.json").exists():
        run(sys.executable, toolkit / "tools/disasm/disasm32.py", dest, "-o", work / "functions.json",
            "--seed-functions", work / "rtti_seeds.json")
    env = os.environ.copy()
    env["PCRECOMP"] = str(toolkit)
    run(sys.executable, "run_lift.py", "--all", "--target", args.target, env=env)
    print("Lift complete. Next: python tools/wasm/build.py --target " + args.target)


if __name__ == "__main__":
    main()
