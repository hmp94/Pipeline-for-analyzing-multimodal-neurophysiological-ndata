"""
utils.py — shared processing and plotting helpers for the Brain-Life pipeline.

All modality-specific analysis files import from here so logic is defined once.
"""

import re
import os
import numpy as np
if not hasattr(np, "trapezoid"):        # NumPy < 2.0 exposes this as np.trapz
    np.trapezoid = np.trapz
from scipy.stats import ttest_rel
from metadata import TASK_DUR, REST_DUR, PREFOCUS_DUR

# ── Window colours (shared across all plots) ──────────────────────────────────
WIN_COLORS = {
    "baseline":  "#7ab8e8",
    "task_odd":  "#72c472",
    "task_even": "#72c472",
    "rest":      "#b0b0b0",
    "prefocus":  "#f5d76e",
}

# ── Timeline helpers ──────────────────────────────────────────────────────────

def parse_task_order(path):
    """Extract ordered task labels from filename; strip any 'B' break tokens."""
    m = re.search(r"((?:F\d+|B)(?:-(?:F\d+|B))+)", os.path.basename(path))
    if m:
        return [p for p in m.group(1).split("-") if p != "B"]
    return [f"F{i}" for i in range(13)]


def build_windows(task_labels):
    """Build window dicts: baseline → [rest → pre-focus → task] × n."""
    windows, cur = [], 0
    for i, label in enumerate(task_labels):
        windows.append(dict(
            label=label, t_start=cur, t_end=cur + TASK_DUR,
            is_baseline=(i == 0), is_interval=False, is_prefocus=False,
        ))
        cur += TASK_DUR
        if i < len(task_labels) - 1:
            if i > 0 and REST_DUR > 0:
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


def get_timeline(path):
    return build_windows(parse_task_order(path))


# ── Signal processing ─────────────────────────────────────────────────────────

def filter_outliers(signal, n_sd=3):
    """Replace samples outside mean ± n_sd*SD with NaN, then linearly interpolate."""
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

def paired_test(pairs):
    """Paired t-test with effect r = |t| / sqrt(t² + df)."""
    if len(pairs) < 3:
        return dict(a_mean=np.nan, a_std=np.nan, b_mean=np.nan, b_std=np.nan,
                    stat=np.nan, p=np.nan, sig="n/a", r=np.nan)
    a = np.array([x for x, _ in pairs])
    b = np.array([x for _, x in pairs])
    stat, p = ttest_rel(a, b)
    sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "ns"
    df = len(pairs) - 1
    r_effect = float(abs(stat) / np.sqrt(stat**2 + df)) if df > 0 else np.nan
    return dict(a_mean=float(np.mean(a)), a_std=float(np.std(a)),
                b_mean=float(np.mean(b)), b_std=float(np.std(b)),
                stat=float(stat), p=float(p), sig=sig, r=r_effect)


def raw_pairs(a_vals, b_vals):
    """Pair tail of a with head of b (matched by length)."""
    n = min(len(a_vals), len(b_vals))
    return list(zip(a_vals[-n:], b_vals[:n]))


def sig_pairs(signal, fs, windows):
    """Pair raw samples task↔adjacent rest."""
    n = len(signal)

    def _block(w):
        s = max(0, int(w["t_start"] * fs))
        e = min(n, int(w["t_end"] * fs))
        return signal[s:e]

    task_wins = [w for w in windows if not w["is_interval"] and not w.get("is_prefocus") and not w["is_baseline"]]
    rest_wins = [w for w in windows if w["is_interval"]]

    tr_pairs = []
    for tw in task_wins:
        tvals = _block(tw)
        rw_cands = [rw for rw in rest_wins if rw["t_start"] >= tw["t_end"]]
        if rw_cands:
            rw = min(rw_cands, key=lambda r: r["t_start"])
            tr_pairs.extend(raw_pairs(tvals, _block(rw)))
    return tr_pairs


