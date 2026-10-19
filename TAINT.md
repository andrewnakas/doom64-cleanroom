# Taint scan evidence

Verbatim output of the last taint scan saved in the local work directory, committed as evidence.
It was not re-run for this commit; check the log date against the date of the published build.

Command: `sh games/doom64/publish.sh (runs games/doom64/taint.py <dirty lumps> <clean Data> --rom build/clean.z64 --retail <rom> and games/doom64/audio_taint.py <dirty Data> <clean Data>)`

Live-build check (2026-10-19): the published gh-pages `game.z64` is byte-identical (git blob d279da66d4) to `D:/n64work/doom64/build/clean.z64`, written one minute before this scan.

## `taint.log` (written 2026-09-28 00:40)

```
byte windows: 0 lumps share 16-byte high-entropy windows with retail
pixel detail correlation: 1436 images, 0 > 0.5: SFONT(sprite_gfx) 0.56, SEXIT(texture) 0.43, SEXITA(texture) 0.43, SPACEBF(texture) 0.39, SPACEBN(texture) 0.38, BFE2E0(sprite) 0.34
  ROM hits at 
ROM data segments: 0 of 942042 sampled windows found in retail (kept maps/demos are stored compressed in retail, so they do not match)
TAINT: 0 failing
```

## `audio_taint.log` (written 2026-09-28 00:40)

```
samples 124  max |xcorr| (lags +-64): median 0.098  flagged >0.5: 0
  worst 5: #78 0.480 (lag 7), #40 0.413 (lag -14), #56 0.392 (lag 21), #20 0.372 (lag 58), #45 0.339 (lag 21)
  retail books surviving: 0/124; retail 8-coef rows reused: 0; loop states surviving: 0/23
  WDD byte equality with retail: 1.08% (chance level ~0.4%+zeros)
```
