"""Build a Doom 64 ROM from the DOOM64-RE sources without the N64 SDK.

    python games/doom64/build_rom.py --src <tree>/doom64 --data <dir with DOOM64.*>
        --code <dir with ucode/ipl3 facts> --out <rom.z64> [--build <dir>] [--ultralib <dir>]

Toolchain: libdragon mips64-elf GCC (o32), ultralib (decompals) 2.0J libgultra_rom
built with its modern-GCC flags, our entry stub + linker script instead of makerom.
ROM layout: 0x0 header, 0x40 IPL3 (6102), 0x1000 code (loaded to 0x80000400),
0x100000 WAD, then WMD, WSD, WDD (16-byte aligned). Prints a one-screen summary.
"""
import argparse
import os
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BIN = Path.home() / ".local/mips64/bin"
GCC = str(BIN / "mips64-elf-gcc.exe")
AR = str(BIN / "mips64-elf-ar.exe")
LD = str(BIN / "mips64-elf-ld.exe")
OBJCOPY = str(BIN / "mips64-elf-objcopy.exe")
NM = str(BIN / "mips64-elf-nm.exe")

ULTRA_VERSION = "J"
ULTRA_SKIP_DIRS = ("debug", "host", "rmon", "log", "error", "gt", "rg", "voice", "flash", "sched")
MGU_MATRIX = ("mtxcatf", "normalize", "scale", "translate")
ARCH = ["-G", "0", "-march=vr4300", "-mfix4300", "-mabi=32", "-mno-abicalls", "-fno-PIC",
        "-mdivide-breaks"]
ULTRA_CFLAGS = ARCH + ["-c", "-nostdinc", "-fno-common", "-ffreestanding", "-fbuiltin",
                       "-fno-builtin-sinf", "-fno-builtin-cosf", "-funsigned-char", "-w",
                       "-fno-strict-aliasing", "-Os", "-ffast-math", "-fno-unsafe-math-optimizations"]
ULTRA_DEFS = ["-DMODERN_CC", "-D_MIPS_SZLONG=32", "-D__USE_ISOC99", "-DF3DEX_GBI",
              f"-DBUILD_VERSION=VERSION_{ULTRA_VERSION}", f'-DBUILD_VERSION_STRING="2.0{ULTRA_VERSION}"',
              "-DNDEBUG", "-D_FINALROM"]
ULTRA_ASFLAGS = ARCH + ["-x", "assembler-with-cpp", "-w", "-nostdinc", "-c", "-mgp32", "-mfp32",
                        "-DMIPSEB", "-D_LANGUAGE_ASSEMBLY", "-D_MIPS_SIM=1", "-D_ULTRA64"]
GAME_CFLAGS = ARCH + ["-c", "-O2", "-nostdinc", "-fcommon", "-ffreestanding", "-fno-builtin",
                      "-fno-strict-aliasing", "-fwrapv", "-w", "-DF3DEX_GBI", "-D_FINALROM", "-DNDEBUG",
                      "-D_MIPS_SZLONG=32", "-D_LANGUAGE_C", "-DMODERN_CC",
                      "-Wno-int-conversion", "-Wno-incompatible-pointer-types",
                      "-Wno-implicit-function-declaration", "-Wno-implicit-int",
                      "-Wno-return-mismatch", "-std=gnu89", "-fno-tree-loop-distribute-patterns"]

GAME_FILES = """graph asci doominfo sprinfo m_bbox am_main doomlib vsprintf c_convert d_main f_main g_game
in_main m_fixed i_main m_main m_password p_base p_misc p_telept p_ceilng p_change p_doors p_enemy
p_floor p_inter p_lights p_map p_slide p_shoot p_maputl p_mobj p_move p_plats p_pspr p_setup p_sight
p_spec p_macros p_switch p_tick p_user r_data r_main r_phase1 r_phase2 r_phase3 s_sound st_main
d_screens w_wad z_zone decodes tables audio wessshell wesstwek wessapi wessapic wessapim wessapip
wessapit wesshand wesstrak wessedit wessarc funqueue wessfade wessseq n64cmd seqload seqloadl
seqloadr""".split()
HEAP_FILES = ["mem_heap", "audio_heap", "cfb"]
UCODES = ["rspboot", "gspF3DEX_NoN_fifo", "gspL3DEX_fifo", "aspMain"]
DATA = ["wad", "wmd", "wsd", "wdd"]
DATA_BASE = 0x100000


