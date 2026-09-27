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
