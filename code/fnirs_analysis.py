#!/usr/bin/env python3
"""
fnirs_analysis.py — Standalone fNIRS two-channel (HbO / HbR) analysis.

Produces a four-panel figure:
  1. HbO time series with task-timeline shading
  2. HbR time series with task-timeline shading
  3. HbO + HbR combined
  4. Paired t-test statistics table (consistent with summary pipeline)

Usage
-----
  python fnirs_analysis.py                         # built-in example
  python fnirs_analysis.py path/to/file.csv        # single file
  python fnirs_analysis.py path/to/folder          # all CSVs in folder
"""

import os
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

from utils import (
    get_timeline, filter_outliers, paired_test, sig_pairs, fmt_paired,
    shade_timeline, WIN_COLORS,
)


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


def filter_fnirs_outliers(hbo, hbr, n_sd=3):
    """Thin wrapper — applies filter_outliers independently to HbO and HbR."""
    return filter_outliers(hbo, n_sd), filter_outliers(hbr, n_sd)


# ── Main plot function ────────────────────────────────────────────────────────

def plot_fnirs(
    csv_path,
    save_path=None,
    show=False,
    col_red=FNIRS_COL_RED,
    col_ir=FNIRS_COL_IR,
    fnirs_fs=FNIRS_FS,
    use_hampel=False,
    use_dwt=False,
):
    stem    = os.path.splitext(os.path.basename(csv_path))[0]
    windows = get_timeline(csv_path)

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

    HbO     = filter_outliers(result["HbO"])
    HbR     = filter_outliers(result["HbR"])
    sci_r   = result.get("sci_r",   float("nan"))
    hb_corr = result.get("Hb_corr", float("nan"))
    fs_used = result.get("fs", fnirs_fs)
    t       = np.arange(len(HbO)) / fs_used
    x_max   = t[-1] if len(t) else 0

    def _f(v, d=4):
        return f"{v:.{d}f}" if not np.isnan(v) else "n/a"

    # ── Figure ────────────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(20, 18))
    fig.suptitle(stem, fontsize=11, fontweight="bold")
    gs = gridspec.GridSpec(4, 1, height_ratios=[3, 3, 3, 2.2], hspace=0.85)

    def _setup_ax(ax, signal, color, label, title):
        shade_timeline(ax, windows, x_max=x_max)
        ax.plot(t, signal, color=color, lw=0.9, label=label, zorder=3)
        ax.set_title(title, fontsize=9)
        ax.set_xlim(0, x_max)
        ax.set_ylim(-5e-6, 5e-6)
        ax.set_xlabel("Time (s)", fontsize=8)
        ax.set_ylabel("µM", fontsize=8)
        ax.legend(loc="upper right", fontsize=8)
        ax.grid(True, alpha=0.25, zorder=0)
        ax.tick_params(labelsize=7)

    ax1 = fig.add_subplot(gs[0])
    _setup_ax(ax1, HbO, "red", "HbO",
              f"fNIRS — HbO   SCI r={sci_r:.3f} | HbO–HbR corr={hb_corr:.3f}")

    ax2 = fig.add_subplot(gs[1])
    _setup_ax(ax2, HbR, "steelblue", "HbR", "fNIRS — HbR")

    ax_c = fig.add_subplot(gs[2])
    shade_timeline(ax_c, windows, x_max=x_max)
    ax_c.plot(t, HbO, color="red",       lw=0.9, label="HbO", zorder=3)
    ax_c.plot(t, HbR, color="steelblue", lw=0.9, label="HbR", zorder=3)
    ax_c.set_title("fNIRS — HbO / HbR", fontsize=9)
    ax_c.set_xlim(0, x_max)
    ax_c.set_ylim(-5e-6, 5e-6)
    ax_c.set_xlabel("Time (s)", fontsize=8)
    ax_c.set_ylabel("µM", fontsize=8)
    ax_c.legend(loc="upper right", fontsize=8)
    ax_c.grid(True, alpha=0.25, zorder=0)
    ax_c.tick_params(labelsize=7)

    # ── Stats table — paired t-test ───────────────────────────────────────────
    ax3 = fig.add_subplot(gs[3])
    ax3.axis("off")
    ax3.set_title(
        "fNIRS — Paired t-test (individual data points, task vs adjacent rest)",
        fontsize=9, pad=4,
    )

    hbo_tr = sig_pairs(HbO, fs_used, windows)
    hbr_tr = sig_pairs(HbR, fs_used, windows)
    stats_rows = [
        fmt_paired("HbO Task vs Rest", paired_test(hbo_tr)),
        fmt_paired("HbR Task vs Rest", paired_test(hbr_tr)),
    ]

    col_labels = ["Measure", "Task mean ± SD (µM)", "Control mean ± SD (µM)",
                  "t statistic", "p-value", "Sig.", "Effect r"]
    tbl = ax3.table(cellText=stats_rows, colLabels=col_labels, loc="center", cellLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8)
    tbl.scale(1, 1.5)
    for c in range(len(col_labels)):
        tbl[0, c].set_text_props(fontweight="bold")
    for ri, row in enumerate(stats_rows, start=1):
        cell = tbl[ri, 5]
        if row[5] in ("*", "**", "***"): cell.set_facecolor("#d4edda")
        elif row[5] == "ns":             cell.set_facecolor("#f8d7da")

    patch_handles = [
        mpatches.Patch(facecolor=WIN_COLORS["baseline"], alpha=0.5, label=f"Baseline F0 ({TASK_DUR}s)"),
        mpatches.Patch(facecolor=WIN_COLORS["task_odd"], alpha=0.5, label=f"Task ({TASK_DUR}s)"),
        mpatches.Patch(facecolor=WIN_COLORS["rest"],     alpha=0.5, label=f"Rest ({REST_DUR}s)"),
        mpatches.Patch(facecolor=WIN_COLORS["prefocus"], alpha=0.5, label=f"Pre-focus ({PREFOCUS_DUR}s)"),
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
