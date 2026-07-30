"""
blink.py — ocular-artifact detection and exclusion for the 2-channel Brain-Life band.

The pipeline's EEG cleaning is DC blocking, notches at 60/50/32 Hz, and a 1-35 Hz
bandpass. Blinks and saccades sit at roughly 0.5-5 Hz, i.e. INSIDE that passband, so
nothing in the pipeline removes them: measured on ban_29_14_40's five logged blink
cues, AF3_processed still reaches 8884 µV peak-to-peak against a 93 µV eyes-open
floor, and delta ends up carrying 77-90% of all 1-35 Hz power.

Why exclusion rather than correction
------------------------------------
The usual fix is ICA, which needs enough channels to isolate an ocular component.
This device gives two bipolar derivations (AF3−T7, AF4−T8) — far too few to
separate blink from brain, and both sit directly over the eyes where the artifact is
largest. Regression needs a dedicated EOG channel, which does not exist here.
Interpolating across a blink would invent data and quietly lower the variance.

So this module DETECTS artifact spans and lets callers EXCLUDE them. Nothing is
reconstructed. `band_power_clean` computes a PSD per surviving segment and averages
them weighted by length, so excising a span never introduces a splice discontinuity
of its own — the failure mode of simply deleting samples and re-running Welch.

The baseline is left alone by default
-------------------------------------
`run_all_experiments` deliberately spends 50 s of its 182 s baseline on guided
blinks and horizontal/vertical eye movements (SESSION["baseline_phases"]). Those
artifacts are the intended signal there — they are what pins the recording's time
alignment, and five of them are individually logged in task.csv. Detecting inside
the baseline would flag the protocol as noise and would also inflate the amplitude
threshold for the whole recording. Hence `skip_baseline=True` and a threshold
estimated only from non-baseline data.
"""

import numpy as np
from scipy.signal import butter, sosfiltfilt, welch

#: Blink and saccade energy concentrates here. The upper edge stays below alpha so
#: the detector does not key on genuine rhythms.
BLINK_BAND = (1.0, 5.0)

#: Envelope smoothing. A blink lasts 100-400 ms; this is long enough to bridge the
#: two lobes of one deflection and short enough not to merge separate events.
ENVELOPE_MS = 200.0

#: Threshold in robust SDs of the envelope. 5 is deliberately conservative — it
#: catches the excursions that dominate the variance without eating ordinary EEG.
N_ROBUST_SD = 5.0

#: Each supra-threshold run is widened by this much on both sides, because the
#: envelope crosses back below threshold while the deflection is still returning.
PAD_S = 0.25

#: Runs shorter than this are not blinks (single-sample spikes, quantisation).
MIN_DUR_S = 0.06


def _robust_sd(x):
    """1.4826·MAD — an amplitude estimate that the artifacts themselves can't inflate."""
    finite = x[np.isfinite(x)]
    if finite.size == 0:
        return float("nan")
    return float(1.4826 * np.median(np.abs(finite - np.median(finite))))


def _envelope(x, fs, band=BLINK_BAND, smooth_ms=ENVELOPE_MS):
    sos = butter(3, band, btype="band", fs=fs, output="sos")
    band_limited = sosfiltfilt(sos, np.nan_to_num(x, nan=0.0))
    k = max(1, int(smooth_ms / 1000.0 * fs))
    kernel = np.ones(k) / k
    return np.convolve(np.abs(band_limited), kernel, mode="same")


def baseline_span(windows):
    """(start, end) of the baseline block in seconds, or None."""
    base = next((w for w in windows if w.get("is_baseline")), None)
    return (base["t_start"], base["t_end"]) if base else None


