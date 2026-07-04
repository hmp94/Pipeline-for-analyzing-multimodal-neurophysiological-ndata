#!/usr/bin/env python3
"""
run_pipeline.py  —  unified multimodal neurophysiology processing pipeline.

Four steps are executed for every CSV recording:

  1. EEG   — quality checks (correlation, zero-signal, artifact ratio, band
              noise), WPT denoising when needed, EDF export
  2. fNIRS — Scalp Coupling Index, SNR, ΔOD, HbO / HbR via MBLL
  3. PPG   — SNR, entropy, template matching, perfusion index
  4. FI    — Focus Index (β/α) timeline chart from the EDF produced in step 1

Usage
-----
  python run_pipeline.py <csv_input> <edf_output> [options]

  <csv_input>   path to a single .csv file  OR  a folder of .csv files
  <edf_output>  folder where EDF files (and quality sub-folders) will be written

Options
-------
  --eeg-fs N        EEG sampling rate Hz          (default 244)
  --device          EEG device: BL or MUSE        (default BL)
  --fnirs-fs N      fNIRS sampling rate Hz         (default 100)
  --ppg-fs N        PPG  sampling rate Hz          (default 100)
  --ppg-skip N      PPG samples to ignore at start (default 0)
  --fnirs-hampel    Hampel spike filter on fNIRS intensity
  --fnirs-dwt       DWT wavelet denoising on fNIRS intensity
  --no-plot         Suppress all matplotlib windows
  --fi-save DIR     Save FI plots to DIR (default: show interactively)

Example
-------
  # single file, plots suppressed, FI charts saved
  python run_pipeline.py data/raw/csv/subject01.csv data/edf \\
      --no-plot --fi-save data/graph

  # whole folder, default settings
  python run_pipeline.py data/raw/csv/ data/edf
"""

import os
import sys

# Set up CODE_DIR on sys.path first so sibling modules are findable when the
# dynamically-loaded modules run their own top-level imports.
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

from metadata import (
    FNIRS_FS, FNIRS_COL_RED, FNIRS_COL_IR,
    EEG_FS, EEG_CHANNELS, EEG_FI_WIN, EEG_FI_STEP,
    GRAPH_FNIRS_DIR, GRAPH_EEG_DIR, GRAPH_SUMMARY_DIR,
)

import argparse
import importlib.util
import shutil
import tempfile

import matplotlib
matplotlib.use("Agg")          # non-interactive backend; overridden below when needed
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
from scipy.signal import find_peaks


