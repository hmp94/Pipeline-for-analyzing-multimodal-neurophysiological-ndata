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
    FNIRS_FS, FNIRS_COL_RED, FNIRS_COL_IR, FNIRS_HEMO_BAND,
    EEG_FS, EEG_CHANNELS, EEG_FI_WIN, EEG_FI_STEP,
    GRAPH_FNIRS_DIR, GRAPH_EEG_DIR, GRAPH_SUMMARY_DIR,
)
from utils import (
    get_timeline, filter_outliers, zscore, paired_test, raw_pairs, sig_pairs, fi_pairs,
    rmssd_windows, fmt_paired, shade_timeline, timeline_legend,
)

import argparse
import shutil
import tempfile

import matplotlib
matplotlib.use("Agg")          # non-interactive backend; overridden below when needed
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
from scipy.signal import find_peaks


# ── Sibling analysis modules (this dir is on sys.path via CODE_DIR above) ─────
# intensity_filter is imported first: fnirs_check does `from intensity_filter import ...`.
import intensity_filter          # noqa: F401 — imported for fnirs_check's benefit
from csv_to_edf_denoised import convert_csv_to_edf
from fnirs_check import check_fNIRS_SCI
import ppg_check as ppg
from eeg_fi_line_chart import plot_fi_timeline, load_eeg_from_edf, compute_fi_timeline

check_ppg = ppg.check_ppg


