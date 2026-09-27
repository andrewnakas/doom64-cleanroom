# Doom 64 clean room: status

## Decisions (log)
- 2026-09-26 23:30 **Web route = 3: clean N64 ROM + N64Wasm** (playbook §4).
  Why: DOOM64-RE (Erick194, GPL-3, non-matching C RE of USA v1.0) has no PC/web port; the only port of it
  (jnmartin84/doom64-dc) is Dreamcast-specific (PVR, KOS). Doom64 EX is not built from the decomp. N64Wasm
  (MIT, prebuilt at `C:/Users/andre/n64work/n64wasm/dist`) is proven by the GE/SF64/SSB64 sessions.
  A direct Emscripten port (own libultra shim + GBI renderer + alSyn mixer + little-endian WAD) was the
  alternative; kept as plan B if the ROM build stalls.
- Toolchain: libdragon `mips64-elf-gcc` 16.2 (the decomp targets the SDK's GCC), ultralib (decompals) for
  libultra, own Python makerom. Kept as code (not art), same as sibling sessions: IPL3 boot, RSP microcode
  (rspboot, F3DEX.NoN.fifo, L3DEX.fifo, aspMain), libultra.
- ROM: USA Rev 1 (`6fb0ce9c...`). The decomp is v1.0 code; data (WAD/WMD/WSD/WDD) is taken from Rev 1
  (dm64ex offsets, region 3).

## What works
- nothing yet

## Next
- dirty extract + WAD census, ROM build with retail data (dirty, dev only) to prove the toolchain
