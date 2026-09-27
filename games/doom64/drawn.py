"""CLEAN ROOM: drawers for lumps that carry text, symbols or pictures.

draw(e, w, h) -> RGBA uint8 (h x w x 4) or None (generic generator).
Everything here is drawn from scratch: OFL fonts (fonts/, Russo One and Anton),
a hand-made 5x7 pixel font, primitives. Inputs are the spec facts for the
lump (size, glyph rectangles from the game's code tables, colour grid).
"""
import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

import wadfmt

HERE = Path(__file__).resolve().parent
FONTS = HERE / "fonts"
LABELS = json.loads((HERE / "text_labels.json").read_text(encoding="utf-8"))
MENU_FONT = FONTS / "RussoOne-Regular.ttf"
TITLE_FONT = FONTS / "Anton-Regular.ttf"


# ------------------------------------------------------------------ text masks
@lru_cache(maxsize=64)
def _font(path, size):
    return ImageFont.truetype(str(path), size)


def text_mask(text, font=MENU_FONT, size=64):
    """Anti-aliased coverage mask of a text line at `size` px, cropped to ink."""
    f = _font(font, size)
    l, t, r, b = f.getbbox(text)
    im = Image.new("L", (r - l + 4, b - t + 4), 0)
    ImageDraw.Draw(im).text((2 - l, 2 - t), text, font=f, fill=255)
    a = np.asarray(im, np.float32) / 255
    ys, xs = np.nonzero(a > 0.02)
    if len(ys) == 0:
        return np.zeros((1, 1), np.float32)
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def resize(mask, w, h):
    im = Image.fromarray((np.clip(mask, 0, 1) * 255).astype(np.uint8))
    return np.asarray(im.resize((max(1, w), max(1, h)), Image.LANCZOS), np.float32) / 255