def run(cmd, cwd=None):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr)


def newer(out: Path, *deps: Path) -> bool:
    return out.exists() and out.stat().st_size > 0 and all(out.stat().st_mtime >= d.stat().st_mtime for d in deps)


def compile_all(jobs):
    """jobs: list of (cmd, out, src). Returns list of (src, log) failures."""
    fails = []

    def one(job):
        cmd, out, src = job
        if newer(out, src):
            return None
        out.parent.mkdir(parents=True, exist_ok=True)
        rc, log = run(cmd)
        return None if rc == 0 else (src, log)

    with ThreadPoolExecutor(4) as ex:
        for r in ex.map(one, jobs):
            if r:
                fails.append(r)
    return fails


def build_ultralib(ul: Path, bdir: Path) -> Path:
    archive = bdir / "libgultra_rom.a"
    names = set((ul / f"base/{ULTRA_VERSION}/libgultra_rom.txt").read_text().split())
    inc = ["-I", str(ul), "-I", str(ul / "include"), "-I", str(ul / "include/compiler/modern_gcc"),
           "-I", str(ul / "include/PR")]
    jobs = []
    for src in sorted((ul / "src").rglob("*")):
        if src.suffix not in (".c", ".s") or any(p in src.parts for p in ULTRA_SKIP_DIRS):
            continue
        if src.stem in MGU_MATRIX and src.parent.name == "mgu":
            continue  # 2.0J uses the C versions in gu/
        if src.stem + ".o" not in names:
            continue
        out = bdir / "ultra" / (src.parent.name + "_" + src.stem + ".o")
        flags = ULTRA_CFLAGS if src.suffix == ".c" else ULTRA_ASFLAGS
        jobs.append(([GCC] + flags + ULTRA_DEFS + inc + ["-I", str(src.parent), "-o", str(out), str(src)],
                     out, src))
    fails = compile_all(jobs)
    for src, log in fails[:8]:
        print(f"ULTRA FAIL {src.relative_to(ul)}: {first_error(log)}")
    objs = [j[1] for j in jobs if j[1].exists()]
    if not newer(archive, *objs):
        archive.unlink(missing_ok=True)
        rsp = bdir / "ultra.rsp"
        rsp.write_text("\n".join(str(o).replace("\\", "/") for o in objs))
        rc, log = run([AR, "rcs", str(archive), f"@{rsp}"])
        if rc:
            raise SystemExit(log)
    print(f"ultralib 2.0{ULTRA_VERSION}: {len(objs)} objects, {len(fails)} failed")
    return archive


def first_error(log: str) -> str:
    for line in log.splitlines():
        if "error" in line.lower():
            return line.strip()[:200]
    return log.strip().splitlines()[-1][:200] if log.strip() else "?"


ENTRY_S = """
.set noreorder
.section .text.entry, "ax"
.global entrypoint
entrypoint:
    lui   $t0, %hi(_codeSegmentBssStart)
    addiu $t0, $t0, %lo(_codeSegmentBssStart)
    lui   $t1, %hi(_codeSegmentBssEnd)
    addiu $t1, $t1, %lo(_codeSegmentBssEnd)
1:  sw    $zero, 0($t0)
    addiu $t0, $t0, 4
    bne   $t0, $t1, 1b
    nop
    lui   $sp, %hi(bootStack + 0x2000)
    addiu $sp, $sp, %lo(bootStack + 0x2000)
    lui   $t2, %hi(I_Start)
    addiu $t2, $t2, %lo(I_Start)
    jr    $t2
    nop
"""


def ucode_s(code: Path) -> str:
    lines = ['.section .text.ucode, "ax"']
    for u in UCODES:
        lines += [".balign 16", f".global {u}TextStart", f".global {u}TextEnd", f"{u}TextStart:",
                  f'.incbin "{(code / (u + ".text.bin")).as_posix()}"', f"{u}TextEnd:"]
    lines += ['.section .data.ucode, "aw"']
    for u in UCODES[1:]:
        lines += [".balign 16", f".global {u}DataStart", f".global {u}DataEnd", f"{u}DataStart:",
                  f'.incbin "{(code / (u + ".data.bin")).as_posix()}"', f"{u}DataEnd:"]
    return "\n".join(lines) + "\n"