# ── Orchestration helpers ─────────────────────────────────────────────────────
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
    windows=None,
    title=None,
):
    """Three-panel figure with task-timeline shading: fNIRS HbO/HbR | PPG | EEG FI.

    `windows` overrides the timeline. Left as None it is recovered from the
    filename's F0-F1-… order, which is right for the 12-block corpus; a
    randomized PsychoPy session must pass the windows built by
    session_timeline.build_session_windows() instead, since its order lives in
    metadata.json rather than the filename.
    """
    stem = os.path.splitext(os.path.basename(csv_path))[0]

    if windows is None:
        try:
            windows = get_timeline(csv_path)
        except Exception:
            windows = []

    fig = plt.figure(figsize=(20, 16))
    fig.suptitle(title or stem, fontsize=11, fontweight="bold")
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
        HbO = zscore(HbO)          # normalized units (~±3); task-vs-rest t-stat unchanged
        HbR = zscore(HbR)
        t    = np.arange(len(HbO)) / fs_f
        shade_timeline(ax1, windows, x_scale=1.0, x_max=t[-1] if len(t) else 0)
        ax1.plot(t, HbO, color="red",  lw=0.9, label="HbO", zorder=3)
        ax1.plot(t, HbR, color="blue", lw=0.9, label="HbR", zorder=3)
        sci     = fnirs_result.get("sci_r", float("nan"))
        hb_corr = fnirs_result.get("Hb_corr", float("nan"))
        ax1.set_title(
            f"fNIRS — HbO / HbR   SCI r={sci:.3f} | HbO–HbR corr={hb_corr:.3f}",
            fontsize=9,
        )
        ax1.set_xlim(0, t[-1])
        # Adaptive y-limit (robust to residual motion spikes) so the response is visible
        _av = np.abs(np.concatenate([HbO, HbR])) if len(HbO) else np.array([5e-6])
        _yl = float(np.nanpercentile(_av, 99)) * 1.2
        ax1.set_ylim(-_yl, _yl) if np.isfinite(_yl) and _yl > 0 else ax1.set_ylim(-5e-6, 5e-6)

        # stats — paired t-test, task vs rest only
        hbo_tr = sig_pairs(HbO, fs_f, windows)
        hbr_tr = sig_pairs(HbR, fs_f, windows)
        stats_rows.append(fmt_paired("fNIRS HbO Task vs Rest", paired_test(hbo_tr)))
        stats_rows.append(fmt_paired("fNIRS HbR Task vs Rest", paired_test(hbr_tr)))
    else:
        ax1.text(0.5, 0.5, f"fNIRS unavailable:\n{fnirs_result}",
                 ha="center", va="center", transform=ax1.transAxes, fontsize=8)
        ax1.set_title("fNIRS — unavailable", fontsize=9)
    ax1.set_xlabel("Time (s)", fontsize=8)
    ax1.set_ylabel("normalized (z)", fontsize=8)
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
        ppg_vals = ppg.truncate_at_first_nan(ppg_vals).dropna()
        ppg_raw  = ppg.convert_to_raw(ppg_vals.to_numpy())
        ppg_raw  = ppg_raw[max(0, ppg_first_samples_to_ignore):]
        ppg_raw  = ppg.fill_missing(ppg_raw)
        ppg_filt = ppg.preprocess_ppg(ppg_raw, ppg_fs, use_sg=True)
        ppg_filt = filter_outliers(ppg_filt, n_sd=3)

        peaks, _ = find_peaks(ppg_filt, distance=int(ppg_fs * 0.4))
        hr = (60 / (np.mean(np.diff(peaks)) / ppg_fs)) if len(peaks) > 1 else float("nan")

        ppg_filt = zscore(ppg_filt)   # normalized units; peaks/HR/RMSSD are timing-based, unaffected
        t_ppg = np.arange(len(ppg_filt)) / ppg_fs
        shade_timeline(ax2, windows, x_scale=1.0, x_max=t_ppg[-1] if len(t_ppg) else 0)
        ax2.plot(t_ppg, ppg_filt, color="darkgreen", lw=0.8, label="PPG filtered", zorder=3)
        if len(peaks):
            ax2.plot(peaks / ppg_fs, ppg_filt[peaks], "ro", ms=2.5, label="Peaks", zorder=4)

        _pz = float(np.nanpercentile(np.abs(ppg_filt), 99)) * 1.2 if len(ppg_filt) else 5.0
        ax2.set_ylim(-_pz, _pz) if np.isfinite(_pz) and _pz > 0 else ax2.set_ylim(-5, 5)
        ax2.set_xlim(0, t_ppg[-1])
        ax2.set_title(f"PPG — filtered signal   HR ≈ {hr:.1f} bpm", fontsize=9)

        # stats — RMSSD per window, task vs rest
        rmssd_p = rmssd_windows(peaks, ppg_fs, windows)
        stats_rows.append(fmt_paired("PPG RMSSD Task vs Rest (ms)", paired_test(rmssd_p)))
    except Exception as exc:
        ax2.text(0.5, 0.5, f"PPG unavailable:\n{exc}",
                 ha="center", va="center", transform=ax2.transAxes, fontsize=8)
        ax2.set_title("PPG — unavailable", fontsize=9)
    ax2.set_xlabel("Time (s)", fontsize=8)
    ax2.set_ylabel("normalized (z)", fontsize=8)
    ax2.legend(loc="upper right", fontsize=8)
    ax2.grid(True, alpha=0.25, zorder=0)
    ax2.tick_params(labelsize=7)

    # ── Panel 3: EEG Focus Index ──────────────────────────────────────────────
    ax3 = fig.add_subplot(gs[2])
    if edf_path and os.path.exists(edf_path):
        try:
            data, _, fs_e = load_eeg_from_edf(edf_path, fi_channels)
            t_c, fi       = compute_fi_timeline(data, fs_e, win_sec=fi_win_sec, step_sec=fi_step_sec)
            fi_avg        = filter_outliers(fi.mean(axis=0), n_sd=3)
            fi_avg        = zscore(fi_avg)     # normalized units; task-vs-rest t-stat unchanged
            t_min         = t_c / 60

            k         = max(1, int(60 / fi_step_sec))
            fi_smooth = np.convolve(fi_avg, np.ones(k) / k, mode="same")

            shade_timeline(ax3, windows, x_scale=1 / 60, x_max=t_min[-1] if len(t_min) else 0)
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
            _fz = float(np.nanpercentile(np.abs(fi_avg), 99)) * 1.2 if len(fi_avg) else 4.0
            ax3.set_ylim(-_fz, _fz) if np.isfinite(_fz) and _fz > 0 else ax3.set_ylim(-4, 4)
            ax3.set_title(
                f"EEG — Focus Index (β/α)   channels: {list(fi_channels)}", fontsize=9
            )
            ax3.set_xlabel("Time (min)", fontsize=8)

            # EEG stats — paired t-test on individual FI values (1 s step)
            tr_pairs = fi_pairs(t_c, fi_avg, windows)
            stats_rows.append(fmt_paired("EEG FI Task vs Rest", paired_test(tr_pairs)))
        except Exception as exc:
            ax3.text(0.5, 0.5, f"FI error:\n{exc}",
                     ha="center", va="center", transform=ax3.transAxes, fontsize=8)
            ax3.set_title("EEG FI — error", fontsize=9)
    else:
        ax3.text(0.5, 0.5, "No EDF produced — EEG FI unavailable",
                 ha="center", va="center", transform=ax3.transAxes, fontsize=8)
        ax3.set_title("EEG FI — unavailable", fontsize=9)
    ax3.set_ylabel("normalized (z)", fontsize=8)
    ax3.legend(loc="upper right", fontsize=8)
    ax3.grid(True, alpha=0.25, zorder=0)
    ax3.tick_params(labelsize=7)

    # ── Panel 4: Statistics table ─────────────────────────────────────────────
    ax4 = fig.add_subplot(gs[3])
    ax4.axis("off")
    ax4.set_title("Paired t-test — task vs adjacent rest  (fNIRS/EEG: z-normalized samples; PPG: RMSSD per window, ms)",
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
        mpatches.Patch(facecolor=color, alpha=0.5, label=label)
        for color, label in timeline_legend(windows)
    ]
    if patch_handles:
        fig.legend(handles=patch_handles, loc="lower center", ncol=len(patch_handles),
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
    fnirs_hemo_band=FNIRS_HEMO_BAND,
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
    # Timeline override
    windows_for=None,
    title_for=None,
):
    """Run all four pipeline steps on one CSV file or a folder of CSV files.

    Returns a list of per-file result dicts with keys:
      file, eeg, fnirs, ppg, fi

    `windows_for` optionally maps a CSV path to a prebuilt timeline, for
    recordings whose block order is not in the filename (see session_timeline).
    `title_for` likewise maps a CSV path to a figure title. Both default to the
    filename-derived behaviour used by the 12-block corpus.
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
        windows = (windows_for or {}).get(csv_path)
        fig_title = (title_for or {}).get(csv_path)

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
                hemo_band=fnirs_hemo_band,
                use_hampel=fnirs_use_hampel,
                use_dwt=fnirs_use_dwt,
            )
        except Exception as exc:
            print(f"  [fNIRS ERROR] {exc}")
            record["fnirs"] = f"error: {exc}"

        if isinstance(record.get("fnirs"), dict):
            record["fnirs"]["HbO"] = filter_outliers(record["fnirs"]["HbO"], n_sd=3)
            record["fnirs"]["HbR"] = filter_outliers(record["fnirs"]["HbR"], n_sd=3)

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
                    windows=windows,
                    title=fig_title,
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
                windows=windows,
                title=fig_title,
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