def detect_blinks(channels, fs, windows=None, skip_baseline=True,
                  n_robust_sd=N_ROBUST_SD, pad_s=PAD_S, min_dur_s=MIN_DUR_S):
    """Find ocular-artifact spans across one or more channels.

    `channels` is a sequence of 1-D arrays sharing a time base; a span flagged on
    either channel is excluded from both, since they are simultaneous samples of
    one head and a blink is never one-sided.

    Returns (spans, info) where spans is a list of (start_s, end_s) and info
    carries the thresholds and the fraction of time excluded.
    """
    n = min(len(c) for c in channels)
    dur = n / fs
    base = baseline_span(windows or []) if skip_baseline else None

    # Estimate the threshold from non-baseline samples only, so the baseline's
    # deliberate blink and eye-movement phases do not raise the bar everywhere else.
    ref = np.ones(n, dtype=bool)
    if base:
        b0, b1 = int(base[0] * fs), int(min(base[1], dur) * fs)
        ref[b0:b1] = False

    flagged = np.zeros(n, dtype=bool)
    thresholds = {}
    for i, ch in enumerate(channels):
        env = _envelope(np.asarray(ch[:n], dtype=float), fs)
        pool = env[ref] if ref.any() else env
        thr = float(np.median(pool) + n_robust_sd * _robust_sd(pool))
        thresholds[i] = thr
        flagged |= env > thr

    if base:
        b0, b1 = int(base[0] * fs), int(min(base[1], dur) * fs)
        flagged[b0:b1] = False          # the baseline's artifacts are the protocol

    # Contiguous runs -> padded, merged spans
    edges = np.diff(flagged.astype(np.int8))
    starts = list((np.flatnonzero(edges == 1) + 1))
    ends = list(np.flatnonzero(edges == -1) + 1)
    if flagged[0]:
        starts.insert(0, 0)
    if flagged[-1]:
        ends.append(n)

    spans = []
    for s, e in zip(starts, ends):
        if (e - s) / fs < min_dur_s:
            continue
        a, b = max(0.0, s / fs - pad_s), min(dur, e / fs + pad_s)
        if spans and a <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], b))
        else:
            spans.append((a, b))

    mask = spans_to_mask(spans, n, fs)
    info = dict(thresholds=thresholds, n_spans=len(spans),
                excluded_frac=float(mask.mean()),
                excluded_s=float(mask.sum() / fs),
                baseline_skipped=bool(base), duration_s=dur)
    return spans, info


def spans_to_mask(spans, n, fs):
    """Boolean array, True where a sample falls inside an artifact span."""
    mask = np.zeros(n, dtype=bool)
    for a, b in spans:
        mask[max(0, int(a * fs)):min(n, int(b * fs))] = True
    return mask


def clean_segments(mask, fs, min_len_s):
    """(start, end) sample indices of artifact-free runs at least min_len_s long."""
    keep = ~mask
    edges = np.diff(keep.astype(np.int8))
    starts = list(np.flatnonzero(edges == 1) + 1)
    ends = list(np.flatnonzero(edges == -1) + 1)
    if keep[0]:
        starts.insert(0, 0)
    if keep[-1]:
        ends.append(len(keep))
    need = int(min_len_s * fs)
    return [(s, e) for s, e in zip(starts, ends) if e - s >= need]


def band_power_clean(x, fs, mask, lo, hi, nperseg_s=4.0):
    """Band power over the artifact-free parts of x.

    One Welch PSD per clean segment, averaged weighted by segment length. Deleting
    the flagged samples and running a single Welch would splice the survivors
    together and put a step at every join — broadband energy that lands mostly in
    the band this is trying to measure.
    """
    x = np.asarray(x, dtype=float)
    segs = clean_segments(mask[:len(x)], fs, nperseg_s)
    if not segs:
        return float("nan")
    nperseg = int(nperseg_s * fs)
    total, weight = 0.0, 0.0
    for s, e in segs:
        seg = x[s:e]
        if len(seg) < nperseg:
            continue
        fr, P = welch(seg, fs=fs, nperseg=nperseg)
        m = (fr >= lo) & (fr <= hi)
        if not m.any():
            continue
        total += float(np.trapezoid(P[m], fr[m])) * len(seg)
        weight += len(seg)
    return total / weight if weight else float("nan")


def summarise(info, per_block=None):
    """One-line description of what was excluded."""
    s = (f"{info['n_spans']} artifact spans, {info['excluded_s']:.0f} s excluded "
         f"({info['excluded_frac'] * 100:.1f}% of {info['duration_s']:.0f} s)")
    if info.get("baseline_skipped"):
        s += "; baseline left intact (its blinks and eye movements are the protocol)"
    return s
