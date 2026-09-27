"""Doom 64 WAD graphic lump formats: decode to RGBA, encode back byte-exact.

Dirty-room tool (reads retail lumps). Formats are derived from how the game
(Erick194/DOOM64-RE) uploads each kind to the RDP:

  palette  RGBA5551 big-endian u16; alpha bit 0 = transparent.
  TMEM swizzle: every image the game loads with gDPLoadBlock(..., dxt=0) is
      stored pre-swizzled: on odd rows (relative to the start of each loaded
      block) the two 32-bit words of every 64-bit TMEM line are swapped.
      Images loaded with LoadTile (gfx pictures, SYMBOLS) or LoadBlock with a
      real dxt (FIRE) are stored linear.

  sprite  (S_START..S_END, also SFONT, STATUS, SPACE, MOUNTA/B/C)
      16-byte header, all BE: u16 tiles, s16 compressed (<0: CI8, >=0: CI4),
      u16 cmpsize, s16 xoffs, s16 yoffs, u16 width, u16 height, u16 tileheight.
      CI8: row width padded to 8 texels, pixels = w8*h bytes. If cmpsize is
        odd the palette is external: lump[this - (cmpsize>>1)] is a PALxxxx
        lump (world things: palette at +8, plus mobjinfo.palette variant) or a
        weapon frame that embeds its palette. Else 256-colour palette at
        16+cmpsize.
      CI4: row width padded to 16 texels, pixels = w16*h/2 bytes = cmpsize,
        16-colour palette (32 bytes) at 16+cmpsize.
      Image is split into `tiles` blocks of `tileheight` rows (last block
      shorter); swizzle row parity restarts at every block.
  palette lump (PALxxxx): 8-byte header (s16 0, s16 256, s16, s16) + 512 bytes.
  texture (T_START..T_END): 8-byte header s16 id, s16 numpal, s16 wshift,
      s16 hshift; CI4 (1<<ws)x(1<<hs) swizzled, then numpal*16 colours.
  gfx (USLEGAL, TITLE, EVIL, ..., SYMBOLS): 8-byte header s16 compressed(-1),
      s16 numpal, s16 width, s16 height; CI8 w*h linear, padded to 8 bytes,
      then 256-colour palette.
  FIRE: gfx header (numpal 0), 64x64 I8 linear, no palette.
  CLOUD: 8-byte header (2,-1,6,5), 64x64 I8 (LoadBlock dxt=0 => swizzled),
      then 512 unused bytes (kept verbatim).

CLI:
  python games/doom64/wadfmt.py dump <lumpdir> <outdir>
  python games/doom64/wadfmt.py selftest <lumpdir>
"""
import json
import struct
import sys
from pathlib import Path

import numpy as np

SPRITE_GFX = ("SFONT", "STATUS", "SPACE", "MOUNTA", "MOUNTB", "MOUNTC")
PLAIN_GFX = ("SYMBOLS", "USLEGAL", "PLLEGAL", "TITLE", "EVIL", "IDCRED1", "IDCRED2",
             "WMSCRED1", "WMSCRED2", "FINAL")

# ---------------------------------------------------------------- code tables
# st_main.c symboldata[]: (x, y, w, h) rectangles inside SYMBOLS (259x113).
SYMBOL_NAMES = (list("0123456789") + ["-", "%", "!", ".", "?", ":"]
                + [chr(c) for c in range(65, 91)] + [chr(c) for c in range(97, 123)]
                + ["slider_bar", "slider_gem"] + ["skull%d" % i for i in range(1, 9)]
                + ["arrow_right", "select_box", "dpad_left", "dpad_right", "dpad_up",
                   "dpad_down", "c_left", "c_right", "c_up", "c_down", "btn_l", "btn_r",
                   "btn_a", "btn_b", "btn_z", "btn_start", "arrow_down", "arrow_up",
                   "arrow_left"])
