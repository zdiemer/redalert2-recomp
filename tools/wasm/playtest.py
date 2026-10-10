"""Run the real WASM game in Chromium and retain logs and a screenshot."""
import argparse
import asyncio
import json
import os
import re
from pathlib import Path
import sys
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".deps/python"))
from playwright.async_api import async_playwright


async def test(args):
    out = args.output or ROOT / "work/wasm" / args.case
    out.mkdir(parents=True, exist_ok=True)
    host_args = ["--debuglog", "--watchdog", str(args.seconds), "--waitlog", "__end_of_test__@9999"]
    if args.case == "skirmish":
        os.environ["RA2_TARGET"] = args.target
        sys.path.insert(0, str(ROOT / "tools"))
        import playtest as native
        host_args.extend(native.CASES["skirmish-start"][0])
    host_args.extend(args.arg)
    url = args.url + "?" + urlencode([("arg", a) for a in host_args])
    logs, errors = [], []
    async with async_playwright() as p:
        options = {"headless":True, "args":["--enable-unsafe-swiftshader"]}
        if args.chromium:
            options["executable_path"] = args.chromium
        browser = await p.chromium.launch(**options)
        page = await browser.new_page(viewport={"width":1360,"height":1100})
        (out / "browser.log").write_text("")
        def record(message):
            logs.append(message)
            with (out / "browser.log").open("a", encoding="utf-8") as stream:
                stream.write(message + "\n")
        page.on("console", lambda msg: record(msg.text))
        page.on("pageerror", lambda exc: (errors.append(str(exc)), record(str(exc))))
        try:
            await page.goto(url, timeout=120000)
            await page.wait_for_function("typeof ready !== 'undefined' && ready", timeout=120000)
            await page.locator("#local").click(timeout=10000)
            # Loading assets and compiling this large module may take a while.
            await page.wait_for_function("document.querySelector('#log').textContent.includes('entering 0x') || document.querySelector('#status').textContent.includes('stopped:')", timeout=120000)
            deployed = False
            for _ in range(args.seconds):
                await asyncio.sleep(1)
                if args.case == "skirmish" and not deployed and any("key 0x48" in line for line in logs):
                    # Exercise DOM input through the scaled canvas, beyond the
                    # host script that navigates the setup dialogs.
                    box = await page.locator("#canvas").bounding_box()
                    await page.mouse.click(box["x"] + box["width"]*236/640,
                                           box["y"] + box["height"]*213/480, delay=250)
                    await page.keyboard.press("d", delay=250)
                    deployed = True
                if errors or any("FATAL:" in line or "Aborted(" in line for line in logs):
                    break
            await page.screenshot(path=str(out / "screen.png"))
            text = "\n".join(logs)
            checks = {"menu": "[dialog] open 0xE2" in text,
                      "frames":len(set(re.findall(r'checksum ([0-9A-F]+)', text))) >= 2}
            if args.case == "skirmish":
                frames = [int(n) for n in re.findall(r'game frame (\d+)', text)]
                checks["ingame"] = "[game] Capture_Mouse()" in text and len(set(frames)) >= 3
                checks["browser_input"] = "Adding event DEPLOY" in text
            audio = await page.evaluate("({state:Module.ra2Audio?.state, chunks:Module.ra2AudioChunks || 0})")
            result = {"status":await page.locator("#status").inner_text(), "errors":errors,
                      "isolated":await page.evaluate("crossOriginIsolated"), "audio":audio, "checks":checks}
            (out / "result.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result), flush=True)
        finally:
            (out / "browser.log").write_text("\n".join(logs + errors), encoding="utf-8")
            if not (out / "screen.png").exists():
                await page.screenshot(path=str(out / "screen.png"))
            await browser.close()
    if errors or not all(checks.values()) or any("FATAL:" in line or "Aborted(" in line for line in logs):
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080/ra2.html")
    parser.add_argument("--target", choices=("game", "gamemd"), default="game")
    parser.add_argument("--case", choices=("menu", "skirmish"), default="menu")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--chromium")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--arg", action="append", default=[])
    args = parser.parse_args()
    sys.exit(asyncio.run(test(args)))


if __name__ == "__main__":
    main()
