"""
fnirs_stroop_pipeline.py
========================
Applies the Stroop MATLAB preprocessing logic to Brain-Life 2-channel fNIRS CSV data.

Stroop logic (translated from process_fNIRS_EEG_Stroop.m + eegfilt.m):
  1. Load intensity from CSV (RED + IR columns)
  2. Median filter  (window = 51 samples)
  3. ΔOD = −log₁₀(I / I₀)   [Stroop uses log base-10, not ln]
  4. FIR bandpass 0.015–0.2 Hz  (eegfilt / firls + filtfilt, order 50)
  5. Modified Beer–Lambert Law → HbO / HbR
  6. Plot with task-timeline shading

Usage
-----
  python fnirs_stroop_pipeline.py                          # example file
  python fnirs_stroop_pipeline.py path/to/file.csv
  python fnirs_stroop_pipeline.py path/to/folder/          # all CSVs

Dependencies
------------
  pip install numpy scipy matplotlib pandas
"""

import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pandas as pd
from scipy.signal import medfilt, firls, filtfilt


# ── Constants ─────────────────────────────────────────────────────────────────
FS = 100          # sampling rate Hz (adjust if different)

# Task-timeline durations (seconds) — matches fnirs_analysis.py
TASK_DUR     = 120
REST_DUR     = 50
PREFOCUS_DUR = 10

# Stroop filter parameters
BANDPASS_LO  = 0.015   # Hz
BANDPASS_HI  = 0.2     # Hz
FIR_ORDER    = 50      # filter order (51 taps)
MEDIAN_WIN   = 51      # samples; MATLAB used 50, rounded to odd

# Beer–Lambert extinction coefficients [RED, IR] × [HbO, HbR]  (mM⁻¹ cm⁻¹, natural-log convention)
EXT_COEF = np.array([[446.0,  1115.88],   # RED  (~730 nm)
                      [1022.0,  692.36]],  # IR   (~850 nm)
                    dtype=float)
DISTANCE_CM = 3.5
DPF         = np.array([6.0, 6.0])        # differential pathlength factor per wavelength

# Output directory
GRAPH_DIR = "/Users/minhphan/Documents/Brain-Life/graph/fnirs_stroop"
DATA_DIR  = "/Users/minhphan/Documents/Brain-Life/data/raw/csv"

_WIN_COLORS = {
    "baseline": "#7ab8e8",
    "task":     "#72c472",
    "rest":     "#b0b0b0",
    "prefocus": "#f5d76e",
}


# ── Signal utilities ──────────────────────────────────────────────────────────

def convert_to_raw(values):
    """Decode 20-bit signed integers from raw ADC column (same as existing code)."""
    arr = np.asarray(values, dtype=np.int32)
    raw_20bit = arr & 0xFFFFF
    signed = np.where(raw_20bit >= (1 << 19), raw_20bit - (1 << 20), raw_20bit)
    signed = np.trim_zeros(signed, 'b')
    return signed.astype(np.float64)


def eegfilt_bandpass(data, srate=FS, locutoff=BANDPASS_LO, hicutoff=BANDPASS_HI,
                     filtorder=FIR_ORDER):
    """
    Two-pass FIR bandpass filter (translated from eegfilt.m by Scott Makeig et al.).

    data : 1-D array (single channel)
    Returns filtered 1-D array.
    """
    nyq   = srate * 0.5
    trans = 0.15

    f = [0.0,
         (1 - trans) * locutoff / nyq,
         locutoff / nyq,
         hicutoff / nyq,
         (1 + trans) * hicutoff / nyq,
         1.0]
    m = [0, 0, 1, 1, 0, 0]

    # firls: numtaps = filtorder + 1; normalized frequencies with Nyquist = 1
    filtwts = firls(filtorder + 1, f, m)
    return filtfilt(filtwts, 1.0, data.astype(float))


# ── Timeline helpers (copied from fnirs_analysis.py) ──────────────────────────

def _parse_task_order(csv_path):
    m = re.search(r"((?:F\d+|B)(?:-(?:F\d+|B))+)", os.path.basename(csv_path))
    if m:
        return [p for p in m.group(1).split("-") if p != "B"]
    return [f"F{i}" for i in range(13)]


def _build_windows(task_labels):
    windows, cur = [], 0
    for i, label in enumerate(task_labels):
        windows.append(dict(label=label, t_start=cur, t_end=cur + TASK_DUR,
                            is_baseline=(i == 0), is_interval=False, is_prefocus=False))
        cur += TASK_DUR
        if i == 0:
            windows.append(dict(label="pre-focus", t_start=cur, t_end=cur + PREFOCUS_DUR,
                                is_baseline=False, is_interval=False, is_prefocus=True))
            cur += PREFOCUS_DUR
        elif i < len(task_labels) - 1:
            windows.append(dict(label="rest", t_start=cur, t_end=cur + REST_DUR,
                                is_baseline=False, is_interval=True, is_prefocus=False))
            cur += REST_DUR
            windows.append(dict(label="pre-focus", t_start=cur, t_end=cur + PREFOCUS_DUR,
                                is_baseline=False, is_interval=False, is_prefocus=True))
            cur += PREFOCUS_DUR
    return windows