# ── Dynamic import  (filenames contain spaces / hyphens) ─────────────────────
def _import_path(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod

# intensity_filter (1).py must be registered under the plain name "intensity_filter"
# before fnirs_check and csv_to_edf_denoised try to import it.
_import_path("intensity_filter", os.path.join(CODE_DIR, "intensity_filter (1).py"))

_csv_to_edf_mod = _import_path(
    "csv_to_edf_denoised",
    os.path.join(CODE_DIR, "csv_to_edf_denoised.py"),
)
_fnirs_mod = _import_path(
    "fnirs_check",
    os.path.join(CODE_DIR, "f-NIRS_check_for_T (1).py"),
)
_ppg_mod = _import_path(
    "ppg_check",
    os.path.join(CODE_DIR, "PPG_check_for_T (1).py"),
)
_fi_mod = _import_path(
    "eeg_fi",
    os.path.join(CODE_DIR, "eeg_fi_line_chart.py"),
)

convert_csv_to_edf  = _csv_to_edf_mod.convert_csv_to_edf
check_fNIRS_SCI     = _fnirs_mod.check_fNIRS_SCI
check_ppg           = _ppg_mod.check_ppg
plot_fi_timeline    = _fi_mod.plot_fi_timeline
load_eeg_from_edf   = _fi_mod.load_eeg_from_edf
compute_fi_timeline = _fi_mod.compute_fi_timeline

from fnirs_analysis import filter_fnirs_outliers


# ── Helpers ───────────────────────────────────────────────────────────────────
def _section(title):
    pad = max(0, 55 - len(title))
    print(f"\n── {title} {'─' * pad}")


def _find_edf(edf_dir, stem):
    """Return the first EDF found for this recording (good > good_denoised > bad_denoised)."""
    for sub in ("good", "good_denoised", "bad_denoised"):
        path = os.path.join(edf_dir, sub, stem + ".edf")
        if os.path.exists(path):
            return path
    return None


def _status_str(val):
    if val is None:
        return "skipped"
    if isinstance(val, dict):
        return "OK"
    if val == "done":
        return "OK"
    return str(val)


def _print_summary(results):
    print(f"\n{'=' * 60}")
    print("PIPELINE SUMMARY")
    print(f"{'=' * 60}")
    for r in results:
        name = os.path.basename(r["file"])
        print(f"\n  {name}")
        print(f"    EEG     : {_status_str(r.get('eeg'))}")
        print(f"    fNIRS   : {_status_str(r.get('fnirs'))}")
        print(f"    PPG     : {_status_str(r.get('ppg'))}")
        print(f"    FI      : {r.get('fi', 'skipped')}")
        print(f"    Summary : {r.get('summary', 'skipped')}")
    print()


# ── Signal helpers ────────────────────────────────────────────────────────────
def _filter_outliers(signal, n_sd=3):
    """Replace samples outside mean±n_sd*std with NaN then linearly interpolate."""
    s = np.array(signal, dtype=float)
    mean, std = np.nanmean(s), np.nanstd(s)
    if std == 0:
        return s
    s[np.abs(s - mean) > n_sd * std] = np.nan
    nans = np.isnan(s)
    if nans.any() and not nans.all():
        idx = np.arange(len(s))
        s[nans] = np.interp(idx[nans], idx[~nans], s[~nans])
    return s


# ── Statistical helpers ───────────────────────────────────────────────────────
from scipy.stats import ttest_rel


def _paired_test(pairs):
    """Paired t-test on all paired window values."""
    if len(pairs) < 3:
        return dict(a_mean=np.nan, a_std=np.nan, b_mean=np.nan, b_std=np.nan,
                    stat=np.nan, p=np.nan, sig="n/a", test="n/a")
    a = np.array([x for x, _ in pairs])
    b = np.array([x for _, x in pairs])
    stat, p = ttest_rel(a, b)
    sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
    df = len(pairs) - 1
    r_effect = float(abs(stat) / np.sqrt(stat**2 + df)) if df > 0 else np.nan
    return dict(a_mean=float(np.mean(a)), a_std=float(np.std(a)),
                b_mean=float(np.mean(b)), b_std=float(np.std(b)),
                stat=float(stat), p=float(p), sig=sig, test="paired-t", r=r_effect)


def _fmt_paired(label, r):
    def _f(v, d=4): return f"{v:.{d}f}" if np.isfinite(v) else "n/a"
    return [label,
            f"{_f(r['a_mean'])} ± {_f(r['a_std'])}",
            f"{_f(r['b_mean'])} ± {_f(r['b_std'])}",
            _f(r['stat'], 3),
            _f(r['p']), r['sig'], _f(r.get('r', float('nan')), 3)]


def _raw_pairs(a_vals, b_vals):
    """Pair raw values tail-of-a with head-of-b (or head-of-a with tail-of-b for pre-focus)."""
    n = min(len(a_vals), len(b_vals))
    return list(zip(a_vals[-n:], b_vals[:n]))


def _sig_pairs(signal, fs, windows):
    """Pair raw individual samples, task↔rest and task↔pre-focus. Returns (tr_pairs, tp_pairs)."""
    n = len(signal)

    def _block_vals(w):
        s = max(0, int(w["t_start"] * fs))
        e = min(n, int(w["t_end"] * fs))
        return signal[s:e]

    task_wins = [w for w in windows if not w["is_interval"] and not w.get("is_prefocus") and not w["is_baseline"]]
    rest_wins = [w for w in windows if w["is_interval"]]
    pre_wins  = [w for w in windows if w.get("is_prefocus")]

    tr_pairs, tp_pairs = [], []
    for tw in task_wins:
        tvals = _block_vals(tw)
        rw_cands = [rw for rw in rest_wins if rw["t_start"] >= tw["t_end"]]
        if rw_cands:
            rw = min(rw_cands, key=lambda r: r["t_start"])
            tr_pairs.extend(_raw_pairs(tvals, _block_vals(rw)))
        pw_cands = [pw for pw in pre_wins if pw["t_end"] <= tw["t_start"]]
        if pw_cands:
            pw = max(pw_cands, key=lambda p: p["t_end"])
            pvals = _block_vals(pw)
            n_p = min(len(tvals), len(pvals))
            if n_p > 0:
                tp_pairs.extend(zip(tvals[:n_p], pvals[-n_p:]))
    return tr_pairs, tp_pairs


def _fi_pairs(t_centers, fi_avg, windows):
    """Pair individual FI values (1 s step), task↔rest and task↔pre-focus. Returns (tr_pairs, tp_pairs)."""
    def _block_vals(w):
        mask = (t_centers >= w["t_start"]) & (t_centers < w["t_end"])
        return fi_avg[mask]

    task_wins = [w for w in windows if not w["is_interval"] and not w.get("is_prefocus") and not w["is_baseline"]]
    rest_wins = [w for w in windows if w["is_interval"]]
    pre_wins  = [w for w in windows if w.get("is_prefocus")]

    tr_pairs, tp_pairs = [], []
    for tw in task_wins:
        tvals = _block_vals(tw)
        rw_cands = [rw for rw in rest_wins if rw["t_start"] >= tw["t_end"]]
        if rw_cands:
            rw = min(rw_cands, key=lambda r: r["t_start"])
            tr_pairs.extend(_raw_pairs(tvals, _block_vals(rw)))
        pw_cands = [pw for pw in pre_wins if pw["t_end"] <= tw["t_start"]]
        if pw_cands:
            pw = max(pw_cands, key=lambda p: p["t_end"])
            pvals = _block_vals(pw)
            n_p = min(len(tvals), len(pvals))
            if n_p > 0:
                tp_pairs.extend(zip(tvals[:n_p], pvals[-n_p:]))
    return tr_pairs, tp_pairs


# ── Combined 3-panel summary plot ────────────────────────────────────────────
_WIN_COLORS = {
    "baseline":  "#7ab8e8",
    "task_odd":  "#72c472",
    "task_even": "#72c472",
    "rest":      "#b0b0b0",
    "prefocus":  "#f5d76e",
}


def _shade_timeline(ax, windows, x_scale=1.0, arrow_y=-0.10, label_y=-0.20, x_max=None):
    """Add coloured spans, double-headed bracket arrows, and labels for each task window.

    x_scale  : multiply window times (1.0 → seconds axis, 1/60 → minutes axis).
    arrow_y  : axes-fraction y for the <-> bracket arrow.
    label_y  : axes-fraction y for the task label (below the arrow).
    x_max    : if set, skip annotations for windows that start at or beyond this x value.
    """
    import re
    tick_half = 0.018   # half-height of the end-cap ticks in axes fraction

    for w in windows:
        x0, x1 = w["t_start"] * x_scale, w["t_end"] * x_scale

        # skip windows entirely beyond data range (prevents huge bbox expansion)
        if x_max is not None and x0 >= x_max:
            continue

        x1_draw = min(x1, x_max) if x_max is not None else x1

        # ── background colour ──────────────────────────────────────────────
        if w["is_baseline"]:
            color = _WIN_COLORS["baseline"]
        elif w["is_interval"]:
            color = _WIN_COLORS["rest"]
        elif w.get("is_prefocus"):
            color = _WIN_COLORS["prefocus"]
        else:
            num = int(re.search(r"\d+", w["label"]).group())
            color = _WIN_COLORS["task_odd"] if num % 2 == 1 else _WIN_COLORS["task_even"]
        ax.axvspan(x0, x1_draw, alpha=0.35, color=color, lw=0)

        if w["is_interval"] or w.get("is_prefocus"):
            continue

        arrow_color = "#1f5fbf" if w["is_baseline"] else "#555555"

        # ── double-headed arrow spanning the window ────────────────────────
        ax.annotate(
            "", xy=(x1_draw, arrow_y), xytext=(x0, arrow_y),
            xycoords=("data", "axes fraction"),
            arrowprops=dict(arrowstyle="<->", color=arrow_color, lw=1.1),
            annotation_clip=False,
        )

        # ── vertical end-cap ticks at x0 and x1 ───────────────────────────
        for xc in (x0, x1_draw):
            ax.annotate(
                "", xy=(xc, arrow_y - tick_half), xytext=(xc, arrow_y + tick_half),
                xycoords=("data", "axes fraction"),
                arrowprops=dict(arrowstyle="-", color=arrow_color, lw=1.1),
                annotation_clip=False,
            )

        # ── task label centred below the arrow ────────────────────────────
        mid = (x0 + x1_draw) / 2
        ax.annotate(
            w["label"],
            xy=(mid, label_y), xycoords=("data", "axes fraction"),
            ha="center", va="top", fontsize=6.5,
            color=arrow_color,
            fontweight="bold" if w["is_baseline"] else "normal",
            annotation_clip=False,
        )


def plot_combined_summary(
    csv_path,
    fnirs_result,
    edf_path,
    fnirs_fs=100,
    ppg_column="Header 25 Data",
    ppg_fs=100,
    ppg_first_samples_to_ignore=0,
    fi_channels=("AF3_processed", "AF4_processed"),
    fi_win_sec=5,
    fi_step_sec=1,
    save_path=None,
    show=False,
):
    """Three-panel figure with task-timeline shading: fNIRS HbO/HbR | PPG | EEG FI."""
    stem = os.path.splitext(os.path.basename(csv_path))[0]

    try:
        windows = _fi_mod.get_timeline(csv_path)
    except Exception:
        windows = []

    fig = plt.figure(figsize=(20, 16))
    fig.suptitle(stem, fontsize=11, fontweight="bold")
    gs = gridspec.GridSpec(4, 1, height_ratios=[3, 3, 3, 1.6], hspace=0.80)

    stats_rows = []   # filled as we process each modality

    # ── Panel 1: fNIRS HbO / HbR ─────────────────────────────────────────────
    ax1 = fig.add_subplot(gs[0])
    if isinstance(fnirs_result, dict):
        HbO  = fnirs_result["HbO"]
        HbR  = fnirs_result["HbR"]
        fs_f = fnirs_result.get("fs", fnirs_fs)
        # cap at session end so rogue trailing samples don't explode the figure
        session_end_samp = int(windows[-1]["t_end"] * fs_f)
        HbO = HbO[:session_end_samp]
        HbR = HbR[:session_end_samp]
        t    = np.arange(len(HbO)) / fs_f
        _shade_timeline(ax1, windows, x_scale=1.0, x_max=t[-1] if len(t) else 0)
        ax1.plot(t, HbO, color="red",  lw=0.9, label="HbO", zorder=3)
        ax1.plot(t, HbR, color="blue", lw=0.9, label="HbR", zorder=3)
        sci     = fnirs_result.get("sci_r", float("nan"))
        hb_corr = fnirs_result.get("Hb_corr", float("nan"))
        ax1.set_title(
            f"fNIRS — HbO / HbR   SCI r={sci:.3f} | HbO–HbR corr={hb_corr:.3f}",
            fontsize=9,
        )
        ax1.set_xlim(0, t[-1])
        ax1.set_ylim(-5e-6, 5e-6)

        # stats — paired t-test on raw individual samples
        hbo_tr, hbo_tp = _sig_pairs(HbO, fs_f, windows)
        hbr_tr, hbr_tp = _sig_pairs(HbR, fs_f, windows)
        stats_rows.append(_fmt_paired("fNIRS HbO Task vs Rest",      _paired_test(hbo_tr)))
        stats_rows.append(_fmt_paired("fNIRS HbO Task vs Pre-focus", _paired_test(hbo_tp)))
        stats_rows.append(_fmt_paired("fNIRS HbR Task vs Rest",      _paired_test(hbr_tr)))
        stats_rows.append(_fmt_paired("fNIRS HbR Task vs Pre-focus", _paired_test(hbr_tp)))
    else:
        ax1.text(0.5, 0.5, f"fNIRS unavailable:\n{fnirs_result}",
                 ha="center", va="center", transform=ax1.transAxes, fontsize=8)
        ax1.set_title("fNIRS — unavailable", fontsize=9)
    ax1.set_xlabel("Time (s)", fontsize=8)
    ax1.set_ylabel("µM", fontsize=8)
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(True, alpha=0.25, zorder=0)
    ax1.tick_params(labelsize=7)

    # ── Panel 2: PPG filtered signal + peaks ─────────────────────────────────
    ax2 = fig.add_subplot(gs[1])
    try:
        df_ppg = pd.read_csv(csv_path)
        df_ppg.columns = df_ppg.columns.str.strip()
        col = ppg_column.strip()
        if col not in df_ppg.columns:
            candidates = [c for c in df_ppg.columns if "25" in c]
            col = candidates[0] if candidates else df_ppg.columns[0]

        ppg_vals = pd.to_numeric(df_ppg[col], errors="coerce")
        ppg_vals = _ppg_mod.truncate_at_first_nan(ppg_vals).dropna()
        ppg_raw  = _ppg_mod.convert_to_raw(ppg_vals.to_numpy())
        ppg_raw  = ppg_raw[max(0, ppg_first_samples_to_ignore):]
        ppg_raw  = _ppg_mod.fill_missing(ppg_raw)
        ppg_filt = _ppg_mod.preprocess_ppg(ppg_raw, ppg_fs, use_sg=True)
        ppg_filt = _filter_outliers(ppg_filt, n_sd=3)

        skip = min(5 * ppg_fs, len(ppg_filt) // 2)
        peaks, _ = find_peaks(ppg_filt, distance=int(ppg_fs * 0.4))
        hr = (60 / (np.mean(np.diff(peaks)) / ppg_fs)) if len(peaks) > 1 else float("nan")

        t_ppg = np.arange(len(ppg_filt)) / ppg_fs
        _shade_timeline(ax2, windows, x_scale=1.0, x_max=t_ppg[-1] if len(t_ppg) else 0)
        ax2.plot(t_ppg, ppg_filt, color="darkgreen", lw=0.8, label="PPG filtered", zorder=3)
        if len(peaks):
            ax2.plot(peaks / ppg_fs, ppg_filt[peaks], "ro", ms=2.5, label="Peaks", zorder=4)

        ax2.set_ylim(-1100, 1100)
        ax2.set_xlim(0, t_ppg[-1])
        ax2.set_title(f"PPG — filtered signal   HR ≈ {hr:.1f} bpm", fontsize=9)

        # stats — paired t-test on raw individual samples
        ppg_tr, ppg_tp = _sig_pairs(ppg_filt, ppg_fs, windows)
        stats_rows.append(_fmt_paired("PPG amplitude Task vs Rest",      _paired_test(ppg_tr)))
        stats_rows.append(_fmt_paired("PPG amplitude Task vs Pre-focus", _paired_test(ppg_tp)))
    except Exception as exc:
        ax2.text(0.5, 0.5, f"PPG unavailable:\n{exc}",
                 ha="center", va="center", transform=ax2.transAxes, fontsize=8)
        ax2.set_title("PPG — unavailable", fontsize=9)
    ax2.set_xlabel("Time (s)", fontsize=8)
    ax2.set_ylabel("Amplitude", fontsize=8)
    ax2.legend(loc="upper right", fontsize=8)
    ax2.grid(True, alpha=0.25, zorder=0)
    ax2.tick_params(labelsize=7)

    # ── Panel 3: EEG Focus Index ──────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[2])
    if edf_path and os.path.exists(edf_path):
        try:
            data, _, fs_e = load_eeg_from_edf(edf_path, fi_channels)
            t_c, fi       = compute_fi_timeline(data, fs_e, win_sec=fi_win_sec, step_sec=fi_step_sec)
            fi_avg        = _filter_outliers(fi.mean(axis=0), n_sd=3)
            t_min         = t_c / 60

            k         = max(1, int(60 / fi_step_sec))
            fi_smooth = np.convolve(fi_avg, np.ones(k) / k, mode="same")

            _shade_timeline(ax3, windows, x_scale=1 / 60, x_max=t_min[-1] if len(t_min) else 0)
            ax3.plot(t_min, fi_avg,    color="#b3a2cc", lw=0.6, alpha=0.6, label="FI = β/α",    zorder=3)
            ax3.plot(t_min, fi_smooth, color="#4a2a6a", lw=1.6,            label="FI smoothed", zorder=4)

            # mean line + I-bar (±1 SD) per task block
            first_mean = True
            for w in windows:
                if w["is_interval"] or w.get("is_prefocus"):
                    continue
                mask = (t_c >= w["t_start"]) & (t_c < w["t_end"])
                if not mask.any():
                    continue
                m_fi  = fi_avg[mask].mean()
                sd_fi = fi_avg[mask].std()
                x0, x1 = w["t_start"] / 60, w["t_end"] / 60
                ax3.errorbar((x0 + x1) / 2, m_fi, yerr=sd_fi, fmt="ko", ms=4, color="black",
                             capsize=5, capthick=1.5, elinewidth=1.5, zorder=6,
                             label="Task mean ± SD" if first_mean else None)
                first_mean = False

            ax3.set_xlim(0, t_min[-1] if len(t_min) else 0)
            ax3.set_ylim(0, 10)
            ax3.set_title(
                f"EEG — Focus Index (β/α)   channels: {list(fi_channels)}", fontsize=9
            )
            ax3.set_xlabel("Time (min)", fontsize=8)

            # EEG stats — paired t-test on individual FI values (1 s step)
            tr_pairs, tp_pairs = _fi_pairs(t_c, fi_avg, windows)
            stats_rows.append(_fmt_paired("EEG FI Task vs Rest",      _paired_test(tr_pairs)))
            stats_rows.append(_fmt_paired("EEG FI Task vs Pre-focus", _paired_test(tp_pairs)))
        except Exception as exc:
            ax3.text(0.5, 0.5, f"FI error:\n{exc}",
                     ha="center", va="center", transform=ax3.transAxes, fontsize=8)
            ax3.set_title("EEG FI — error", fontsize=9)
    else:
        ax3.text(0.5, 0.5, "No EDF produced — EEG FI unavailable",
                 ha="center", va="center", transform=ax3.transAxes, fontsize=8)
        ax3.set_title("EEG FI — unavailable", fontsize=9)
    ax3.set_ylabel("FI = β/α", fontsize=8)
    ax3.legend(loc="upper right", fontsize=8)
    ax3.grid(True, alpha=0.25, zorder=0)
    ax3.tick_params(labelsize=7)

    # ── Panel 4: Statistics table ─────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[3])
    ax4.axis("off")
    ax4.set_title("Paired t-test (individual data points, task vs adjacent rest / pre-focus)",
                  fontsize=9, fontweight="bold", pad=14)

    col_labels = ["Measure", "Group A mean ± SD", "Group B mean ± SD",
                  "t statistic", "p-value", "Sig.", "Effect r"]
    if stats_rows:
        tbl = ax4.table(
            cellText=stats_rows,
            colLabels=col_labels,
            loc="center",
            cellLoc="center",
        )
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8)
        tbl.scale(1, 1.5)

        # colour the significance column
        sig_col_idx = 5
        for row_idx, row in enumerate(stats_rows, start=1):
            sig = row[sig_col_idx]
            cell = tbl[row_idx, sig_col_idx]
            if sig in ("*", "**", "***"):
                cell.set_facecolor("#d4edda")   # green
            elif sig == "ns":
                cell.set_facecolor("#f8d7da")   # red
        # bold header
        for col_idx in range(len(col_labels)):
            tbl[0, col_idx].set_text_props(fontweight="bold")
    else:
        ax4.text(0.5, 0.5, "No statistics available",
                 ha="center", va="center", transform=ax4.transAxes, fontsize=9)

    # ── Legend for window colours ─────────────────────────────────────────────
    import matplotlib.patches as mpatches
    patch_handles = [
        mpatches.Patch(facecolor=_WIN_COLORS["baseline"],  alpha=0.5, label="Baseline (F0, 120s)"),
        mpatches.Patch(facecolor=_WIN_COLORS["task_odd"],  alpha=0.5, label="Task (120s)"),
        mpatches.Patch(facecolor=_WIN_COLORS["rest"],      alpha=0.5, label="Rest (50s)"),
        mpatches.Patch(facecolor=_WIN_COLORS["prefocus"],  alpha=0.5, label="Pre-focus (10s)"),
    ]
    fig.legend(handles=patch_handles, loc="lower center", ncol=4,
               fontsize=8, framealpha=0.8, bbox_to_anchor=(0.5, 0.005))

    plt.subplots_adjust(bottom=0.06)

    if save_path:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"  Saved → {save_path}")
    if show:
        plt.show()
    plt.close(fig)


