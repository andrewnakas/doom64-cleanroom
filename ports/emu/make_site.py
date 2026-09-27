"""Assemble the web site: N64Wasm (MIT, prebuilt ParaLLEl core) + our page hooks + a ROM.

    python ports/emu/make_site.py <out dir> <rom.z64> [--n64wasm C:/Users/andre/n64work/n64wasm/dist]

Hooks added to N64Wasm's script.js:
  ?rom=<url>    auto-load that ROM when the wasm module is ready (default: the site's ROM)
  ?keys=t:key:dur,...   scripted key presses (dev: headless checks)
The ROM is written as game.z64. Never point this at a retail ROM for a published site.
"""
import argparse
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))

AUTOLOAD = r"""
    async initModule(){
        console.log('module initialized');
        myClass.rivetsData.moduleInitializing = false;
        let q = new URLSearchParams(location.search);
        let rom = q.get('rom') || window.SITE_ROM;
        if (q.get('rice')) myClass.rivetsData.ricePlugin = true;
        if (q.get('angry')) myClass.rivetsData.forceAngry = true;
        if (rom) { myClass.rom_name = myClass.extractRomName(rom); myClass.load_url(rom); }
        if (q.get('keys')) window.cleanroomKeys(q.get('keys'));
        if (q.get('nosave')) myClass.SaveSram = function () {};
    }
"""

KEYS_JS = r"""
// dev hook: ?keys=t:key:dur,... (seconds; key = KeyboardEvent.key, e.g. Enter, d, ArrowLeft)
window.cleanroomKeys = function (spec) {
  const t0 = performance.now();
  spec.split(',').forEach(item => {
    const [t, key, dur] = item.split(':');
    setTimeout(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: key, bubbles: true }));
      setTimeout(() => document.dispatchEvent(new KeyboardEvent('keyup', { key: key, bubbles: true })),
                 1000 * parseFloat(dur || '0.15'));
    }, 1000 * parseFloat(t));
  });
};

// Browsers start an AudioContext suspended unless a user gesture created it; the ROM auto-loads
// without one, so resume audio on the first click / key / touch (gamepad presses don't count).
(function () {
  function wake() {
    try {
      if (typeof myClass !== 'undefined' && myClass.audioContext && myClass.audioContext.state !== 'running') {
        myClass.audioContext.resume();
      }
    } catch (e) {}
    try {
      const ok = myClass && myClass.audioContext && myClass.audioContext.state === 'running';
      const hint = document.getElementById('soundHint');
      if (hint && ok) hint.style.display = 'none';
    } catch (e) {}
  }
  document.addEventListener('keydown', e => {
    if ([' ', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Tab'].includes(e.key) && e.target === document.body) e.preventDefault();
  }, true);
  ['pointerdown', 'mousedown', 'keydown', 'touchstart'].forEach(ev => document.addEventListener(ev, wake, true));
  setInterval(wake, 1000);
})();

// dev hook: ?audiolog=1 prints the RMS of the emulator's audio ring buffer every 2 s
if (new URLSearchParams(location.search).get('audiolog')) {
  setInterval(() => {
    try {
      const b = myClass.audioBufferResampled; let s = 0;
      for (let i = 0; i < b.length; i++) s += b[i] * b[i];
      console.log('audiolog rms=' + Math.sqrt(s / b.length).toFixed(1) + ' state=' + myClass.audioContext.state);
    } catch (e) { console.log('audiolog n/a'); }
  }, 2000);
}
"""

KEYMAP = {  # N64Wasm defaults -> Doom 64 (default config: Z fire, C> use, C^ map, C< run, Cv strafe, L/R strafe, A/B weapons)
    "Mapping_Up": "'w'", "Mapping_Down": "'s'", "Mapping_Left": "','", "Mapping_Right": "'.'",
    "Mapping_Action_A": "'q'", "Mapping_Action_B": "'r'", "Mapping_Action_Start": "'Enter'",
    "Mapping_Action_CUP": "'m'", "Mapping_Action_CDOWN": "'c'", "Mapping_Action_CLEFT": "'shift'",
    "Mapping_Action_CRIGHT": "'e'", "Mapping_Action_Z": "' '", "Mapping_Action_L": "'a'", "Mapping_Action_R": "'d'",
    "Joy_Mapping_Action_A": "2", "Joy_Mapping_Action_B": "3", "Joy_Mapping_Action_Z": "7",
    "Joy_Mapping_Action_L": "4", "Joy_Mapping_Action_R": "5", "Joy_Mapping_Action_CLEFT": "1",
    "Joy_Mapping_Action_CRIGHT": "0", "Joy_Mapping_Action_CUP": "8", "Joy_Mapping_Action_CDOWN": "6",
}
# letters arrive upper-case while Shift (run) is held: match mappings case-insensitively
NORMALIZE_KEY = """
        if (event.key && (event.key.length == 1 || event.key == 'Shift')) event = { key: event.key.toLowerCase() };"""

SOUND_HINT = """<div id="soundHint" style="max-width:720px;margin:8px auto;padding:6px 10px;background:#fff3cd;
border:1px solid #e0c060;border-radius:6px;font-size:14px">Sound starts after your first click or key press
on this page (browsers block audio until then).</div>"""


