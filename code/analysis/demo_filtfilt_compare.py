"""
demo_filtfilt_compare.py
Runs for every EDF in the good/ folder.
Compares FI from:
  - AF3_processed / AF4_processed (current: lfilter, causal)
  - Same filter chain applied with filtfilt (zero-phase)
Saves one PNG per subject into graph/proposed processing/
"""
import os, sys, glob
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec
from scipy.signal import butter, filtfilt, iirnotch
from scipy.stats import mannwhitneyu, norm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eeg_fi_line_chart import load_eeg_from_edf, compute_fi_timeline, get_timeline, _WIN_COLORS
from metadata import TASK_DUR, REST_DUR, PREFOCUS_DUR, EEG_FI_WIN, EEG_FI_STEP

EDF_DIR = "/Users/minhphan/Documents/Brain-Life/data/raw/edf/good"
OUT_DIR = "/Users/minhphan/Documents/Brain-Life/graph/proposed processing"
os.makedirs(OUT_DIR, exist_ok=True)


def preprocess_filtfilt(data, fs=244):
    out = data.copy().astype(np.float64)
    b, a = iirnotch(60 / (fs / 2), Q=12); out = filtfilt(b, a, out)
    b, a = iirnotch(50 / (fs / 2), Q=5);  out = filtfilt(b, a, out)
    b, a = iirnotch(32 / (fs / 2), Q=10); out = filtfilt(b, a, out)
    b, a = butter(4, [1 / (fs / 2), 35 / (fs / 2)], btype='band')
    out  = filtfilt(b, a, out)
    return out


def fi_segments(t_c, fi_avg, windows):
    task, rest, pre = [], [], []
    for w in windows:
        mask = (t_c >= w["t_start"]) & (t_c < w["t_end"])
        if not mask.any():
            continue
        seg = fi_avg[mask]
        if w.get("is_prefocus"):        pre.append(seg)
        elif w["is_baseline"] or w["is_interval"]: rest.append(seg)
        else:                           task.append(seg)
    return task, rest, pre


def mw_test(a_segs, b_segs):
    a_vals = [float(np.mean(s)) for s in a_segs if len(s) > 0]
    b_vals = [float(np.mean(s)) for s in b_segs if len(s) > 0]
    row = {"a": f"{np.mean(a_vals):.3f} ± {np.std(a_vals):.3f}",
           "b": f"{np.mean(b_vals):.3f} ± {np.std(b_vals):.3f}",
           "U": "n/a", "p": "n/a", "sig": "n/a", "r": "n/a"}
    if len(a_vals) >= 2 and len(b_vals) >= 2:
        U, p = mannwhitneyu(a_vals, b_vals, alternative="two-sided")
        z    = abs(norm.ppf(p / 2)) if 0 < p < 1 else 0.0
        r    = z / np.sqrt(len(a_vals) + len(b_vals))
        sig  = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
        row.update({"U": f"{U:.0f}", "p": f"{p:.4f}", "sig": sig, "r": f"{r:.3f}"})
    return row


def build_row(label, d):
    return [label, d["a"], d["b"], d["U"], d["p"], d["sig"], d["r"]]