SYMBOL_RECTS = [
    (120, 14, 13, 13), (134, 14, 9, 13), (144, 14, 14, 13), (159, 14, 14, 13),
    (174, 14, 16, 13), (191, 14, 13, 13), (205, 14, 13, 13), (219, 14, 14, 13),
    (234, 14, 14, 13), (0, 29, 13, 13), (67, 28, 14, 13), (36, 28, 15, 14),
    (28, 28, 7, 14), (14, 29, 6, 13), (52, 28, 13, 13), (21, 29, 6, 13),
    (0, 0, 13, 13), (14, 0, 13, 13), (28, 0, 13, 13), (42, 0, 14, 13), (57, 0, 14, 13),
    (72, 0, 10, 13), (87, 0, 15, 13), (103, 0, 15, 13), (119, 0, 6, 13), (122, 0, 13, 13),
    (140, 0, 14, 13), (155, 0, 11, 13), (167, 0, 15, 13), (183, 0, 16, 13), (200, 0, 15, 13),
    (216, 0, 13, 13), (230, 0, 15, 13), (246, 0, 13, 13), (0, 14, 14, 13), (15, 14, 14, 13),
    (30, 14, 13, 13), (44, 14, 15, 13), (60, 14, 15, 13), (76, 14, 15, 13), (92, 14, 13, 13),
    (106, 14, 13, 13),
    (83, 31, 10, 11), (93, 31, 10, 11), (103, 31, 11, 11), (114, 31, 11, 11),
    (125, 31, 11, 11), (136, 31, 11, 11), (147, 31, 12, 11), (159, 31, 12, 11),
    (171, 31, 4, 11), (175, 31, 10, 11), (185, 31, 11, 11), (196, 31, 9, 11),
    (205, 31, 12, 11), (217, 31, 13, 11), (230, 31, 12, 11), (242, 31, 11, 11),
    (0, 43, 12, 11), (12, 43, 11, 11), (23, 43, 11, 11), (34, 43, 10, 11), (44, 43, 11, 11),
    (55, 43, 12, 11), (67, 43, 13, 11), (80, 43, 13, 11), (93, 43, 10, 11), (103, 43, 11, 11),
    (0, 95, 108, 11), (108, 95, 6, 11),
    (0, 54, 32, 26), (32, 54, 32, 26), (64, 54, 32, 26), (96, 54, 32, 26),
    (128, 54, 32, 26), (160, 54, 32, 26), (192, 54, 32, 26), (224, 54, 32, 26),
    (134, 97, 7, 11), (114, 95, 20, 18),
    (105, 80, 15, 15), (120, 80, 15, 15), (135, 80, 15, 15), (150, 80, 15, 15),
    (45, 80, 15, 15), (60, 80, 15, 15), (75, 80, 15, 15), (90, 80, 15, 15),
    (165, 80, 15, 15), (180, 80, 15, 15), (0, 80, 15, 15), (15, 80, 15, 15),
    (195, 80, 15, 15), (30, 80, 15, 15),
    (156, 96, 13, 13), (143, 96, 13, 13), (169, 96, 7, 13),
]
# Note: the game's LoadTile/TextureRectangle uses x..x+w inclusive (w+1 columns),
# the rectangle above is the table value.


def sfont_rect(ch):
    """ST_Message: 8x8 cell in SFONT (256x16) for character ch, or None."""
    c = ord(ch)
    if 97 <= c <= 122:
        c -= 32
    if not 33 <= c <= 95:
        return None
    i = c - 33
    return ((i & ~32) * 8, 0 if i < 32 else 8, 8, 8)


# STATUS (76x16, padded 80): labels + key cards, from ST_Drawer.
STATUS_RECTS = {"HEALTH": (0, 0, 40, 6), "ARMOR": (40, 0, 36, 6),
                **{k: (i * 9, 6, 9, 10) for i, k in enumerate(
                    ("blue_card", "yellow_card", "red_card",
                     "blue_skull", "yellow_skull", "red_skull"))}}


