"""Doom 64 WESS audio module formats (DOOM64.WMD / .WSD / .WDD) -- dirty-room codec.

Derived from how the game (Erick194/DOOM64-RE: wessapi.c, n64cmd.c, seqload.c,
wessseq.c, wessarc.h) loads the files. All numbers big-endian except the
2-byte arguments inside track event streams (read byte-wise little-endian).

WMD (module, "SN64" v2, decomp_type 0 = stored):
  0   module_header (32): id 'SN64', version 2, pad, u16 pad, u16 sequences,
      u8 decomp_type, 3 pad, u32 compress_size, u32 data_size, u32 pad
  32  patch_group_header (24): u32 load_flags, u16 patches, u16 patch_size(4),
      u16 patchmaps, u16 patchmap_size(20), u16 patchinfo, u16 patchinfo_size(24),
      u16 drummaps, u16 drummap_size, u32 extra_data_size
  56  data (data_size bytes), sub-blocks each padded to 8 (relative to 56):
      patches[patches]      4B: u8 patchmap_cnt, u8 pad, u16 patchmap_idx
      patchmaps[patchmaps] 20B: priority volume pan reverb root_key fine_adj
                                note_min note_max pitchstep_min pitchstep_max,
                                u16 sample_id, attack/decay/release time,
                                u8 attack_level, decay_level
      patchinfo[patchinfo] 24B (= samples): u32 wdd_offset, s32 len,
                                u8 type (0 ADPCM, 1 RAW16), u8 flags, u16 pad,
                                s32 pitch (cents; stored in the 'loop' slot),
                                s32 loop_index (-1 none; in the 'book' slot),
                                s32 pad (runtime 'pitch' slot)
      drummaps[drummaps]    4B each (0 in Doom 64)
      loopinfo (8B): u16 nsfx1, rawcount, adpcmcount, nsfx2
      rawloops[rawcount]   16B: start, end, count, pad
      adpcmloops[adpcmcount] 48B: u32 start, end, count, s16 state[16], u32 pad
      books[patchinfo]    264B: s32 order, s32 npredictors, s16 book[128]
                                (fixed-size slot, indexed by sample index)
  trailer: file padding after the data block.
  WDD base = ROM segment start (g_wddloc); wave.base = WDD offset.
  Playback: ratio = 2^((pitch + (key-root_key)*100 - fine_adj)/1200) *
  22050/outrate, i.e. native rate at root key = 22050 * 2^(pitch/1200).

WSD: module_header (32, id 'SSSP'... value 0x53534551 is not checked), then
  sequences * 16B {u16 tracks, u16 decomp_type, u32 trkinfolength,
  u32 fileposition}, then per sequence at 32+data_size+fileposition: per
  track: track_header(20B, voices_type = sndclass 0 sfx/1 music/2 drums/3
  sfxdrums, initpatchnum ...), labellist u32[], event data.
"""
import json
import os
import struct
import sys
import wave

import numpy as np

try:  # optional JIT; everything also works (slowly) without it
    from numba import njit
except Exception:  # pragma: no cover
    def njit(*a, **k):
        if a and callable(a[0]):
            return a[0]
        return lambda f: f

OUT_RATE_BASE = 22050.0
AL_ADPCM_WAVE, AL_RAW16_WAVE = 0, 1


def _pad8(n):
    return (n + 7) & ~7


