"""CLEAN ROOM: regenerate the Doom 64 sound bank from facts.

    python games/doom64/audio_gen.py <spec dir> <data out dir>

Reads only <spec>/audio.json and <spec>/kept_audio/DOOM64.{WMD,WSD}. Every
sample is resynthesised from its coarse descriptor (instruments as harmonic
tones at the kept median f0), loops are made seamless, a new VADPCM book is
designed from OUR audio, the sample is encoded to exactly its kept slot size,
the loop state is recomputed from our decoded audio, and book + loop state
are written into a copy of the kept WMD (the kept copy's book/loop-state
bytes are retail-derived and are all overwritten). Writes DOOM64.WMD,
DOOM64.WSD (unchanged) and DOOM64.WDD into <data>.
"""
import hashlib
import json
import shutil
import struct
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))
import wessfmt as W  # noqa: E402
from cleanroom.audio import descriptor  # noqa: E402

TARGET_DB = -3.0


def _seed(*parts):
    return int.from_bytes(hashlib.sha1('/'.join(map(str, parts)).encode()).digest()[:4], 'big')


# ------------------------------------------------------------------ synthesis
def _frame_centers(nframes, n):
    b = np.linspace(0, n, nframes + 1)
    return 0.5 * (b[:-1] + b[1:])


def _tonal(desc, n, rate, f0, pre, seed, h, loop_len=None):
    """Harmonic tone at a fixed f0 over samples [-pre, n); per-harmonic
    amplitudes follow the per-frame band envelope, level follows frame RMS.
    Global time base, so it is exactly periodic in the phase of every
    partial whenever f0 * L / rate is an integer."""
    frames = desc['frames']
    rng = np.random.default_rng(seed)
    t = np.arange(-pre, n)
    cen = _frame_centers(len(frames), n)
    nh = max(1, min(48, int((rate / 2 - 300) / f0)))
    hf = f0 * np.arange(1, nh + 1)
    logc = np.log(descriptor.CENTERS)
    A = np.zeros((len(frames), nh))
    for k, f in enumerate(frames):
        db = np.asarray(f['db'], float)
        a = 10 ** ((np.interp(np.log(hf), logc, db, left=db[0], right=descriptor.FLOOR_DB) - db.max()) / 20)
        a[hf > rate / 2 - 300] = 0
        A[k] = a / (np.sqrt(np.sum(a ** 2) / 2) + 1e-12)  # unit rms
    # two slightly detuned voices (chorus) with gentle vibrato (~10 cents,
    # ~5 Hz). For loops the detune step and the vibrato rate are whole cycles
    # per loop, so the waveform stays exactly periodic in the loop length.
    period = loop_len or n
    if loop_len:
        f0b = f0 + rate / loop_len * max(1, round(f0 * 0.004 * loop_len / rate))
    else:
        f0b = f0 * 2 ** (7 / 1200)
    m = max(1, round(5.0 * period / rate))
    fm = 2 * np.pi * m / period
    x = np.zeros(len(t))
    tt = np.clip(t, 0, n - 1)
    amps = [np.interp(tt, cen, A[:, p]) if A[:, p].max() >= 1e-3 else None for p in range(nh)]
    for fv in (f0, f0b):
        ph = rng.uniform(0, 2 * np.pi, nh)
        w = 2 * np.pi * fv / rate
        beta = fv * (2 ** (10 / 1200) - 1) / (m * rate / period)  # peak phase dev. (rad)
        vib = beta * np.sin(fm * t + rng.uniform(0, 2 * np.pi))
        for p in range(nh):
            if amps[p] is not None and (p + 1) * fv < rate / 2 - 300:
                x += amps[p] * np.sin(w * (p + 1) * t + (p + 1) * vib + ph[p]) * 0.7071
    rms_db = np.array([f['rms'] for f in frames], float)
    env = 10 ** (np.interp(tt, cen, rms_db) / 20)
    tone = x * env * h
    # a quiet shaped-noise bed (breath) following the mean band envelope
    mdb = np.mean([f['db'] for f in frames], axis=0)
    amp = 10 ** ((mdb - mdb.max()) / 20)
    nz = descriptor._shape_noise(len(t), amp, rate, rng)
    nz = nz / (np.sqrt(np.mean(nz ** 2)) + 1e-12)
    return tone + nz * env * np.sqrt(max(0.0, 1 - h * h)) * 0.35