# ---------------------------------------------------------------- helpers
def read_index(lumpdir):
    """Parse index.tsv -> list of dicts (index, name, compressed, method, size, stored, kind)."""
    lumpdir = Path(lumpdir)
    rows = []
    for line in (lumpdir / "index.tsv").read_text().splitlines():
        f = line.split("\t")
        if len(f) < 6 or not f[0].isdigit():
            continue
        rows.append(dict(index=int(f[0]), name=f[1], compressed=int(f[2]), method=f[3],
                         size=int(f[4]), stored=int(f[5])))
    section = None
    for r in rows:
        n = r["name"]
        if n in ("S_START", "T_START"):
            section = n[0]
            r["kind"] = "marker"
            continue
        if n in ("S_END", "T_END", "ENDOFWAD"):
            section = None
            r["kind"] = "marker"
            continue
        if section == "S":
            r["kind"] = "palette" if n.startswith("PAL") and r["size"] == 520 else "sprite"
        elif section == "T":
            r["kind"] = "texture"
        elif n in SPRITE_GFX:
            r["kind"] = "sprite_gfx"
        elif n in PLAIN_GFX:
            r["kind"] = "gfx"
        elif n == "FIRE":
            r["kind"] = "fire"
        elif n == "CLOUD":
            r["kind"] = "cloud"
        elif n.startswith("MAP"):
            r["kind"] = "map"
        elif n.startswith("DEMO"):
            r["kind"] = "demo"
        else:
            r["kind"] = "other"
    return rows


def load_lump(lumpdir, index):
    return (Path(lumpdir) / ("%04d.lmp" % index)).read_bytes()


def pal_to_rgba(pal_bytes):
    """RGBA5551 BE -> Nx4 uint8."""
    v = np.frombuffer(pal_bytes, ">u2").astype(np.uint32)
    c = lambda x: ((x << 3) | (x >> 2)).astype(np.uint8)
    return np.stack([c((v >> 11) & 31), c((v >> 6) & 31), c((v >> 1) & 31),
                     ((v & 1) * 255).astype(np.uint8)], -1)


def rgba_to_pal(rgba):
    """Nx4 uint8 -> RGBA5551 BE bytes (inverse of pal_to_rgba for 5-bit values)."""
    rgba = np.asarray(rgba, np.uint32)
    v = ((rgba[:, 0] >> 3) << 11) | ((rgba[:, 1] >> 3) << 6) | ((rgba[:, 2] >> 3) << 1) | (rgba[:, 3] >= 128)
    return v.astype(">u2").tobytes()


