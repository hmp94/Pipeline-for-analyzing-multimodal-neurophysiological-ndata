#!/usr/bin/env python3
"""
plot_raw_eeg.py — plot the RAW EEG traces of a Brain-Life recording.

The existing figures show the Focus Index (β/α), a derived measure. This one
shows the underlying EEG voltage itself, over the same block timeline, so a
recording's quality can be judged by eye before any of the derived numbers are
trusted.

"Raw" here means the device's own samples converted to microvolts and
DC-corrected, computed straight from the CSV in float:

    uV = (count - 2**23) * 1e6 * 1.6 / 2**23 / 2      (0.095367 uV per count)

That is deliberately NOT read back from the EDF the pipeline exports.
csv_to_edf_denoised.convert_to_uV() applies the same scale but then casts to
np.int16 BEFORE removing the DC offset. These electrodes sit at roughly
-160 to -200 mV, i.e. -1.7e5 to -2.1e5 uV, so every single sample is outside
int16's ±32767 and the cast wraps modulo 65536. Whether that matters depends on
where a recording's range happens to fall:

  * if the whole range sits inside one 65536-wide band, the wrap is a constant
    offset and is harmless (ban_29_14_40: 0 induced jumps);
  * if the range straddles a band edge, the signal is shredded by ±65536 uV step
    discontinuities (minhanh_29_16_29: 41329 on AF3, ~1495 per minute).

So the bottom "as exported" panel is not decoration — it is how you tell which
of those two a recording is, and therefore whether its EDF-derived FI means
anything. Fixing the export is a one-line reorder in csv_to_edf_denoised.py
(subtract the DC reference, and keep float, before any cast); this script does not
change it, it only shows the consequence.

Usage
-----
  python plot_raw_eeg.py                       # every recording in code/results/eeg_bl/
  python plot_raw_eeg.py --only ban            # filter by filename substring
  python plot_raw_eeg.py --zoom-at 700 --zoom-len 10
"""

import argparse
import glob
import os
import sys

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import session_timeline as st
from utils import shade_timeline, timeline_legend

REPO_ROOT     = os.path.dirname(os.path.dirname(CODE_DIR))
EEG_BL_DIR    = os.path.join(REPO_ROOT, "code", "results", "eeg_bl")
BEHAVIORS_DIR = os.path.join(REPO_ROOT, "code", "results", "behaviors")
GRAPH_DIR     = os.path.join(REPO_ROOT, "graph", "eeg_bl")

EEG_FS   = 244.0
MIDSCALE = 2 ** 23
UV_PER_COUNT = 1_000_000 * 1.6 / MIDSCALE / 2      # 0.095367 uV/count
INT16_SPAN   = 65536

#: Brain-Life column -> channel. Both are bipolar derivations, not referential.
CHANNELS = [("AF3", "Header 26 Data", "AF3 − T7"),
            ("AF4", "Header 24 Data", "AF4 − T8")]


def load_raw_uv(csv_path):
    """Raw EEG in microvolts, DC-corrected, as float. Returns (dict, dc_offsets)."""
    cols = [c for _, c, _ in CHANNELS]
    df = pd.read_csv(csv_path, usecols=cols)
    out, dc = {}, {}
    for name, col, _ in CHANNELS:
        counts = pd.to_numeric(df[col], errors="coerce").to_numpy(np.float64)
        uv = (counts - MIDSCALE) * UV_PER_COUNT
        dc[name] = float(np.nanmean(uv))
        out[name] = uv - dc[name]          # remove the electrode DC offset
    return out, dc


def wrapped_as_exported(csv_path):
    """Reproduce what the EDF export actually stores, wrap and all.

    Mirrors csv_to_edf_denoised.convert_to_uV: scale, cast to int16, then
    subtract the first sample. Also returns the count of wrap-induced steps.
    """
    cols = [c for _, c, _ in CHANNELS]
    df = pd.read_csv(csv_path, usecols=cols)
    out, jumps = {}, {}
    for name, col, _ in CHANNELS:
        counts = pd.to_numeric(df[col], errors="coerce").to_numpy(np.float64)
        true_uv = (counts - MIDSCALE) * UV_PER_COUNT
        cast = ((counts - MIDSCALE) * UV_PER_COUNT).astype(np.int16).astype(np.float64)
        cast = cast - cast[0]
        out[name] = cast
        d_true, d_cast = np.abs(np.diff(true_uv)), np.abs(np.diff(cast))
        jumps[name] = int(np.sum((d_cast > INT16_SPAN * 0.45) & (d_true < INT16_SPAN * 0.45)))
    return out, jumps


