"""DEV ONLY (reads retail): compare clean vs retail Doom 64 samples.

    python games/doom64/audio_taint.py <dirty Data dir> <clean Data dir>

Per sample: max |normalised cross-correlation| over lags -64..64 between the
decoded clean and retail waveforms; flags > 0.5. Also reports whether any
retail book coefficients or loop-state bytes survive in the clean WMD.
"""
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import wessfmt as W  # noqa: E402

LAG = 64


def xcorr_max(a, b, lag=LAG):
    a = a.astype(np.float64); b = b.astype(np.float64)
    a -= a.mean(); b -= b.mean()
    na, nb = np.sqrt(np.sum(a * a)), np.sqrt(np.sum(b * b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0, 0
    n = len(a) + len(b)
    m = 1 << (n - 1).bit_length()
    c = np.fft.irfft(np.fft.rfft(a, m) * np.conj(np.fft.rfft(b, m)), m)
    lags = np.r_[np.arange(0, lag + 1), np.arange(-lag, 0)]
    v = np.abs(c[lags % m]) / (na * nb)
    k = int(np.argmax(v))
    return float(v[k]), int(lags[k])


def main(argv):
    if len(argv) < 3:
        print(__doc__); return 2
    d, c = Path(argv[1]), Path(argv[2])
    rw = W.parse_wmd((d / 'DOOM64.WMD').read_bytes())
    cw = W.parse_wmd((c / 'DOOM64.WMD').read_bytes())
    rdd, cdd = (d / 'DOOM64.WDD').read_bytes(), (c / 'DOOM64.WDD').read_bytes()
    res = []
    for i in range(len(rw['samples'])):
        ri, ci = W.sample_info(rw, i), W.sample_info(cw, i)
        a, b = W.decode_sample(rdd, ri), W.decode_sample(cdd, ci)
        v, lag = xcorr_max(a, b)
        res.append((v, i, lag))
    res.sort(reverse=True)
    flagged = [r for r in res if r[0] > 0.5]
    print('samples %d  max |xcorr| (lags +-%d): median %.3f  flagged >0.5: %d' % (
        len(res), LAG, float(np.median([r[0] for r in res])), len(flagged)))
    print('  worst 5:', ', '.join('#%d %.3f (lag %d)' % (i, v, l) for v, i, l in res[:5]))
    bsame = [i for i, (x, y) in enumerate(zip(rw['books'], cw['books'])) if x['book'] == y['book']]
    lsame = [j for j, (x, y) in enumerate(zip(rw['adpcmloops'], cw['adpcmloops'])) if x['state'] == y['state']]
    # also any retail book predictor row (8 coefs) reused anywhere
    rows = {tuple(b['book'][k:k + 8]) for b in rw['books'] for k in range(0, b['order'] * b['npredictors'] * 8, 8)}
    rows.discard((0,) * 8)
    reuse = sum(1 for b in cw['books'] for k in range(0, b['order'] * b['npredictors'] * 8, 8)
                if tuple(b['book'][k:k + 8]) in rows)
    wdd_same = float(np.mean(np.frombuffer(rdd, np.uint8) == np.frombuffer(cdd, np.uint8))) if len(rdd) == len(cdd) else -1
    print('  retail books surviving: %d/%d; retail 8-coef rows reused: %d; loop states surviving: %d/%d' % (
        len(bsame), len(rw['books']), reuse, len(lsame), len(rw['adpcmloops'])))
    print('  WDD byte equality with retail: %.2f%% (chance level ~0.4%%+zeros)' % (100 * wdd_same))
    return 1 if flagged or bsame or lsame else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
