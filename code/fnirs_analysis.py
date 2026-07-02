#!/usr/bin/env python3
"""
fnirs_analysis.py — Standalone fNIRS two-channel (HbO / HbR) analysis.

Timeline structure (parsed from filename):
  F0 (120s baseline) → PRE (10s) → F1 (120s task) → REST (50s) → PRE (10s) → F2 → ...

Supports both old filenames (F0-F1-F2-...) and new format (F0-F1-B-F2-B-...).
'B' tokens in filename are treated as break markers and stripped; the break
segments (REST + PRE-FOCUS) are inserted automatically.

Produces a three-panel figure:
  1. HbO time series with task-timeline shading
  2. HbR time series with task-timeline shading
  3. Task vs Rest vs Pre-focus Mann-Whitney U statistics table

Usage
-----
  python fnirs_analysis.py                         # runs built-in example
  python fnirs_analysis.py path/to/file.csv        # single file
  python fnirs_analysis.py path/to/folder          # all CSVs in folder
"""

import os
import re
import sys
import importlib.util
from metadata import (
    TASK_DUR, REST_DUR, PREFOCUS_DUR,
    FNIRS_FS, FNIRS_COL_RED, FNIRS_COL_IR,
    GRAPH_FNIRS_DIR,
)

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import numpy as np
from scipy.stats import mannwhitneyu, norm


# ── Dynamic imports (filenames contain spaces) ────────────────────────────────
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)


