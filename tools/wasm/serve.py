"""Serve a private WASM build on localhost with browser-thread headers."""
import argparse
import json
import mimetypes
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


def game_files(root, target):
    names = {"blowfish.dll", target + ".exe"}
    for path in sorted(root.iterdir()):
        name = path.name.lower()
        if path.is_file() and (name in names or (
            path.suffix.lower() in {".mix", ".mmx", ".yro", ".map", ".ini", ".csf", ".pkt", ".tlb"}
            and (target == "gamemd" or "md" not in name)
        )):
            yield path


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, game=None, font=None, target="game", **kwargs):
        self.assets = {p.name: p for p in game_files(game, target)} if game else {}
        self.font = font
        super().__init__(*args, **kwargs)

    def end_headers(self):
        self.send_header("Cross-Origin-Opener-Policy", "same-origin")
        self.send_header("Cross-Origin-Embedder-Policy", "require-corp")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def do_GET(self):
        path = unquote(urlsplit(self.path).path)
        if path == "/local-manifest":
            if not self.assets:
                self.send_error(404)
                return
            data = json.dumps([{"name":n,"size":p.stat().st_size} for n,p in self.assets.items()]).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        asset = self.font if path == "/local-font" else self.assets.get(path.removeprefix("/local-game/")) if path.startswith("/local-game/") else None
        if asset:
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(asset.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(asset.stat().st_size))
            self.end_headers()
            with asset.open("rb") as stream:
                self.copyfile(stream, self.wfile)
            return
        # Only build output is public, never the workspace or installation.
        super().do_GET()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=Path("build-wasm-game"))
    parser.add_argument("--game-dir", type=Path)
    parser.add_argument("--target", choices=("game", "gamemd"), default="game")
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/arial.ttf"))
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    if not (args.build / "ra2.html").is_file():
        parser.error("Build ra2.html first with tools/wasm/build.py")
    if not args.font.is_file():
        parser.error("--font must be a readable TrueType font")
    handler = partial(Handler, directory=str(args.build.resolve()), game=args.game_dir,
                      font=args.font, target=args.target)
    print(f"Open http://127.0.0.1:{args.port}/ra2.html", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