def envelope(x, fs, n_cols=4000):
    """Min/max decimation: keeps spikes visible while plotting few points.

    Returns (t, lo, hi) so the trace can be drawn with fill_between. Plotting
    405k raw points per channel hides nothing but costs a lot; a per-column
    min/max band shows the true excursion at every pixel.
    """
    n = len(x)
    if n <= n_cols * 2:
        return np.arange(n) / fs, x, x
    step = int(np.ceil(n / n_cols))
    trim = (n // step) * step
    blocks = x[:trim].reshape(-1, step)
    lo = np.nanmin(blocks, axis=1)
    hi = np.nanmax(blocks, axis=1)
    t = (np.arange(blocks.shape[0]) * step + step / 2) / fs
    return t, lo, hi


def robust_ylim(x, pct=99.5, pad=1.15):
    v = np.nanpercentile(np.abs(x[np.isfinite(x)]), pct) if np.isfinite(x).any() else 1.0
    v = float(v) * pad
    return (-v, v) if v > 0 else (-1.0, 1.0)


def plot_recording(csv_path, windows, title, save_path, zoom_at=None, zoom_len=10.0):
    stem = os.path.splitext(os.path.basename(csv_path))[0]
    raw, dc = load_raw_uv(csv_path)
    wrapped, jumps = wrapped_as_exported(csv_path)

    n = len(next(iter(raw.values())))
    dur = n / EEG_FS

    # Default the zoom to the middle of the first real task block, where the
    # trace should be ordinary EEG rather than baseline eye movements.
    if zoom_at is None:
        tasks = [w for w in windows
                 if not w["is_baseline"] and not w["is_interval"] and not w["is_prefocus"]]
        zoom_at = (tasks[0]["t_start"] + tasks[0]["t_end"]) / 2 - zoom_len / 2 if tasks else dur / 2
    zoom_at = max(0.0, min(float(zoom_at), max(0.0, dur - zoom_len)))

    fig = plt.figure(figsize=(20, 15))
    fig.suptitle(f"{title}   —   RAW EEG", fontsize=11, fontweight="bold")
    gs = gridspec.GridSpec(4, 1, height_ratios=[3, 3, 2.6, 2.2], hspace=0.85)

    # ── Panels 1-2: each channel across the whole session ────────────────────
    for i, (name, _, deriv) in enumerate(CHANNELS):
        ax = fig.add_subplot(gs[i])
        x = raw[name]
        t, lo, hi = envelope(x, EEG_FS)
        shade_timeline(ax, windows, x_scale=1.0, x_max=dur)
        ax.fill_between(t, lo, hi, color="#243b6b", lw=0, zorder=3)
        ax.set_xlim(0, dur)
        ax.set_ylim(*robust_ylim(x))
        ax.set_title(
            f"{name} ({deriv}) — raw, DC-corrected   "
            f"DC offset {dc[name] / 1000:+.1f} mV   "
            f"full range {np.nanmin(x):,.0f} … {np.nanmax(x):,.0f} µV "
            f"(y-axis clipped to ±99.5th pct)",
            fontsize=9)
        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_ylabel("µV", fontsize=8)
        ax.grid(True, alpha=0.25, zorder=0)
        ax.tick_params(labelsize=7)

    # ── Panel 3: short zoom, so real rhythms are visible at all ──────────────
    ax3 = fig.add_subplot(gs[2])
    s0, s1 = int(zoom_at * EEG_FS), int((zoom_at + zoom_len) * EEG_FS)
    tz = np.arange(s0, s1) / EEG_FS
    for name, color in (("AF3", "#1f5fbf"), ("AF4", "#c2410c")):
        seg = raw[name][s0:s1]
        ax3.plot(tz, seg - np.nanmean(seg), lw=0.8, color=color, label=name, zorder=3)
    block = next((w["label"] for w in windows
                  if w["t_start"] <= zoom_at < w["t_end"]), "?")
    ax3.set_xlim(zoom_at, zoom_at + zoom_len)
    ax3.set_title(f"Zoom — {zoom_len:g} s from t={zoom_at:.0f} s (inside “{block}”), "
                  f"each channel re-centred", fontsize=9)
    ax3.set_xlabel("Time (s)", fontsize=8)
    ax3.set_ylabel("µV", fontsize=8)
    ax3.legend(loc="upper right", fontsize=8)
    ax3.grid(True, alpha=0.25, zorder=0)
    ax3.tick_params(labelsize=7)

    # ── Panel 4: what the EDF export actually contains ───────────────────────
    ax4 = fig.add_subplot(gs[3])
    total_jumps = sum(jumps.values())
    for name, color in (("AF3", "#1f5fbf"), ("AF4", "#c2410c")):
        t, lo, hi = envelope(wrapped[name], EEG_FS)
        ax4.fill_between(t, lo, hi, color=color, lw=0, alpha=0.75, zorder=3,
                         label=f"{name} ({jumps[name]:,} wrap steps)")
    ax4.set_xlim(0, dur)
    verdict = ("no wrap steps — the cast is a harmless constant offset here"
               if total_jumps == 0 else
               f"{total_jumps:,} wrap steps of ±{INT16_SPAN:,} µV — EDF-derived EEG is unusable")
    ax4.set_title(f"As exported to EDF (int16 cast before DC removal): {verdict}",
                  fontsize=9,
                  color="#7f1d1d" if total_jumps else "#14532d")
    ax4.set_xlabel("Time (s)", fontsize=8)
    ax4.set_ylabel("µV", fontsize=8)
    ax4.legend(loc="upper right", fontsize=7)
    ax4.grid(True, alpha=0.25, zorder=0)
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
    return dict(stem=stem, dur=dur, dc=dc, jumps=jumps,
                span={k: float(np.nanmax(v) - np.nanmin(v)) for k, v in raw.items()})


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eeg-dir", default=EEG_BL_DIR)
    ap.add_argument("--graph-dir", default=GRAPH_DIR)
    ap.add_argument("--only", default=None, help="substring filter on the filename")
    ap.add_argument("--zoom-at", type=float, default=None,
                    help="start of the zoom window in seconds (default: mid first task)")
    ap.add_argument("--zoom-len", type=float, default=10.0)
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(args.eeg_dir, "*.csv")))
    if args.only:
        paths = [p for p in paths if args.only in os.path.basename(p)]
    if not paths:
        print(f"No CSV recordings in {args.eeg_dir}")
        return 1

    summary = []
    for csv_path in paths:
        stem = os.path.splitext(os.path.basename(csv_path))[0]
        print(f"\n{stem}")
        session, note = st.find_session_for_recording(csv_path, BEHAVIORS_DIR)
        if session is not None:
            windows = st.build_session_windows(
                session["task_order"], measured=st.measure_block_durations(session["dir"]))
            title = f"{stem}   —   session {session['session']}"
        else:
            windows = st.build_session_windows(st.generic_task_order())
            title = f"{stem}   —   NO PAIRED SESSION, block labels are generic"
        print(f"  pairing: {note}")

        summary.append(plot_recording(
            csv_path, windows, title,
            os.path.join(args.graph_dir, stem + "_raw_eeg.png"),
            zoom_at=args.zoom_at, zoom_len=args.zoom_len))

    print(f"\n{'=' * 72}\nRaw-EEG quality summary\n{'=' * 72}")
    for s in summary:
        flag = "OK" if sum(s["jumps"].values()) == 0 else "CORRUPT IN EDF"
        print(f"  {s['stem'][:34]:34s} {flag:15s} "
              f"AF3 span {s['span']['AF3']:8,.0f} µV  AF4 span {s['span']['AF4']:8,.0f} µV  "
              f"wrap steps AF3={s['jumps']['AF3']:,} AF4={s['jumps']['AF4']:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
