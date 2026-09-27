#!/bin/sh
# Regenerate -> build -> taint (must be 0 failing) -> site -> push gh-pages.
#   sh games/doom64/publish.sh [work dir]
set -e
W="${1:-D:/n64work/doom64}"
HERE=$(cd "$(dirname "$0")" && pwd); REPO="$HERE/../.."
RETAIL="$W/rom/Doom 64 (USA) (Rev 1).z64"
python "$HERE/generate.py" "$W/spec" "$W/clean/Data" | tail -2
python "$HERE/build_rom.py" --src "$W/pristine/doom64" --data "$W/clean/Data" --code "$W/dirty/code" \
    --out "$W/build/clean.z64" --ultralib "$W/ultralib" | tail -1
python "$HERE/taint.py" "$W/dirty/lumps" "$W/clean/Data" --rom "$W/build/clean.z64" --retail "$RETAIL" | tail -3
python "$HERE/audio_taint.py" "$W/dirty/Data" "$W/clean/Data" | tail -2
rm -rf "$W/site"
python "$REPO/ports/emu/make_site.py" "$W/site" "$W/build/clean.z64"
E=$(git -C "$REPO" config user.email); N=$(git -C "$REPO" config user.name)
cd "$W/site"
git init -q -b gh-pages
git config core.autocrlf false; git config user.email "$E"; git config user.name "$N"
git add -A
git commit -qm "site: $(git -C "$REPO" log --oneline -1)"
git push -qf https://github.com/andrewnakas/doom64-cleanroom.git gh-pages
echo "pushed gh-pages"