def _noisy(desc, n, rate, pre, seed):
    """descriptor.synthesize over [0, n); a pre-roll (for loops starting near
    0) is the time-reversed head, which is continuous into sample 0."""
    x = descriptor.synthesize(desc, n, rate, seed=seed).astype(np.float64)
    if pre:
        head = x[1:pre + 1][::-1]
        head = np.concatenate([np.zeros(pre - len(head)), head])
        x = np.concatenate([head, x])
    return x


def _seamless(x, pre, start, end, coherent):
    """Crossfade the end of the loop into the audio just before its start
    (x has `pre` samples of pre-roll)."""
    L = end - start
    K = int(min(2048, max(16, L // 4)))
    s, e = start + pre, end + pre
    if s - K < 0:
        K = s
    if K < 8:
        return x
    r = np.linspace(0, 1, K)
    a, b = (1 - r, r) if coherent else (np.cos(r * np.pi / 2), np.sin(r * np.pi / 2))
    x = x.copy()
    x[e - K:e] = x[e - K:e] * a + x[s - K:s] * b
    return x


def synth_sample(r):
    n, rate, desc = r['nsamples'], r['rate'], r['desc']
    lp = r['loop']
    seed = _seed('doom64-smp', r['index'])
    pre = 2048 if lp else 0
    frames = desc['frames']
    hs = [f['h'] for f in frames if f['rms'] > max(f2['rms'] for f2 in frames) - 30] or [0]
    h = float(np.median(hs))
    f0 = r.get('median_f0')
    if not f0:
        tonal = [f['f0'] for f in frames if f['f0'] > 20 and f['h'] > 0.3]
        f0 = float(np.median(tonal)) if tonal else None
    coherent = r['kind'] == 'music' and f0 is not None and h >= 0.45 and 30 <= f0 <= rate / 4
    if coherent:
        if lp:  # integer number of cycles in the loop -> phase-continuous wrap
            L = lp['end'] - lp['start']
            f0 = max(1, round(f0 * L / rate)) * rate / L
        x = _tonal(desc, n, rate, f0, pre, seed, min(1.0, h + 0.2),
                   (lp['end'] - lp['start']) if lp else None)
    else:
        x = _noisy(desc, n, rate, pre, seed)
    if lp and lp['end'] - lp['start'] > 32:
        x = _seamless(x, pre, lp['start'], min(lp['end'], n), coherent)
    x = x[pre:pre + n]
    # zero tail after a finite (non-looping) sound's last 1 ms fade
    if not lp:
        k = min(len(x), max(8, int(rate * 0.004)))
        x[-k:] *= np.linspace(1, 0, k)
    peak = np.abs(x).max()
    tgt = min(TARGET_DB, r.get('peak_db', 0))
    if peak > 0:
        x = x / peak * 10 ** (tgt / 20)
    dither = np.random.default_rng(seed ^ 0x5A5A).integers(-1, 2, n)
    pcm = np.clip(np.round(x * 32767) + dither, -32768, 32767).astype(np.int64)
    return pcm, ('tone %.0fHz' % f0) if coherent else 'noise/outline'


# ------------------------------------------------------------------ main
def slot_ranges(wmd):
    """byte ranges (in the WMD file) of every book slot and loop-state field."""
    off = wmd['offsets']
    books = [(off['books'] + 264 * i, off['books'] + 264 * i + 264) for i in range(len(wmd['books']))]
    states = [(off['adpcmloops'] + 48 * j + 12, off['adpcmloops'] + 48 * j + 44)
              for j in range(len(wmd['adpcmloops']))]
    return books, states


def main_gen(spec, data):
    t0 = time.time()
    spec, data = Path(spec), Path(data)
    facts = json.loads((spec / 'audio.json').read_text())
    kept_wmd = (spec / 'kept_audio' / 'DOOM64.WMD').read_bytes()
    wmd = W.parse_wmd(kept_wmd)
    rows = facts['samples']
    assert len(rows) == len(wmd['samples'])
    blobs, peaks, modes = {}, [], {}
    booked, stated = set(), set()
    for r in rows:
        i = r['index']
        info = W.sample_info(wmd, i)
        assert info['length'] == r['length_bytes'] and info['offset'] == r['wdd_offset']
        pcm, mode = synth_sample(r)
        modes[mode.split()[0]] = modes.get(mode.split()[0], 0) + 1
        if info['type'] == W.AL_ADPCM_WAVE:
            # never hand the kept (retail) book to the encoder: only its shape
            shape = {'order': r['book_order'], 'npredictors': r['book_npredictors'], 'book': []}
            info = dict(info, book=shape)
            book = W.compute_book(pcm, r['book_order'], r['book_npredictors'])
            blob, book, dec, st = W.encode_sample(pcm, info, book=book)
            W.set_book(wmd, i, book)
            booked.add(i)
            if st is not None:
                W.set_loop_state(wmd, i, st)
                stated.add(wmd['samples'][i]['loop_index'])
        else:
            blob, _, dec, _ = W.encode_sample(pcm, info)
        blobs[i] = blob
        peaks.append(20 * np.log10(np.abs(dec.astype(np.float64)).max() / 32768 + 1e-9))
    # book slots of non-ADPCM samples (none in Doom 64) are zeroed, not kept
    for i, b in enumerate(wmd['books']):
        if i not in booked:
            b['book'] = [0] * 128
            booked.add(i)
    for j, l in enumerate(wmd['adpcmloops']):
        if j not in stated:
            l['state'] = [0] * 16
            stated.add(j)
    new_wmd = W.write_wmd(wmd)
    wdd = W.rebuild_wdd(wmd, blobs, facts['wdd_size'])
    data.mkdir(parents=True, exist_ok=True)
    (data / 'DOOM64.WMD').write_bytes(new_wmd)
    (data / 'DOOM64.WDD').write_bytes(wdd)
    shutil.copyfile(spec / 'kept_audio' / 'DOOM64.WSD', data / 'DOOM64.WSD')

    # ---- checks
    sizes_ok = all(len(blobs[r['index']]) == r['length_bytes'] for r in rows) and \
        len(wdd) == facts['wdd_size'] and len(new_wmd) == len(kept_wmd)
    a = np.frombuffer(new_wmd, np.uint8)
    b = np.frombuffer(kept_wmd, np.uint8)
    diff = np.nonzero(a != b)[0]
    books, states = slot_ranges(wmd)
    inside = np.zeros(len(a), bool)
    for s, e in books + states:
        inside[s:e] = True
    outside = int(np.sum(~inside[diff]))
    same_books = [i for i, (s, e) in enumerate(books) if new_wmd[s + 8:e] == kept_wmd[s + 8:e]]
    same_states = [j for j, (s, e) in enumerate(states) if new_wmd[s:e] == kept_wmd[s:e]]
    peaks = np.array(peaks)
    print('audio: %d samples (%s) in %.1fs -> %s' % (len(rows), modes, time.time() - t0, data))
    print('  sizes equal to kept slots: %s (WDD %d bytes, WMD %d bytes)' % (
        'yes' if sizes_ok else 'NO', len(wdd), len(new_wmd)))
    print('  peak dBFS (decoded): min %.1f median %.1f max %.1f' % (peaks.min(), np.median(peaks), peaks.max()))
    print('  WMD vs kept: %d differing bytes, %d outside book/loop-state slots' % (len(diff), outside))
    print('  book slots overwritten: %d/%d (coefs identical by chance: %d)  loop states: %d/%d (identical: %d)' % (
        len(booked), len(books), len(same_books), len(stated), len(states), len(same_states)))
    return sizes_ok and outside == 0


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(0 if main_gen(Path(sys.argv[1]), Path(sys.argv[2])) else 1)
