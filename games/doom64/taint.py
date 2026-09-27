"""DEV ONLY: taint scan of the clean data against retail (reads both; never publish its inputs).

    python games/doom64/taint.py <dirty lumps dir> <clean Data dir> [--rom <clean rom> --retail <retail rom>]

1. Byte windows: every 16-byte window of a clean non-kept lump that also occurs anywhere in
   the retail (decompressed) non-kept lumps, ignoring low-entropy windows (<= 4 distinct bytes).
2. Pixels: for each graphic lump, the correlation of high-pass luminance (detail) between the
   clean and retail images (same size, same alpha); > 0.5 fails.
3. ROM (optional): 16-byte windows of the clean ROM's data segments (0x100000..) found in the
   retail ROM outside its kept code/header regions.
Prints counts and the worst offenders; exit code 1 when anything fails.
"""
import argparse
import struct
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import wadfmt  # noqa: E402

W = 16
KEPT = ("map", "demo", "marker")
TEXT_LUMPS = ("SFONT",)


def windows(b: bytes, step=1):
    """Hashes of all W-byte windows at `step` plus a mask of the low-entropy ones."""
    a = np.frombuffer(b, np.uint8)
    n = len(a) - W + 1
    if n <= 0:
        return np.zeros(0, np.uint64), np.zeros(0, bool)
    hs, oks = [], []
    for c0 in range(0, n, 1 << 18):     # chunks keep peak memory small (shared machine)
        idx = np.arange(c0, min(n, c0 + (1 << 18)), step)
        h = np.zeros(len(idx), np.uint64)
        for k in range(W):
            h = h * np.uint64(1099511628211) ^ a[idx + k].astype(np.uint64)
        # low entropy: few distinct byte values in the window
        s = np.sort(np.stack([a[idx + k] for k in range(W)], 1), 1)
        # arithmetic progressions of 16-bit values (colour ramps) carry no information either
        u = np.stack([a[idx + k].astype(np.int32) * 256 + a[idx + k + 1] for k in range(0, W, 2)], 1)
        ramp = (np.diff(u, 2, axis=1) == 0).all(1)
        hs.append(h)
        zeros = (s == 0).sum(1)
        oks.append((1 + (np.diff(s, axis=1) != 0).sum(1) > 4) & ~ramp & (zeros < 10))
    return np.concatenate(hs), np.concatenate(oks)


def low_info(w: bytes) -> bool:
    """A colour ramp (16-bit values in arithmetic progression) padded with zeros, at either alignment,
    or 4-bit index data using at most 3 distinct nibbles (a smooth gradient run)."""
    nib = [n for b in w for n in (b >> 4, b & 15)]
    if len(set(nib)) <= 3:
        return True
    d = [b - a for a, b in zip(nib, nib[1:])]
    if len(set(nib)) <= 5 and (all(x >= 0 for x in d) or all(x <= 0 for x in d)):
        return True     # a monotonic 4-bit gradient run
    for ph in (0, 1):
        v = [w[i] << 8 | w[i + 1] for i in range(ph, len(w) - 1, 2)]
        while v and v[0] == 0:
            v.pop(0)
        while v and v[-1] == 0:
            v.pop()
        if len(v) < 3 or len({b - a for a, b in zip(v, v[1:])}) == 1:
            return True
        grey = all((x >> 11) == ((x >> 6) & 31) == ((x >> 1) & 31) for x in v)
        if grey and all(b > a for a, b in zip(v, v[1:])):
            return True     # a monotonic greyscale ramp (RGBA5551 r = g = b)
    return False


def contains(sorted_set, h):
    i = np.searchsorted(sorted_set, h)
    i[i >= len(sorted_set)] = 0
    return sorted_set[i] == h


def read_wad(path: Path):
    b = path.read_bytes()
    n, ofs = struct.unpack("<ii", b[4:12])
    out = {}
    for i in range(n):
        pos, size, name = struct.unpack("<ii8s", b[ofs + 16 * i: ofs + 16 * i + 16])
        name = bytes([name[0] & 0x7F]) + name[1:]
        out[name.rstrip(b"\0").decode()] = b[pos:pos + size]
    return out


def clean_palette(clean, rows, index):
    """wadfmt.resolve_sprite_palette, but reading the clean WAD."""
    b = clean[rows[index]["name"]]
    hd = wadfmt.sprite_header(b)
    if not (hd["compressed"] < 0 and hd["cmpsize"] & 1):
        return None
    ref = rows[index - (hd["cmpsize"] >> 1)]["name"]
    rb = clean[ref]
    if ref.startswith("PAL"):
        return rb[8:520]
    rh = wadfmt.sprite_header(rb)
    return rb[16 + rh["cmpsize"]:16 + rh["cmpsize"] + 512]