def linker_script(objs, heaps, libs, data_syms) -> str:
    sym = "\n".join(f"  {k} = 0x{v:X};" for k, v in data_syms.items())
    o = "\n".join(f"    {p.as_posix()}(.text*)" for p in objs)
    return f"""OUTPUT_ARCH(mips)
ENTRY(entrypoint)
SECTIONS
{{
{sym}
  . = 0x80000400;
  _codeSegmentStart = .;
  .text : {{
    *(.text.entry)
    *(.text .text.* )
  }}
  .rodata : {{ *(.rodata .rodata.* .rodata1) }}
  .data : {{ *(.data .data.* .sdata .sdata.* .lit4 .lit8) . = ALIGN(16); }}
  _codeSegmentDataEnd = .;
  _codeSegmentRomSize = _codeSegmentDataEnd - _codeSegmentStart;
  .bss (NOLOAD) : {{
    . = ALIGN(16);
    _codeSegmentBssStart = .;
    *(EXCLUDE_FILE({' '.join(h.as_posix() for h in heaps)}) .bss .bss.* .sbss .scommon COMMON)
    . = ALIGN(16);
    _codeSegmentBssEnd = .;
  }}
  _codeSegmentEnd = .;
  .heaps (NOLOAD) : {{
    . = ALIGN(64);
    {heaps[0].as_posix()}(.bss COMMON)
    . = ALIGN(64);
    {heaps[1].as_posix()}(.bss COMMON)
    . = ALIGN(64);
    {heaps[2].as_posix()}(.bss COMMON)
  }}
  _heapsEnd = .;
  /DISCARD/ : {{ *(.MIPS.abiflags) *(.reginfo) *(.comment) *(.pdr) *(.gnu.attributes) *(.mdebug*) }}
}}
"""


