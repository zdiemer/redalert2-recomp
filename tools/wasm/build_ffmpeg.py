"""Build the small, pinned Bink decoder used by the browser HLE."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
REV = "f893221c8d89cb798b829bebe71d55e1a3f242fd"


def main():
    source = ROOT / ".deps/ffmpeg"
    if not source.exists():
        subprocess.run(["git", "clone", "https://github.com/FFmpeg/FFmpeg.git", str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "checkout", REV], check=True)
    sdk = Path(os.environ.get("EMSDK", ROOT / ".deps/emsdk"))
    build = ROOT / ".deps/ffmpeg-wasm"
    build.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["EMSDK"] = str(sdk)
    if os.name == "nt":
        shell = Path("C:/msys64/usr/bin/bash.exe")
        if not shell.exists():
            raise RuntimeError("Install MSYS2 with make to build FFmpeg on Windows")
        env["PATH"] = os.pathsep.join([str(shell.parent), "C:/msys64/mingw64/bin",
                                      "C:/Program Files/Git/usr/bin", env["PATH"]])
        def posix(path):
            path = Path(path).resolve().as_posix()
            return "/" + path[0].lower() + path[2:]
        python = sdk / "python/3.13.3_64bit/python.exe"
        cc = build / "emcc.sh"
        cc.write_text(f'#!/bin/sh\nexec "{posix(python)}" "{posix(sdk / "upstream/emscripten/emcc.py")}" "$@"\n', newline="\n")
        compiler = "sh " + posix(cc)
        configure = [str(shell), posix(source / "configure")]
        prefix = posix(build / "install")
        llvm = posix(sdk / "upstream/bin")
        make = str(shell.parent / "make.exe")
    else:
        compiler = str(sdk / "upstream/emscripten/emcc")
        configure = [str(source / "configure")]
        prefix = str(build / "install")
        llvm = str(sdk / "upstream/bin")
        make = "make"
    subprocess.run(configure + [
        "--prefix=" + prefix, "--cc=" + compiler, "--ld=" + compiler,
        "--ar=" + llvm + "/llvm-ar", "--ranlib=" + llvm + "/llvm-ranlib",
        "--nm=" + llvm + "/llvm-nm", "--enable-cross-compile", "--target-os=none",
        "--arch=wasm32", "--disable-asm", "--disable-inline-asm",
        "--disable-everything", "--disable-autodetect", "--disable-programs", "--disable-doc",
        "--disable-avdevice", "--disable-avfilter", "--disable-swscale", "--disable-network",
        "--disable-iconv", "--enable-avcodec", "--enable-avformat", "--enable-swresample",
        "--enable-decoder=bink,binkaudio_dct,binkaudio_rdft", "--enable-demuxer=bink",
        "--enable-protocol=file", "--extra-cflags=-O2 -pthread", "--extra-ldflags=-pthread",
    ], cwd=build, env=env, check=True)
    subprocess.run([make, "-j6", "install"], cwd=build, env=env, check=True)


if __name__ == "__main__":
    main()
