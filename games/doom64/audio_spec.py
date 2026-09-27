"""DIRTY ROOM: Doom 64 audio facts -> <spec>/audio.json (+ kept WMD/WSD).

    python games/doom64/audio_spec.py <dirty Data dir> <spec dir>

Per sample only kept facts: slot size/frames, rate, loop points, book
order/npredictors, music-vs-sfx, referencing patches (+ their root keys),
median f0, whole-dB peak and the coarse outline of
`cleanroom.audio.descriptor.describe`. No sample data, no book coefficients.
The WMD copy in kept_audio/ is kept structure; its book and loop-state bytes
are retail-derived and are overwritten by the clean step (audio_gen.py).
"""
import json
import shutil
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import wessfmt as W  # noqa: E402
from cleanroom.audio import descriptor  # noqa: E402
from cleanroom.audio.pitch import median_f0  # noqa: E402


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    ddir, spec = Path(argv[1]), Path(argv[2])
    wmdb = (ddir / 'DOOM64.WMD').read_bytes()
    wsdb = (ddir / 'DOOM64.WSD').read_bytes()
    wdd = (ddir / 'DOOM64.WDD').read_bytes()
    wmd, wsd = W.parse_wmd(wmdb), W.parse_wsd(wsdb)
    use = W.sample_usage(wmd, wsd)
    refp = {i: [] for i in range(len(wmd['samples']))}
    roots = {i: [] for i in range(len(wmd['samples']))}
    for pn, pt in enumerate(wmd['patches']):
        for m in range(pt['patchmap_idx'], pt['patchmap_idx'] + pt['patchmap_cnt']):
            pm = wmd['patchmaps'][m]
            refp[pm['sample_id']].append(pn)
            roots[pm['sample_id']].append([pm['root_key'], pm['fine_adj']])
    rows = []
    for info in W.all_samples(wmd):
        i = info['index']
        pcm = W.decode_sample(wdd, info).astype(np.float64)
        rate = info['rate']
        cl = sorted(W.CLASS[c] for c in use[i]['classes'])
        if cl:
            kind = 'sfx' if all(c.startswith('sfx') for c in cl) else 'music'
        else:
            kind = 'music' if i <= 32 else 'sfx'
        lp = info['loop']
        f0 = median_f0((pcm / 32768).astype(np.float32), rate)
        peak = np.abs(pcm).max()
        rows.append({
            'index': i, 'wdd_offset': info['offset'], 'length_bytes': info['length'],
            'type': 'adpcm' if info['type'] == W.AL_ADPCM_WAVE else 'raw16',
            'frames': info['frames'], 'nsamples': info['nsamples'],
            'pitch_cents': info['pitch'], 'rate': round(rate, 3),
            'loop': None if lp is None else {
                'start': int(lp['start']), 'end': int(lp['end']),
                'count': int(lp['count']) - (1 << 32) if lp['count'] >= 1 << 31 else int(lp['count'])},
            'book_order': info['book']['order'] if info['book'] else None,
            'book_npredictors': info['book']['npredictors'] if info['book'] else None,
            'kind': kind, 'classes': cl,
            'patches': sorted(set(refp[i])), 'played_by_patches': sorted(use[i]['patches']),
            'root_keys': sorted({tuple(r) for r in roots[i]}),
            'median_f0': None if f0 is None else round(f0, 1),
            'peak_db': int(round(20 * np.log10(peak / 32768.0 + 1e-9))) if peak else -90,
            'desc': descriptor.describe(pcm, rate),
        })
        print('\r%3d/%d' % (i + 1, len(wmd['samples'])), end='', flush=True)
    print()
    spec.mkdir(parents=True, exist_ok=True)
    wdd_size = max(r['wdd_offset'] + r['length_bytes'] for r in rows)
    out = {'wdd_size': len(wdd), 'wdd_used': wdd_size, 'samples': rows}
    (spec / 'audio.json').write_text(json.dumps(out, separators=(',', ':')))
    kd = spec / 'kept_audio'
    kd.mkdir(exist_ok=True)
    shutil.copyfile(ddir / 'DOOM64.WMD', kd / 'DOOM64.WMD')
    shutil.copyfile(ddir / 'DOOM64.WSD', kd / 'DOOM64.WSD')
    from collections import Counter
    print('samples %d (%s)  WDD %d bytes  loops %d  f0 found %d' % (
        len(rows), dict(Counter(r['kind'] for r in rows)), len(wdd),
        sum(1 for r in rows if r['loop']), sum(1 for r in rows if r['median_f0'])))
    print('peak dBFS histogram', dict(sorted(Counter(r['peak_db'] for r in rows).items())))
    print('wrote', spec / 'audio.json', 'and', kd)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