# ---------------------------------------------------------------- WMD parse
def parse_wmd(data: bytes) -> dict:
    d = bytes(data)
    mh = struct.unpack('>IIIHHBBBBIII', d[:32])
    hdr = dict(zip(['module_id_text', 'module_version', 'pad1', 'pad2', 'sequences',
                    'decomp_type', 'pad3', 'pad4', 'pad5', 'compress_size', 'data_size',
                    'pad6'], mh))
    if hdr['module_id_text'] != 0x534E3634 or hdr['module_version'] != 2:
        raise ValueError('not a WESS SN64 v2 module')
    if hdr['decomp_type'] != 0:
        raise ValueError('compressed WMD not supported')
    gh = struct.unpack('>IHHHHHHHHI', d[32:56])
    grp = dict(zip(['load_flags', 'patches', 'patch_size', 'patchmaps', 'patchmap_size',
                    'patchinfo', 'patchinfo_size', 'drummaps', 'drummap_size',
                    'extra_data_size'], gh))
    base = 56
    off = {}
    p = 0

    def block(name, n):
        nonlocal p
        off[name] = base + p
        start = p
        p = _pad8(p + n)
        return base + start, base + start + n, base + p  # start, end, padded end

    s, e, pe = block('patches', grp['patches'] * 4)
    patches = [dict(zip(['patchmap_cnt', 'pad1', 'patchmap_idx'], struct.unpack_from('>BBH', d, s + 4 * i)))
               for i in range(grp['patches'])]
    pads = {'patches': d[e:pe]}
    s, e, pe = block('patchmaps', grp['patchmaps'] * 20)
    mk = ['priority', 'volume', 'pan', 'reverb', 'root_key', 'fine_adj', 'note_min', 'note_max',
          'pitchstep_min', 'pitchstep_max', 'sample_id', 'attack_time', 'decay_time',
          'release_time', 'attack_level', 'decay_level']
    patchmaps = [dict(zip(mk, struct.unpack_from('>10BHHHHBB', d, s + 20 * i)))
                 for i in range(grp['patchmaps'])]
    pads['patchmaps'] = d[e:pe]
    s, e, pe = block('patchinfo', grp['patchinfo'] * 24)
    ik = ['offset', 'length', 'type', 'flags', 'pad', 'pitch', 'loop_index', 'pad2']
    samples = [dict(zip(ik, struct.unpack_from('>IiBBHiii', d, s + 24 * i)))
               for i in range(grp['patchinfo'])]
    pads['patchinfo'] = d[e:pe]
    s, e, pe = block('drummaps', grp['drummaps'] * 4)
    drummaps = d[s:e]
    pads['drummaps'] = d[e:pe]
    q = pe
    off['loopinfo'] = q
    loopinfo = dict(zip(['nsfx1', 'rawcount', 'adpcmcount', 'nsfx2'], struct.unpack_from('>4H', d, q)))
    q += 8
    off['rawloops'] = q
    rawloops = [dict(zip(['start', 'end', 'count', 'pad'], struct.unpack_from('>4I', d, q + 16 * i)))
                for i in range(loopinfo['rawcount'])]
    q += 16 * loopinfo['rawcount']
    off['adpcmloops'] = q
    adpcmloops = []
    for i in range(loopinfo['adpcmcount']):
        v = struct.unpack_from('>III16hI', d, q + 48 * i)
        adpcmloops.append({'start': v[0], 'end': v[1], 'count': v[2], 'state': list(v[3:19]), 'pad': v[19]})
    q += 48 * loopinfo['adpcmcount']
    off['books'] = q
    books = []
    for i in range(grp['patchinfo']):
        o, n = struct.unpack_from('>ii', d, q + 264 * i)
        coefs = list(struct.unpack_from('>128h', d, q + 264 * i + 8))
        books.append({'order': o, 'npredictors': n, 'book': coefs})
    q += 264 * grp['patchinfo']
    end_data = base + hdr['data_size']
    if q > end_data:
        raise ValueError('WMD tables overrun data_size')
    return {'header': hdr, 'group': grp, 'offsets': off, 'patches': patches,
            'patchmaps': patchmaps, 'samples': samples, 'drummaps': drummaps,
            'loopinfo': loopinfo, 'rawloops': rawloops, 'adpcmloops': adpcmloops,
            'books': books, 'pads': pads, 'tail_in_data': d[q:end_data],
            'trailer': d[end_data:]}