# ── Core pipeline ─────────────────────────────────────────────────────────────
def run_pipeline(
    csv_input,
    edf_output_dir,
    # EEG
    eeg_sampling_rate=EEG_FS,
    eeg_device="BL",
    # fNIRS
    fnirs_fs=FNIRS_FS,
    fnirs_col_red=FNIRS_COL_RED,
    fnirs_col_ir=FNIRS_COL_IR,
    fnirs_signal_range=None,
    fnirs_use_hampel=False,
    fnirs_use_dwt=False,
    fnirs_plot=True,
    # PPG
    ppg_column="Header 25 Data",
    ppg_fs=100,
    ppg_first_samples_to_ignore=0,
    ppg_plot=False,
    # Focus Index
    fi_channels=EEG_CHANNELS,
    fi_win_sec=EEG_FI_WIN,
    fi_step_sec=EEG_FI_STEP,
    fi_save_dir=None,
    # Combined summary
    summary_save_dir=GRAPH_SUMMARY_DIR,
    show_summary=False,
):
    """Run all four pipeline steps on one CSV file or a folder of CSV files.

    Returns a list of per-file result dicts with keys:
      file, eeg, fnirs, ppg, fi
    """
    # Collect input files
    if os.path.isdir(csv_input):
        csv_files = sorted(
            os.path.join(csv_input, f)
            for f in os.listdir(csv_input)
            if f.endswith(".csv")
            and not os.path.isdir(os.path.join(csv_input, f))
            and "(" not in f
        )
    else:
        csv_files = [csv_input]

    print(f"\n{'=' * 60}")
    print(f"Pipeline  —  {len(csv_files)} file(s)  →  {edf_output_dir}")
    print(f"{'=' * 60}")

    results = []

    for csv_path in csv_files:
        stem = os.path.splitext(os.path.basename(csv_path))[0]
        print(f"\n{'#' * 60}")
        print(f"  FILE: {stem}")
        print(f"{'#' * 60}")

        record = {"file": csv_path}

        # ── Step 1: EEG ──────────────────────────────────────────────────────
        _section("STEP 1 — EEG quality check + EDF export")
        try:
            tmp = tempfile.mkdtemp()
            shutil.copy2(csv_path, tmp)
            convert_csv_to_edf(tmp, edf_output_dir, eeg_sampling_rate, device=eeg_device)
            shutil.rmtree(tmp, ignore_errors=True)
            record["eeg"] = "done"
        except Exception as exc:
            print(f"  [EEG ERROR] {exc}")
            record["eeg"] = f"error: {exc}"

        edf_path = _find_edf(edf_output_dir, stem)

        # ── Step 2: fNIRS ────────────────────────────────────────────────────
        _section("STEP 2 — fNIRS SCI + HbO/HbR quality check")
        try:
            record["fnirs"] = check_fNIRS_SCI(
                csv_path,
                signal_range=fnirs_signal_range,
                plot=fnirs_plot,
                show_plots=False,
                fs=fnirs_fs,
                col_red=fnirs_col_red,
                col_ir=fnirs_col_ir,
                use_hampel=fnirs_use_hampel,
                use_dwt=fnirs_use_dwt,
            )
        except Exception as exc:
            print(f"  [fNIRS ERROR] {exc}")
            record["fnirs"] = f"error: {exc}"

        if isinstance(record.get("fnirs"), dict):
            hbo_c, hbr_c = filter_fnirs_outliers(
                record["fnirs"]["HbO"], record["fnirs"]["HbR"], n_sd=3
            )
            record["fnirs"]["HbO"] = hbo_c
            record["fnirs"]["HbR"] = hbr_c

        # ── Step 3: PPG ──────────────────────────────────────────────────────
        _section("STEP 3 — PPG quality check")
        try:
            record["ppg"] = check_ppg(
                csv_path,
                first_samples_to_ignore=ppg_first_samples_to_ignore,
                column_name=ppg_column,
                fs=ppg_fs,
                plot=ppg_plot,
                show_plots=ppg_plot,
            )
        except Exception as exc:
            print(f"  [PPG ERROR] {exc}")
            record["ppg"] = f"error: {exc}"

        # ── Step 4: Focus Index timeline ─────────────────────────────────────
        _section("STEP 4 — Focus Index (β/α) timeline")
        if edf_path:
            print(f"  EDF: {edf_path}")
            try:
                fi_save = None
                if fi_save_dir:
                    os.makedirs(fi_save_dir, exist_ok=True)
                    fi_save = os.path.join(fi_save_dir, stem + "_FI.png")
                plot_fi_timeline(
                    edf_path,
                    channels=fi_channels,
                    win_sec=fi_win_sec,
                    step_sec=fi_step_sec,
                    save_path=fi_save,
                )
                record["fi"] = fi_save if fi_save else "shown"
            except Exception as exc:
                print(f"  [FI ERROR] {exc}")
                record["fi"] = f"error: {exc}"
        else:
            print("  Skipped — no EDF produced for this recording.")
            record["fi"] = "skipped"

        # ── Step 5: Combined 3-panel summary ─────────────────────────────────
        _section("STEP 5 — Combined summary plot (fNIRS | PPG | EEG FI)")
        try:
            summary_path = None
            if summary_save_dir:
                os.makedirs(summary_save_dir, exist_ok=True)
                summary_path = os.path.join(summary_save_dir, stem + "_summary.png")
            plot_combined_summary(
                csv_path=csv_path,
                fnirs_result=record.get("fnirs"),
                edf_path=edf_path,
                fnirs_fs=fnirs_fs,
                ppg_column=ppg_column,
                ppg_fs=ppg_fs,
                ppg_first_samples_to_ignore=ppg_first_samples_to_ignore,
                fi_channels=fi_channels,
                fi_win_sec=fi_win_sec,
                fi_step_sec=fi_step_sec,
                save_path=summary_path,
                show=show_summary,
            )
            record["summary"] = summary_path or ("shown" if show_summary else "skipped")
        except Exception as exc:
            print(f"  [SUMMARY ERROR] {exc}")
            record["summary"] = f"error: {exc}"

        results.append(record)
        plt.close("all")

    _print_summary(results)
    return results


