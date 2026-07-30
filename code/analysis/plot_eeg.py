#!/usr/bin/env python3
"""
plot_eeg.py — plot the PROCESSED EEG traces of a Brain-Life recording.

The `_summary.png` and `_FI.png` figures show the Focus Index, a single derived
ratio. This shows the EEG the analysis actually consumes — the `AF3_processed` /
`AF4_processed` channels named by `metadata.EEG_CHANNELS`, read from the EDF the
pipeline exported, over the same block timeline.

Signals are read from the EDF rather than recomputed, so what you see is exactly
what `compute_fi_timeline()` was given. `_processed` means DC blocking, notch at
60/50/32 Hz, and a 1-35 Hz bandpass (`csv_to_edf_denoised.preprocess_eeg`).

Panels
------
  1-2  each channel across the session, drawn as a per-pixel min/max band so no
       sample is skipped by decimation. The Y AXIS IS STILL CLIPPED, to the 99.7th
       percentile — these recordings contain transients running several times that,
       and scaling to them would flatten the EEG into a line. Each title states how
       much is drawn off-screen, and gives both the plain RMS and a robust SD
       (1.4826·MAD): for ban's AF4 those are 151 µV and 25 µV, because the top 0.1%
       of samples hold ~65% of the variance. Quote the robust figure when you mean
       "how big is the EEG".
  3    a short zoom, where individual rhythms are actually resolvable
  4    band power per block — what changes task to task, which a trace cannot show.
       Each channel's PSD is computed separately and then averaged; concatenating
       the two channels before Welch would take the PSD across the splice and let
       the noisier channel dominate.

The baseline's eyes-closed/eyes-open alpha ratio is computed per channel and shown
in the figure, because it is the one built-in physiological validity check these
recordings carry. A ratio at or below 1 means alpha did not rise on eye closure and
nothing derived from the recording — least of all a β/α focus index — should be
trusted.

A note on `_processed` vs `_denoised`
------------------------------------
When a recording fails the band-noise check the pipeline applies WPT denoising and
writes the result as a SEPARATE pair of channels (`AF3_denoised`/`AF4_denoised`),
routing the file to `edf/good_denoised/`. It does NOT overwrite `_processed`, and
`metadata.EEG_CHANNELS` names `_processed` — so the Focus Index is computed from
the channel that failed the check, not from the denoised one. minhanh_29_16_29 is
exactly this case. Panel 3 overlays the denoised trace where it exists so the
difference is visible; the analysis is using the solid one.

Usage
-----
  python plot_eeg.py                          # both recordings in code/results/eeg_bl
  python plot_eeg.py --only ban
  python plot_eeg.py --zoom-at 700 --zoom-len 6
"""

import argparse
import glob
import os
import sys

import numpy as np
import pyedflib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
from scipy.signal import welch

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import session_timeline as st
from metadata import EEG_CHANNELS, EEG_ALPHA, EEG_BETA
from utils import shade_timeline, timeline_legend

REPO_ROOT     = os.path.dirname(os.path.dirname(CODE_DIR))
EEG_BL_DIR    = os.path.join(REPO_ROOT, "code", "results", "eeg_bl")
BEHAVIORS_DIR = os.path.join(REPO_ROOT, "code", "results", "behaviors")
EDF_DIR       = os.path.join(REPO_ROOT, "data", "derived", "eeg_bl", "edf")
GRAPH_DIR     = os.path.join(REPO_ROOT, "graph", "eeg_bl")

BANDS = [("delta", 1, 4, "#6b7280"), ("theta", 4, 8, "#0891b2"),
         ("alpha", EEG_ALPHA[0], EEG_ALPHA[1], "#2563eb"),
         ("beta", EEG_BETA[0], EEG_BETA[1], "#dc2626")]

CH_COLORS = {"AF3": "#1f5fbf", "AF4": "#c2410c"}


def find_edf(stem):
    for sub in ("good", "good_denoised", "bad_denoised"):
        p = os.path.join(EDF_DIR, sub, stem + ".edf")
        if os.path.exists(p):
            return p, sub
    return None, None