def _shade_timeline(ax, windows):
    for w in windows:
        x0, x1 = w["t_start"], w["t_end"]
        if w["is_baseline"]:   color = _WIN_COLORS["baseline"]
        elif w["is_interval"]: color = _WIN_COLORS["rest"]
        elif w["is_prefocus"]: color = _WIN_COLORS["prefocus"]
        else:                  color = _WIN_COLORS["task"]
        ax.axvspan(x0, x1, alpha=0.35, color=color, lw=0)
        mid = (x0 + x1) / 2
        if w["is_interval"]:
            label, fc = "REST",   "#444444"
        elif w["is_prefocus"]:
            label, fc = "PRE",    "#8a6800"
        elif w["is_baseline"]:
            label, fc = "BASELINE", "#1f5fbf"
        else:
            label, fc = "TASK",   "#2a6e2a"
        ax.text(mid, 0.97, label, transform=ax.get_xaxis_transform(),
                ha="center", va="top", fontsize=5.5, color=fc, fontweight="bold")


# ── Core processing ───────────────────────────────────────────────────────────

def run_stroop_pipeline(csv_path,
                        col_red="Header 27 Data",
                        col_ir="Header 28 Data",
                        baseline_start_s=0.0,
                        baseline_len_s=8.0):
    """
    Apply Stroop MATLAB preprocessing to one Brain-Life CSV file.

    Returns dict with HbO, HbR, time array, and intermediate signals.
    """
    df = pd.read_csv(csv_path)
    df.columns = df.columns.str.strip()
    col_red = col_red.strip()
    col_ir  = col_ir.strip()

    if col_red not in df.columns or col_ir not in df.columns:
        raise KeyError(
            f"Columns '{col_red}' / '{col_ir}' not found. "
            f"Available: {list(df.columns)}"
        )

    I_red = convert_to_raw(df[col_red].to_numpy())
    I_ir  = convert_to_raw(df[col_ir].to_numpy())

    n = min(len(I_red), len(I_ir))
    I_red = I_red[:n]
    I_ir  = I_ir[:n]

    # ── Step 1: median filter (Stroop: medfilt2 with window [50,1] → 51 for odd) ──
    I_red_mf = medfilt(I_red, MEDIAN_WIN)
    I_ir_mf  = medfilt(I_ir,  MEDIAN_WIN)

    # ── Step 2: ΔOD = −log₁₀(I / I₀)  (Stroop uses log base-10) ──────────────
    skip  = int(baseline_start_s * FS)
    blen  = int(baseline_len_s   * FS)
    eps   = 1e-12

    I_red_mf = np.clip(I_red_mf, eps, None)
    I_ir_mf  = np.clip(I_ir_mf,  eps, None)

    I0_red = np.mean(I_red_mf[skip: skip + blen])
    I0_ir  = np.mean(I_ir_mf[skip:  skip + blen])

    dOD_red = -np.log10(I_red_mf / I0_red)
    dOD_ir  = -np.log10(I_ir_mf  / I0_ir)

    # Remove mean over baseline so traces start at zero
    dOD_red -= np.mean(dOD_red[skip: skip + blen])
    dOD_ir  -= np.mean(dOD_ir[skip:  skip + blen])

    # ── Step 3: FIR bandpass 0.015–0.2 Hz (Stroop eegfilt, order 50) ──────────
    dOD_red_f = eegfilt_bandpass(dOD_red)
    dOD_ir_f  = eegfilt_bandpass(dOD_ir)

    # ── Step 4: Modified Beer–Lambert Law ──────────────────────────────────────
    # Convert log10 OD → natural-log OD so ext_coef (mM⁻¹ cm⁻¹, ln convention) applies
    dOD_red_ln = dOD_red_f * np.log(10)
    dOD_ir_ln  = dOD_ir_f  * np.log(10)

    L   = DISTANCE_CM * DPF                      # effective pathlength per wavelength
    EL  = EXT_COEF * L[:, None]                  # (2, 2)
    iEL = np.linalg.pinv(EL)                     # pseudo-inverse

    dOD_mat = np.vstack([dOD_red_ln, dOD_ir_ln]) # (2, N)
    Hb_mat  = iEL @ dOD_mat                      # (2, N)
    HbO = Hb_mat[0] * 1e3                        # → µM
    HbR = Hb_mat[1] * 1e3

    t = np.arange(n) / FS

    return dict(
        HbO=HbO, HbR=HbR, t=t,
        dOD_red=dOD_red, dOD_ir=dOD_ir,
        dOD_red_f=dOD_red_f, dOD_ir_f=dOD_ir_f,
        I_red=I_red, I_ir=I_ir,
        I_red_mf=I_red_mf, I_ir_mf=I_ir_mf,
    )