def write_wmd(w: dict) -> bytes:
    h, g = w['header'], w['group']
    out = bytearray(struct.pack('>IIIHHBBBBIII', *[h[k] for k in (
        'module_id_text', 'module_version', 'pad1', 'pad2', 'sequences', 'decomp_type',
        'pad3', 'pad4', 'pad5', 'compress_size', 'data_size', 'pad6')]))
    out += struct.pack('>IHHHHHHHHI', *[g[k] for k in (
        'load_flags', 'patches', 'patch_size', 'patchmaps', 'patchmap_size', 'patchinfo',
        'patchinfo_size', 'drummaps', 'drummap_size', 'extra_data_size')])
    for p in w['patches']:
        out += struct.pack('>BBH', p['patchmap_cnt'], p['pad1'], p['patchmap_idx'])
    out += w['pads']['patches']
    for m in w['patchmaps']:
        out += struct.pack('>10BHHHHBB', *[m[k] for k in (
            'priority', 'volume', 'pan', 'reverb', 'root_key', 'fine_adj', 'note_min', 'note_max',
            'pitchstep_min', 'pitchstep_max', 'sample_id', 'attack_time', 'decay_time',
            'release_time', 'attack_level', 'decay_level')])
    out += w['pads']['patchmaps']
    for s in w['samples']:
        out += struct.pack('>IiBBHiii', *[s[k] for k in (
            'offset', 'length', 'type', 'flags', 'pad', 'pitch', 'loop_index', 'pad2')])
    out += w['pads']['patchinfo']
    out += w['drummaps'] + w['pads']['drummaps']
    li = w['loopinfo']
    out += struct.pack('>4H', li['nsfx1'], li['rawcount'], li['adpcmcount'], li['nsfx2'])
    for r in w['rawloops']:
        out += struct.pack('>4I', r['start'], r['end'], r['count'], r['pad'])
    for l in w['adpcmloops']:
        out += struct.pack('>III16hI', l['start'], l['end'], l['count'], *l['state'], l['pad'])
    for b in w['books']:
        coefs = list(b['book']) + [0] * (128 - len(b['book']))
        out += struct.pack('>ii128h', b['order'], b['npredictors'], *coefs)
    out += w['tail_in_data']
    if len(out) != 56 + h['data_size']:
        raise ValueError('WMD size changed: %d != %d' % (len(out), 56 + h['data_size']))
    out += w['trailer']
    return bytes(out)


# ---------------------------------------------------------------- sample info
def sample_info(wmd: dict, i: int) -> dict:
    s = wmd['samples'][i]
    info = {'index': i, 'offset': s['offset'], 'length': s['length'], 'type': s['type'],
            'pitch': s['pitch'], 'rate': OUT_RATE_BASE * 2.0 ** (s['pitch'] / 1200.0),
            'loop': None, 'book': None}
    if s['type'] == AL_ADPCM_WAVE:
        info['frames'] = s['length'] // 9
        info['nsamples'] = info['frames'] * 16
        info['book'] = wmd['books'][i]
        if s['loop_index'] != -1:
            info['loop'] = wmd['adpcmloops'][s['loop_index']]
    else:
        info['frames'] = s['length'] // 2
        info['nsamples'] = info['frames']
        if s['loop_index'] != -1:
            info['loop'] = wmd['rawloops'][s['loop_index']]
    return info


def all_samples(wmd):
    return [sample_info(wmd, i) for i in range(len(wmd['samples']))]


def _book_array(book):
    o, n = book['order'], book['npredictors']
    return np.asarray(book['book'][:o * n * 8], dtype=np.int64).reshape(n, o, 8)


def _coef_table(book):
    """(npred, 8, order+8) matrix per predictor, SDK vdecodeframe layout."""
    b = _book_array(book)
    n, o = b.shape[0], b.shape[1]
    t = np.zeros((n, 8, o + 8), dtype=np.int64)
    for p in range(n):
        for i in range(8):
            for k in range(o):
                t[p, i, k] = b[p, k, i]
            for m in range(i):
                t[p, i, o + m] = b[p, o - 1, i - 1 - m]
            t[p, i, o + i] = 2048
    return t


# ---------------------------------------------------------------- VADPCM kernels
@njit(cache=True)
def _dec_kernel(buf, table, order, nframes):
    out = np.zeros(nframes * 16, dtype=np.int64)
    hist = np.zeros(8, dtype=np.int64)  # last outputs, hist[8-order:]
    vec = np.zeros(order + 8, dtype=np.int64)
    for f in range(nframes):
        h = buf[f * 9]
        scale = h >> 4
        pred = h & 15
        ix = np.zeros(16, dtype=np.int64)
        for j in range(8):
            b = buf[f * 9 + 1 + j]
            a = b >> 4
            c = b & 15
            if a >= 8:
                a -= 16
            if c >= 8:
                c -= 16
            ix[2 * j] = a << scale
            ix[2 * j + 1] = c << scale
        for g in range(2):
            for k in range(order):
                vec[k] = hist[8 - order + k]
            for i in range(8):
                vec[order + i] = ix[g * 8 + i]
            for i in range(8):
                acc = 0
                for k in range(order + 8):
                    acc += table[pred, i, k] * vec[k]
                v = acc >> 11
                if v > 32767:
                    v = 32767
                elif v < -32768:
                    v = -32768
                out[f * 16 + g * 8 + i] = v
                hist[i] = v
    return out