def fi_pairs(t_centers, fi_avg, windows):
    """Pair FI values (1 s step) task↔adjacent rest."""
    def _block(w):
        mask = (t_centers >= w["t_start"]) & (t_centers < w["t_end"])
        return fi_avg[mask]

    task_wins = [w for w in windows if not w["is_interval"] and not w.get("is_prefocus") and not w["is_baseline"]]
    rest_wins = [w for w in windows if w["is_interval"]]

    tr_pairs = []
    for tw in task_wins:
        tvals = _block(tw)
        rw_cands = [rw for rw in rest_wins if rw["t_start"] >= tw["t_end"]]
        if rw_cands:
            rw = min(rw_cands, key=lambda r: r["t_start"])
            tr_pairs.extend(raw_pairs(tvals, _block(rw)))
    return tr_pairs


def rmssd_windows(peaks, fs, windows):
    """RMSSD of inter-beat intervals per window; return (task_rmssd, rest_rmssd) pairs."""
    def _win_rmssd(w):
        lo, hi = w["t_start"] * fs, w["t_end"] * fs
        wp = peaks[(peaks >= lo) & (peaks < hi)]
        if len(wp) < 3:
            return np.nan
        rr = np.diff(wp.astype(float)) / fs * 1000  # convert to ms
        sd = np.diff(rr)
        return float(np.sqrt(np.mean(sd ** 2)))

    task_wins = [w for w in windows if not w["is_interval"] and not w.get("is_prefocus") and not w["is_baseline"]]
    rest_wins = [w for w in windows if w["is_interval"]]

    pairs = []
    for tw in task_wins:
        t_val = _win_rmssd(tw)
        if np.isnan(t_val):
            continue
        rw_cands = [rw for rw in rest_wins if rw["t_start"] >= tw["t_end"]]
        if rw_cands:
            rw = min(rw_cands, key=lambda r: r["t_start"])
            r_val = _win_rmssd(rw)
            if not np.isnan(r_val):
                pairs.append((t_val, r_val))
    return pairs


def lfhf_windows(peaks, fs, windows):
    """LF/HF power ratio of IBI series per window; return (task, rest) pairs.

    IBI series is interpolated to 4 Hz then Welch PSD applied.
    LF = 0.04–0.15 Hz (sympathovagal), HF = 0.15–0.40 Hz (vagal).
    """
    from scipy.signal import welch as _welch
    from scipy.interpolate import interp1d

    LF = (0.04, 0.15)
    HF = (0.15, 0.40)
    INTERP_FS = 4.0

    def _win_lfhf(w):
        lo, hi = w["t_start"] * fs, w["t_end"] * fs
        wp = peaks[(peaks >= lo) & (peaks < hi)]
        if len(wp) < 5:
            return np.nan
        t_ibi  = wp[:-1].astype(float) / fs          # onset time of each beat
        ibi_ms = np.diff(wp.astype(float)) / fs * 1000
        t_even = np.arange(t_ibi[0], t_ibi[-1], 1.0 / INTERP_FS)
        if len(t_even) < 16:
            return np.nan
        ibi_even = interp1d(t_ibi, ibi_ms, kind="linear",
                            bounds_error=False, fill_value="extrapolate")(t_even)
        nperseg = min(len(ibi_even), 128)
        f, Pxx  = _welch(ibi_even, fs=INTERP_FS, nperseg=nperseg)
        lf = np.trapezoid(Pxx[(f >= LF[0]) & (f <= LF[1])], f[(f >= LF[0]) & (f <= LF[1])])
        hf = np.trapezoid(Pxx[(f >= HF[0]) & (f <= HF[1])], f[(f >= HF[0]) & (f <= HF[1])])
        return float(lf / hf) if hf > 1e-12 else np.nan

    task_wins = [w for w in windows if not w["is_interval"] and not w.get("is_prefocus") and not w["is_baseline"]]
    rest_wins = [w for w in windows if w["is_interval"]]

    pairs = []
    for tw in task_wins:
        t_val = _win_lfhf(tw)
        if np.isnan(t_val):
            continue
        rw_cands = [rw for rw in rest_wins if rw["t_start"] >= tw["t_end"]]
        if rw_cands:
            rw = min(rw_cands, key=lambda r: r["t_start"])
            r_val = _win_lfhf(rw)
            if not np.isnan(r_val):
                pairs.append((t_val, r_val))
    return pairs