# ── Plotting ──────────────────────────────────────────────────────────────────

def plot_result(csv_path, result, save_path=None, show=False):
    stem    = os.path.splitext(os.path.basename(csv_path))[0]
    windows = _build_windows(_parse_task_order(csv_path))

    HbO = result["HbO"]
    HbR = result["HbR"]
    t   = result["t"]

    fig, axes = plt.subplots(3, 1, figsize=(18, 14), sharex=True)
    fig.suptitle(f"{stem}\n(Stroop pipeline: median filter → log₁₀ OD → FIR 0.015–0.2 Hz → MBLL)",
                 fontsize=10, fontweight="bold")

    # Panel 1: ΔOD (filtered)
    ax = axes[0]
    _shade_timeline(ax, windows)
    ax.plot(t, result["dOD_red_f"], color="red",   lw=0.8, label="ΔOD RED (filtered)")
    ax.plot(t, result["dOD_ir_f"],  color="green", lw=0.8, label="ΔOD IR (filtered)")
    ax.set_ylabel("ΔOD (log₁₀ a.u.)")
    ax.set_title("ΔOD after FIR bandpass (0.015–0.2 Hz)", fontsize=9)
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.25)

    # Panel 2: HbO
    ax = axes[1]
    _shade_timeline(ax, windows)
    ax.plot(t, HbO, color="red",      lw=0.9, label="HbO")
    ax.set_ylabel("µM")
    ax.set_title("Oxyhemoglobin (HbO)", fontsize=9)
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.25)

    # Panel 3: HbR + HbO overlay
    ax = axes[2]
    _shade_timeline(ax, windows)
    ax.plot(t, HbO, color="red",       lw=0.9, label="HbO")
    ax.plot(t, HbR, color="steelblue", lw=0.9, label="HbR")
    ax.set_ylabel("µM")
    ax.set_xlabel("Time (s)")
    ax.set_title("HbO / HbR", fontsize=9)
    ax.legend(loc="upper right", fontsize=8)
    ax.grid(True, alpha=0.25)

    patch_handles = [
        mpatches.Patch(facecolor=_WIN_COLORS["baseline"], alpha=0.5, label="Baseline F0 (120s)"),
        mpatches.Patch(facecolor=_WIN_COLORS["task"],     alpha=0.5, label="Task (120s)"),
        mpatches.Patch(facecolor=_WIN_COLORS["rest"],     alpha=0.5, label="Rest (50s)"),
        mpatches.Patch(facecolor=_WIN_COLORS["prefocus"], alpha=0.5, label="Pre-focus (10s)"),
    ]
    fig.legend(handles=patch_handles, loc="lower center", ncol=4,
               fontsize=8, framealpha=0.8, bbox_to_anchor=(0.5, 0.01))
    plt.subplots_adjust(bottom=0.07, hspace=0.35)

    if save_path:
        os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
        plt.savefig(save_path, dpi=150, bbox_inches="tight")
        print(f"  Saved → {save_path}")
    if show:
        plt.show()
    plt.close(fig)


# ── Entry point ───────────────────────────────────────────────────────────────

def _collect_targets(arg):
    if os.path.isdir(arg):
        return sorted(
            os.path.join(arg, f) for f in os.listdir(arg) if f.endswith(".csv")
        )
    return [arg]


if __name__ == "__main__":
    if len(sys.argv) > 1:
        targets = []
        for a in sys.argv[1:]:
            targets.extend(_collect_targets(a))
    else:
        # Default: first CSV in DATA_DIR
        if os.path.isdir(DATA_DIR):
            targets = sorted(
                os.path.join(DATA_DIR, f) for f in os.listdir(DATA_DIR) if f.endswith(".csv")
            )[:1]
        else:
            print(f"No argument given and DATA_DIR not found: {DATA_DIR}")
            sys.exit(1)

    os.makedirs(GRAPH_DIR, exist_ok=True)

    for csv_path in targets:
        stem = os.path.splitext(os.path.basename(csv_path))[0]
        print(f"\nProcessing: {stem}")
        try:
            result = run_stroop_pipeline(csv_path)
            save_path = os.path.join(GRAPH_DIR, f"{stem}_stroop.png")
            plot_result(csv_path, result, save_path=save_path)
            print(f"  HbO range: [{result['HbO'].min():.4f}, {result['HbO'].max():.4f}] µM")
            print(f"  HbR range: [{result['HbR'].min():.4f}, {result['HbR'].max():.4f}] µM")
        except Exception as e:
            print(f"  ERROR: {e}")