@njit(cache=True)
def _enc_kernel(x, table, order, npred, nframes):
    """Brute force over (predictor, scale) per frame; greedy closed-loop
    quantisation; exact decoder model. Returns bytes array and decoded pcm."""
    outb = np.zeros(nframes * 9, dtype=np.uint8)
    dec = np.zeros(nframes * 16, dtype=np.int64)
    hist = np.zeros(8, dtype=np.int64)
    best_n = np.zeros(16, dtype=np.int64)
    best_o = np.zeros(16, dtype=np.int64)
    cur_n = np.zeros(16, dtype=np.int64)
    cur_o = np.zeros(16, dtype=np.int64)
    vec = np.zeros(order + 8, dtype=np.int64)
    for f in range(nframes):
        best_e = -1.0
        best_p = 0
        best_s = 0
        for p in range(npred):
            for s in range(13):
                e = 0.0
                for g in range(2):
                    for k in range(order):
                        if g == 0:
                            vec[k] = hist[8 - order + k]
                        else:
                            vec[k] = cur_o[8 - order + k]
                    for i in range(8):
                        acc = 0
                        for k in range(order + i):
                            acc += table[p, i, k] * vec[k]
                        tgt = x[f * 16 + g * 8 + i]
                        want = (tgt * 2048.0 - acc) / (2048.0 * (1 << s))
                        n = int(np.floor(want + 0.5))
                        if n > 7:
                            n = 7
                        elif n < -8:
                            n = -8
                        while True:
                            v = (acc + ((n << s) << 11)) >> 11
                            if (v <= 32767 and v >= -32768) or n == 0:
                                break
                            n += -1 if n > 0 else 1
                        v = (acc + ((n << s) << 11)) >> 11
                        if v > 32767:
                            v = 32767
                        elif v < -32768:
                            v = -32768
                        vec[order + i] = n << s
                        cur_n[g * 8 + i] = n
                        cur_o[g * 8 + i] = v
                        d = float(v - tgt)
                        e += d * d
                    if best_e >= 0 and e >= best_e:
                        break
                if best_e < 0 or e < best_e:
                    best_e = e
                    best_p = p
                    best_s = s
                    for i in range(16):
                        best_n[i] = cur_n[i]
                        best_o[i] = cur_o[i]
        outb[f * 9] = (best_s << 4) | best_p
        for j in range(8):
            outb[f * 9 + 1 + j] = ((best_n[2 * j] & 15) << 4) | (best_n[2 * j + 1] & 15)
        for i in range(16):
            dec[f * 16 + i] = best_o[i]
        for i in range(8):
            hist[i] = best_o[8 + i]
    return outb, dec


def vadpcm_decode(data: bytes, book) -> np.ndarray:
    nframes = len(data) // 9
    t = _coef_table(book)
    buf = np.frombuffer(bytes(data[:nframes * 9]), dtype=np.uint8).astype(np.int64)
    return _dec_kernel(buf, t, book['order'], nframes).astype(np.int16)


def vadpcm_encode(pcm, book, nframes=None):
    x = np.asarray(pcm, dtype=np.int64)
    if nframes is None:
        nframes = (len(x) + 15) // 16
    x = np.concatenate([x, np.zeros(max(0, nframes * 16 - len(x)), dtype=np.int64)])[:nframes * 16]
    x = np.clip(x, -32768, 32767)
    t = _coef_table(book)
    b, dec = _enc_kernel(x, t, book['order'], book['npredictors'], nframes)
    return b.tobytes(), dec.astype(np.int16)


