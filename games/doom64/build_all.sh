#!/bin/sh
# Doom 64 clean room: full pipeline.
#   sh games/doom64/build_all.sh <retail rom.z64> [work dir]
# dirty room: extract facts (spec) + code facts (IPL3, RSP ucode) from YOUR ROM;
# clean room: regenerate every asset, build the ROM from DOOM64-RE, assemble the site.
set -e
ROM="$1"; W="${2:-D:/n64work/doom64}"
HERE=$(cd "$(dirname "$0")" && pwd); REPO="$HERE/../.."
[ -d "$W/pristine" ] || git clone --depth 1 -c core.autocrlf=false -c core.eol=lf https://github.com/Erick194/DOOM64-RE "$W/pristine"
[ -d "$W/ultralib" ] || git clone --depth 1 -c core.autocrlf=false -c core.eol=lf https://github.com/decompals/ultralib "$W/ultralib"
python "$HERE/extract_rom.py" "$ROM" "$W/dirty"                       # dirty
python "$HERE/spec_extract.py" "$W/dirty/lumps" "$W/spec"               # dirty -> coarse facts
python "$HERE/audio_spec.py" "$W/dirty/Data" "$W/spec"                  # dirty -> coarse facts
python "$HERE/generate.py" "$W/spec" "$W/clean/Data"                    # clean
python "$HERE/build_rom.py" --src "$W/pristine/doom64" --data "$W/clean/Data" \
    --code "$W/dirty/code" --out "$W/build/clean.z64" --ultralib "$W/ultralib"
python "$REPO/ports/emu/make_site.py" "$W/site" "$W/build/clean.z64"
