#!/usr/bin/env python3
"""
plot_eeg_windows.py — browse the processed EEG in short time windows.

A whole 28-minute recording on one axis is ~405,000 samples across 20 inches, which
is about 340 samples per pixel. Nothing survives that: what you see is the envelope
of the record, which is why it reads as a solid chunked band. Individual waveforms
need on the order of 20 s per axis to be legible.

So this renders the recording as a strip chart — the way EEG is actually read. Each
strip is a short window at consistent scale, strips stack down the page, and pages
run to the end of the recording. Both channels share a strip, offset vertically so
they do not overlap.

Blink and ocular spans (blink.py) are shaded on each strip. They are detected
OUTSIDE the baseline only: the baseline's blinks and eye movements are the protocol,
and its guided-blink cues are what pin the recording's time alignment.

Output
------
One multi-page PDF per recording, plus a PNG of one page so there is something to
open immediately. Every strip is labelled with its block, so a page can be read
without cross-referencing the session timeline.

Usage
-----
  python plot_eeg_windows.py                          # 20 s strips, 12 per page
  python plot_eeg_windows.py --win 10 --strips 15
  python plot_eeg_windows.py --only ban --png-page 3
  python plot_eeg_windows.py --from 700 --to 900      # just this span
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
import matplotlib.patches as mpatches
from matplotlib.backends.backend_pdf import PdfPages

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import blink as bl
import session_timeline as st
from metadata import EEG_CHANNELS

REPO_ROOT     = os.path.dirname(os.path.dirname(CODE_DIR))
EEG_BL_DIR    = os.path.join(REPO_ROOT, "code", "results", "eeg_bl")
BEHAVIORS_DIR = os.path.join(REPO_ROOT, "code", "results", "behaviors")
EDF_DIR       = os.path.join(REPO_ROOT, "data", "derived", "eeg_bl", "edf")
GRAPH_DIR     = os.path.join(REPO_ROOT, "graph", "eeg_bl")

CH_COLORS = {"AF3": "#2a78d6", "AF4": "#eb6834"}   # validated categorical slots 1-2
INK       = "#52514e"
ARTIFACT  = "#e34948"                              # status:critical, reserved


def find_edf(stem):
    for sub in ("good", "good_denoised", "bad_denoised"):
        p = os.path.join(EDF_DIR, sub, stem + ".edf")
        if os.path.exists(p):
            return p, sub
    return None, None


def block_at(windows, t):
    for w in windows:
        if w["t_start"] <= t < w["t_end"]:
            if w["is_interval"]:
                return "rest"
            if w.get("is_prefocus"):
                return w["label"]
            return w["label"]
    return "—"


def draw_page(proc, fs, spans, windows, t0, win, strips, scale, title, subtitle):
    """One page of `strips` consecutive windows of `win` seconds each."""
    fig, axes = plt.subplots(strips, 1, figsize=(19, 1.15 * strips + 1.6))
    if strips == 1:
        axes = [axes]
    fig.suptitle(title, fontsize=11, fontweight="bold", y=0.995)
    fig.text(0.5, 0.972, subtitle, ha="center", fontsize=8.5, color=INK)

    offset = scale                      # AF3 up, AF4 down, so they never cross
    n = len(proc["AF3"])
    for k, ax in enumerate(axes):
        a = t0 + k * win
        b = a + win
        s0, s1 = int(a * fs), int(min(b * fs, n))
        if s0 >= n:
            ax.axis("off")
            continue
        t = np.arange(s0, s1) / fs

        for sa, sb in spans:                       # ocular spans behind the traces
            if sb > a and sa < b:
                ax.axvspan(max(sa, a), min(sb, b), color=ARTIFACT, alpha=0.16,
                           lw=0, zorder=1)

        for ch, sign in (("AF3", +1), ("AF4", -1)):
            ax.plot(t, proc[ch][s0:s1] + sign * offset, lw=0.7,
                    color=CH_COLORS[ch], zorder=3, solid_capstyle="round")
            ax.axhline(sign * offset, color=INK, lw=0.4, alpha=0.35, zorder=2)

        ax.set_xlim(a, b)
        ax.set_ylim(-2.1 * offset, 2.1 * offset)
        ax.set_yticks([offset, -offset])
        ax.set_yticklabels(["AF3", "AF4"], fontsize=7.5)
        for lbl, ch in zip(ax.get_yticklabels(), ("AF3", "AF4")):
            lbl.set_color(CH_COLORS[ch])
            lbl.set_fontweight("bold")
        ax.set_xticks(np.arange(a, b + 0.001, max(1, win // 10)))
        ax.tick_params(labelsize=7, colors=INK, length=2)
        ax.grid(True, axis="x", alpha=0.14, lw=0.5)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.spines["bottom"].set_color(INK)
        ax.spines["bottom"].set_linewidth(0.5)
        # Block name on the strip, so a page reads standalone.
        ax.annotate(f"{a:.0f}–{b:.0f} s   {block_at(windows, (a + b) / 2)}",
                    xy=(0.002, 0.97), xycoords="axes fraction", va="top",
                    fontsize=7.5, color="#0b0b0b", fontweight="bold")

    axes[-1].set_xlabel("Time (s)", fontsize=8.5, color=INK)
    fig.legend(handles=[mpatches.Patch(facecolor=ARTIFACT, alpha=0.4,
                                       label="blink / ocular span (excluded from statistics; "
                                             "baseline not screened)")],
               loc="lower center", ncol=1, fontsize=8, frameon=False,
               bbox_to_anchor=(0.5, 0.002))
    fig.tight_layout(rect=(0, 0.02, 1, 0.965))
    return fig


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eeg-dir", default=EEG_BL_DIR)
    ap.add_argument("--graph-dir", default=GRAPH_DIR)
    ap.add_argument("--only", default=None, help="substring filter on the filename")
    ap.add_argument("--win", type=float, default=20.0, help="seconds per strip")
    ap.add_argument("--strips", type=int, default=12, help="strips per page")
    ap.add_argument("--scale", type=float, default=None,
                    help="µV half-height per channel (default: 6x robust SD)")
    ap.add_argument("--from", dest="t_from", type=float, default=0.0)
    ap.add_argument("--to", dest="t_to", type=float, default=None)
    ap.add_argument("--png-page", type=int, default=None,
                    help="1-based page to also write as PNG (default: first page "
                         "containing a task block)")
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(args.eeg_dir, "*.csv")))
    if args.only:
        paths = [p for p in paths if args.only in os.path.basename(p)]
    if not paths:
        print(f"No recordings in {args.eeg_dir}")
        return 1

    os.makedirs(args.graph_dir, exist_ok=True)
    for csv_path in paths:
        stem = os.path.splitext(os.path.basename(csv_path))[0]
        edf_path, quality = find_edf(stem)
        print(f"\n{stem}")
        if edf_path is None:
            print("  no EDF — run run_session_analysis.py first")
            continue

        with pyedflib.EdfReader(edf_path) as f:
            labels = f.getSignalLabels()
            fs = float(f.getSampleFrequency(0))
            sig = {l: f.readSignal(i) for i, l in enumerate(labels)}
        proc = {ch: sig[f"{ch}_processed"] for ch in ("AF3", "AF4")}

        session, note = st.find_session_for_recording(csv_path, BEHAVIORS_DIR)
        if session is not None:
            windows = st.build_session_windows(
                session["task_order"], measured=st.measure_block_durations(session["dir"]))
            who = f"session {session['session']}"
        else:
            windows = st.build_session_windows(st.generic_task_order())
            who = "NO PAIRED SESSION, block labels generic"

        spans, binfo = bl.detect_blinks([proc["AF3"], proc["AF4"]], fs,
                                        windows=windows, skip_baseline=True)
        print(f"  {bl.summarise(binfo)}")

        scale = args.scale or 6.0 * max(bl._robust_sd(proc[ch]) for ch in proc)
        dur = len(proc["AF3"]) / fs
        t_end = min(args.t_to, dur) if args.t_to else dur
        page_len = args.win * args.strips
        n_pages = int(np.ceil((t_end - args.t_from) / page_len))
        print(f"  {args.win:g} s strips x {args.strips} per page -> {n_pages} pages, "
              f"±{scale:.0f} µV per channel")

        pdf_path = os.path.join(args.graph_dir, stem + "_windows.pdf")
        png_page = args.png_page
        if png_page is None:                     # default: first page with a task block
            first_task = next((w["t_start"] for w in windows
                               if not w["is_baseline"] and not w["is_interval"]
                               and not w.get("is_prefocus")), args.t_from)
            png_page = int((first_task - args.t_from) // page_len) + 1

        with PdfPages(pdf_path) as pdf:
            for pg in range(n_pages):
                t0 = args.t_from + pg * page_len
                fig = draw_page(
                    proc, fs, spans, windows, t0, args.win, args.strips, scale,
                    f"{stem}   —   {who}   —   {', '.join(EEG_CHANNELS)}",
                    f"page {pg + 1}/{n_pages}   ·   {t0:.0f}–{min(t0 + page_len, t_end):.0f} s"
                    f"   ·   ±{scale:.0f} µV per channel   ·   "
                    f"{binfo['n_spans']} ocular spans, {binfo['excluded_frac'] * 100:.1f}% of time")
                pdf.savefig(fig, dpi=110)
                if pg + 1 == png_page:
                    png = os.path.join(args.graph_dir, f"{stem}_windows_p{pg + 1}.png")
                    fig.savefig(png, dpi=110, bbox_inches="tight")
                    print(f"  Saved → {png}")
                plt.close(fig)
        print(f"  Saved → {pdf_path}  ({n_pages} pages)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
