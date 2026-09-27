"""Dev tool: open a page in headless Edge/Chrome via CDP and save screenshots at given times.

    python ports/emu/shot.py <out dir> --url http://localhost:8070/index.html --secs 10,20 [--query keys=...]
        [--sheet]  also write sheet.png (all shots side by side)

Writes shot_<sec>.png and console.txt (page console + exceptions).
"""
import argparse
import base64
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.request

import websocket

BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe"]


KEYS = {"Enter": (13, "Enter"), "ArrowLeft": (37, "ArrowLeft"), "ArrowUp": (38, "ArrowUp"),
        "ArrowRight": (39, "ArrowRight"), "ArrowDown": (40, "ArrowDown"), " ": (32, "Space")}


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--url", default="http://localhost:8070/index.html")
    ap.add_argument("--secs", default="10,20")
    ap.add_argument("--query", default="")
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--keys", default="", help="t:key:dur,... real key events via CDP (Enter, d, s, a, ArrowLeft, ...)")
    ap.add_argument("--gpu", action="store_true", help="use the real GPU instead of SwiftShader")
    ap.add_argument("--nolimit", action="store_true", help="disable vsync / frame-rate limit")
    ap.add_argument("--profile", default="", help="t0:t1 CPU profile window (seconds); prints top functions")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    exe = next(b for b in BROWSERS if os.path.exists(b))
    prof = os.path.join(a.out, "_profile")
    shutil.rmtree(prof, ignore_errors=True)
    port = free_port()
    args = [exe, "--headless=new", f"--user-data-dir={prof}", f"--remote-debugging-port={port}",
            "--no-first-run", "--autoplay-policy=no-user-gesture-required", "--window-size=900,760",
            "--remote-allow-origins=*", "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows"]
    if a.nolimit:
        args += ["--disable-gpu-vsync", "--disable-frame-rate-limit"]
    if not a.gpu:
        args += ["--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"]
    else:
        # hardware ANGLE on the discrete GPU (headless otherwise may fall back to software)
        args += ["--use-angle=d3d11", "--ignore-gpu-blocklist", "--enable-gpu-rasterization",
                 "--force_high_performance_gpu"]
    p = subprocess.Popen(args + ["about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.1)
        ws = websocket.create_connection(ws_url, timeout=60)
        mid = [0]
        console = []

        def send(method, **params):
            mid[0] += 1
            ws.send(json.dumps({"id": mid[0], "method": method, "params": params}))
            want = mid[0]
            while True:
                m = json.loads(ws.recv())
                if m.get("id") == want:
                    return m.get("result", {})
                note(m)

        def note(m):
            meth = m.get("method")
            if meth == "Runtime.consoleAPICalled":
                console.append(" ".join(str(x.get("value", x.get("description", ""))) for x in m["params"]["args"]))
            elif meth == "Runtime.exceptionThrown":
                d = m["params"]["exceptionDetails"]
                ex = d.get("exception", {})
                console.append("EXC " + d.get("text", "") + " " + str(ex.get("description", ex.get("value", "")))[:300]
                               + " @" + str(d.get("url", "")) + ":" + str(d.get("lineNumber", "")))

        send("Runtime.enable")
        send("Page.enable")
        url = a.url + (("&" if "?" in a.url else "?") + a.query if a.query else "")
        send("Page.navigate", url=url)
        t0 = time.time()
        shots = []
        events = []
        for item in filter(None, a.keys.split(",")):
            t, key, *dur = item.split(":")
            dur = float(dur[0]) if dur else 0.15
            events += [(float(t), "keyDown", key), (float(t) + dur, "keyUp", key)]
        events.sort()

        def key_event(kind, key):
            vk = KEYS.get(key, (ord(key.upper()), "Key" + key.upper()) if len(key) == 1 else (0, key))
            send("Input.dispatchKeyEvent", type=kind, key=key, code=vk[1], windowsVirtualKeyCode=vk[0],
                 nativeVirtualKeyCode=vk[0])

        def pump(until):
            ws.settimeout(0.05)
            while time.time() - t0 < until:
                while events and time.time() - t0 >= events[0][0]:
                    _, kind, key = events.pop(0)
                    ws.settimeout(60)
                    key_event(kind, key)
                    ws.settimeout(0.05)
                try:
                    note(json.loads(ws.recv()))
                except Exception:
                    pass

        if a.profile:
            p0, p1 = (float(x) for x in a.profile.split(":"))
            pump(p0)
            ws.settimeout(60)
            send("Profiler.enable")
            send("Profiler.start")
            pump(p1)
            ws.settimeout(120)
            prof = send("Profiler.stop")["profile"]
            self_t = {}
            dt = prof.get("timeDeltas", [])
            byid = {n["id"]: n for n in prof["nodes"]}
            for sid, d in zip(prof.get("samples", []), dt):
                cf = byid[sid]["callFrame"]
                k = cf["functionName"] or cf["url"][-30:] or "(anon)"
                self_t[k] = self_t.get(k, 0) + d
            tot = sum(self_t.values()) or 1
            for k, v in sorted(self_t.items(), key=lambda kv: -kv[1])[:25]:
                console.append(f"PROF {100 * v / tot:5.1f}% {k}")
        for s in sorted(float(x) for x in a.secs.split(",")):
            pump(s)
            ws.settimeout(60)
            ws.settimeout(60)
            r = send("Page.captureScreenshot", format="png")
            fn = os.path.join(a.out, f"shot_{s:g}.png")
            open(fn, "wb").write(base64.b64decode(r["data"]))
            shots.append(fn)
        ws.close()
    finally:
        p.kill()
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
    open(os.path.join(a.out, "console.txt"), "w", encoding="utf-8").write("\n".join(console))
    print(f"{len(shots)} shots, {len(console)} console lines -> {a.out}")
    for line in console[-8:]:
        print("  |", line[:160])
    if a.sheet and shots:
        from PIL import Image, ImageDraw
        ims = [Image.open(f).convert("RGB").crop((110, 134, 750, 614)).resize((400, 300)) for f in shots]
        cols = min(4, len(ims))
        rows = (len(ims) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * 400, rows * 300))
        for i, (im, f) in enumerate(zip(ims, shots)):
            sheet.paste(im, ((i % cols) * 400, (i // cols) * 300))
            ImageDraw.Draw(sheet).text(((i % cols) * 400 + 4, (i // cols) * 300 + 4), os.path.basename(f), fill=(255, 255, 0))
        sheet.save(os.path.join(a.out, "sheet.png"))


if __name__ == "__main__":
    main()
