"""CLEAN ROOM: spec/ -> clean DOOM64.WAD (+ kept WMD/WSD, regenerated WDD) for build_rom.py.

    python games/doom64/generate.py <spec dir> <out Data dir> [--sheet <png dir>]

Reads only spec/lumps.json, spec/kept/ and our own drawers (drawn.py). Every
image lump is generated from its coarse facts (grid + 2-bit alpha outline) or a
drawer, quantised to fresh palettes, and packed with wadfmt's encoders (padding
bytes zeroed). Lumps are stored uncompressed (the game reads either form).
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage
from scipy.spatial import cKDTree
from sklearn.cluster import MiniBatchKMeans

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import wadfmt  # noqa: E402

try:
    import drawn  # noqa: E402  (per-lump drawers: text, pictures, fonts)
except ImportError:
    drawn = None


def h32(*parts):
    return int.from_bytes(hashlib.sha1("/".join(map(str, parts)).encode()).digest()[:4], "little")


# ------------------------------------------------------------------ facts -> rgba
def upsample_grid(g, w, h):
    n = int(round(len(g) ** 0.5))
    g = np.asarray(g, np.float32).reshape(n, n, 3)
    ys = (np.arange(h, dtype=np.float32) + 0.5) / h * n - 0.5
    xs = (np.arange(w, dtype=np.float32) + 0.5) / w * n - 0.5
    y0 = np.clip(np.floor(ys).astype(int), 0, n - 1)
    x0 = np.clip(np.floor(xs).astype(int), 0, n - 1)
    y1, x1 = np.clip(y0 + 1, 0, n - 1), np.clip(x0 + 1, 0, n - 1)
    fy = np.clip(ys - np.floor(ys), 0, 1)[:, None, None]
    fx = np.clip(xs - np.floor(xs), 0, 1)[None, :, None]
    top = g[y0][:, x0] * (1 - fx) + g[y0][:, x1] * fx
    bot = g[y1][:, x0] * (1 - fx) + g[y1][:, x1] * fx
    return top * (1 - fy) + bot * fy


def noise(seed, w, h, cell=4.0, octaves=2):
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w), np.float32)
    amp = 1.0
    for o in range(octaves):
        c = cell / (2 ** o)
        lat = rng.standard_normal((int(h / c) + 3, int(w / c) + 3)).astype(np.float32)
        ys, xs = np.arange(h, dtype=np.float32) / c, np.arange(w, dtype=np.float32) / c
        y0, x0 = ys.astype(int), xs.astype(int)
        fy, fx = (ys - y0)[:, None], (xs - x0)[None, :]
        fy, fx = fy * fy * (3 - 2 * fy), fx * fx * (3 - 2 * fx)
        out += amp * ((lat[y0][:, x0] * (1 - fx) + lat[y0][:, x0 + 1] * fx) * (1 - fy)
                      + (lat[y0 + 1][:, x0] * (1 - fx) + lat[y0 + 1][:, x0 + 1] * fx) * fy)
        amp *= 0.5
    return out


def alpha_of(e, w, h):
    if "alpha2" not in e:
        return np.full((h, w), 255, np.uint8)
    b = np.frombuffer(bytes.fromhex(e["alpha2"]), np.uint8)
    a = np.empty(len(b) * 4, np.uint8)
    a[0::4], a[1::4], a[2::4], a[3::4] = b >> 6, (b >> 4) & 3, (b >> 2) & 3, b & 3
    return np.where(a[: w * h].reshape(h, w) >= 2, 255, 0).astype(np.uint8)


def shaded_sprite(e, w, h):
    """Silhouette + coarse colour -> a lit, rounded figure (pillow shading from the outline)."""
    a = alpha_of(e, w, h)
    m = a > 0
    col = upsample_grid(e["grid"], w, h)
    if not m.any():
        return np.dstack([col, a]).clip(0, 255).astype(np.uint8)
    size = max(4.0, np.sqrt(m.sum()) / 6)
    d = ndimage.distance_transform_edt(m).astype(np.float32)
    hgt = np.sqrt(np.minimum(d, size * 2.5) / (size * 2.5))
    hgt = ndimage.gaussian_filter(hgt, max(1.0, size / 5))
    hgt += 0.10 * noise(h32("bump", e["name"]), w, h, cell=max(2.0, size / 2), octaves=3)
    gy, gx = np.gradient(hgt * size * 1.2)
    nz = np.ones_like(gx)
    nrm = np.sqrt(gx * gx + gy * gy + nz * nz)
    lx, ly, lz = -0.45, -0.6, 0.66
    lam = np.clip((-gx * lx - gy * ly + nz * lz) / nrm, 0, 1)
    shade = 0.45 + 0.75 * lam
    rim = (d <= 1.0) & m
    shade = np.where(rim, shade * 0.55, shade)
    shade *= 1.0 + 0.06 * noise(h32("grain", e["name"]), w, h, cell=2.0)
    rgb = col * shade[..., None]
    return np.dstack([rgb, a]).clip(0, 255).astype(np.uint8)


def textured(e, w, h, amount=0.10):
    col = upsample_grid(e["grid"], w, h)
    n = noise(h32("tex", e["name"]), w, h, cell=8.0, octaves=3)
    col *= (1.0 + amount * n)[..., None]
    return np.dstack([col, alpha_of(e, w, h)]).clip(0, 255).astype(np.uint8)


def fire_image(e, w, h):
    rng = np.random.default_rng(h32("fire"))
    ys = np.linspace(0, 1, h, dtype=np.float32)[:, None]
    n = noise(h32("fire", 1), w, h, cell=6.0, octaves=4) * 0.35 + rng.random((h, w)) * 0.25
    v = np.clip(ys * 1.4 - 0.35 + n, 0, 1) ** 1.3 * 255
    return np.dstack([v, v, v, np.full_like(v, 255)]).astype(np.uint8)


def cloud_image(e, w, h):
    # tileable: noise on a torus by wrapping the lattice
    n = noise(h32("cloud"), w * 2, h * 2, cell=16.0, octaves=4)
    n = n[:h, :w] * 0.5 + n[h:, w:] * 0.5
    v = np.clip(0.5 + 0.35 * n, 0, 1) * 255
    return np.dstack([v, v, v, np.full_like(v, 255)]).astype(np.uint8)


def image_for(e):
    m = e["meta"]
    w, h = m["width"], m["height"]
    if drawn is not None:
        img = drawn.draw(e, w, h)
        if img is not None:
            return img
    if e["kind"] == "fire":
        return fire_image(e, w, h)
    if e["kind"] == "cloud":
        return cloud_image(e, w, h)
    if e["kind"] == "texture":
        return textured(e, w, h)
    if e["kind"] in ("sprite", "sprite_gfx"):
        return shaded_sprite(e, w, h)
    return textured(e, w, h, 0.06)


# ------------------------------------------------------------------ palettes
def fit_palette(pixels, n, seed):
    """k-means colours (5-bit) for an Nx3 pixel set."""
    px = np.asarray(pixels, np.float32)
    if len(px) > 60000:
        px = px[np.random.default_rng(seed).choice(len(px), 60000, replace=False)]
    uniq = np.unique((px.astype(np.int32) >> 3), axis=0)
    if len(uniq) <= n:
        cents = (uniq << 3 | 4).astype(np.float32)
    else:
        km = MiniBatchKMeans(n, random_state=seed % (2 ** 31), n_init=1, batch_size=4096, max_iter=60)
        cents = km.fit(px).cluster_centers_
    pal = np.zeros((n, 4), np.uint8)
    pal[: len(cents), :3] = np.clip(cents, 0, 255)
    pal[: len(cents), 3] = 255
    if len(cents) < n:
        pal[len(cents):] = pal[0]
    return pal


def make_palette(images, ncolors, seed):
    """Palette with index 0 transparent when any image has transparency."""
    trans = any((im[..., 3] < 128).any() for im in images)
    px = np.concatenate([im[..., :3][im[..., 3] >= 128] for im in images] + [np.zeros((0, 3), np.uint8)])
    if len(px) == 0:
        px = np.zeros((1, 3), np.uint8)
    if trans:
        pal = np.zeros((ncolors, 4), np.uint8)
        pal[1:] = fit_palette(px, ncolors - 1, seed)
        return pal
    return fit_palette(px, ncolors, seed)


def index_image(img, pal):
    opaque = np.flatnonzero(pal[:, 3] >= 128)
    tree = cKDTree(pal[opaque, :3].astype(np.float32))
    flat = img.reshape(-1, 4)
    _, k = tree.query(flat[:, :3].astype(np.float32))
    idx = opaque[k].astype(np.uint8)
    tr = np.flatnonzero(pal[:, 3] < 128)
    if len(tr):
        idx[flat[:, 3] < 128] = tr[0]
    return idx.reshape(img.shape[:2])


def apply_matrix(pal, M):
    M = np.asarray(M, np.float32)
    X = np.concatenate([pal[:, :3].astype(np.float32) / 255, np.ones((len(pal), 1), np.float32)], 1)
    out = pal.copy()
    out[:, :3] = np.clip(X @ M.T * 255, 0, 255)
    return out


def clean_meta(e):
    """wadfmt encoder meta from spec facts: padding/tails are zero bytes of the recorded length."""
    m = dict(e["meta"])
    for k in list(m):
        if k.endswith("_len"):
            m["_" + k[:-4]] = b"\0" * m.pop(k)
    if "header" in m:
        m["_header"] = bytes.fromhex(m.pop("header"))
    return m


# ------------------------------------------------------------------ main
def generate(spec: Path):
    lumps = json.loads((spec / "lumps.json").read_text())
    by_name = {e["name"]: e for e in lumps}
    imgs = {}
    for e in lumps:
        if "meta" in e:
            imgs[e["name"]] = image_for(e)
    out = {}

    # sprite families that share a palette (PALxxxx lump, or a weapon's first frame)
    fam = {}
    for e in lumps:
        if e["kind"] == "sprite" and e.get("palette_lump") not in (None, "embedded"):
            fam.setdefault(e["palette_lump"], []).append(e["name"])
    fam_pal = {}
    for src, names in fam.items():
        members = names + ([src] if src in imgs else [])
        fam_pal[src] = make_palette([imgs[n] for n in members], 256, h32("pal", src))

    for e in lumps:
        name, kind = e["name"], e["kind"]
        if e.get("kept"):
            out[name] = (spec / "kept" / f"{name}.lmp").read_bytes()
        elif kind == "marker":
            out[name] = b""
        elif kind == "palette":
            base = e.get("variant_of")
            pal = fam_pal[name] if base is None else apply_matrix(fam_pal[base], e["matrix"])
            pal[0] = 0
            out[name] = bytes.fromhex(e["header"]) + wadfmt.rgba_to_pal(pal)
        elif kind in ("sprite", "sprite_gfx"):
            m = clean_meta(e)
            img = imgs[name]
            if m["palette_source"] == "external":
                pal = fam_pal[e["palette_lump"]]
                out[name] = wadfmt.encode_sprite(index_image(img, pal), m)
            else:
                n = 256 if m["format"] == "ci8" else 16
                pal = fam_pal[name] if name in fam_pal else make_palette([img], n, h32("pal", name))
                out[name] = wadfmt.encode_sprite(index_image(img, pal), m, wadfmt.rgba_to_pal(pal))
        elif kind == "texture":
            m = clean_meta(e)
            img = imgs[name]
            pal = make_palette([img], 16, h32("pal", name))
            pals = [pal] + [apply_matrix(pal, M) for M in e.get("variants", [])]
            out[name] = wadfmt.encode_texture(index_image(img, pal), m, [wadfmt.rgba_to_pal(p) for p in pals])
        elif kind in ("gfx", "fire", "cloud"):
            m = clean_meta(e)
            img = imgs[name]
            if m["format"] == "i8":
                out[name] = wadfmt.encode_gfx(img, m, name=name)
            else:
                pal = make_palette([img], 256, h32("pal", name))
                out[name] = wadfmt.encode_gfx(index_image(img, pal), m, wadfmt.rgba_to_pal(pal), name=name)
        else:
            raise SystemExit(f"unhandled lump {name} ({kind})")
    return lumps, out, imgs


def write_wad(lumps, out, path: Path):
    body = bytearray()
    dirs = []
    for e in lumps:
        b = out[e["name"]]
        pos = 12 + len(body)
        body += b
        body += b"\0" * ((-len(body)) % 8)
        dirs.append(struct.pack("<ii8s", pos, len(b), e["name"].encode()[:8]))
    ofs = 12 + len(body)
    path.write_bytes(b"IWAD" + struct.pack("<ii", len(lumps), ofs) + bytes(body) + b"".join(dirs))
    return ofs + 16 * len(lumps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("data")
    ap.add_argument("--sheet", default="")
    ap.add_argument("--kept-audio", default="", help="dir with the kept DOOM64.WMD/WSD (facts)")
    a = ap.parse_args()
    spec, data = Path(a.spec), Path(a.data)
    data.mkdir(parents=True, exist_ok=True)
    lumps, out, imgs = generate(spec)
    size = write_wad(lumps, out, data / "DOOM64.WAD")
    print(f"WAD: {len(lumps)} lumps, {size / 1e6:.1f} MB (uncompressed) -> {data / 'DOOM64.WAD'}")
    audio = HERE / "audio_gen.py"
    if audio.exists():
        import audio_gen  # noqa: E402
        audio_gen.main_gen(spec, data)
    if a.sheet:
        sheets(lumps, imgs, Path(a.sheet))


def sheets(lumps, imgs, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    groups = {"gfx": [], "sprites": [], "textures": []}
    for e in lumps:
        if e["name"] not in imgs:
            continue
        g = "textures" if e["kind"] == "texture" else "sprites" if e["kind"] == "sprite" else "gfx"
        groups[g].append({"name": e["name"], "rgba": imgs[e["name"]]})
    for g, items in groups.items():
        wadfmt.make_sheets([(it["name"], it["rgba"]) for it in items], f"clean_{g}", outdir)
    print("sheets ->", outdir)


if __name__ == "__main__":
    main()