def _import_path(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


_import_path("intensity_filter", os.path.join(CODE_DIR, "intensity_filter (1).py"))
_fnirs_mod      = _import_path("fnirs_check", os.path.join(CODE_DIR, "f-NIRS_check_for_T (1).py"))
check_fNIRS_SCI = _fnirs_mod.check_fNIRS_SCI


# ── Timeline constants ────────────────────────────────────────────────────────
# Timeline loaded from metadata.py

_WIN_COLORS = {
    "baseline": "#7ab8e8",
    "task":     "#72c472",
    "rest":     "#b0b0b0",
    "prefocus": "#f5d76e",
}


# ── Timeline helpers ──────────────────────────────────────────────────────────
def _parse_task_order(csv_path):
    """Extract ordered task labels from filename; strip any 'B' break tokens."""
    m = re.search(r"((?:F\d+|B)(?:-(?:F\d+|B))+)", os.path.basename(csv_path))
    if m:
        return [p for p in m.group(1).split("-") if p != "B"]
    return [f"F{i}" for i in range(13)]


def _build_windows(task_labels):
    """
    Build window dicts for the timeline:
      F0 (baseline) → PRE-FOCUS → F1 (task) → REST → PRE-FOCUS → F2 → ...
    No rest after the last task.
    """
    windows, cur = [], 0
    for i, label in enumerate(task_labels):
        windows.append(dict(
            label=label, t_start=cur, t_end=cur + TASK_DUR,
            is_baseline=(i == 0), is_interval=False, is_prefocus=False,
        ))
        cur += TASK_DUR

        if i < len(task_labels) - 1:
            if REST_DUR > 0:
                windows.append(dict(
                    label="rest", t_start=cur, t_end=cur + REST_DUR,
                    is_baseline=False, is_interval=True, is_prefocus=False,
                ))
                cur += REST_DUR
            if PREFOCUS_DUR > 0:
                windows.append(dict(
                    label="pre-focus", t_start=cur, t_end=cur + PREFOCUS_DUR,
                    is_baseline=False, is_interval=False, is_prefocus=True,
                ))
                cur += PREFOCUS_DUR

    return windows


# ── Timeline shading ──────────────────────────────────────────────────────────
def _shade_timeline(ax, windows, arrow_y=-0.10, label_y=-0.20):
    tick_half = 0.018
    for w in windows:
        x0, x1 = w["t_start"], w["t_end"]
        if w["is_baseline"]:   color = _WIN_COLORS["baseline"]
        elif w["is_interval"]: color = _WIN_COLORS["rest"]
        elif w["is_prefocus"]: color = _WIN_COLORS["prefocus"]
        else:                  color = _WIN_COLORS["task"]
        ax.axvspan(x0, x1, alpha=0.4, color=color, lw=0)

        mid = (x0 + x1) / 2

        # Top label inside the band
        if w["is_interval"]:
            ax.text(mid, 0.97, "REST", transform=ax.get_xaxis_transform(),
                    ha="center", va="top", fontsize=5.5, color="#444444",
                    fontweight="bold", style="italic")
            continue
        elif w["is_prefocus"]:
            ax.text(mid, 0.97, "PRE", transform=ax.get_xaxis_transform(),
                    ha="center", va="top", fontsize=5.5, color="#8a6800",
                    fontweight="bold")
            continue
        elif w["is_baseline"]:
            top_label, top_color = "BASELINE", "#1f5fbf"
        else:
            top_label, top_color = "TASK", "#2a6e2a"
        ax.text(mid, 0.97, top_label, transform=ax.get_xaxis_transform(),
                ha="center", va="top", fontsize=5.5, color=top_color,
                fontweight="bold")

        # Bracket arrow + label below axis
        arrow_color = "#1f5fbf" if w["is_baseline"] else "#555555"
        ax.annotate("", xy=(x1, arrow_y), xytext=(x0, arrow_y),
                    xycoords=("data", "axes fraction"),
                    arrowprops=dict(arrowstyle="<->", color=arrow_color, lw=1.1),
                    annotation_clip=False)
        for xc in (x0, x1):
            ax.annotate("", xy=(xc, arrow_y - tick_half), xytext=(xc, arrow_y + tick_half),
                        xycoords=("data", "axes fraction"),
                        arrowprops=dict(arrowstyle="-", color=arrow_color, lw=1.1),
                        annotation_clip=False)
        ax.annotate(w["label"], xy=(mid, label_y),
                    xycoords=("data", "axes fraction"),
                    ha="center", va="top", fontsize=6.5, color=arrow_color,
                    fontweight="bold" if w["is_baseline"] else "normal",
                    annotation_clip=False)


# ── Statistical analysis ──────────────────────────────────────────────────────
def _window_segments(signal, fs, windows):
    """Split signal into task, rest, and pre-focus segments."""
    n = len(signal)
    task_segs, rest_segs, pre_segs = [], [], []
    for w in windows:
        s = max(0, int(w["t_start"] * fs))
        e = min(n, int(w["t_end"] * fs))
        if e <= s:
            continue
        seg = signal[s:e]
        if w["is_prefocus"]:
            pre_segs.append(seg)
        elif w["is_baseline"] or w["is_interval"]:
            rest_segs.append(seg)
        else:
            task_segs.append(seg)
    return task_segs, rest_segs, pre_segs


def _mw_test(a_segs, b_segs, reducer=np.mean):
    """Mann-Whitney U between two groups of segments."""
    a_vals = [float(reducer(s)) for s in a_segs if len(s) > 0]
    b_vals = [float(reducer(s)) for s in b_segs if len(s) > 0]
    out = {
        "a_mean": np.nanmean(a_vals) if a_vals else np.nan,
        "a_std":  np.nanstd(a_vals)  if a_vals else np.nan,
        "b_mean": np.nanmean(b_vals) if b_vals else np.nan,
        "b_std":  np.nanstd(b_vals)  if b_vals else np.nan,
        "U": np.nan, "p": np.nan, "sig": "n/a", "r": np.nan,
    }
    if len(a_vals) >= 2 and len(b_vals) >= 2:
        try:
            U, p = mannwhitneyu(a_vals, b_vals, alternative="two-sided")
            z = abs(norm.ppf(p / 2)) if 0 < p < 1 else 0.0
            r = z / np.sqrt(len(a_vals) + len(b_vals))
            sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
            out.update({"U": U, "p": p, "sig": sig, "r": r})
        except Exception:
            pass
    return out


# ── Main plot function ────────────────────────────────────────────────────────
def plot_fnirs(
    csv_path,
    save_path=None,
    show=False,
    col_red="Header 27 Data",
    col_ir="Header 28 Data",
    fnirs_fs=100,
    use_hampel=False,
    use_dwt=False,
):
    stem    = os.path.splitext(os.path.basename(csv_path))[0]
    windows = _build_windows(_parse_task_order(csv_path))

    print(f"\nProcessing: {stem}")

    result  = check_fNIRS_SCI(
        csv_path,
        plot=False,
        show_plots=False,
        fs=fnirs_fs,
        col_red=col_red,
        col_ir=col_ir,
        use_hampel=use_hampel,
        use_dwt=use_dwt,
    )

    HbO     = result["HbO"]
    HbR     = result["HbR"]
    sci_r   = result.get("sci_r",   float("nan"))
    hb_corr = result.get("Hb_corr", float("nan"))
    fs_used = result.get("fs", fnirs_fs)
    t       = np.arange(len(HbO)) / fs_used

    def _fmt(v, d=4):
        return f"{v:.{d}f}" if not np.isnan(v) else "n/a"

    # ── Figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(20, 18))
    fig.suptitle(stem, fontsize=11, fontweight="bold")
    gs = gridspec.GridSpec(4, 1, height_ratios=[3, 3, 3, 2.2], hspace=0.85)

    # Panel 1 — HbO
    ax1 = fig.add_subplot(gs[0])
    _shade_timeline(ax1, windows)
    ax1.plot(t, HbO, color="red", lw=0.9, label="HbO", zorder=3)
    ax1.set_title(f"fNIRS — HbO   SCI r={sci_r:.3f} | HbO–HbR corr={hb_corr:.3f}", fontsize=9)
    ax1.set_xlim(0, t[-1])
    ax1.set_xlabel("Time (s)", fontsize=8)
    ax1.set_ylabel("µM", fontsize=8)
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(True, alpha=0.25, zorder=0)
    ax1.tick_params(labelsize=7)

    # Panel 2 — HbR
    ax2 = fig.add_subplot(gs[1])
    _shade_timeline(ax2, windows)
    ax2.plot(t, HbR, color="steelblue", lw=0.9, label="HbR", zorder=3)
    ax2.set_title(f"fNIRS — HbR", fontsize=9)
    ax2.set_xlim(0, t[-1])
    ax2.set_xlabel("Time (s)", fontsize=8)
    ax2.set_ylabel("µM", fontsize=8)
    ax2.legend(loc="upper right", fontsize=8)
    ax2.grid(True, alpha=0.25, zorder=0)
    ax2.tick_params(labelsize=7)

    # Panel 3 — HbO + HbR combined
    ax_c = fig.add_subplot(gs[2])
    _shade_timeline(ax_c, windows)
    ax_c.plot(t, HbO, color="red",      lw=0.9, label="HbO", zorder=3)
    ax_c.plot(t, HbR, color="steelblue", lw=0.9, label="HbR", zorder=3)
    ax_c.set_title(f"fNIRS — HbO / HbR", fontsize=9)
    ax_c.set_xlim(0, t[-1])
    ax_c.set_xlabel("Time (s)", fontsize=8)
    ax_c.set_ylabel("µM", fontsize=8)
    ax_c.legend(loc="upper right", fontsize=8)
    ax_c.grid(True, alpha=0.25, zorder=0)
    ax_c.tick_params(labelsize=7)

    # Panel 3 — Statistics table (Task vs Rest vs Pre-focus)
    ax3 = fig.add_subplot(gs[3])
    ax3.axis("off")
    ax3.set_title("Task vs Rest vs Pre-focus — Mann-Whitney U (two-sided)", fontsize=9, pad=4)

    col_labels = ["Channel", "Comparison",
                  "Group A mean ± SD (µM)", "Group B mean ± SD (µM)",
                  "U", "p-value", "Sig.", "Effect r"]
    rows = []
    for ch_label, sig_data in [("HbO", HbO), ("HbR", HbR)]:
        task_s, rest_s, pre_s = _window_segments(sig_data, fs_used, windows)
        for comp, s in [
            ("Task vs Rest",      _mw_test(task_s, rest_s)),
            ("Task vs Pre-focus", _mw_test(task_s, pre_s)),
            ("Rest vs Pre-focus", _mw_test(rest_s, pre_s)),
        ]:
            rows.append([
                ch_label, comp,
                f"{_fmt(s['a_mean'])} ± {_fmt(s['a_std'])}",
                f"{_fmt(s['b_mean'])} ± {_fmt(s['b_std'])}",
                _fmt(s["U"], 0) if not np.isnan(s["U"]) else "n/a",
                _fmt(s["p"])    if not np.isnan(s["p"]) else "n/a",
                s["sig"],
                _fmt(s["r"], 3) if not np.isnan(s["r"]) else "n/a",
            ])

    tbl = ax3.table(cellText=rows, colLabels=col_labels, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(7.5)
    tbl.scale(1, 1.4)
    for c in range(len(col_labels)):
        tbl[0, c].set_text_props(fontweight="bold")
    sig_col = 6
    for ri, row in enumerate(rows, start=1):
        cell = tbl[ri, sig_col]
        if row[sig_col] in ("*", "**", "***"): cell.set_facecolor("#d4edda")
        elif row[sig_col] == "ns":              cell.set_facecolor("#f8d7da")

    # Legend
    patch_handles = [
        mpatches.Patch(facecolor=_WIN_COLORS["baseline"], alpha=0.5, label="Baseline F0 (120s)"),
        mpatches.Patch(facecolor=_WIN_COLORS["task"],     alpha=0.5, label="Task (120s)"),
        mpatches.Patch(facecolor=_WIN_COLORS["rest"],     alpha=0.5, label="Rest (50s)"),
        mpatches.Patch(facecolor=_WIN_COLORS["prefocus"], alpha=0.5, label="Pre-focus (10s)"),
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


# ── Entry point ───────────────────────────────────────────────────────────────
DATA_DIR  = "/Users/minhphan/Documents/Brain-Life/data/raw/csv"
GRAPH_DIR = GRAPH_FNIRS_DIR


def _find_example():
    for f in sorted(os.listdir(DATA_DIR)):
        if f.lower().startswith("moon") and f.endswith(".csv"):
            return os.path.join(DATA_DIR, f)
    raise FileNotFoundError(f"No Moon CSV found in {DATA_DIR}")


EXAMPLE = _find_example()

if __name__ == "__main__":
    targets = []

    if len(sys.argv) > 1:
        path = sys.argv[1]
        if os.path.isdir(path):
            targets = sorted(
                os.path.join(path, f) for f in os.listdir(path) if f.endswith(".csv")
            )
        else:
            targets = [path]
    else:
        targets = [EXAMPLE]

    for csv in targets:
        stem = os.path.splitext(os.path.basename(csv))[0]
        plot_fnirs(csv, save_path=os.path.join(GRAPH_DIR, f"{stem}_fnirs.png"))