def fit(mask, w, h, stretch=True, align="center"):
    """Place a mask in a w x h box: stretched to fill, or scaled to fit keeping aspect."""
    out = np.zeros((h, w), np.float32)
    mh, mw = mask.shape
    if stretch:
        return resize(mask, w, h)
    s = min(w / mw, h / mh)
    nw, nh = max(1, int(round(mw * s))), max(1, int(round(mh * s)))
    m = resize(mask, nw, nh)
    x = {"left": 0, "center": (w - nw) // 2, "right": w - nw}[align]
    y = (h - nh) // 2
    out[y:y + nh, x:x + nw] = m[: h - y, : w - x]
    return out


def style(mask, top, bottom, outline=(20, 16, 16), edge=True, thresh=0.45, bevel=0.35):
    """1-bit-alpha glyph: vertical gradient fill, lit top edge, dark outline."""
    h, w = mask.shape
    fill = mask >= thresh
    g = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    col = np.asarray(top, np.float32) * (1 - g) + np.asarray(bottom, np.float32) * g
    col = np.broadcast_to(col, (h, w, 3)).copy()
    if bevel:
        up = np.roll(fill, 1, 0)
        up[0] = False
        col[fill & ~up] = np.minimum(255, col[fill & ~up] * (1 + bevel) + 30)
        dn = np.roll(fill, -1, 0)
        dn[-1] = False
        col[fill & ~dn] *= 1 - bevel * 0.8
    img = np.zeros((h, w, 4), np.float32)
    img[..., :3] = col
    img[..., 3] = fill * 255
    if edge:
        ring = ndimage.binary_dilation(fill) & ~fill
        img[ring, :3] = outline
        img[ring, 3] = 255
    return img


def paste(canvas, img, x, y):
    h, w = img.shape[:2]
    H, W = canvas.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 <= x0 or y1 <= y0:
        return
    src = img[y0 - y:y1 - y, x0 - x:x1 - x]
    a = src[..., 3:4] > 0
    canvas[y0:y1, x0:x1] = np.where(a, src, canvas[y0:y1, x0:x1])


def text_line(text, h, font=MENU_FONT, top=(236, 236, 236), bottom=(120, 120, 130), cap=None):
    """A styled line of text whose cap height is about h-2 px (width follows)."""
    m = text_mask(text.upper() if cap else text, font, 96)
    s = (h - 2) / m.shape[0]
    m = resize(m, max(1, int(round(m.shape[1] * s))), h - 2)
    pad = np.zeros((h, m.shape[1] + 2), np.float32)
    pad[1:-1, 1:-1] = m
    return style(pad, top, bottom)


def paragraph(lines, w, h, align="left", top=(230, 230, 230), bottom=(120, 120, 128)):
    img = np.zeros((h, w, 4), np.float32)
    lh = h / len(lines)
    ch = max(7, int(lh * 0.82))
    for i, t in enumerate(lines):
        ln = text_line(t, ch, top=top, bottom=bottom)
        if ln.shape[1] > w:
            ln = squeeze(ln, w)
        x = 0 if align == "left" else (w - ln.shape[1]) // 2
        paste(img, ln, x, int(round(i * lh + (lh - ch) / 2)))
    return img


def squeeze(img, w):
    """Horizontally squeeze a styled RGBA image to width w (nearest, keeps 1-bit alpha)."""
    xs = np.linspace(0, img.shape[1] - 1, w).round().astype(int)
    return img[:, xs]


# ------------------------------------------------------------------ 5x7 / 5x5 pixel fonts
F57 = {
    "!": "00100 00100 00100 00100 00100 00000 00100", '"': "01010 01010 00000 00000 00000 00000 00000",
    "#": "01010 11111 01010 01010 11111 01010 00000", "$": "00100 01111 10100 01110 00101 11110 00100",
    "%": "11001 11010 00010 00100 01000 01011 10011", "&": "01100 10010 10100 01000 10101 10010 01101",
    "'": "00100 00100 00000 00000 00000 00000 00000", "(": "00010 00100 01000 01000 01000 00100 00010",
    ")": "01000 00100 00010 00010 00010 00100 01000", "*": "00000 00100 10101 01110 10101 00100 00000",
    "+": "00000 00100 00100 11111 00100 00100 00000", ",": "00000 00000 00000 00000 00110 00100 01000",
    "-": "00000 00000 00000 11111 00000 00000 00000", ".": "00000 00000 00000 00000 00000 00110 00110",
    "/": "00001 00010 00010 00100 01000 01000 10000", "0": "01110 10001 10011 10101 11001 10001 01110",
    "1": "00100 01100 00100 00100 00100 00100 01110", "2": "01110 10001 00001 00110 01000 10000 11111",
    "3": "11110 00001 00001 01110 00001 00001 11110", "4": "00010 00110 01010 10010 11111 00010 00010",
    "5": "11111 10000 11110 00001 00001 10001 01110", "6": "00110 01000 10000 11110 10001 10001 01110",
    "7": "11111 00001 00010 00100 01000 01000 01000", "8": "01110 10001 10001 01110 10001 10001 01110",
    "9": "01110 10001 10001 01111 00001 00010 01100", ":": "00000 00110 00110 00000 00110 00110 00000",
    ";": "00000 00110 00110 00000 00110 00100 01000", "<": "00010 00100 01000 10000 01000 00100 00010",
    "=": "00000 00000 11111 00000 11111 00000 00000", ">": "01000 00100 00010 00001 00010 00100 01000",
    "?": "01110 10001 00001 00010 00100 00000 00100", "@": "01110 10001 10111 10101 10110 10000 01110",
    "A": "01110 10001 10001 11111 10001 10001 10001", "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110", "D": "11100 10010 10001 10001 10001 10010 11100",
    "E": "11111 10000 10000 11110 10000 10000 11111", "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111", "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "01110 00100 00100 00100 00100 00100 01110", "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001", "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001", "N": "10001 10001 11001 10101 10011 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110", "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101", "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110", "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110", "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 10101 01010", "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 01010 00100 00100 00100 00100", "Z": "11111 00001 00010 00100 01000 10000 11111",
    "[": "01110 01000 01000 01000 01000 01000 01110", "\\": "10000 01000 01000 00100 00010 00010 00001",
    "]": "01110 00010 00010 00010 00010 00010 01110", "^": "00100 01010 10001 00000 00000 00000 00000",
    "_": "00000 00000 00000 00000 00000 00000 11111",
}
F55 = {
    "H": "10001 10001 11111 10001 10001", "E": "11111 10000 11110 10000 11111",
    "A": "01110 10001 11111 10001 10001", "L": "10000 10000 10000 10000 11111",
    "T": "11111 00100 00100 00100 00100", "R": "11110 10001 11110 10010 10001",
    "M": "10001 11011 10101 10001 10001", "O": "01110 10001 10001 10001 01110",
}


def bitmap(rows):
    return np.array([[c == "1" for c in r] for r in rows.split()], bool)


def pixel_text(text, font, gap=1):
    glyphs = [bitmap(font[c]) if c in font else np.zeros((len(next(iter(font.values())).split()), 3), bool)
              for c in text]
    h = glyphs[0].shape[0]
    out = np.zeros((h, sum(g.shape[1] + gap for g in glyphs) - gap), bool)
    x = 0
    for g in glyphs:
        out[:, x:x + g.shape[1]] = g
        x += g.shape[1] + gap
    return out


# ------------------------------------------------------------------ SFONT / STATUS
def draw_sfont(w, h):
    """256x16: 8x8 cells for '!'..'_' (index c-33; x=(i&~32)*8, y=0/8). White with a dark shadow."""
    img = np.zeros((h, w, 4), np.float32)
    for c in range(33, 96):
        x, y, _, _ = wadfmt.sfont_rect(chr(c))
        g = bitmap(F57[chr(c)])
        cell = np.zeros((8, 8, 4), np.float32)
        sh = np.zeros((8, 8), bool)
        sh[1:8, 2:7] = g
        cell[sh] = (40, 30, 30, 255)
        fg = np.zeros((8, 8), bool)
        fg[0:7, 1:6] = g
        grad = np.linspace(255, 190, 7)
        for r in range(7):
            cell[r][fg[r]] = (grad[r], grad[r], grad[r], 255)
        img[y:y + 8, x:x + 8] = cell
    return img


def key_card(color, w=9, h=10):
    c = np.asarray(color, np.float32)
    img = np.zeros((h, w, 4), np.float32)
    img[1:h - 1, 1:w - 1] = (*(c * 0.55), 255)
    img[2:h - 2, 2:w - 2] = (*c, 255)
    img[2:4, 3:w - 3] = (*np.minimum(255, c * 0.5 + 140), 255)   # stripe
    return img


def key_skull(color, w=9, h=10):
    c = np.asarray(color, np.float32)
    m = bitmap("0011100 0111110 1111111 1011101 1111111 0110110 0111110 0101010")
    img = np.zeros((h, w, 4), np.float32)
    for y, x in zip(*np.nonzero(m)):
        img[y + 1, x + 1] = (*(c * (1.1 - 0.08 * y)).clip(0, 255), 255)
    for y, x in ((3, 2), (3, 6)):
        img[y + 1, x + 1] = (20, 10, 10, 255)
    return img


def draw_status(w, h):
    img = np.zeros((h, w, 4), np.float32)
    for label, (x, y, lw, lh) in (("HEALTH", wadfmt.STATUS_RECTS["HEALTH"]), ("ARMOR", wadfmt.STATUS_RECTS["ARMOR"])):
        m = pixel_text(label, F55)
        ox = x + (lw - m.shape[1]) // 2
        for yy, xx in zip(*np.nonzero(m)):
            img[y + yy + 1, ox + xx] = (60, 20, 20, 255)
            img[y + yy, ox + xx] = (230 - 18 * yy, 60, 50, 255)
    cols = {"blue": (40, 80, 255), "yellow": (240, 210, 40), "red": (230, 30, 30)}
    for name, (x, y, kw, kh) in wadfmt.STATUS_RECTS.items():
        if "_" in name:
            col, kind = name.split("_")
            k = key_card(cols[col], kw, kh) if kind == "card" else key_skull(cols[col], kw, kh)
            img[y:y + kh, x:x + kw] = k
    return img


# ------------------------------------------------------------------ SYMBOLS
PUNCT = {  # (x0, y0, x1, y1) boxes in unit cell coordinates
    "-": [(0.1, 0.42, 0.9, 0.62)],
    ".": [(0.15, 0.72, 0.85, 1.0)],
    ":": [(0.15, 0.12, 0.85, 0.38), (0.15, 0.72, 0.85, 1.0)],
    "!": [(0.2, 0.0, 0.8, 0.64), (0.2, 0.78, 0.8, 1.0)],
}


def metal_glyph(ch, w, h, small=False):
    if ch in PUNCT:
        pad = np.zeros((h, w), np.float32)
        for x0, y0, x1, y1 in PUNCT[ch]:
            pad[1 + int(round(y0 * (h - 2))):1 + int(round(y1 * (h - 2))),
                int(round(x0 * (w - 1))):max(int(round(x0 * (w - 1))) + 2, int(round(x1 * (w - 1))))] = 1
        return style(pad, (245, 245, 245), (110, 110, 118))
    m = text_mask(ch.upper(), MENU_FONT, 96)
    gh = h - 2
    gw = w - 1
    if ch in ".:!":
        gw = min(gw, max(3, int(m.shape[1] / m.shape[0] * gh * 1.1)))
    pad = np.zeros((h, w), np.float32)
    g = resize(m, gw, gh)
    pad[1:1 + gh, (w - gw) // 2:(w - gw) // 2 + gw] = g
    return style(pad, (245, 245, 245), (110, 110, 118) if not small else (130, 130, 138))


def demon_skull(frame, w, h):
    """Menu cursor: a horned skull turning (8 frames)."""
    ss = 4
    W, H = w * ss, h * ss
    ang = frame / 8 * 2 * math.pi
    ca, sa = math.cos(ang), math.sin(ang)
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy = W / 2, H * 0.55
    rx, ry = W * 0.26, H * 0.36
    # horns: base at +-0.8 rx (rotated around the vertical axis), tips up and out
    for side in (-1, 1):
        bx = cx + side * rx * 0.75 * ca
        vis = side * sa  # >0: horn behind the head
        tip = (cx + side * rx * 1.75 * ca, cy - ry * 1.35)
        mid = (cx + side * rx * 1.45 * ca, cy - ry * 0.55)
        col = (150, 120, 90, 255) if vis <= 0.3 else (110, 85, 65, 255)
        d.polygon([(bx - W * 0.05, cy - ry * 0.35), mid, tip, (bx + W * 0.05 * side, cy - ry * 0.6)], fill=col)
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(150, 85, 50, 255))
    d.ellipse([cx - rx * 0.8, cy - ry * 0.9, cx + rx * 0.55, cy + ry * 0.2], fill=(185, 115, 70, 255))
    if ca > -0.2:  # face visible
        for side in (-1, 1):
            ex = cx + (side * rx * 0.42 * ca) - rx * 0.9 * sa * 0.6
            ey = cy - ry * 0.12
            er = W * 0.055 * max(0.35, ca)
            d.ellipse([ex - er * 1.5, ey - er, ex + er * 1.5, ey + er], fill=(40, 10, 5, 255))
            d.ellipse([ex - er * 0.8, ey - er * 0.55, ex + er * 0.8, ey + er * 0.55], fill=(255, 200, 40, 255))
        mx = cx - rx * 0.9 * sa * 0.6
        d.polygon([(mx - rx * 0.45 * ca, cy + ry * 0.35), (mx + rx * 0.45 * ca, cy + ry * 0.35),
                   (mx, cy + ry * 0.75)], fill=(40, 10, 5, 255))
        for t in (-0.25, 0, 0.25):
            tx = mx + t * rx * ca
            d.polygon([(tx - W * 0.02, cy + ry * 0.36), (tx + W * 0.02, cy + ry * 0.36), (tx, cy + ry * 0.52)],
                      fill=(240, 230, 200, 255))
    a = np.asarray(im.resize((w, h), Image.LANCZOS), np.float32)
    a[..., 3] = (a[..., 3] > 110) * 255
    return a


def button(name, w, h):
    ss = 4
    W, H = w * ss, h * ss
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    colors = {"btn_a": (40, 70, 230), "btn_b": (40, 170, 60), "btn_start": (200, 30, 30),
              "btn_z": (110, 110, 120), "btn_l": (110, 110, 120), "btn_r": (110, 110, 120)}
    letter = {"btn_a": "A", "btn_b": "B", "btn_z": "Z", "btn_l": "L", "btn_r": "R", "btn_start": ""}
    if name.startswith("c_"):
        d.ellipse([2, 2, W - 3, H - 3], fill=(230, 200, 30, 255), outline=(90, 70, 0, 255), width=ss)
        arrow(d, name[2:], W, H, (60, 40, 0, 255), 0.28)
    elif name.startswith("dpad_"):
        d.rounded_rectangle([2, 2, W - 3, H - 3], radius=ss * 2, fill=(80, 80, 90, 255), outline=(30, 30, 35, 255), width=ss)
        arrow(d, name[5:], W, H, (230, 230, 230, 255), 0.3)
    else:
        c = colors[name]
        if name in ("btn_l", "btn_r", "btn_z"):
            d.rounded_rectangle([2, 2, W - 3, H - 3], radius=ss * 3, fill=c + (255,), outline=(30, 30, 35, 255), width=ss)
        else:
            d.ellipse([2, 2, W - 3, H - 3], fill=c + (255,), outline=(20, 20, 25, 255), width=ss)
        if letter[name]:
            f = _font(MENU_FONT, int(H * 0.62))
            d.text((W / 2, H / 2), letter[name], font=f, fill=(255, 255, 255, 255), anchor="mm")
    a = np.asarray(im.resize((w, h), Image.LANCZOS), np.float32)
    a[..., 3] = (a[..., 3] > 110) * 255
    return a


def arrow(d, direction, W, H, fill, s):
    cx, cy = W / 2, H / 2
    r = min(W, H) * s
    pts = {"up": [(cx, cy - r), (cx - r, cy + r * 0.7), (cx + r, cy + r * 0.7)],
           "down": [(cx, cy + r), (cx - r, cy - r * 0.7), (cx + r, cy - r * 0.7)],
           "left": [(cx - r, cy), (cx + r * 0.7, cy - r), (cx + r * 0.7, cy + r)],
           "right": [(cx + r, cy), (cx - r * 0.7, cy - r), (cx - r * 0.7, cy + r)]}[direction]
    d.polygon(pts, fill=fill)


def simple_arrow(direction, w, h):
    ss = 4
    im = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    arrow(ImageDraw.Draw(im), direction, w * ss, h * ss, (220, 220, 225, 255), 0.45)
    a = np.asarray(im.resize((w, h), Image.LANCZOS), np.float32)
    a[..., 3] = (a[..., 3] > 110) * 255
    return a


def draw_symbols(w, h):
    img = np.zeros((h, w, 4), np.float32)
    rects = list(zip(wadfmt.SYMBOL_NAMES, wadfmt.SYMBOL_RECTS))
    for name, (x, y, rw, rh) in rects:
        # clip to the next rectangle starting inside this one on the same row
        for _, (x2, y2, _, h2) in rects:
            if x < x2 < x + rw and y2 < y + rh and y < y2 + h2:
                rw = x2 - x
        if len(name) == 1:
            g = metal_glyph(name, rw, rh, small=name.islower())
        elif name.startswith("skull"):
            g = demon_skull(int(name[5:]) - 1, rw, rh)
        elif name.startswith(("btn_", "c_", "dpad_")):
            g = button(name, rw, rh)
        elif name.startswith("arrow_"):
            g = simple_arrow(name[6:], rw, rh)
        elif name == "slider_bar":
            g = np.zeros((rh, rw, 4), np.float32)
            g[3:rh - 3, :] = (90, 20, 20, 255)
            g[4:rh - 4, 1:rw - 1] = (160, 40, 30, 255)
            g[4, 1:rw - 1] = (220, 90, 70, 255)
        elif name == "slider_gem":
            g = np.zeros((rh, rw, 4), np.float32)
            g[:, :] = (230, 230, 230, 255)
            g[:, -1] = (90, 90, 90, 255)
            g[-1, :] = (90, 90, 90, 255)
        elif name == "select_box":
            g = np.zeros((rh, rw, 4), np.float32)
            g[[0, 1, -2, -1], :] = (230, 230, 230, 255)
            g[:, [0, 1, -2, -1]] = (230, 230, 230, 255)
        else:
            continue
        paste(img, g, x, y)
    return img


# ------------------------------------------------------------------ pictures
def wordmark(lines, w, h, fonts, heights, top, bottom, gap=2):
    img = np.zeros((h, w, 4), np.float32)
    total = sum(heights) + gap * (len(lines) - 1)
    y = (h - total) // 2
    for t, f, lh in zip(lines, fonts, heights):
        m = text_mask(t, f, 160)
        s = lh / m.shape[0]
        mw = min(w - 4, int(round(m.shape[1] * s)))
        m = resize(m, mw, lh)
        pad = np.zeros((lh + 4, mw + 4), np.float32)
        pad[2:-2, 2:-2] = m
        g = style(pad, top, bottom, outline=(30, 10, 5), bevel=0.25)
        g[..., 3] = np.maximum(g[..., 3], ndimage.binary_dilation(pad >= 0.45, iterations=2) * 255)
        dark = (g[..., 3] > 0) & (pad < 0.45)
        g[dark, :3] = (30, 10, 5)
        paste(img, g, (w - g.shape[1]) // 2, y - 2)
        y += lh + gap
    return img


def draw_title(w, h):
    return wordmark(["DOOM", "64"], w, h, [TITLE_FONT, MENU_FONT], [int(h * 0.62), int(h * 0.26)],
                    top=(255, 210, 90), bottom=(150, 50, 10))


def draw_evil(w, h):
    ss = 4
    W, H = w * ss, h * ss
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy, r = W / 2, H / 2, min(W, H) / 2 - 3 * ss
    ring = (120, 25, 15, 255)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ring, width=int(r * 0.07))
    pts = [(cx + r * 0.93 * math.sin(a), cy + r * 0.93 * math.cos(a))
           for a in [math.pi + k * 4 * math.pi / 5 for k in range(5)]]
    for i in range(5):
        d.line([pts[i], pts[(i + 1) % 5]], fill=ring, width=int(r * 0.06))
    # demon head
    hr = r * 0.42
    for side in (-1, 1):
        d.polygon([(cx + side * hr * 0.5, cy - hr * 0.6), (cx + side * hr * 1.25, cy - hr * 1.5),
                   (cx + side * hr * 0.9, cy - hr * 0.35)], fill=(170, 130, 90, 255))
    d.ellipse([cx - hr, cy - hr * 0.9, cx + hr, cy + hr * 1.1], fill=(140, 55, 30, 255))
    d.ellipse([cx - hr * 0.8, cy - hr * 0.8, cx + hr * 0.5, cy + hr * 0.2], fill=(175, 80, 45, 255))
    for side in (-1, 1):
        ex = cx + side * hr * 0.38
        d.polygon([(ex - hr * 0.25, cy - hr * 0.2), (ex + hr * 0.25, cy - hr * 0.2 + side * hr * 0.08),
                   (ex, cy + hr * 0.05)], fill=(255, 210, 60, 255))
    d.polygon([(cx - hr * 0.5, cy + hr * 0.45), (cx + hr * 0.5, cy + hr * 0.45), (cx, cy + hr * 0.85)],
              fill=(40, 5, 0, 255))
    for t in (-0.3, -0.1, 0.1, 0.3):
        tx = cx + t * hr
        d.polygon([(tx - hr * 0.07, cy + hr * 0.46), (tx + hr * 0.07, cy + hr * 0.46), (tx, cy + hr * 0.62)],
                  fill=(240, 230, 200, 255))
    a = np.asarray(im.resize((w, h), Image.LANCZOS), np.float32)
    a[..., 3] = (a[..., 3] > 100) * 255
    return a


def draw_credits(name, w, h):
    lab = LABELS[name]
    rows = []
    for role, names in lab["columns"]:
        for i, n in enumerate(names):
            rows.append((role if i == 0 else "", n))
        rows.append(None)
    rows = rows[:-1]
    foot = lab.get("footer", [])
    n = len(rows) + len(foot) + (1 if foot else 0)
    lh = h / n
    ch = max(7, int(lh * 0.8))
    img = np.zeros((h, w, 4), np.float32)
    y = 0.0
    for r in rows:
        if r:
            role, who = r
            if role:
                ln = text_line(role, ch, top=(250, 200, 120), bottom=(150, 80, 40))
                paste(img, squeeze(ln, min(ln.shape[1], w // 2 - 4)), 0, int(y))
            ln = text_line(who, ch)
            paste(img, squeeze(ln, min(ln.shape[1], w // 2 - 2)), w // 2, int(y))
        y += lh
    if foot:
        y += lh
        for i, t in enumerate(foot):
            ln = text_line(t, ch, top=(250, 200, 120), bottom=(150, 80, 40)) if i == 0 else text_line(t, ch)
            ln = squeeze(ln, min(ln.shape[1], w))
            paste(img, ln, (w - ln.shape[1]) // 2, int(y))
            y += lh
    return img


def draw_space(w, h):
    rng = np.random.default_rng(64)
    img = np.zeros((h, w, 4), np.float32)
    img[..., 3] = 255
    img[..., :3] = (2, 2, 6)
    for _ in range(420):
        x, y = rng.integers(0, w), rng.integers(0, h)
        b = rng.random() ** 2.2
        tint = rng.choice([(1, 1, 1), (0.75, 0.85, 1), (1, 0.9, 0.75)])
        img[y, x, :3] = np.asarray(tint) * (40 + 215 * b)
        if b > 0.8:
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                yy, xx = (y + dy) % h, (x + dx) % w
                img[yy, xx, :3] = np.maximum(img[yy, xx, :3], np.asarray(tint) * 90)
    return img


def draw_mountains(e, w, h):
    from generate import alpha_of, noise, upsample_grid, h32
    a = alpha_of(e, w, h)
    col = upsample_grid(e["grid"], w, h)
    n = noise(h32("rock", e["name"]), w, h, cell=12.0, octaves=5)
    ridge = 1 - np.abs(noise(h32("ridge", e["name"]), w, h, cell=24.0, octaves=3))
    shade = 0.75 + 0.35 * n + 0.25 * ridge
    # light from the upper left on the silhouette's top edge
    top = np.argmax(a > 0, axis=0)
    ys = np.arange(h)[:, None]
    depth = np.clip((ys - top[None, :]) / 20.0, 0, 1)
    shade *= 1.25 - 0.45 * depth
    rgb = col * shade[..., None]
    return np.dstack([rgb, a]).clip(0, 255)


def label_panel(text, w, h, bg, ink):
    img = np.zeros((h, w, 4), np.float32)
    img[..., :3] = bg
    img[..., 3] = 255
    lines = text.split()
    lh = h // len(lines) if len(text) > 8 else h
    if len(text) <= 8:
        lines = [text]
    for i, t in enumerate(lines):
        m = text_mask(t, MENU_FONT, 96)
        m = fit(m, w - 4, max(3, lh - 2), stretch=False)
        pad = np.zeros((lh, w), np.float32)
        pad[1:1 + m.shape[0], 2:2 + m.shape[1]] = m
        g = style(pad, ink, tuple(v * 0.7 for v in ink), outline=tuple(v * 0.4 for v in bg), bevel=0.2)
        paste(img, g, 0, i * lh + (h - lh * len(lines)) // 2)
    return img


def draw_final(e, w, h):
    """End picture: a marine seen from behind on a hellish ridge under a red sky.
    Colours follow the kept 16x16 grid; the scene is drawn from scratch."""
    from generate import upsample_grid, noise, h32
    base = upsample_grid(e["grid"], w, h)
    ys = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    clouds = noise(h32("final-sky"), w, h, cell=40.0, octaves=5)[..., None]
    sky = base * (0.8 + 0.35 * clouds) + np.array([60, 0, 0], np.float32) * (1 - ys)
    img = np.dstack([sky, np.full((h, w), 255, np.float32)])
    ss = 3
    im = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    rng = np.random.default_rng(h32("final-ridge"))
    for layer, (y0, amp, col) in enumerate([(0.55, 0.10, (70, 12, 8, 255)), (0.66, 0.08, (40, 6, 4, 255)),
                                            (0.80, 0.05, (18, 3, 2, 255))]):
        xs = np.linspace(0, w * ss, 40)
        ridge = y0 * h * ss - amp * h * ss * np.abs(np.cumsum(rng.normal(0, 1, 40)) / 4)
        d.polygon([(0, h * ss)] + list(zip(xs, ridge)) + [(w * ss, h * ss)], fill=col)
    ridges = np.asarray(im.resize((w, h), Image.LANCZOS), np.float32)
    ra = ridges[..., 3:4] / 255
    img[..., :3] = img[..., :3] * (1 - ra) + ridges[..., :3] * ra
    # the marine, from behind: boots, legs, belt, torso with pack, shoulder pads, arms, helmet
    cx, gy = w * ss * 0.5, h * ss * 0.88
    s = h * ss / 240
    fig = Image.new("L", (w * ss, h * ss), 0)
    f = ImageDraw.Draw(fig)
    for side in (-1, 1):
        f.polygon([(cx + side * 5 * s, gy - 62 * s), (cx + side * 19 * s, gy - 62 * s),
                   (cx + side * 17 * s, gy - 6 * s), (cx + side * 6 * s, gy - 6 * s)], fill=255)   # legs
        f.rounded_rectangle([cx + min(side * 4, side * 20) * s, gy - 10 * s, cx + max(side * 4, side * 20) * s, gy],
                            radius=3 * s, fill=255)                                                    # boots
        f.polygon([(cx + side * 22 * s, gy - 118 * s), (cx + side * 31 * s, gy - 108 * s),
                   (cx + side * 29 * s, gy - 74 * s), (cx + side * 22 * s, gy - 76 * s)], fill=255)   # arms
        f.ellipse([cx + side * 26 * s - 10 * s, gy - 126 * s, cx + side * 26 * s + 10 * s, gy - 106 * s], fill=255)
    f.polygon([(cx - 23 * s, gy - 120 * s), (cx + 23 * s, gy - 120 * s), (cx + 19 * s, gy - 66 * s),
               (cx - 19 * s, gy - 66 * s)], fill=255)                                                  # torso
    f.ellipse([cx - 10 * s, gy - 142 * s, cx + 10 * s, gy - 118 * s], fill=255)                     # helmet
    m = np.asarray(fig.resize((w, h), Image.LANCZOS), np.float32) / 255 > 0.5
    dist = ndimage.distance_transform_edt(m)
    hgt = ndimage.gaussian_filter(np.sqrt(np.minimum(dist, 6) / 6), 1.0)
    gy_, gx_ = np.gradient(hgt * 5)
    lam = np.clip((gx_ * 0.6 + gy_ * 0.5 + 0.6) / np.sqrt(gx_ ** 2 + gy_ ** 2 + 1), 0, 1)
    armour = np.array([46, 62, 40], np.float32)
    col = armour * (0.35 + 0.8 * lam)[..., None]
    yy = np.arange(h)[:, None] * np.ones((1, w))
    belt = m & (np.abs(yy - (gy / ss - 66 * s / ss)) < 2)
    pack = m & (np.abs(np.arange(w)[None, :] - cx / ss) < 9 * s / ss) & (yy > gy / ss - 112 * s / ss) & (yy < gy / ss - 86 * s / ss)
    col[belt] = (70, 50, 30)
    col[pack] = col[pack] * 0.7 + np.array([30, 30, 26]) 
    rim = m & (dist <= 1.2)
    col[rim] = np.minimum(255, col[rim] * 0.5 + np.array([150, 40, 25]))
    img[m, :3] = col[m]
    img[..., 3] = 255
    return img


# ------------------------------------------------------------------ dispatch
def draw(e, w, h):
    n = e["name"]
    img = None
    if n == "SFONT":
        img = draw_sfont(w, h)
    elif n == "STATUS":
        img = draw_status(w, h)
    elif n == "SYMBOLS":
        img = draw_symbols(w, h)
    elif n in ("USLEGAL", "PLLEGAL"):
        img = paragraph(LABELS[n]["lines"], w, h)
    elif n in ("IDCRED2", "WMSCRED2"):
        img = draw_credits(n, w, h)
    elif n == "TITLE":
        img = draw_title(w, h)
    elif n == "EVIL":
        img = draw_evil(w, h)
    elif n == "IDCRED1":
        img = wordmark(["id", "SOFTWARE"], w, h, [MENU_FONT, MENU_FONT], [int(h * 0.6), int(h * 0.14)],
                       top=(230, 210, 120), bottom=(120, 100, 30))
    elif n == "WMSCRED1":
        img = wordmark(["MIDWAY", "HOME ENTERTAINMENT INC."], w, h, [MENU_FONT, MENU_FONT],
                       [int(h * 0.55), int(h * 0.16)], top=(250, 250, 250), bottom=(150, 150, 160))
    elif n == "SPACE":
        img = draw_space(w, h)
    elif n == "FINAL":
        img = draw_final(e, w, h)
    elif n.startswith("MOUNT"):
        img = draw_mountains(e, w, h)
    elif n in ("SEXIT", "SEXITA"):
        img = label_panel("EXIT", w, h, (120, 10, 10), (255, 80, 60))
    elif n == "?" or n.startswith("F_SKY"):
        img = label_panel("I SUCK AT MAKING MAPS", w, h, (20, 200, 20), (230, 20, 20))
    if img is None:
        return None
    return np.clip(img, 0, 255).astype(np.uint8)
