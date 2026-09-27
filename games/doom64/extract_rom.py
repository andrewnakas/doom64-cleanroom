"""Dirty room: split the retail ROM into DOOM64.WAD/WMD/WSD/WDD and the code facts.

    python games/doom64/extract_rom.py <rom.z64> <dirty dir>

Offsets are dm64ex's table (USA v1.0 and Rev 1). Writes <dirty>/Data/* and
<dirty>/lumps/ (every WAD lump decompressed, via tools/d64wad).
"""
import hashlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LAYOUT = {  # region: (wad, wmd, wsd, wdd) as (offset, size)
    "usa10": ((0x63D10, 0x5D18B0), (0x6355C0, 0xB9E0), (0x640FA0, 0x142F8), (0x6552A0, 0x1716C4)),
    "usa11": ((0x63DC0, 0x5D301C), (0x636DE0, 0xB9E0), (0x6427C0, 0x142F8), (0x656AC0, 0x1716C4)),
}
NAMES = ("DOOM64.WAD", "DOOM64.WMD", "DOOM64.WSD", "DOOM64.WDD")
# Kept as code (not art): header, IPL3 boot, RSP microcode. Rev 1 offsets, found from the game's
# OSTask initialisers and lui/addiu references (text) and the ucode ID strings (data).
CODE = {"usa11": {
    "header.bin": (0x0, 0x40), "ipl3.bin": (0x40, 0xFC0),
    "rspboot.text.bin": (0x4AC90, 0xD0),
    "gspF3DEX_NoN_fifo.text.bin": (0x4AD60, 0x13C0), "gspF3DEX_NoN_fifo.data.bin": (0x62B00, 0x800),
    "gspL3DEX_fifo.text.bin": (0x4C120, 0xF70), "gspL3DEX_fifo.data.bin": (0x63300, 0x800),
    "aspMain.text.bin": (0x4D090, 0xE20), "aspMain.data.bin": (0x63B00, 0x2C0),
}}


def build_tool(name: str) -> Path:
    exe = HERE / "tools" / f"{name}.exe"
    src = HERE / "tools" / f"{name}.c"
    if not exe.exists() or exe.stat().st_mtime < src.stat().st_mtime:
        subprocess.run(["bash", str(Path(__file__).parents[2] / "tools/winbin/gcc"), "-O2",
                        "-I", str(HERE / "tools"),
                        "-o", str(exe), str(src)], check=True)
    return exe


def main():
    rom = Path(sys.argv[1]).read_bytes()
    out = Path(sys.argv[2])
    region = {0xA8: "usa10", 0x42: "usa11"}[rom[0x10]] if rom[0x3E] == 0x45 else None
    if region is None:
        raise SystemExit("not a USA Doom 64 ROM")
    (out / "Data").mkdir(parents=True, exist_ok=True)
    for name, (off, size) in zip(NAMES, LAYOUT[region]):
        blob = rom[off:off + size]
        (out / "Data" / name).write_bytes(blob)
        print(f"{name:11} {off:#08x} {size:#08x} sha1 {hashlib.sha1(blob).hexdigest()[:12]}")
    (out / "code").mkdir(exist_ok=True)
    for name, (off, size) in CODE[region].items():
        (out / "code" / name).write_bytes(rom[off:off + size])
    print("code facts", len(CODE[region]))
    lumps = out / "lumps"
    lumps.mkdir(exist_ok=True)
    subprocess.run([str(build_tool("d64wad")), str(out / "Data/DOOM64.WAD"), str(lumps)], check=True)
    print("region", region)


if __name__ == "__main__":
    main()