def tmem_swizzle(buf, rowbytes, block_rows=None):
    """Swap the 32-bit word pairs of every 8-byte group on odd rows.

    Involution: same call swizzles and unswizzles. `block_rows` restarts the
    row parity every block (sprites loaded tile by tile)."""
    a = np.frombuffer(bytes(buf), np.uint8).copy()
    rows = len(a) // rowbytes
    if rowbytes % 8:
        raise ValueError("row not 8-byte aligned")
    m = a[: rows * rowbytes].reshape(rows, rowbytes // 8, 2, 4)
    r = np.arange(rows)
    if block_rows:
        r = r % block_rows
    odd = (r & 1) == 1
    m[odd] = m[odd][:, :, ::-1, :]
    return a.tobytes()


def unpack4(data, h, w):
    a = np.frombuffer(data, np.uint8)
    return np.stack([a >> 4, a & 15], -1).reshape(h, w)


def pack4(idx):
    idx = np.asarray(idx, np.uint8)
    return ((idx[:, 0::2] << 4) | (idx[:, 1::2] & 15)).astype(np.uint8).tobytes()


def quantize(rgba, pal_rgba):
    """Map RGBA pixels to palette indices (exact match first, else nearest)."""
    rgba = np.asarray(rgba, np.int32)
    pal = np.asarray(pal_rgba, np.int32)
    flat = rgba.reshape(-1, 4)
    opaque = pal[:, 3] > 0
    tr = np.flatnonzero(~opaque)
    d =((flat[:, None, :3] - pal[None, :, :3]) ** 2).sum(-1)
    d[:, ~opaque] += 1 << 20
    out = d.argmin(1).astype(np.uint8)
    if len(tr):
        out[flat[:, 3] < 128] = tr[0]
    return out.reshape(rgba.shape[:2])


def _as_indices(img, meta, pal_rgba, full_w):
    img = np.asarray(img)
    if img.ndim == 3:
        img = quantize(img, pal_rgba)
    h = meta["height"]
    if img.shape[1] == full_w:
        return img.astype(np.uint8)
    out = np.zeros((h, full_w), np.uint8)
    pad = meta.get("_indices")
    if pad is not None:
        out[:] = pad
    out[:, : img.shape[1]] = img
    return out


def _jsonable(meta):
    return {k: v for k, v in meta.items() if not k.startswith("_")}


# ---------------------------------------------------------------- sprites
SPR_HDR = ">HhHhhHHH"


def sprite_header(b):
    t, c, cmp, xo, yo, w, h, th = struct.unpack(SPR_HDR, b[:16])
    return dict(tiles=t, compressed=c, cmpsize=cmp, xoffs=xo, yoffs=yo, width=w,
                height=h, tileheight=th)


def resolve_sprite_palette(lumpdir, rows, index, variant=0):
    """Palette bytes for a CI8 sprite with odd cmpsize (external palette).

    Returns (palette_bytes, source_name). variant = mobjinfo.palette (world)."""
    b = load_lump(lumpdir, index)
    hd = sprite_header(b)
    if not (hd["compressed"] < 0 and hd["cmpsize"] & 1):
        return None, "embedded"
    ref = index - (hd["cmpsize"] >> 1)
    if rows[ref]["name"].startswith("PAL"):
        ref += variant
        return load_lump(lumpdir, ref)[8:8 + 512], rows[ref]["name"]
    # weapon frames: palette embedded in first frame of the animation
    rb = load_lump(lumpdir, ref)
    rh = sprite_header(rb)
    return rb[16 + rh["cmpsize"]:16 + rh["cmpsize"] + 512], rows[ref]["name"]


def decode_sprite(b, palette=None):
    hd = sprite_header(b)
    w, h, th = hd["width"], hd["height"], hd["tileheight"]
    ci8 = hd["compressed"] < 0
    if ci8:
        w2 = (w + 7) & ~7
        rowbytes, nbytes = w2, w2 * h
    else:
        w2 = (w + 15) & ~15
        rowbytes, nbytes = w2 // 2, w2 * h // 2
    ext = ci8 and (hd["cmpsize"] & 1)
    raw = b[16:16 + nbytes]
    lin = tmem_swizzle(raw, rowbytes, th)
    idx = np.frombuffer(lin, np.uint8).reshape(h, w2) if ci8 else unpack4(lin, h, w2)
    if ext:
        palb = palette
        end = 16 + nbytes
    else:
        po = 16 + hd["cmpsize"]
        palb = b[po:po + (512 if ci8 else 32)]
        end = po + len(palb)
    meta = dict(hd, format="ci8" if ci8 else "ci4", padded_width=w2,
                palette_source="external" if ext else "embedded",
                _indices=idx, _gap=b[16 + nbytes:16 + hd["cmpsize"]] if not ext else b"",
                _tail=b[end:])
    if palb is None:
        pal = np.stack([np.arange(256)] * 3 + [np.full(256, 255)], -1).astype(np.uint8)
    else:
        pal = pal_to_rgba(palb)
        meta["_palette"] = palb
    return pal[idx[:, :w]], meta


def encode_sprite(img, meta, palette=None):
    """img: indexed (h x w or h x padded_w) or RGBA; palette: bytes (needed for
    RGBA input with external palette, or to replace the embedded one)."""
    ci8 = meta["format"] == "ci8"
    w2 = meta["padded_width"]
    palb = palette if palette is not None else meta.get("_palette")
    idx = _as_indices(img, meta, pal_to_rgba(palb) if palb is not None else None, w2)
    lin = idx.tobytes() if ci8 else pack4(idx)
    raw = tmem_swizzle(lin, w2 if ci8 else w2 // 2, meta["tileheight"])
    hdr = struct.pack(SPR_HDR, meta["tiles"], meta["compressed"], meta["cmpsize"],
                      meta["xoffs"], meta["yoffs"], meta["width"], meta["height"],
                      meta["tileheight"])
    out = hdr + raw + meta.get("_gap", b"")
    if meta["palette_source"] == "embedded":
        out += palb
    return out + meta.get("_tail", b"")


# ---------------------------------------------------------------- textures
def decode_texture(b):
    tid, npal, ws, hs = struct.unpack(">hhhh", b[:8])
    w, h = 1 << ws, 1 << hs
    n = w * h // 2
    lin = tmem_swizzle(b[8:8 + n], max(w // 2, 8))
    idx = unpack4(lin, h, w)
    pals = [b[8 + n + 32 * i:8 + n + 32 * (i + 1)] for i in range(npal)]
    meta = dict(id=tid, numpal=npal, wshift=ws, hshift=hs, width=w, height=h, format="ci4",
                _indices=idx, _palettes=pals, _tail=b[8 + n + 32 * npal:])
    return [(pal_to_rgba(p)[idx], dict(meta, palette=i)) for i, p in enumerate(pals)]


def encode_texture(img, meta, palettes=None):
    pals = palettes if palettes is not None else meta["_palettes"]
    idx = _as_indices(img, meta, pal_to_rgba(pals[0]), meta["width"])
    raw = tmem_swizzle(pack4(idx), max(meta["width"] // 2, 8))
    return (struct.pack(">hhhh", meta["id"], len(pals), meta["wshift"], meta["hshift"])
            + raw + b"".join(pals) + meta.get("_tail", b""))


# ---------------------------------------------------------------- gfx
def decode_gfx(b, name=""):
    """Full-screen pictures, SYMBOLS, fonts/HUD/skies (dispatches by name)."""
    if name in SPRITE_GFX:
        return decode_sprite(b)
    c, npal, w, h = struct.unpack(">hhhh", b[:8])
    if name == "CLOUD":
        raw = b[8:8 + 4096]
        idx = np.frombuffer(tmem_swizzle(raw, 64), np.uint8).reshape(64, 64)
        meta = dict(format="i8", width=64, height=64, _header=b[:8], _indices=idx,
                    _tail=b[8 + 4096:])
        g = idx
        return np.stack([g, g, g, np.full_like(g, 255)], -1), meta
    if name == "FIRE" or npal == 0 and c >= 0:
        idx = np.frombuffer(b[8:8 + w * h], np.uint8).reshape(h, w)
        meta = dict(format="i8", compressed=c, numpal=npal, width=w, height=h,
                    _header=b[:8], _indices=idx, _tail=b[8 + w * h:])
        return np.stack([idx, idx, idx, np.full_like(idx, 255)], -1), meta
    n = w * h
    po = 8 + ((n + 7) & ~7)
    idx = np.frombuffer(b[8:8 + n], np.uint8).reshape(h, w)
    palb = b[po:po + 512]
    meta = dict(format="ci8", compressed=c, numpal=npal, width=w, height=h,
                _indices=idx, _gap=b[8 + n:po], _palette=palb, _tail=b[po + 512:])
    return pal_to_rgba(palb)[idx], meta


def encode_gfx(img, meta, palette=None, name=""):
    if "tiles" in meta:
        return encode_sprite(img, meta, palette)
    if meta["format"] == "i8":
        img = np.asarray(img)
        g = img[..., 0] if img.ndim == 3 else img
        g = np.asarray(g, np.uint8)
        if "compressed" not in meta:  # CLOUD
            return meta["_header"] + tmem_swizzle(g.tobytes(), 64) + meta["_tail"]
        return meta["_header"] + g.tobytes() + meta["_tail"]
    palb = palette if palette is not None else meta["_palette"]
    idx = _as_indices(img, meta, pal_to_rgba(palb), meta["width"])
    n = idx.size
    gap = meta.get("_gap", b"\0" * (((n + 7) & ~7) - n))
    return (struct.pack(">hhhh", meta["compressed"], meta["numpal"], meta["width"], meta["height"])
            + idx.tobytes() + gap + palb + meta.get("_tail", b""))


# ---------------------------------------------------------------- driver
def decode_all(lumpdir, with_bytes=False):
    """Yield (row, rgba, meta, bytes) for every graphic lump."""
    rows = read_index(lumpdir)
    for r in rows:
        k = r["kind"]
        if k not in ("sprite", "palette", "texture", "gfx", "sprite_gfx", "fire", "cloud"):
            continue
        b = load_lump(lumpdir, r["index"])
        if k == "palette":
            rgba = pal_to_rgba(b[8:520]).reshape(16, 16, 4)
            meta = dict(format="rgba5551", colors=256, header=b[:8].hex(), width=16, height=16)
            yield r, rgba, meta, b
        elif k == "sprite":
            hd = sprite_header(b)
            pal, src = resolve_sprite_palette(lumpdir, rows, r["index"])
            rgba, meta = decode_sprite(b, pal)
            if pal is not None:
                meta["palette_lump"] = src
                if src.startswith("PAL"):
                    base = src[:-1]
                    meta["palette_variants"] = [x["name"] for x in rows
                                                if x["name"].startswith(base) and x["kind"] == "palette"]
            yield r, rgba, meta, b
        elif k == "texture":
            res = decode_texture(b)
            rgba, meta = res[0]
            meta["_all"] = res
            yield r, rgba, meta, b
        else:
            rgba, meta = decode_gfx(b, r["name"])
            yield r, rgba, meta, b


def roundtrip(r, rgba, meta, b):
    k = r["kind"]
    if k == "palette":
        out = b[:8] + rgba_to_pal(rgba.reshape(-1, 4)) + b[520:]
    elif k == "sprite":
        out = encode_sprite(meta["_indices"], meta, meta.get("_palette"))
        if meta["palette_source"] == "external":
            out = out  # palette lives in another lump; not re-emitted
    elif k == "texture":
        out = encode_texture(meta["_indices"], meta)
    else:
        out = encode_gfx(meta["_indices"], meta, name=r["name"])
    if out == b:
        return True, ""
    n = min(len(out), len(b))
    d = next((i for i in range(n) if out[i] != b[i]), n)
    return False, "len %d vs %d, first diff at %d" % (len(out), len(b), d)


def selftest(lumpdir, quiet=False):
    import collections
    tot = collections.Counter()
    ok = collections.Counter()
    fails = []
    # also verify RGBA->index re-quantisation path on a sample
    for r, rgba, meta, b in decode_all(lumpdir):
        k = r["kind"]
        tot[k] += 1
        good, why = roundtrip(r, rgba, meta, b)
        if good:
            ok[k] += 1
        else:
            fails.append((r["name"], why))
    if not quiet:
        for k in tot:
            print("roundtrip %-10s %4d / %4d identical" % (k, ok[k], tot[k]))
        for f in fails[:10]:
            print("  FAIL", *f)
    return tot, ok, fails


def _checker(h, w, a=90, b=120):
    y, x = np.mgrid[0:h, 0:w]
    v = np.where(((x // 8) + (y // 8)) & 1, a, b).astype(np.uint8)
    return np.stack([v, v, v], -1)


def _compose(rgba):
    a = rgba[..., 3:4].astype(np.float32) / 255
    bg = _checker(*rgba.shape[:2]).astype(np.float32)
    return (rgba[..., :3] * a + bg * (1 - a)).astype(np.uint8)


def make_sheets(items, prefix, outdir, maxw=2000, maxh=2000, scale_small=True):
    """items: list of (label, rgba). Shelf-pack into labelled sheets."""
    from PIL import Image, ImageDraw
    sheets, cur, x, y, shelf = [], [], 4, 4, 0
    lab = 12
    for label, rgba in items:
        h, w = rgba.shape[:2]
        s = 2 if (scale_small and max(h, w) <= 48) else 1
        cw, ch = max(w * s, 6 * len(label)) + 4, h * s + lab + 4
        if x + cw > maxw:
            x, y, shelf = 4, y + shelf, 0
        if y + ch > maxh and cur:
            sheets.append(cur)
            cur, x, y, shelf = [], 4, 4, 0
        cur.append((label, rgba, s, x, y))
        x += cw
        shelf = max(shelf, ch)
    if cur:
        sheets.append(cur)
    paths = []
    for n, sh in enumerate(sheets):
        W = min(maxw, max(px + max(r.shape[1] * s, 6 * len(l)) + 8 for l, r, s, px, py in sh))
        H = max(py + r.shape[0] * s + lab + 8 for l, r, s, px, py in sh)
        im = Image.new("RGB", (W, H), (40, 40, 48))
        dr = ImageDraw.Draw(im)
        for l, r, s, px, py in sh:
            c = _compose(r)
            if s > 1:
                c = c.repeat(s, 0).repeat(s, 1)
            im.paste(Image.fromarray(c), (px, py + lab))
            dr.text((px, py), l, fill=(255, 255, 160))
        p = Path(outdir) / ("%s_%02d.png" % (prefix, n) if len(sheets) > 1 or prefix != "sheet_gfx"
                            else "%s.png" % prefix)
        im.save(p)
        paths.append(p)
    return paths


def dump(lumpdir, outdir):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from cleanroom.gfx import png
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    allmeta = {}
    groups = {}
    tex_items, gfx_items = [], []
    import collections
    tot, ok, fails = collections.Counter(), collections.Counter(), []
    for r, rgba, meta, b in decode_all(lumpdir):
        k, name = r["kind"], r["name"]
        fn = "%04d_%s.png" % (r["index"], name.replace("?", "Q"))
        png.write(outdir / fn, rgba)
        m = _jsonable(meta)
        m.update(name=name, kind=k, file=fn)
        if k == "texture" and meta["numpal"] > 1:
            for rg, mm in meta["_all"][1:]:
                f2 = fn[:-4] + "_pal%d.png" % mm["palette"]
                png.write(outdir / f2, rg)
            m["palette_files"] = [fn[:-4] + "_pal%d.png" % i for i in range(1, meta["numpal"])]
        allmeta[r["index"]] = m
        tot[k] += 1
        good, why = roundtrip(r, rgba, meta, b)
        ok[k] += good
        if not good:
            fails.append((name, why))
        if k == "sprite":
            groups.setdefault(name[:4], []).append((name, rgba))
        elif k == "texture":
            tex_items.append((name, rgba))
        else:
            gfx_items.append((name, rgba))
            if name == "SYMBOLS":
                for sn, (x, y, w, h) in zip(SYMBOL_NAMES, SYMBOL_RECTS):
                    gfx_items.append(("sym " + sn, rgba[y:y + h, x:x + w]))
            if name == "STATUS":
                for sn, (x, y, w, h) in STATUS_RECTS.items():
                    gfx_items.append(("st " + sn, rgba[y:y + h, x:x + w]))
    (outdir / "meta.json").write_text(json.dumps(allmeta, indent=1))
    spr_items = [it for g in groups.values() for it in g]
    sheets = make_sheets(spr_items, "sheet_sprites", outdir)
    sheets += make_sheets(tex_items, "sheet_textures", outdir, scale_small=False)
    sheets += make_sheets(gfx_items, "sheet_gfx", outdir, maxw=2000, maxh=4000)
    print("decoded:", ", ".join("%s %d" % kv for kv in sorted(tot.items())))
    print("roundtrip identical:", ", ".join("%s %d/%d" % (k, ok[k], tot[k]) for k in sorted(tot)))
    for f in fails[:10]:
        print("  FAIL", *f)
    print("sheets:", len(sheets), "->", outdir)


if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "dump":
        dump(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 3 and sys.argv[1] == "selftest":
        t, o, f = selftest(sys.argv[2])
        sys.exit(1 if f else 0)
    else:
        print(__doc__)
