"""DIRTY ROOM: retail lumps -> clean-room spec (coarse facts only).

    python games/doom64/spec_extract.py <dirty lumps dir> <spec dir>

Per graphic lump: header fields (format, size, offsets, tiling, palette links),
an alpha-weighted colour grid (4x4; 16x16 when >= 128 px), a 2-bit alpha
outline when the image has transparency, and for palette variants a 3x4 colour
matrix (variant ~ M @ [r,g,b,1] of the base palette). Kept verbatim (user-approved
facts): MAPxx (level geometry/things/lights), DEMOxLMP (demo inputs).
Writes spec/lumps.json (directory order + facts) and spec/kept/<name>.lmp.
"""
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wadfmt  # noqa: E402

KEEP_KINDS = ("map", "demo")


def grid(rgba, n):
    h, w = rgba.shape[:2]
    a = rgba[..., 3:4].astype(np.float64) / 255.0
    rgb = rgba[..., :3].astype(np.float64)
    tot = (rgb * a).sum((0, 1)) / max(a.sum(), 1e-6)
    out = []
    for gy in range(n):
        for gx in range(n):
            y0, y1 = gy * h // n, max(gy * h // n + 1, (gy + 1) * h // n)
            x0, x1 = gx * w // n, max(gx * w // n + 1, (gx + 1) * w // n)
            ca = a[y0:y1, x0:x1]
            s = ca.sum()
            c = (rgb[y0:y1, x0:x1] * ca).sum((0, 1)) / s if s > 0 else tot
            out.append([int(round(v)) for v in c])
    return out


def alpha2(alpha):
    a = (alpha.astype(np.uint8) >> 6).ravel()
    a = np.concatenate([a, np.zeros((-len(a)) % 4, np.uint8)])
    return ((a[0::4] << 6) | (a[1::4] << 4) | (a[2::4] << 2) | a[3::4]).astype(np.uint8).tobytes().hex()


def color_matrix(base, var):
    """Least-squares 3x4 matrix mapping base palette colours to a variant."""
    X = np.concatenate([base[:, :3].astype(np.float64) / 255, np.ones((len(base), 1))], 1)
    Y = var[:, :3].astype(np.float64) / 255
    M, *_ = np.linalg.lstsq(X, Y, rcond=None)
    return [[round(float(v), 4) for v in row] for row in M.T]


def header_meta(meta):
    keep = {}
    for k, v in meta.items():
        if k.startswith("_"):
            if isinstance(v, (bytes, bytearray)):
                keep[k[1:] + "_len"] = len(v)
            continue
        keep[k] = v
    if "_palettes" in meta:
        keep["numpal"] = len(meta["_palettes"])
    return keep


def main():
    lumps, spec = Path(sys.argv[1]), Path(sys.argv[2])
    (spec / "kept").mkdir(parents=True, exist_ok=True)
    rows = wadfmt.read_index(lumps)
    out, counts = [], {}
    for r in rows:
        kind = r["kind"]
        e = {"index": r["index"], "name": r["name"], "kind": kind, "size": r["size"]}
        counts[kind] = counts.get(kind, 0) + 1
        b = wadfmt.load_lump(lumps, r["index"]) if r["size"] else b""
        if kind in KEEP_KINDS:
            (spec / "kept" / f"{r['name']}.lmp").write_bytes(b)
            e["kept"] = True
        elif kind == "palette":
            base_idx = r["index"]
            while not rows[base_idx]["name"].endswith("0"):
                base_idx -= 1
            e["header"] = b[:8].hex()
            if base_idx != r["index"]:
                base = wadfmt.pal_to_rgba(wadfmt.load_lump(lumps, base_idx)[8:520])
                var = wadfmt.pal_to_rgba(b[8:520])
                e["variant_of"] = rows[base_idx]["name"]
                e["matrix"] = color_matrix(base, var)
        elif kind == "sprite":
            pal, src = wadfmt.resolve_sprite_palette(lumps, rows, r["index"])
            rgba, meta = wadfmt.decode_sprite(b, pal)
            e["meta"] = header_meta(meta)
            e["palette_lump"] = src
            add_image_facts(e, rgba)
        elif kind == "texture":
            imgs = wadfmt.decode_texture(b)
            e["meta"] = header_meta(imgs[0][1])
            add_image_facts(e, imgs[0][0])
            if len(imgs) > 1:
                base = wadfmt.pal_to_rgba(imgs[0][1]["_palettes"][0])
                e["variants"] = [color_matrix(base, wadfmt.pal_to_rgba(p)) for p in imgs[0][1]["_palettes"][1:]]
        elif kind in ("sprite_gfx", "gfx", "fire", "cloud"):
            rgba, meta = wadfmt.decode_gfx(b, r["name"])
            e["meta"] = header_meta(meta)
            if "_header" in meta:
                e["meta"]["header"] = meta["_header"].hex()
            add_image_facts(e, rgba)
        out.append(e)
    (spec / "lumps.json").write_text(json.dumps(out, separators=(",", ":")))
    print("spec:", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print("kept:", sum(1 for e in out if e.get("kept")), "lumps ->", spec / "kept")


def add_image_facts(e, rgba):
    h, w = rgba.shape[:2]
    n = 16 if max(w, h) >= 128 else 4
    e["grid"] = grid(rgba, n)
    if (rgba[..., 3] < 250).any():
        e["alpha2"] = alpha2(rgba[..., 3])


if __name__ == "__main__":
    main()
