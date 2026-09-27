# Doom 64 clean room: status

## For the morning
- **Play**: https://andrewnakas.github.io/doom64-cleanroom/ (published 2026-09-27 ~00:45; republished after each
  improvement by `sh games/doom64/publish.sh`, which refuses to push unless both taint scans pass).
  Keyboard: arrows = stick, W/S forward/back, A/D strafe, Space fire, E use, Shift run, Q/R weapons
  (Q = A = select in menus, R = B = back), M map, Enter = Start. Gamepad: RT fire, A use, LB/RB strafe.
- **Voices**: Doom 64 has no speech, so there is nothing to record: no placeholder voices, no practice pack.
- **Look at**: sprites (silhouette + coarse colour + rounded shading; eyes on front frames; metal weapons;
  glowing effects), title / menu font / skull cursor / credits / end picture (drawn), textures (structured:
  stone / riveted panels / cracked rock / liquids, tile seamlessly).
- **Machine**: C: was at 0 bytes free around 01:00 (other sessions); this game keeps temp files on D:.
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
- Gameplay verified with a dev-only autostart build (clean data, `DEV_AUTOSTART` patch in a copy of the
  source, never published): HUD labels + counters, pickup messages ("YOU GOT THE SHOTGUN!"), weapons,
  damage, movement/fire/use from the keyboard map, automap (line + textured modes), level title.
- Audio verified in the page (?audiolog=1): clean RMS 200-1200 during play vs 550-1240 for retail data.
- Drawn detail passes: monster eyes (front frames), carved demon-mask wall textures (19), computer screens
  (SMON*, one colour per animated screen), key cards / skull keys, medikit / stimpack crosses, FINAL scene,
  switch plates with indicator lights (SWX*), pentagram teleport pads (HTEL*), pinky demon toothed maw.
- Clean ROM boots in N64Wasm: legal screen (re-typeset), title flyover demo, menus (pak prompt, New Game,
  Options, skill select) in our font with our cursor; demo gameplay renders with clean sprites/textures/sky.
- Taint: `games/doom64/taint.py` (byte windows, image detail correlation, ROM data), `audio_taint.py`
  (0 flagged, max xcorr 0.48).

## Next
- **For you to judge by ear**: music instruments are outline-shaped harmonic tones + a breath-noise bed
  (`audio_gen._tonal`); sound effects are resynthesised noise from the outline. Say which ones sound wrong.
- remaining polish: grate/emblem textures with alpha (C77, CASFL28), armour sheen, a lighting check vs retail.
- Disk: this game uses ~0.2 GB on D: (browser profiles are now deleted after each headless shot).