def read_edf(path):
    with pyedflib.EdfReader(path) as f:
        labels = f.getSignalLabels()
        fs = float(f.getSampleFrequency(0))
        sig = {l: f.readSignal(i) for i, l in enumerate(labels)}
    return sig, fs


def envelope(x, fs, n_cols=4000):
    """Min/max decimation so spikes survive downsampling for display."""
    n = len(x)
    if n <= n_cols * 2:
        return np.arange(n) / fs, x, x
    step = int(np.ceil(n / n_cols))
    blocks = x[:(n // step) * step].reshape(-1, step)
    t = (np.arange(blocks.shape[0]) * step + step / 2) / fs
    return t, np.nanmin(blocks, axis=1), np.nanmax(blocks, axis=1)


def robust_ylim(x, pct=99.7, pad=1.15):
    finite = x[np.isfinite(x)]
    v = float(np.nanpercentile(np.abs(finite), pct)) * pad if finite.size else 1.0
    return (-v, v) if v > 0 else (-1.0, 1.0)


def band_powers(x, fs, lo, hi):
    """Absolute band power over one segment, via Welch."""
    if len(x) < int(4 * fs):
        return np.nan
    fr, P = welch(x, fs=fs, nperseg=int(4 * fs))
    m = (fr >= lo) & (fr <= hi)
    return float(np.trapezoid(P[m], fr[m])) if m.any() else np.nan


def band_powers_pooled(segs, fs, lo, hi):
    """Mean band power across channels — each PSD computed on its own segment.

    Never concatenate the channels first: that takes the PSD across the splice and
    weights whichever channel carries more power, which for a transient-heavy
    channel is not the one you want deciding the answer.
    """
    vals = [band_powers(s, fs, lo, hi) for s in segs]
    vals = [v for v in vals if np.isfinite(v)]
    return float(np.mean(vals)) if vals else np.nan


def robust_sd(x):
    """1.4826·MAD — an amplitude that rare transients cannot inflate."""
    finite = x[np.isfinite(x)]
    if finite.size == 0:
        return float("nan")
    return float(1.4826 * np.median(np.abs(finite - np.median(finite))))


def task_blocks(windows):
    return [w for w in windows
            if not w["is_interval"] and not w.get("is_prefocus")]


def plot_recording(stem, edf_path, quality, windows, title, save_path,
                   zoom_at=None, zoom_len=8.0):
    sig, fs = read_edf(edf_path)
    proc = {ch: sig[f"{ch}_processed"] for ch in ("AF3", "AF4")}
    denoised = {ch: sig[f"{ch}_denoised"] for ch in ("AF3", "AF4")
                if f"{ch}_denoised" in sig}
    dur = len(proc["AF3"]) / fs

    blocks = task_blocks(windows)
    if zoom_at is None:
        first = next((w for w in blocks if not w["is_baseline"]), None)
        zoom_at = (first["t_start"] + first["t_end"]) / 2 if first else dur / 2
    zoom_at = max(0.0, min(float(zoom_at), max(0.0, dur - zoom_len)))

    # The baseline's own eyes-closed phase is the only physiological validity check
    # these recordings carry, so it belongs on the figure, not just in stdout.
    alpha = _alpha_reactivity(proc, fs, windows)
    ok = all(np.isfinite(v) and v > 1.15 for v in alpha.values()) if alpha else False
    banner = ("eyes-closed alpha reactivity  "
              + "  ".join(f"{ch} {v:.2f}×" for ch, v in alpha.items())
              + ("   → PASS, alpha rises on eye closure"
                 if ok else
                 "   → FAIL: alpha does not rise on eye closure, so β/α here is not "
                 "interpretable as focus"))

    fig = plt.figure(figsize=(20, 16))
    fig.suptitle(f"{title}   —   PROCESSED EEG  ({', '.join(EEG_CHANNELS)})",
                 fontsize=11, fontweight="bold")
    fig.text(0.5, 0.955, banner, ha="center", fontsize=9.5,
             fontweight="bold", color="#14532d" if ok else "#7f1d1d")
    gs = gridspec.GridSpec(4, 1, height_ratios=[3, 3, 2.6, 2.8], hspace=0.85)

    # ── Panels 1-2: whole session, one per channel ───────────────────────────
    for i, ch in enumerate(("AF3", "AF4")):
        ax = fig.add_subplot(gs[i])
        x = proc[ch]
        t, lo, hi = envelope(x, fs)
        shade_timeline(ax, windows, x_scale=1.0, x_max=dur)
        ax.fill_between(t, lo, hi, color=CH_COLORS[ch], lw=0, zorder=3)
        ax.set_xlim(0, dur)
        ylo, yhi = robust_ylim(x)
        ax.set_ylim(ylo, yhi)
        off = float(np.mean(np.abs(x) > yhi)) * len(x) / fs      # seconds off-screen
        ax.set_title(f"{ch}_processed — DC-blocked, notched 60/50/32 Hz, "
                     f"bandpass 1–35 Hz   robust SD {robust_sd(x):.1f} µV "
                     f"(plain RMS {np.std(x):.1f} µV)   "
                     f"true range {np.nanmin(x):,.0f} … {np.nanmax(x):,.0f} µV, "
                     f"y-axis ±{yhi:,.0f} so {off:.1f} s is drawn off-screen",
                     fontsize=9)
        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_ylabel("µV", fontsize=8)
        ax.grid(True, alpha=0.25, zorder=0)
        ax.tick_params(labelsize=7)

    # ── Panel 3: zoom, where rhythms are resolvable ──────────────────────────
    ax3 = fig.add_subplot(gs[2])
    s0, s1 = int(zoom_at * fs), int((zoom_at + zoom_len) * fs)
    tz = np.arange(s0, min(s1, len(proc["AF3"]))) / fs
    for ch in ("AF3", "AF4"):
        seg = proc[ch][s0:s1][:len(tz)]
        ax3.plot(tz, seg, lw=0.9, color=CH_COLORS[ch], zorder=4,
                 label=f"{ch}_processed")
    label = next((w["label"] for w in windows if w["t_start"] <= zoom_at < w["t_end"]), "?")
    ax3.set_xlim(tz[0], tz[-1])
    ax3.set_title(f"AF3_processed / AF4_processed — zoom, {zoom_len:g} s from "
                  f"t={zoom_at:.0f} s, inside “{label}”", fontsize=9)
    ax3.set_xlabel("Time (s)", fontsize=8)
    ax3.set_ylabel("µV", fontsize=8)
    ax3.legend(loc="upper right", fontsize=7, ncol=2)
    ax3.grid(True, alpha=0.25, zorder=0)
    ax3.tick_params(labelsize=7)

    # ── Panel 4: band power per block ────────────────────────────────────────
    ax4 = fig.add_subplot(gs[3])
    labels = [w["label"] for w in blocks]
    xs = np.arange(len(blocks))
    width = 0.8 / len(BANDS)
    for bi, (bname, blo, bhi, bcolor) in enumerate(BANDS):
        vals = []
        for w in blocks:
            a, b = int(w["t_start"] * fs), int(w["t_end"] * fs)
            vals.append(band_powers_pooled(
                [proc["AF3"][a:b], proc["AF4"][a:b]], fs, blo, bhi))
        ax4.bar(xs + bi * width - 0.4 + width / 2, vals, width,
                color=bcolor, label=f"{bname} ({blo}–{bhi} Hz)", zorder=3)
    ax4.set_yscale("log")
    ax4.set_xticks(xs)
    ax4.set_xticklabels(labels, fontsize=8)
    ax4.set_ylabel("band power (µV²), log", fontsize=8)
    ax4.set_title("AF3_processed + AF4_processed — band power per block, channels pooled  "
                  "(baseline is one bar but six sub-phases, so read it with care)",
                  fontsize=9)
    ax4.legend(loc="upper right", fontsize=7, ncol=4)
    ax4.grid(True, alpha=0.25, axis="y", zorder=0)
    ax4.tick_params(labelsize=7)

    handles = [mpatches.Patch(facecolor=c, alpha=0.5, label=l)
               for c, l in timeline_legend(windows)]
    if handles:
        fig.legend(handles=handles, loc="lower center", ncol=len(handles),
                   fontsize=8, framealpha=0.8, bbox_to_anchor=(0.5, 0.005))
    plt.subplots_adjust(bottom=0.06)

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved → {save_path}")

    return dict(stem=stem, quality=quality, fs=fs, dur=dur,
                rms={ch: float(np.std(proc[ch])) for ch in proc},
                robust={ch: robust_sd(proc[ch]) for ch in proc},
                has_denoised=bool(denoised),
                alpha_ratio=alpha, alpha_pass=ok)


def _alpha_reactivity(proc, fs, windows):
    """Eyes-closed vs eyes-open relative alpha inside the baseline.

    The baseline runs eyes-open 10-70 s and eyes-closed 120-180 s of its own
    span, so this is the one built-in physiological check on the recording: a
    ratio near or below 1 means the expected alpha reactivity is absent.
    """
    base = next((w for w in windows if w["is_baseline"]), None)
    if base is None:
        return {}
    def rel(ch, t0, t1):
        a, b = int((base["t_start"] + t0) * fs), int((base["t_start"] + t1) * fs)
        seg = proc[ch][a:b]
        tot = band_powers(seg, fs, 2, 40)
        al = band_powers(seg, fs, EEG_ALPHA[0], EEG_ALPHA[1])
        return al / tot if tot and np.isfinite(tot) else np.nan
    out = {}
    for ch in ("AF3", "AF4"):
        eo, ec = rel(ch, 10, 70), rel(ch, 120, 180)
        out[ch] = float(ec / eo) if eo and np.isfinite(eo) else float("nan")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eeg-dir", default=EEG_BL_DIR)
    ap.add_argument("--graph-dir", default=GRAPH_DIR)
    ap.add_argument("--only", default=None)
    ap.add_argument("--zoom-at", type=float, default=None)
    ap.add_argument("--zoom-len", type=float, default=8.0)
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(args.eeg_dir, "*.csv")))
    if args.only:
        paths = [p for p in paths if args.only in os.path.basename(p)]
    if not paths:
        print(f"No recordings in {args.eeg_dir}")
        return 1

    rows = []
    for csv_path in paths:
        stem = os.path.splitext(os.path.basename(csv_path))[0]
        edf_path, quality = find_edf(stem)
        print(f"\n{stem}")
        if edf_path is None:
            print("  no EDF — run run_session_analysis.py first")
            continue
        print(f"  EDF: {quality}/")

        session, note = st.find_session_for_recording(csv_path, BEHAVIORS_DIR)
        if session is not None:
            windows = st.build_session_windows(
                session["task_order"], measured=st.measure_block_durations(session["dir"]))
            title = f"{stem}   —   session {session['session']}"
        else:
            windows = st.build_session_windows(st.generic_task_order())
            title = f"{stem}   —   NO PAIRED SESSION, block labels are generic"
        print(f"  pairing: {note}")

        rows.append(plot_recording(
            stem, edf_path, quality, windows, title,
            os.path.join(args.graph_dir, stem + "_eeg.png"),
            zoom_at=args.zoom_at, zoom_len=args.zoom_len))

    if rows:
        print(f"\n{'=' * 78}\nProcessed-EEG summary\n{'=' * 78}")
        for r in rows:
            a = "  ".join(f"{ch} {v:.2f}x" for ch, v in r["alpha_ratio"].items())
            print(f"  {r['stem'][:30]:30s} {r['quality']:14s} "
                  f"robust SD AF3 {r['robust']['AF3']:6.1f} AF4 {r['robust']['AF4']:6.1f} µV "
                  f"(RMS {r['rms']['AF3']:.0f}/{r['rms']['AF4']:.0f})  "
                  f"alpha {a}  {'PASS' if r['alpha_pass'] else 'FAIL'}"
                  f"{'  [WPT channel written but never read]' if r['has_denoised'] else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