# ---------------------------------------------------------------- book design
def _autocorr_frames(x, order, fs=16):
    """Per-frame autocorrelation with `order` samples of history (tabledesign-like)."""
    x = np.asarray(x, dtype=np.float64)
    n = len(x) // fs
    xp = np.concatenate([np.zeros(order), x[:n * fs]])
    R = np.zeros((n, order + 1, order + 1))
    idx = np.arange(fs)[None, :] + (np.arange(n) * fs)[:, None] + order  # (n, fs)
    for a in range(order + 1):
        for b in range(order + 1):
            R[:, a, b] = np.sum(xp[idx - a] * xp[idx - b], axis=1)
    return R  # R[.,0,0]=energy; predictor a: x[t] ~ sum a_k x[t-k]


def _solve(Rs, order):
    A = Rs[1:, 1:] + np.eye(order) * (1e-6 * (Rs[0, 0] + 1.0))
    r = Rs[1:, 0]
    try:
        return np.linalg.solve(A, r)
    except np.linalg.LinAlgError:
        return np.zeros(order)


def _stabilise(a):
    """Bandwidth-expand until the predictor is stable and its book fits int16."""
    a = np.asarray(a, dtype=np.float64)
    for _ in range(200):
        roots = np.roots(np.concatenate([[1.0], -a])) if len(a) else np.array([])
        ok = np.all(np.abs(roots) < 0.9995) if len(roots) else True
        if ok and np.max(np.abs(_impulse(a))) * 2048 < 32767:
            return a
        a = a * (0.97 ** np.arange(1, len(a) + 1))
    return np.zeros_like(a)


def _impulse(a):
    order = len(a)
    resp = np.zeros((order, 8))
    for k in range(order):  # state element k (k=0 oldest)
        hist = [0.0] * order
        hist[k] = 1.0
        for i in range(8):
            v = sum(a[j] * hist[-1 - j] for j in range(order))
            resp[k, i] = v
            hist = hist[1:] + [v]
    return resp


def compute_book(pcm, order=2, npredictors=4, iters=12):
    """Design a VADPCM codebook from our own audio: LBG clustering of
    per-frame LPC predictors under the prediction-error metric."""
    R = _autocorr_frames(pcm, order)
    energy = R[:, 0, 0]
    act = R[energy > 16 * 16 * 16] if np.any(energy > 4096) else R
    if len(act) == 0:
        act = np.zeros((1, order + 1, order + 1))
    preds = [_solve(act.sum(0), order)]
    while len(preds) < npredictors:  # split
        new = []
        for a in preds:
            new += [a * 1.01 + 0.005, a * 0.99 - 0.005]
        preds = new[:npredictors]
        for _ in range(iters):
            P = np.array(preds)  # (K, order)
            # E = r00 - 2 a.r + a^T R a
            r = act[:, 1:, 0]
            Rm = act[:, 1:, 1:]
            E = act[:, 0, 0][:, None] - 2 * r @ P.T + np.einsum('ki,nij,kj->nk', P, Rm, P)
            lab = np.argmin(E, axis=1)
            for k in range(len(preds)):
                sel = act[lab == k]
                if len(sel):
                    preds[k] = _solve(sel.sum(0), order)
    while len(preds) < npredictors:
        preds.append(np.zeros(order))
    coefs = []
    for a in preds:
        resp = _impulse(_stabilise(a))
        coefs += [int(max(-32768, min(32767, round(v * 2048)))) for v in resp.reshape(-1)]
    return {'order': order, 'npredictors': npredictors,
            'book': coefs + [0] * (128 - len(coefs))}


# ---------------------------------------------------------------- sample API
def decode_sample(wdd: bytes, info: dict) -> np.ndarray:
    raw = wdd[info['offset']:info['offset'] + info['length']]
    if info['type'] == AL_RAW16_WAVE:
        return np.frombuffer(raw, dtype='>i2').astype(np.int16)
    return vadpcm_decode(raw, info['book'])


def loop_state_for(decoded, loop):
    """ADPCM loop state (libultra convention, verified 23/23 on retail): the
    16 decoded samples of the frame that CONTAINS the loop start, i.e.
    decoded[f*16:f*16+16] with f = start // 16. On wrap the synth serves the
    tail of that frame from the state and resumes decoding at frame f+1."""
    f = int(loop['start']) // 16
    s = np.zeros(16, dtype=np.int64)
    seg = np.asarray(decoded[f * 16:f * 16 + 16], dtype=np.int64)
    s[:len(seg)] = seg
    return [int(v) for v in s]