# ── CLI ───────────────────────────────────────────────────────────────────────
def _parse_args():
    p = argparse.ArgumentParser(
        description="Unified multimodal neurophysiology pipeline (EEG + fNIRS + PPG)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("csv_input",      help="CSV file or folder of CSV files")
    p.add_argument("edf_output",     help="Output folder for EDF files")
    p.add_argument("--eeg-fs",       type=int, default=EEG_FS,  help=f"EEG sampling rate (default {EEG_FS})")
    p.add_argument("--device",       default="BL", choices=["BL", "MUSE"], help="EEG device type")
    p.add_argument("--fnirs-fs",     type=int, default=100,  help="fNIRS sampling rate (default 100)")
    p.add_argument("--ppg-fs",       type=int, default=100,  help="PPG sampling rate (default 100)")
    p.add_argument("--ppg-skip",     type=int, default=0,    help="PPG samples to ignore at start")
    p.add_argument("--fnirs-hampel", action="store_true",    help="Hampel filter on fNIRS intensity")
    p.add_argument("--fnirs-dwt",    action="store_true",    help="DWT denoising on fNIRS intensity")
    p.add_argument("--no-plot",      action="store_true",    help="Suppress all matplotlib windows")
    p.add_argument("--fi-save",      default=None,           help="Dir to save FI plots (default: show)")
    p.add_argument("--summary-save", default=GRAPH_SUMMARY_DIR, help="Dir to save combined summary PNGs")
    p.add_argument("--show-summary",   action="store_true", help="Show combined summary plot interactively")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    run_pipeline(
        csv_input=args.csv_input,
        edf_output_dir=args.edf_output,
        eeg_sampling_rate=args.eeg_fs,
        eeg_device=args.device,
        fnirs_fs=args.fnirs_fs,
        ppg_fs=args.ppg_fs,
        ppg_first_samples_to_ignore=args.ppg_skip,
        fnirs_use_hampel=args.fnirs_hampel,
        fnirs_use_dwt=args.fnirs_dwt,
        fnirs_plot=not args.no_plot,
        ppg_plot=False,
        fi_save_dir=args.fi_save,
        summary_save_dir=args.summary_save,
        show_summary=args.show_summary,
    )
