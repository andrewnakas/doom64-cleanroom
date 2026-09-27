"""CLEAN ROOM: wall/floor texture synthesis.

Colour comes from the kept 4x4 grid; structure is ours, chosen by the texture's name family
(the names are the WAD directory, a kept fact): stone blocks (castle C*), riveted metal panels
(tech S*/SPACE*), cracked rock (hell H*), smooth liquids. Everything tiles (periodic noise).
"""
import numpy as np

LIQUIDS = ("WATER", "BLOOD", "SLIME", "SLUDGE", "WFALL")


def pnoise(seed, w, h, cell, octaves=3):
    """Periodic value noise (tiles on a w x h torus)."""
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w), np.float32)
    amp = 1.0
    for o in range(octaves):
        c = max(1.0, cell / (2 ** o))
        gy, gx = max(1, int(round(h / c))), max(1, int(round(w / c)))
        lat = rng.standard_normal((gy, gx)).astype(np.float32)
        ys = np.arange(h, dtype=np.float32) * gy / h
        xs = np.arange(w, dtype=np.float32) * gx / w
        y0, x0 = ys.astype(int), xs.astype(int)
        fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
        fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
        y1, x1 = (y0 + 1) % gy, (x0 + 1) % gx
        out += amp * ((lat[y0][:, x0] * (1 - fx) + lat[y0][:, x1] * fx) * (1 - fy)
                      + (lat[y1][:, x0] * (1 - fx) + lat[y1][:, x1] * fx) * fy)
        amp *= 0.5
    return out


def family(name):
    if name.startswith(LIQUIDS):
        return "liquid"
    if name.startswith(("SPACE", "SDOOR", "SMON", "SW", "STRA", "SFLA", "SDFL", "SPORT", "SEXIT", "SPAC", "CTEL")):
        return "metal"
    if name.startswith(("H", "HELL")):
        return "rock"
    if name.startswith(("C", "TITLE")):
        return "stone"
    return "plain"