def encode_sample(pcm, info: dict, book=None):
    """Encode to exactly the original slot size. Returns (bytes, book,
    decoded int16, loop_state or None)."""
    if info['type'] == AL_RAW16_WAVE:
        n = info['length'] // 2
        x = np.clip(np.asarray(pcm, dtype=np.int64), -32768, 32767)
        x = np.concatenate([x, np.zeros(max(0, n - len(x)), dtype=np.int64)])[:n]
        return x.astype('>i2').tobytes() + b'\0' * (info['length'] - 2 * n), None, x.astype(np.int16), None
    ob = info['book']
    if book is None:
        book = compute_book(pcm, ob['order'], ob['npredictors'])
    if book['order'] != ob['order'] or book['npredictors'] != ob['npredictors']:
        raise ValueError('book order/npredictors must match the original slot')
    data, dec = vadpcm_encode(pcm, book, info['frames'])
    data += b'\0' * (info['length'] - len(data))
    st = loop_state_for(dec, info['loop']) if info['loop'] else None
    return data, book, dec, st


def set_book(wmd: dict, index: int, book: dict):
    b = wmd['books'][index]
    if book['order'] != b['order'] or book['npredictors'] != b['npredictors']:
        raise ValueError('order/npredictors must stay identical')
    coefs = list(book['book']) + [0] * (128 - len(book['book']))
    b['book'] = coefs[:128]


def set_loop_state(wmd: dict, index: int, state):
    li = wmd['samples'][index]['loop_index']
    if li == -1 or wmd['samples'][index]['type'] != AL_ADPCM_WAVE:
        return
    wmd['adpcmloops'][li]['state'] = [int(v) for v in state]


def rebuild_wdd(wmd: dict, blobs: dict, size: int) -> bytes:
    """blobs: sample index -> bytes (same length as the slot). Gaps keep zeros."""
    out = bytearray(size)
    for i, s in enumerate(wmd['samples']):
        b = blobs[i]
        if len(b) != s['length']:
            raise ValueError('sample %d length changed' % i)
        out[s['offset']:s['offset'] + s['length']] = b
    return bytes(out)


# ---------------------------------------------------------------- WSD (read only)
CMD_LEN = [0, 0, 0, 0, 0, 0, 0, 3, 2, 3, 2, 2, 2, 2, 2, 2, 2, 3, 2, 4, 5, 5, 2, 2,
           3, 3, 3, 3, 1, 1, 3, 3, 3, 1, 1, 1]


def _vlq(d, p):
    v = d[p]; p += 1
    if v & 0x80:
        v &= 0x7F
        while True:
            c = d[p]; p += 1
            v = (c & 0x7F) + (v << 7)
            if not c & 0x80:
                break
    return v, p


def parse_wsd(data: bytes) -> dict:
    d = bytes(data)
    mh = struct.unpack('>IIIHHBBBBIII', d[:32])
    nseq, dsize = mh[4], mh[10]
    base = 32 + dsize
    seqs = []
    for s in range(nseq):
        ntr, dt, ln, fp = struct.unpack_from('>HHII', d, 32 + 16 * s)
        p = base + fp
        tracks = []
        for _ in range(ntr):
            th = struct.unpack_from('>BBHHBBBBHHHI', d, p)
            th = dict(zip(['voices_type', 'reverb', 'initpatchnum', 'initpitch_cntrl',
                           'initvolume_cntrl', 'initpan_cntrl', 'substack_count', 'mutebits',
                           'initppq', 'initqpm', 'labellist_count', 'data_size'], th))
            ev = p + 20 + 4 * th['labellist_count']
            end = ev + th['data_size']
            patches, notes = {th['initpatchnum']}, set()
            cur = th['initpatchnum']
            q = ev
            try:
                _, q = _vlq(d, q)
                while q < end:
                    c = d[q]
                    if c >= 36:
                        break
                    if c == 7:
                        cur = d[q + 1] | (d[q + 2] << 8)
                        patches.add(cur)
                    elif c == 17:
                        notes.add((cur, d[q + 1]))
                    if c in (29, 34):  # SeqEnd / TrkEnd
                        break
                    q += CMD_LEN[c]
                    _, q = _vlq(d, q)
            except IndexError:
                pass
            th['patches'] = sorted(patches)
            th['notes'] = sorted(notes)
            tracks.append(th)
            p = end
        seqs.append({'tracks': tracks, 'decomp_type': dt, 'trkinfolength': ln, 'fileposition': fp})
    return {'sequences': seqs, 'data_size': dsize, 'size': len(d)}