def run_one(edf_path):
    stem = os.path.splitext(os.path.basename(edf_path))[0]
    save = os.path.join(OUT_DIR, f"{stem}_proposed.png")

    raw_data, _, fs = load_eeg_from_edf(edf_path, ("AF3", "AF4"))
    filtfilt_data   = np.vstack([preprocess_filtfilt(raw_data[0], fs),
                                  preprocess_filtfilt(raw_data[1], fs)])
    proc_data, _, _ = load_eeg_from_edf(edf_path, ("AF3_processed", "AF4_processed"))

    windows = get_timeline(edf_path)
    t_c, fi_proc     = compute_fi_timeline(proc_data,     fs, EEG_FI_WIN, EEG_FI_STEP)
    _,   fi_filtfilt = compute_fi_timeline(filtfilt_data, fs, EEG_FI_WIN, EEG_FI_STEP)

    fi_proc_avg     = fi_proc.mean(axis=0)
    fi_filtfilt_avg = fi_filtfilt.mean(axis=0)
    t_min = t_c / 60

    k = max(1, int(60 / EEG_FI_STEP))
    sm_proc     = np.convolve(fi_proc_avg,     np.ones(k) / k, mode="same")
    sm_filtfilt = np.convolve(fi_filtfilt_avg, np.ones(k) / k, mode="same")

    fi_t_lf, fi_r_lf, fi_p_lf = fi_segments(t_c, fi_proc_avg,     windows)
    fi_t_ff, fi_r_ff, fi_p_ff = fi_segments(t_c, fi_filtfilt_avg, windows)

    col_labels  = ["Comparison", "Group A (mean±SD)", "Group B (mean±SD)", "U", "p", "sig", "r"]
    rows_lf_fmt = [build_row("Task vs Rest",      mw_test(fi_t_lf, fi_r_lf)),
                   build_row("Task vs Pre-focus", mw_test(fi_t_lf, fi_p_lf)),
                   build_row("Rest vs Pre-focus", mw_test(fi_r_lf, fi_p_lf))]
    rows_ff_fmt = [build_row("Task vs Rest",      mw_test(fi_t_ff, fi_r_ff)),
                   build_row("Task vs Pre-focus", mw_test(fi_t_ff, fi_p_ff)),
                   build_row("Rest vs Pre-focus", mw_test(fi_r_ff, fi_p_ff))]

    fig = plt.figure(figsize=(22, 14))
    gs  = GridSpec(4, 1, figure=fig, height_ratios=[3, 3, 2, 2], hspace=0.65)
    ax_lf  = fig.add_subplot(gs[0])
    ax_ff  = fig.add_subplot(gs[1], sharex=ax_lf)
    ax_tlf = fig.add_subplot(gs[2])
    ax_tff = fig.add_subplot(gs[3])

    subject = stem.split("_")[0]
    fig.suptitle(f"{subject} — EEG FI: lfilter (current) vs filtfilt (proposed, zero-phase)\n"
                 "Mann-Whitney U test (two-sided)",
                 fontsize=11, fontweight="bold")

    for ax, title, fi_raw, fi_sm, raw_col, sm_col in [
        (ax_lf, "lfilter — current  (AF3_processed / AF4_processed, causal)",
         fi_proc_avg, sm_proc, "#b3a2cc", "#4a2a6a"),
        (ax_ff, "filtfilt — proposed  (raw AF3/AF4 re-processed, zero-phase)",
         fi_filtfilt_avg, sm_filtfilt, "#a2c4b3", "#1a5c3a"),
    ]:
        for w in windows:
            if w["is_baseline"]:   c = _WIN_COLORS["baseline"]
            elif w["is_interval"]: c = _WIN_COLORS["rest"]
            elif w["is_prefocus"]: c = _WIN_COLORS["prefocus"]
            else:                  c = _WIN_COLORS["task_odd"]
            ax.axvspan(w["t_start"] / 60, w["t_end"] / 60, alpha=0.28, color=c, lw=0)
        ax.plot(t_min, fi_raw, color=raw_col, lw=0.5, alpha=0.5, label="FI raw")
        ax.plot(t_min, fi_sm,  color=sm_col,  lw=1.8, label="FI smoothed")
        first = True
        for w in windows:
            if w["is_interval"] or w["is_prefocus"]:
                continue
            mask = (t_c >= w["t_start"]) & (t_c < w["t_end"])
            if not mask.any():
                continue
            ax.hlines(fi_raw[mask].mean(), w["t_start"] / 60, w["t_end"] / 60,
                      colors="red", linewidths=2.0, zorder=5,
                      label="Task mean FI" if first else None)
            first = False
        ax.set_title(title, fontsize=9, fontweight="bold")
        ax.set_ylabel("FI = β/α", fontsize=9)
        ax.grid(True, alpha=0.2)
        ax.set_xlim(0, t_min[-1])
        ax.legend(loc="upper right", fontsize=8, framealpha=0.8)

    ax_ff.set_xlabel("Time (min)", fontsize=9)

    sig_col = col_labels.index("sig")
    for ax_t, rows, version in [(ax_tlf, rows_lf_fmt, "lfilter (current)"),
                                  (ax_tff, rows_ff_fmt, "filtfilt (proposed)")]:
        ax_t.axis("off")
        ax_t.set_title(f"Mann-Whitney U test (two-sided) — {version}",
                       fontsize=9, fontweight="bold", pad=10)
        tbl = ax_t.table(cellText=rows, colLabels=col_labels,
                         loc="center", cellLoc="center")
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(9)
        tbl.scale(1, 1.8)
        for row_i, row in enumerate(rows, start=1):
            sig   = row[sig_col]
            color = ("#c8f0c8" if sig in ("*", "**", "***") else
                     "#f0c8c8" if sig == "ns" else "white")
            tbl[row_i, sig_col].set_facecolor(color)

    patches = [
        mpatches.Patch(facecolor=_WIN_COLORS["baseline"],  label=f"Baseline (F0, {TASK_DUR}s)"),
        mpatches.Patch(facecolor=_WIN_COLORS["task_odd"],  label=f"Task ({TASK_DUR}s)"),
        mpatches.Patch(facecolor=_WIN_COLORS["rest"],      label=f"Rest ({REST_DUR}s)"),
        mpatches.Patch(facecolor=_WIN_COLORS["prefocus"],  label=f"Pre-focus ({PREFOCUS_DUR}s)"),
    ]
    fig.legend(handles=patches, loc="lower center", ncol=4,
               fontsize=8, framealpha=0.9, bbox_to_anchor=(0.5, 0.0))

    plt.savefig(save, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {save}")


for edf in sorted(glob.glob(os.path.join(EDF_DIR, "*.edf"))):
    try:
        run_one(edf)
    except Exception as e:
        print(f"SKIP {os.path.basename(edf)}: {e}")
