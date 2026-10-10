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
    for name in ("result.json", "screen.png"):
        (out / name).unlink(missing_ok=True)
    host_args = ["--debuglog", "--watchdog", str(args.seconds), "--waitlog", "__end_of_test__@9999"]
    if args.case in ("skirmish", "campaign") or args.skip_intro:
        os.environ["RA2_TARGET"] = args.target
        sys.path.insert(0, str(ROOT / "tools"))
        import playtest as native
    if args.case in ("skirmish", "campaign"):
        host_args.extend(native.CASES["skirmish-start" if args.case == "skirmish" else "campaign-allied"][0])
    host_args.extend(args.arg)
    url = args.url + "?" + urlencode([("arg", a) for a in host_args] + [("resolution",args.resolution)])
    logs, errors = [], []
    async with async_playwright() as p:
        options = {"headless":True, "args":["--enable-unsafe-swiftshader",*args.browser_arg]}
        if args.native_logs:
            options["args"].extend(["--enable-logging", "--log-file="+str((out/"chrome.log").resolve())])
        if args.chromium:
            options["executable_path"] = args.chromium
        browser = await p.chromium.launch(**options)
        page = await browser.new_page(viewport={"width":1360,"height":1100},
                                      screen={"width":1920,"height":1080})
        if args.skip_intro:
            async def skip_intro(route):
                response = await route.fetch()
                text = await response.text()
                text = native.set_ini(text.encode(), "Intro", "Play", "no").decode()
                await route.fulfill(response=response, body=text)
            await page.route("**/local-game/RA2.INI", skip_intro)
        (out / "browser.log").write_text("")
        def record(message):
            logs.append(message)
            with (out / "browser.log").open("a", encoding="utf-8") as stream:
                stream.write(message + "\n")
        page.on("console", lambda msg: record(msg.text))
        page.on("pageerror", lambda exc: (errors.append(str(exc)), record(str(exc))))
        page.on("crash", lambda _: (errors.append("Chromium renderer crashed"), record("[browser] renderer crashed")))
        browser_debug = await browser.new_browser_cdp_session()
        await browser_debug.send("Target.setDiscoverTargets", {"discover":True})
        def crashed(event):
            message = "Chromium target crashed: " + json.dumps(event)
            errors.append(message)
            record(message)
        browser_debug.on("Target.targetCrashed", crashed)
        debug = await page.context.new_cdp_session(page)
        if args.debug_stall:
            await debug.send("Debugger.enable")
            debug.on("Debugger.paused", lambda event: record("[paused] " + json.dumps(event.get("callFrames", []))))
        mouse = [0, 0]
        async def move_game(x, y, steps=1):
            state = await page.evaluate("({locked:document.pointerLockElement===Module.canvas, x:Module.ra2Cursor.x,y:Module.ra2Cursor.y})")
            box = await page.locator("#canvas").bounding_box()
            if state["locked"]:
                mouse[0] += (x-state["x"])*box["width"]/await page.evaluate("Module.canvas.width")
                mouse[1] += (y-state["y"])*box["height"]/await page.evaluate("Module.canvas.height")
            else:
                mouse[0] = box["x"]+x*box["width"]/await page.evaluate("Module.canvas.width")
                mouse[1] = box["y"]+y*box["height"]/await page.evaluate("Module.canvas.height")
            await page.mouse.move(*mouse, steps=steps)
        async def selected_unit():
            # Tanya is the only player unit in this view. Track her selected
            # health bar in canvas pixels; campaign movement emits no network
            # MEGAMISSION log. Its white border distinguishes it from terrain.
            return await page.evaluate("""() => {
                const w=Module.canvas.width,h=Module.canvas.height;
                const p=Module.ra2Context.getImageData(0,0,w,h).data;
                const white=(x,y)=>{const i=(y*w+x)*4;return p[i]===255&&p[i+1]===255&&p[i+2]===255;};
                for(let y=2;y<h-34;y++) {
                    let xs=[];
                    for(let x=1;x<w-169;x++) {
                        const i=(y*w+x)*4;
                        if(p[i]===0&&p[i+1]===255&&p[i+2]===0&&white(x,y-1)&&white(x,y+2)) {
                            if(xs.length&&x-xs.at(-1)>2) xs=[];
                            xs.push(x);
                            if(xs.length>=6) return {x:(xs[0]+x)/2,y};
                        }
                    }
                }
                return null;
            }""")
        checks = {}
        try:
            await page.goto(url, timeout=120000)
            await page.wait_for_function("typeof ready !== 'undefined' && ready", timeout=120000)
            # Loading assets and compiling this large module may take a while.
            await page.wait_for_function("document.querySelector('#log').textContent.includes('entering 0x') || document.querySelector('#status').textContent.includes('stopped:')", timeout=120000)
            await page.keyboard.press("Shift")  # Unlock Web Audio without skipping a movie.
            deployed = False
            last_order_try = 0
            movie_count, movie_seen, movie_at = 0, 0, 0
            for elapsed in range(args.seconds):
                await asyncio.sleep(1)
                # Title animations and in-game radar messages also use Bink.
                # Escape on those opens menus instead of skipping a cutscene.
                movies = sum("with sound" in line and int(match[1]) >= 640
                             for line in logs if (match := re.match(r'\[bink\] (\d+)x(\d+),', line)))
                if movies > movie_count:
                    movie_count, movie_at = movies, elapsed
                if args.case != "video" and not args.no_skip_movies and movie_count > movie_seen and elapsed-movie_at >= 3:
                    await page.screenshot(path=str(out / f"movie-{movie_count}.png"),timeout=10000)
                    await asyncio.wait_for(page.keyboard.press("Escape", delay=150), 10)
                    movie_seen = movie_count
                if args.case == "skirmish" and not deployed and any("key 0x48" in line for line in logs):
                    # Exercise DOM input through the scaled canvas, beyond the
                    # host script that navigates the setup dialogs.
                    width, height = await page.evaluate("[Module.canvas.width,Module.canvas.height]")
                    await move_game((width-168)/2,(height-54)/2)
                    await page.mouse.click(*mouse)
                    await page.keyboard.press("d", delay=250)
                    deployed = True
                # The mission begins with a scripted camera sequence. Wait
                # for gameplay to advance before trying to select its units.
                frames = [int(n) for n in re.findall(r'game frame (\d+)', "\n".join(logs))]
                if args.case == "campaign" and not deployed and frames and frames[-1] >= 1100 and frames[-1]-last_order_try >= 300:
                    last_order_try = frames[-1]
                    width, height = await page.evaluate("[Module.canvas.width,Module.canvas.height]")
                    await move_game(16,16)
                    await page.mouse.down()
                    await asyncio.sleep(0.15)
                    await move_game(width-188,height-52,steps=20)
                    await asyncio.sleep(0.15)
                    await page.mouse.up()
                    await asyncio.sleep(0.2)
                    await page.screenshot(path=str(out/f"selection-{last_order_try}.png"),timeout=10000)
                    before = await selected_unit()
                    await move_game((width-168)/2,height/2)
                    await page.mouse.click(*mouse)
                    await asyncio.sleep(2)
                    after = await selected_unit()
                    if before and after:
                        distance = ((after["x"]-before["x"])**2+(after["y"]-before["y"])**2)**0.5
                        deployed = distance >= 8
                        record(f"[browser check] selected unit {before} -> {after}, moved {distance:.1f} pixels")
                if errors or any("FATAL:" in line or "Aborted(" in line for line in logs):
                    break
            if errors:
                raise RuntimeError(errors[-1])
            await page.screenshot(path=str(out / "screen.png"))
            text = "\n".join(logs)
            checks = {"frames":len(set(re.findall(r'checksum ([0-9A-F]+)', text))) >= 2}
            if args.case != "video":
                checks["menu"] = "[dialog] open 0xE2" in text
            timing = [{"frame":int(frame), "elapsedMs":int(ms), "fps":(int(frame)-1)*1000/int(ms)}
                      for frame, ms in re.findall(r'\[bink timing\].*? frame=(\d+) elapsed=(\d+)', text)
                      if int(ms) >= 5000 and int(frame) >= 75]
            if args.case == "video":
                checks["realtime_video"] = bool(timing) and all(14.5 <= item["fps"] <= 15.5 for item in timing)
            if args.case in ("skirmish", "campaign"):
                frames = [int(n) for n in re.findall(r'game frame (\d+)', text)]
                checks["ingame"] = "[game] Capture_Mouse()" in text and len(set(frames)) >= 3
                checks["browser_input"] = "Adding event DEPLOY" in text if args.case == "skirmish" else deployed
                checks["mouse_capture"] = await page.evaluate("document.pointerLockElement === Module.canvas")
            checks["movie"] = movie_count > 0
            audio = await page.evaluate("({state:Module.ra2Audio?.state, chunks:Module.ra2AudioChunks || 0, queuedSeconds:(Module.ra2AudioNext || 0)-(Module.ra2Audio?.currentTime || 0)})")
            result = {"status":await page.locator("#status").inner_text(), "errors":errors,
                      "isolated":await page.evaluate("crossOriginIsolated"), "audio":audio, "movieTiming":timing,
                      "display":await page.evaluate("({requested:Module.ra2Resolution,width:Module.canvas.width,height:Module.canvas.height})"), "checks":checks}
            (out / "result.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result), flush=True)
        except Exception as exc:
            errors.append(str(exc))
            record("[test] " + str(exc))
            result = {"status":"Browser test failed", "errors":errors,"checks":checks}
            (out / "result.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result), flush=True)
        finally:
            if args.debug_stall and errors:
                try:
                    await asyncio.wait_for(debug.send("Debugger.pause"), 5)
                    await asyncio.sleep(1)
                    await asyncio.wait_for(debug.send("Debugger.resume"), 5)
                except Exception as exc:
                    record("[debug] " + str(exc))
            (out / "browser.log").write_text("\n".join(logs + errors), encoding="utf-8")
            try:
                if not (out / "screen.png").exists():
                    try:
                        await page.screenshot(path=str(out / "screen.png"), timeout=5000)
                    except Exception as exc:
                        record("[screenshot] " + str(exc))
            finally:
                await browser.close()
    if errors or not all(checks.values()) or any("FATAL:" in line or "Aborted(" in line for line in logs):
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080/ra2.html")
    parser.add_argument("--target", choices=("game", "gamemd"), default="game")
    parser.add_argument("--case", choices=("menu", "skirmish", "campaign", "video"), default="menu")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--chromium")
    parser.add_argument("--browser-arg",action="append",default=[],help="Extra Chromium flag for diagnostics")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resolution",default="640x480")
    parser.add_argument("--skip-intro",action="store_true",help="Skip the first-run intro via the test's in-memory INI")
    parser.add_argument("--no-skip-movies",action="store_true",help="Leave movies playing to measure their real-time pace")
    parser.add_argument("--debug-stall",action="store_true",help="Capture debugger stacks if the browser stops responding")
    parser.add_argument("--native-logs",action="store_true",help="Retain Chromium's native crash log")
    parser.add_argument("--arg", action="append", default=[])
    args = parser.parse_args()
    sys.exit(asyncio.run(test(args)))


if __name__ == "__main__":
    main()