def sample_usage(wmd, wsd):
    """sample index -> {'patches': set, 'seqs': set, 'classes': set}."""
    use = {i: {'patches': set(), 'seqs': set(), 'classes': set()} for i in range(len(wmd['samples']))}
    for si, sq in enumerate(wsd['sequences']):
        for t in sq['tracks']:
            for (pn, note) in t['notes']:
                if pn >= len(wmd['patches']):
                    continue
                pt = wmd['patches'][pn]
                for m in range(pt['patchmap_idx'], pt['patchmap_idx'] + pt['patchmap_cnt']):
                    pm = wmd['patchmaps'][m]
                    if pm['note_min'] <= note <= pm['note_max']:
                        u = use[pm['sample_id']]
                        u['patches'].add(pn); u['seqs'].add(si); u['classes'].add(t['voices_type'])
    return use


# ---------------------------------------------------------------- CLI
def _load(ddir):
    rd = lambda n: open(os.path.join(ddir, n), 'rb').read()
    return rd('DOOM64.WMD'), rd('DOOM64.WSD'), rd('DOOM64.WDD')


def _write_wav(path, pcm, rate):
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(int(round(rate)))
        w.writeframes(np.asarray(pcm, dtype='<i2').tobytes())


CLASS = {0: 'sfx', 1: 'music', 2: 'drums', 3: 'sfxdrums'}


def cmd_dump(ddir, outdir):
    wmdb, wsdb, wdd = _load(ddir)
    wmd, wsd = parse_wmd(wmdb), parse_wsd(wsdb)
    use = sample_usage(wmd, wsd)
    # patches referencing a sample via patchmaps (regardless of notes played)
    refp = {i: set() for i in range(len(wmd['samples']))}
    for pn, pt in enumerate(wmd['patches']):
        for m in range(pt['patchmap_idx'], pt['patchmap_idx'] + pt['patchmap_cnt']):
            refp[wmd['patchmaps'][m]['sample_id']].add(pn)
    os.makedirs(outdir, exist_ok=True)
    rows = []
    for info in all_samples(wmd):
        i = info['index']
        pcm = decode_sample(wdd, info)
        _write_wav(os.path.join(outdir, 'sample_%03d.wav' % i), pcm, info['rate'])
        cl = sorted(CLASS[c] for c in use[i]['classes'])
        lp = info['loop']
        rows.append({'index': i, 'wdd_offset': info['offset'], 'length_bytes': info['length'],
                     'type': 'adpcm' if info['type'] == 0 else 'raw16',
                     'frames': info['frames'], 'nsamples': info['nsamples'],
                     'pitch_cents': info['pitch'], 'rate': round(info['rate'], 3),
                     'loop': None if lp is None else {'start': lp['start'], 'end': lp['end'],
                                                      'count': lp['count'] - (1 << 32) if lp['count'] >= 1 << 31 else lp['count']},
                     'book_order': info['book']['order'] if info['book'] else None,
                     'book_npredictors': info['book']['npredictors'] if info['book'] else None,
                     'patches': sorted(refp[i]), 'played_by_patches': sorted(use[i]['patches']),
                     'sequences': sorted(use[i]['seqs']), 'classes': cl,
                     'use': ('sfx' if cl and all(c.startswith('sfx') for c in cl) else
                             'music' if cl and not any(c.startswith('sfx') for c in cl) else
                             'both' if cl else 'unused')})
    json.dump(rows, open(os.path.join(outdir, 'samples.json'), 'w'), indent=1)
    rates = sorted({r['rate'] for r in rows})
    from collections import Counter
    print('samples %d  frames %d  seconds %.1f' % (len(rows), sum(r['frames'] for r in rows),
                                                   sum(r['nsamples'] / r['rate'] for r in rows)))
    print('rates', rates)
    print('use', dict(Counter(r['use'] for r in rows)))
    print('books', dict(Counter((r['book_order'], r['book_npredictors']) for r in rows)))
    print('loops', sum(1 for r in rows if r['loop']))
    nsq = len(wsd['sequences'])
    tc = Counter(t['voices_type'] for s in wsd['sequences'] for t in s['tracks'])
    print('WSD: %d sequences, track classes %s' % (nsq, {CLASS.get(k, k): v for k, v in tc.items()}))
    print('wrote', outdir)