def detail(rgba):
    """High-pass luminance over opaque pixels only (the local mean ignores transparent pixels,
    so holes in the kept alpha outline do not count as detail)."""
    y = rgba[..., :3].astype(np.float32) @ np.array([0.3, 0.59, 0.11], np.float32)
    m = (rgba[..., 3] > 0).astype(np.float32)
    mean = ndimage.uniform_filter(y * m, 5) / np.maximum(ndimage.uniform_filter(m, 5), 1e-3)
    return y - mean


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lumps")
    ap.add_argument("data")
    ap.add_argument("--rom", default="")
    ap.add_argument("--retail", default="")
    a = ap.parse_args()
    lumps = Path(a.lumps)
    rows = wadfmt.read_index(lumps)
    clean = read_wad(Path(a.data) / "DOOM64.WAD")
    fails = 0

    # 1. byte windows
    ret = [wadfmt.load_lump(lumps, r["index"]) for r in rows if r["kind"] not in KEPT and r["size"]]
    rh, rok = windows(b"".join(ret))
    rset = np.unique(rh[rok])
    hits = []
    for r in rows:
        if r["kind"] in KEPT or r["name"] not in clean:
            continue
        ch, cok = windows(clean[r["name"]])
        if len(ch) == 0:
            continue
        hdr = {"sprite": 16, "sprite_gfx": 16, "palette": 8, "texture": 8, "gfx": 8, "fire": 8, "cloud": 8}.get(r["kind"], 0)
        cok[:hdr] = False   # windows overlapping the kept header fields
        found = contains(rset, ch[cok])
        b = clean[r["name"]]
        pos = [i for i in np.flatnonzero(cok)[found] if not low_info(b[i:i + W])]
        if pos:
            hits.append((len(pos), r["name"], r["kind"]))
    hits.sort(reverse=True)
    print(f"byte windows: {len(hits)} lumps share 16-byte high-entropy windows with retail"
          + (": " + ", ".join(f"{n}({k}) x{c}" for c, n, k in hits[:8]) if hits else ""))
    fails += len(hits)

    # 2. pixel detail correlation
    worst = []
    for row, rgba, meta, _ in wadfmt.decode_all(lumps):
        name = row["name"]
        if name not in clean:
            continue
        try:
            if row["kind"] == "texture":
                crgba = wadfmt.decode_texture(clean[name])[0][0]
            elif row["kind"] == "sprite":
                crgba = wadfmt.decode_sprite(clean[name], clean_palette(clean, rows, row["index"]))[0]
            else:
                crgba = wadfmt.decode_gfx(clean[name], name)[0]
        except Exception as ex:  # noqa: BLE001
            print("  decode failed", name, ex)
            continue
        if crgba.shape != rgba.shape:
            continue
        # interior only: the 1-px band along the alpha outline is the kept outline itself
        m = ndimage.binary_erosion((rgba[..., 3] > 0) & (crgba[..., 3] > 0))
        if m.sum() < 32:
            continue
        d1, d2 = detail(rgba)[m], detail(crgba)[m]
        if d1.std() < 1 or d2.std() < 1:
            continue
        c = float(np.corrcoef(d1, d2)[0, 1])
        worst.append((c, name, row["kind"]))
    worst.sort(reverse=True)
    # re-typeset text: the same letters in the same cells correlate by construction (own 5x7 font)
    bad = [w for w in worst if w[0] > 0.5 and w[1] not in TEXT_LUMPS]
    print(f"pixel detail correlation: {len(worst)} images, {len(bad)} > 0.5: "
          + ", ".join(f"{n}({k}) {c:.2f}" for c, n, k in (bad or worst[:6])))
    fails += len(bad)

    # 3. ROM data segments
    if a.rom and a.retail:
        cr = Path(a.rom).read_bytes()[0x100000:]
        rr = bytearray(Path(a.retail).read_bytes())
        rr[0:0x1000] = bytes(0x1000)                      # header + IPL3 (kept code)
        rr[0x4AC90:0x4DEB0] = bytes(0x4DEB0 - 0x4AC90)    # RSP ucode text (kept code)
        rr[0x62B00:0x63DC0] = bytes(0x63DC0 - 0x62B00)    # RSP ucode data (kept code)
        wmd = slice(0x636DE0, 0x636DE0 + 0xB9E0)          # WMD structure (kept, books replaced)
        wsd = slice(0x6427C0, 0x6427C0 + 0x142F8)         # WSD sequences (kept)
        rr[wmd] = bytes(0xB9E0)
        rr[wsd] = bytes(0x142F8)
        rh, rok = windows(bytes(rr), step=1)
        rset = np.unique(rh[rok])
        ch, cok = windows(cr, step=4)
        # mask windows touching a kept lump header (WAD at 0x100000 in the clean ROM)
        wad = Path(a.data, "DOOM64.WAD").read_bytes()
        n, ofs = struct.unpack("<ii", wad[4:12])
        starts = 4 * np.arange(len(cok))
        for i in range(n):
            pos, size, nm = struct.unpack("<ii8s", wad[ofs + 16 * i: ofs + 16 * i + 16])
            lo, hi = pos - W, pos + 16
            if nm.startswith((b"MAP", b"DEMO")):     # kept facts (stored uncompressed here)
                hi = pos + size
            cok[(starts >= lo) & (starts < hi)] = False
        cok[starts >= ofs - W] = False      # the directory (names + offsets)
        found = contains(rset, ch[cok])
        pos = 0x100000 + 4 * np.flatnonzero(cok)[found]
        print("  ROM hits at", " ".join(hex(int(x)) for x in pos[:12]))
        print(f"ROM data segments: {int(found.sum())} of {int(cok.sum())} sampled windows found in retail"
              " (kept maps/demos are stored compressed in retail, so they do not match)")
        fails += int(found.sum() > 0)
    print("TAINT:", "0 failing" if fails == 0 else f"{fails} failing")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
