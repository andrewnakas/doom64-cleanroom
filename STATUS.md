# Doom 64 clean room: status

## For the morning
- **Play**: https://andrewnakas.github.io/doom64-cleanroom/ (once published; see "Publish" below).
  Keyboard: arrows = stick, W/S forward/back, A/D strafe, Space fire, E use, Shift run, Q/R weapons
  (Q = A = select in menus, R = B = back), M map, Enter = Start. Gamepad: RT fire, A use, LB/RB strafe.
- **Voices**: Doom 64 has no speech, so there is nothing to record: no placeholder voices, no practice pack.
- **Look at**: sprites (monsters are silhouette + coarse colour + rounded shading; no faces yet),
  title / menu font / skull cursor / credits (drawn), textures (colour grid + noise: flat-ish).
- Headless FPS drops seen tonight were host load (the original retail ROM dropped the same way).

## Decisions (log)
- 23:30 **Web route = 3: clean N64 ROM + N64Wasm** (playbook §4).
  Why: DOOM64-RE (Erick194, GPL-3, non-matching C RE of USA v1.0) has no PC/web port; the only port of it
  (jnmartin84/doom64-dc) is Dreamcast-specific (PVR, KOS). Doom64 EX is not built from the decomp. N64Wasm
  (MIT, prebuilt at `C:/Users/andre/n64work/n64wasm/dist`) is proven by the GE/SF64/SSB64 sessions.
  Plan B was a direct Emscripten port (libultra shim + GBI renderer + alSyn mixer + little-endian WAD).
- Toolchain (no N64 SDK): libdragon `mips64-elf-gcc` 16.2 (-O2, -fcommon, o32), ultralib 2.0J libgultra_rom
  built with its modern-GCC flags (392 objects), `rt/support.c` (abs/mem*, __osThreadSave), own entry stub,
  linker script and packer (`build_rom.py`; data at fixed ROM 0x100000, CIC-6102 CRC). **Boots first try.**
- Kept as code (not art), as in the sibling sessions: IPL3 boot (from ROM 0x40), RSP microcode (rspboot,
  F3DEX.NoN.fifo, L3DEX.fifo, aspMain; located from the game's OSTask initialisers), libultra.
- ROM: USA Rev 1 (`6fb0ce9c...`); the decomp is v1.0 code; data (WAD/WMD/WSD/WDD) from Rev 1 (dm64ex offsets).
- Kept facts: maps (MAPxx: geometry, things, sector light colours, macros), demos (DEMOxLMP), WSD (note
  sequences), WMD structure (patches, sample table, loops; books + loop states regenerated), text.
- WAD lumps stored **uncompressed** (the game's W_ReadLump reads either); ROM 16 MB.
- Graphics facts: 4x4 colour grid (16x16 for >= 128 px), alpha-weighted over opaque pixels; 2-bit alpha;
  palette variants as a 3x4 colour matrix (spectre / nightmare imp / player colours / switch states).
- Clean generator: sprites = silhouette + grid colour + pillow shading from the outline (distance transform)
  + rim; textures = grid + fbm noise; k-means palettes per sprite family (shared PALxxxx lumps) or per image;
  padding bytes zeroed. Drawn (`drawn.py`): SYMBOLS menu font (Russo One, metal bevel), skull cursor (8
  turning frames), buttons/arrows/slider, SFONT (own 5x7 pixel font), STATUS (own 5x5 labels + key cards /
  skulls), TITLE (Anton "DOOM" + "64"), EVIL (pentagram + demon head), id/Midway credits + legal re-typeset
  (`text_labels.json`), SPACE starfield, MOUNTx rock shading on the kept outline, FIRE/CLOUD procedural,
  EXIT signs and the "I SUCK AT MAKING MAPS" placeholder re-typeset.
- Audio: 124 samples resynthesised (27 pitched instruments as detuned tones at the kept f0 with loops that
  fit whole cycles; the rest from the descriptor), new books + loop states, sizes identical.
- Site: `ports/emu/make_site.py` (from the GE session): Doom key defaults, case-insensitive keys (Shift = run),
  own key-mapping storage key (all clean-room sites share the github.io origin).

## What works
- Clean ROM boots in N64Wasm: legal screen (re-typeset), title flyover demo, menus (pak prompt, New Game,
  Options, skill select) in our font with our cursor; demo gameplay renders with clean sprites/textures/sky.
- Taint: `games/doom64/taint.py` (byte windows, image detail correlation, ROM data), `audio_taint.py`
  (0 flagged, max xcorr 0.48).

## Next
- publish (repo + gh-pages), then: monster faces/eyes on front frames, weapon (first-person) detail,
  item icons (medkit cross, armor, keys), textures with structure (bricks/panels), FINAL picture.