def deriv_pairs(signal, fs, windows):
    """Mean absolute first derivative per window; return (task, rest) pairs.

    High values indicate rapid signal change (responsive); low values indicate
    a flat/steady signal within the window.
    """
    deriv = np.abs(np.gradient(np.array(signal, dtype=float), 1.0 / fs))
    n = len(deriv)

    def _mean_deriv(w):
        s = max(0, int(w["t_start"] * fs))
        e = min(n, int(w["t_end"] * fs))
        seg = deriv[s:e]
        return float(np.mean(seg)) if len(seg) > 0 else np.nan

    task_wins = [w for w in windows if not w["is_interval"] and not w.get("is_prefocus") and not w["is_baseline"]]
    rest_wins = [w for w in windows if w["is_interval"]]

    pairs = []
    for tw in task_wins:
        t_val = _mean_deriv(tw)
        if np.isnan(t_val):
            continue
        rw_cands = [rw for rw in rest_wins if rw["t_start"] >= tw["t_end"]]
        if rw_cands:
            rw = min(rw_cands, key=lambda r: r["t_start"])
            r_val = _mean_deriv(rw)
            if not np.isnan(r_val):
                pairs.append((t_val, r_val))
    return pairs


def fmt_paired(label, r):
    """Format a paired_test result as a stats-table row."""
    def _f(v, d=4): return f"{v:.{d}f}" if np.isfinite(v) else "n/a"
    return [label,
            f"{_f(r['a_mean'])} ± {_f(r['a_std'])}",
            f"{_f(r['b_mean'])} ± {_f(r['b_std'])}",
            _f(r['stat'], 3),
            _f(r['p']), r['sig'], _f(r.get('r', float('nan')), 3)]


# ── Shared plot helper ────────────────────────────────────────────────────────

def shade_timeline(ax, windows, x_scale=1.0, arrow_y=-0.10, label_y=-0.20, x_max=None):
    """Colour spans + bracket arrows + labels for each task window.

    x_scale : multiply window times (1.0 = seconds, 1/60 = minutes).
    x_max   : skip annotations for windows starting at or beyond this value
               (prevents bbox expansion for short recordings).
    """
    tick_half = 0.018

    for w in windows:
        x0, x1 = w["t_start"] * x_scale, w["t_end"] * x_scale
        if x_max is not None and x0 >= x_max:
            continue
        x1_draw = min(x1, x_max) if x_max is not None else x1

        if w["is_baseline"]:
            color = WIN_COLORS["baseline"]
        elif w["is_interval"]:
            color = WIN_COLORS["rest"]
        elif w.get("is_prefocus"):
            color = WIN_COLORS["prefocus"]
        else:
            num = int(re.search(r"\d+", w["label"]).group())
            color = WIN_COLORS["task_odd"] if num % 2 == 1 else WIN_COLORS["task_even"]
        ax.axvspan(x0, x1_draw, alpha=0.35, color=color, lw=0)

        if w["is_interval"] or w.get("is_prefocus"):
            continue

        arrow_color = "#1f5fbf" if w["is_baseline"] else "#555555"
        ax.annotate("", xy=(x1_draw, arrow_y), xytext=(x0, arrow_y),
                    xycoords=("data", "axes fraction"),
                    arrowprops=dict(arrowstyle="<->", color=arrow_color, lw=1.1),
                    annotation_clip=False)
        for xc in (x0, x1_draw):
            ax.annotate("", xy=(xc, arrow_y - tick_half), xytext=(xc, arrow_y + tick_half),
                        xycoords=("data", "axes fraction"),
                        arrowprops=dict(arrowstyle="-", color=arrow_color, lw=1.1),
                        annotation_clip=False)
        mid = (x0 + x1_draw) / 2
        ax.annotate(w["label"], xy=(mid, label_y), xycoords=("data", "axes fraction"),
                    ha="center", va="top", fontsize=6.5, color=arrow_color,
                    fontweight="bold" if w["is_baseline"] else "normal",
                    annotation_clip=False)