def blocks(w, h, seed, rows, cols, stagger=True, mortar=1):
    """Brick/block layout: per-pixel block id, and a mortar + bevel mask."""
    yy, xx = np.mgrid[0:h, 0:w]
    bh, bw = h / rows, w / cols
    r = (yy // bh).astype(int)
    off = ((r % 2) * bw / 2) if stagger else 0
    c = (((xx + off) % w) // bw).astype(int)
    fy = (yy % bh) / bh
    fx = (((xx + off) % w) % bw) / bw
    rng = np.random.default_rng(seed)
    jit = rng.uniform(-1, 1, (rows, cols + 1)).astype(np.float32)
    ids = jit[r, c]
    my, mx = mortar / bh, mortar / bw
    joint = (fy < my) | (fx < mx)
    bevel = np.where(fy < my * 2.5, 0.25, 0) + np.where(fx < mx * 2.5, 0.15, 0) \
        - np.where(fy > 1 - my * 2, 0.25, 0) - np.where(fx > 1 - mx * 2, 0.15, 0)
    return ids, joint, bevel


def synth(name, col, w, h, seed):
    """col: h x w x 3 grid colour. Returns h x w x 3 float."""
    fam = family(name)
    n = pnoise(seed, w, h, cell=max(4.0, min(w, h) / 6), octaves=4)
    sp = special(name, col, w, h, seed, n)
    if sp is not None:
        return sp
    if fam == "liquid":
        wave = pnoise(seed + 1, w, h, cell=max(8.0, min(w, h) / 3), octaves=2)
        return col * (1.0 + 0.18 * wave[..., None] + 0.05 * n[..., None])
    if fam == "stone":
        rows = max(1, h // 16)
        cols = max(1, w // 32)
        ids, joint, bevel = blocks(w, h, seed, rows, cols, stagger=True)
        shade = 1.0 + 0.10 * ids + 0.9 * bevel * 0.4 + 0.10 * n
        shade = np.where(joint, 0.45, shade)
        return col * shade[..., None]
    if fam == "metal":
        rows = max(1, h // 32)
        cols = max(1, w // 32)
        ids, joint, bevel = blocks(w, h, seed, rows, cols, stagger=False)
        yy, xx = np.mgrid[0:h, 0:w]
        bh, bw = h / rows, w / cols
        fy, fx = (yy % bh), (xx % bw)
        rivet = np.zeros((h, w), bool)
        for cy in (3, bh - 4):
            for cx in (3, bw - 4):
                rivet |= ((fy - cy) ** 2 + (fx - cx) ** 2) <= 1.5
        brushed = pnoise(seed + 2, w, h, cell=2.0, octaves=1) * 0.04
        shade = 1.0 + 0.06 * ids + 0.5 * bevel + 0.06 * n + brushed
        shade = np.where(joint, 0.5, shade)
        shade = np.where(rivet, 1.35, shade)
        return col * shade[..., None]
    if fam == "rock":
        # cellular cracks: distance to the nearest of a periodic set of points
        rng = np.random.default_rng(seed)
        k = max(4, (w * h) // 256)
        pts = rng.uniform(0, 1, (k, 2)) * [h, w]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        d1 = np.full((h, w), 1e9, np.float32)
        d2 = np.full((h, w), 1e9, np.float32)
        for py, px in pts:
            dy = np.minimum(np.abs(yy - py), h - np.abs(yy - py))
            dx = np.minimum(np.abs(xx - px), w - np.abs(xx - px))
            d = np.sqrt(dy * dy + dx * dx)
            d2 = np.where(d < d1, d1, np.minimum(d2, d))
            d1 = np.minimum(d1, d)
        crack = np.clip((d2 - d1) / 2.5, 0, 1)
        shade = (0.55 + 0.45 * crack) * (1.0 + 0.16 * n)
        return col * shade[..., None]
    return col * (1.0 + 0.12 * n[..., None])


# ------------------------------------------------------------------ faces and screens
# Carved faces (gargoyles, demon masks) and computer screens, by texture name (kept directory facts).
FACES = ("C1", "C22", "C23", "C302", "C306", "C307", "C307B", "C308", "C42", "C58", "C62", "C63",
         "CFACEA", "CFACEB", "CFACEC", "H30", "H31", "H66", "HELLAS")
SCREENS = ("SMON",)


def _ellipse(yy, xx, cy, cx, ry, rx):
    return np.clip(1 - ((yy - cy) / ry) ** 2 - ((xx - cx) / rx) ** 2, 0, 1)


def relief_face(w, h, seed, horns=True):
    """Height field of a carved demon face filling the texture (0..1)."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cy, cx = h * rng.uniform(0.5, 0.58), w * 0.5
    ew, ms, hw = rng.uniform(0.1, 0.16), rng.uniform(0.12, 0.2), rng.uniform(0.3, 0.4)
    H = 0.6 * np.sqrt(_ellipse(yy, xx, cy, cx, h * 0.42, w * hw))                     # head mass
    brow = np.sqrt(_ellipse(yy, xx, cy - h * 0.12, cx, h * 0.07, w * 0.3)) * 0.35
    H = H + brow
    for side in (-1, 1):
        H -= 0.45 * np.sqrt(_ellipse(yy, xx, cy - h * 0.02, cx + side * w * ew, h * 0.07, w * 0.08))  # sockets
        H += 0.25 * np.sqrt(_ellipse(yy, xx, cy - h * 0.02, cx + side * w * ew, h * 0.03, w * 0.035))  # eyeballs
        if horns:
            t = np.clip((cy - h * 0.2 - yy) / (h * 0.3), 0, 1)
            hx = cx + side * (w * 0.22 + t * w * 0.14 * rng.uniform(0.8, 1.2))
            H += 0.45 * np.clip(1 - np.abs(xx - hx) / (w * 0.06 * (1.1 - t)), 0, 1) * (t > 0) * (yy > h * 0.02)
    H += 0.35 * np.sqrt(_ellipse(yy, xx, cy + h * 0.1, cx, h * 0.1, w * 0.06))                 # nose
    my = cy + h * 0.25
    mouth = _ellipse(yy, xx, my, cx, h * 0.07, w * ms)
    H -= 0.45 * np.sqrt(mouth)
    # fangs: downward triangles hanging from the upper lip
    nf = int(rng.integers(3, 6))
    for k in range(nf):
        fx = cx + (k - (nf - 1) / 2) * (2 * w * ms / nf) * 0.8
        fl = h * (0.07 if k in (0, nf - 1) else 0.045)
        fw = w * 0.022
        tri = (yy >= my - h * 0.05) & (yy <= my - h * 0.05 + fl) &               (np.abs(xx - fx) <= fw * (1 - (yy - (my - h * 0.05)) / fl))
        H = np.where(tri & (mouth > 0), 0.55, H)
    return np.clip(H, 0, 1.2)


def emboss(Hm, col, n, light=(-0.6, -0.8)):
    gy, gx = np.gradient(Hm * 6)
    lam = np.clip((-gx * light[0] - gy * light[1] + 0.7) / np.sqrt(gx * gx + gy * gy + 1), 0, 1.3)
    shade = (0.45 + 0.7 * lam) * (0.8 + 0.35 * Hm) * (1 + 0.08 * n)
    return col * shade[..., None]


def screen(col, w, h, seed, family_seed):
    rng = np.random.default_rng(seed)
    frng = np.random.default_rng(family_seed)
    out = col * 0.8
    m = max(3, min(w, h) // 8)
    y0, y1, x0, x1 = m, h - m, m, w - m
    out[y0 - 1:y1 + 1, x0 - 1:x1 + 1] = col[y0:y1 + 2, x0:x1 + 2].mean((0, 1)) * 0.35
    glow = np.array(frng.choice([(60, 220, 90), (80, 180, 255), (230, 200, 60)]), np.float32)
    out[y0:y1, x0:x1] = glow * 0.12
    for y in range(y0 + 2, y1 - 2, 3):
        L = int(rng.integers(2, max(3, x1 - x0 - 4)))
        out[y, x0 + 2:x0 + 2 + L] = glow * rng.uniform(0.6, 1.0)
    out[y0:y1:2, x0:x1] *= 0.85                       # scanlines
    return out


def special(name, col, w, h, seed, n):
    if name.startswith(SCREENS):   # SMONxA..D are animation frames of one screen: same colour
        return screen(col, w, h, seed, sum(map(ord, name[:5])))
    if name in FACES:
        return emboss(relief_face(w, h, seed, horns=not name.startswith("CFACE")), col, n)
    return None