def n64_crc(rom: bytearray):
    """CIC 6102 checksum over 0x1000..0x101000, written to 0x10."""
    seed = 0xF8CA4DDC
    t1 = t2 = t3 = t4 = t5 = t6 = seed
    M = 0xFFFFFFFF
    words = struct.unpack(">262144I", bytes(rom[0x1000:0x101000]))
    for d in words:
        if (t6 + d) & M < t6:
            t4 = (t4 + 1) & M
        t6 = (t6 + d) & M
        t3 ^= d
        r = ((d << (d & 0x1F)) | (d >> (32 - (d & 0x1F)))) & M if d & 0x1F else d
        t5 = (t5 + r) & M
        t2 = t2 ^ r if t2 > d else t2 ^ (t6 ^ d)
        t1 = (t1 + (t5 ^ d)) & M
    struct.pack_into(">II", rom, 0x10, t6 ^ t4 ^ t3, t5 ^ t2 ^ t1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--code", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--build", default="D:/n64work/doom64/build")
    ap.add_argument("--ultralib", default="D:/n64work/doom64/ultralib")
    ap.add_argument("--define", action="append", default=[])
    a = ap.parse_args()
    src, data, code, bdir, ul = map(Path, (a.src, a.data, a.code, a.build, a.ultralib))
    bdir.mkdir(parents=True, exist_ok=True)
    os.environ["PATH"] = str(BIN) + os.pathsep + os.environ["PATH"]
    tmp = bdir / "tmp"          # GCC temp files: never on C: (full on the shared machine)
    tmp.mkdir(exist_ok=True)
    for k in ("TMP", "TEMP", "TMPDIR"):
        os.environ[k] = str(tmp)

    lib = build_ultralib(ul, bdir)
    inc = ["-I", str(src), "-I", str(ul / "include"), "-I", str(ul / "include/PR"),
           "-I", str(ul / "include/compiler/modern_gcc")]
    gdir = bdir / "game"
    jobs = [([GCC] + GAME_CFLAGS + [f"-D{d}" for d in a.define] + inc + ["-o", str(gdir / f"{n}.o"), str(src / f"{n}.c")]
             + (["-fno-common"] if n in HEAP_FILES else []), gdir / f"{n}.o", src / f"{n}.c")
            for n in GAME_FILES + HEAP_FILES]
    rt = Path(__file__).resolve().parent / "rt"
    jobs.append(([GCC] + GAME_CFLAGS + inc + ["-o", str(gdir / "support.o"), str(rt / "support.c")],
                 gdir / "support.o", rt / "support.c"))
    jobs.append(([GCC] + ULTRA_ASFLAGS + inc + ["-o", str(gdir / "wessint_s.o"), str(src / "wessint_s.s")],
                 gdir / "wessint_s.o", src / "wessint_s.s"))
    (bdir / "entry.s").write_text(ENTRY_S)
    (bdir / "ucode.s").write_text(ucode_s(code))
    for n in ("entry", "ucode"):
        jobs.append(([GCC] + ULTRA_ASFLAGS + ["-o", str(bdir / f"{n}.o"), str(bdir / f"{n}.s")],
                     bdir / f"{n}.o", bdir / f"{n}.s"))
    fails = compile_all(jobs)
    for s, log in fails:
        print(f"FAIL {s.name}: {first_error(log)}")
    if fails:
        (bdir / "fail.log").write_text("\n\n".join(f"== {s}\n{log}" for s, log in fails))
        raise SystemExit(f"{len(fails)} compile failures (details in {bdir / 'fail.log'})")

    # data segments at fixed ROM offsets so the link needs no second pass
    blobs = [(data / f"DOOM64.{k.upper()}").read_bytes() for k in DATA]
    syms, off = {}, DATA_BASE
    for k, b in zip(DATA, blobs):
        syms[f"_doom64_{k}SegmentRomStart"] = off
        syms[f"_doom64_{k}SegmentRomEnd"] = off + len(b)
        off = (off + len(b) + 15) & ~15
    objs = [bdir / "entry.o"] + [gdir / f"{n}.o" for n in GAME_FILES] + [gdir / "wessint_s.o", gdir / "support.o", bdir / "ucode.o"]
    heaps = [gdir / f"{n}.o" for n in HEAP_FILES]
    (bdir / "doom64.ld").write_text(linker_script(objs, heaps, [lib], syms))
    libgcc = subprocess.run([GCC, "-mabi=32", "-march=vr4300", "-print-libgcc-file-name"],
                            capture_output=True, text=True).stdout.strip()
    elf = bdir / "doom64.elf"
    rsp = bdir / "link.rsp"
    rsp.write_text("\n".join(p.as_posix() for p in objs + heaps) + "\n" + lib.as_posix() + "\n" + Path(libgcc).as_posix())
    rc, log = run([LD, "-T", str(bdir / "doom64.ld"), "-Map", str(bdir / "doom64.map"), "--no-check-sections",
                   "-o", str(elf), f"@{rsp}"])
    if rc:
        errs = [l for l in log.splitlines() if "undefined reference" in l or "error" in l.lower()]
        und = sorted({l.split("`")[-1].rstrip("'") for l in errs if "undefined reference" in l})
        print("LINK FAILED;", len(und), "undefined:", " ".join(und[:40]))
        print("\n".join([l for l in errs if "undefined reference" not in l][:10]))
        raise SystemExit(1)
    binf = bdir / "code.bin"
    rc, log = run([OBJCOPY, "-O", "binary", "--only-section=.text", "--only-section=.rodata",
                   "--only-section=.data", str(elf), str(binf)])
    if rc:
        raise SystemExit(log)
    codebin = binf.read_bytes()
    nm = dict((l.split()[2], int(l.split()[0], 16)) for l in
              subprocess.run([NM, str(elf)], capture_output=True, text=True).stdout.splitlines() if len(l.split()) == 3)
    if len(codebin) > DATA_BASE - 0x1000:
        raise SystemExit(f"code too big: {len(codebin):#x}")
    rom = bytearray(off)
    rom[0:0x40] = (code / "header.bin").read_bytes()
    rom[0x40:0x1000] = (code / "ipl3.bin").read_bytes()
    struct.pack_into(">I", rom, 8, 0x80000400)
    rom[0x1000:0x1000 + len(codebin)] = codebin
    for k, b in zip(DATA, blobs):
        s = syms[f"_doom64_{k}SegmentRomStart"]
        rom[s:s + len(b)] = b
    size = 1 << 20
    while size < len(rom):
        size <<= 1
    rom += b"\xff" * (size - len(rom))
    n64_crc(rom)
    Path(a.out).write_bytes(rom)
    end = nm.get("_heapsEnd", 0)
    print(f"code {len(codebin):#x} bytes, bss end {nm.get('_codeSegmentEnd', 0):#x}, heaps end {end:#x}"
          f" ({'OK' if end <= 0x80400000 else 'OVER 4MB'}), rom {len(rom) >> 20} MB -> {a.out}")


if __name__ == "__main__":
    main()