INFO = """
<div style="max-width:720px;margin:16px auto;font-size:14px;line-height:1.45;text-align:left">
<p><b>Controls</b> (keyboard): <b>arrow keys</b> = stick (turn / move) &middot; <b>W</b>/<b>S</b> = forward / back &middot;
<b>A</b>/<b>D</b> = strafe &middot; <b>Space</b> = fire &middot; <b>E</b> = use / open &middot; <b>Shift</b> = run &middot;
<b>Q</b>/<b>R</b> = previous / next weapon (and select / back in menus) &middot; <b>M</b> = map &middot;
<b>C</b> = strafe modifier &middot; <b>Enter</b> = Start (menus, pause).
<b>Gamepad</b>: left stick move/turn, RT fire, LB/RB strafe, A use, B run, X/Y weapons, Back map, LT strafe modifier, Start.
Remap anything under the <code>`</code> menu.</p>
<p>Doom 64 built from <a href="https://github.com/Erick194/DOOM64-RE">DOOM64-RE</a> (Erick194, GPL-3) with an SDK-free
toolchain. Every sprite, wall/floor texture, sky, font, menu symbol, HUD icon and picture (title, credits, legal
screens) and every instrument / sound-effect sample was regenerated from coarse facts (size, format, a colour grid,
a 2-bit alpha outline; sample length, loops, pitch and a spectral outline) or drawn from scratch &mdash; no original
pixels or samples are included. Level geometry, music note data, demo inputs, text and game code come from the
decomp / level data. Runs on <a href="https://github.com/nbarkhina/N64Wasm">N64Wasm</a> (MIT).
Source: <a href="https://github.com/andrewnakas/doom64-cleanroom">andrewnakas/doom64-cleanroom</a>.</p>
</div>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("rom")
    ap.add_argument("--n64wasm", default="C:/Users/andre/n64work/n64wasm/dist")
    ap.add_argument("--index", default=os.path.join(HERE, "index.html"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    for f in ("assets.zip", "n64wasm.js", "n64wasm.wasm", "settings.js"):
        shutil.copy(os.path.join(a.n64wasm, f), os.path.join(a.out, f))
    src = open(os.path.join(a.n64wasm, "script.js"), encoding="utf-8").read()
    old_start = src.index("    async initModule(){")
    old_end = src.index("    //not being used currently")
    src = src[:old_start] + AUTOLOAD.lstrip("\n") + "\n" + src[old_end:]
    # callMain / LoadSram can throw a bare value in some runs (seen headless), which skipped
    # showing the canvas: keep going and log it instead
    src = src.replace("Module.callMain(['custom.v64']);",
                      "try { Module.callMain(['custom.v64']); } catch (e) { console.log('callMain threw', e); }", 1)
    src = src.replace("await this.LoadSram();",
                      "try { await this.LoadSram(); } catch (e) { console.log('LoadSram threw', e); }", 1)
    # IndexedDB can answer before `myClass` exists on a slow page load (TDZ ReferenceError)
    src = src.replace("myClass.dblist.push(rom);", "try { myClass.dblist.push(rom); } catch (e) {}", 1)
    src = src.replace("if (myClass.dblist.length > 0) {", "if (false) {", 1)
    # per-game key mapping storage (all the clean-room sites share one origin)
    src = src.replace("n64wasm_mappings_v3", "doom64cr_mappings_v1")
    open(os.path.join(a.out, "script.js"), "w", encoding="utf-8").write(KEYS_JS + src)
    ic = open(os.path.join(a.n64wasm, "input_controller.js"), encoding="utf-8").read()
    for k, v in KEYMAP.items():
        ic, n = re.subn(r"(%s: )([^,]+),\n" % k, lambda m: m.group(1) + v + ",\n", ic, count=1)
        if not n:
            raise SystemExit("keymap default not found: " + k)
    for fn in ("keyDown(event) {", "keyUp(event) {"):
        ic = ic.replace(fn, fn + NORMALIZE_KEY, 1)
    open(os.path.join(a.out, "input_controller.js"), "w", encoding="utf-8").write(ic)
    open(os.path.join(a.out, "romlist.js"), "w").write("var ROMLIST = [];\nwindow.SITE_ROM = 'game.z64';\n")
    idx = a.index if os.path.exists(a.index) else os.path.join(a.n64wasm, "index.html")
    html = open(idx, encoding="utf-8").read()
    html = html.replace("<title>N64 Wasm</title>", "<title>Doom 64 clean room</title>")
    html = re.sub(r"<h1>\s*N64 Wasm", '<h1>Doom 64 <small style="font-size:50%">clean room</small>', html, 1)
    html = html.replace('<div id="bottomPanel"', SOUND_HINT + INFO + '<div id="bottomPanel"', 1)
    # serve the page's libraries ourselves (a slow or blocked CDN left the emulator hidden)
    vend = os.path.join(HERE, "vendor")
    os.makedirs(os.path.join(a.out, "vendor"), exist_ok=True)
    for m in re.finditer(r'(?:src|href)="(https?://[^"]+\.(?:js|css))"', html):
        name = m.group(1).rsplit("/", 1)[1]
        if os.path.exists(os.path.join(vend, name)):
            shutil.copy(os.path.join(vend, name), os.path.join(a.out, "vendor", name))
            html = html.replace(m.group(1), "vendor/" + name)
    open(os.path.join(a.out, "index.html"), "w", encoding="utf-8").write(html)
    open(os.path.join(a.out, ".nojekyll"), "w").write("")
    shutil.copy(a.rom, os.path.join(a.out, "game.z64"))
    print("site ->", a.out)


if __name__ == "__main__":
    main()