def cmd_selftest(ddir):
    import time
    wmdb, wsdb, wdd = _load(ddir)
    wmd = parse_wmd(wmdb)
    ok = write_wmd(wmd) == wmdb
    print('(a) WMD parse/write round-trip byte-exact:', ok)
    wsd = parse_wsd(wsdb)
    print('    WSD: %d sequences, %d tracks, size %d (unchanged, not rewritten)' % (
        len(wsd['sequences']), sum(len(s['tracks']) for s in wsd['sequences']), wsd['size']))
    t0 = time.time()
    infos = all_samples(wmd)
    blobs, snrs, lenok, stok, st_orig = {}, [], True, [], []
    wmd2 = parse_wmd(wmdb)
    for info in infos:
        pcm = decode_sample(wdd, info)
        data, book, dec, st = encode_sample(pcm, info, book=info['book'])
        lenok &= len(data) == info['length']
        dec2 = decode_sample(data + b'', dict(info, offset=0))
        assert np.array_equal(dec2, dec), 'encoder decoder model mismatch'
        e = np.sum((dec.astype(np.float64) - pcm) ** 2)
        snrs.append(10 * np.log10((np.sum(pcm.astype(np.float64) ** 2) + 1) / (e + 1)))
        blobs[info['index']] = data
        if st is not None:
            orig = wmd['adpcmloops'][wmd['samples'][info['index']]['loop_index']]['state']
            st_orig.append(np.array_equal(loop_state_for(pcm, info['loop']), orig))
            set_loop_state(wmd2, info['index'], st)
    snrs = np.array(snrs)
    print('(b) re-encode with original books: %d samples in %.1fs, lengths match: %s' % (
        len(infos), time.time() - t0, lenok))
    print('    SNR dB min %.1f median %.1f mean %.1f (worst idx %d)' % (
        snrs.min(), np.median(snrs), snrs.mean(), int(np.argmin(snrs))))
    print('    loop state == frame containing loop start (retail): %d/%d' % (sum(st_orig), len(st_orig)))
    new = rebuild_wdd(wmd, blobs, len(wdd))
    offs_ok = all(sample_info(wmd, i)['offset'] == s['offset'] for i, s in enumerate(wmd['samples']))
    print('(c) rebuilt WDD size %d == %d: %s; offsets unchanged: %s; identical bytes: %.1f%%' % (
        len(new), len(wdd), len(new) == len(wdd), offs_ok,
        100.0 * np.mean(np.frombuffer(new, np.uint8) == np.frombuffer(wdd, np.uint8))))
    w2 = write_wmd(wmd2)
    print('    WMD with recomputed loop states: size unchanged %s, identical %s' % (
        len(w2) == len(wmdb), w2 == wmdb))
    # clean-style book from own pcm for a few samples
    for i in [0, int(np.argmin(snrs)), len(infos) - 1]:
        info = infos[i]
        pcm = decode_sample(wdd, info)
        data, book, dec, st = encode_sample(pcm, info)
        e = np.sum((dec.astype(np.float64) - pcm) ** 2)
        print('    computed-book encode idx %d: SNR %.1f dB (orig-book %.1f)' % (
            i, 10 * np.log10((np.sum(pcm.astype(np.float64) ** 2) + 1) / (e + 1)), snrs[i]))


if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) >= 3 and a[0] == 'dump':
        cmd_dump(a[1], a[2])
    elif len(a) >= 2 and a[0] == 'selftest':
        cmd_selftest(a[1])
    else:
        print('usage: wessfmt.py dump <Data dir> <outdir> | selftest <Data dir>')
