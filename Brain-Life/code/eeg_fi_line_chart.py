import re
import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from scipy.signal import welch
import pyedflib
from metadata import (
    TASK_DUR, EEG_REST_DUR as REST_DUR, PREFOCUS_DUR,
    EEG_CHANNELS, EEG_ALPHA, EEG_BETA, EEG_FI_WIN, EEG_FI_STEP,
    DATA_EDF_DIR, GRAPH_EEG_DIR,
)

# ── Timeline ──────────────────────────────────────────────────────────────────
# Loaded from metadata.py

def parse_task_order(edf_path):
    m = re.search(r'(F\d+(?:-F\d+)+)', os.path.basename(edf_path))
    return m.group(1).split('-') if m else [f'F{i}' for i in range(13)]

def build_windows(task_labels):
    windows, t = [], 0
    for i, label in enumerate(task_labels):
        windows.append(dict(label=label, t_start=t, t_end=t + TASK_DUR,
                            is_baseline=(i == 0), is_interval=False, is_prefocus=False))
        t += TASK_DUR
        if i < len(task_labels) - 1:
            windows.append(dict(label='rest', t_start=t, t_end=t + REST_DUR,
                                is_baseline=False, is_interval=True, is_prefocus=False))
            t += REST_DUR
            windows.append(dict(label='pre-focus', t_start=t, t_end=t + PREFOCUS_DUR,
                                is_baseline=False, is_interval=False, is_prefocus=True))
            t += PREFOCUS_DUR
    return windows

def get_timeline(edf_path):
    return build_windows(parse_task_order(edf_path))

# ── Band power ────────────────────────────────────────────────────────────────
def bandpower(x, fs, lo, hi, nperseg):
    f, Pxx = welch(x, fs=fs, nperseg=nperseg)
    mask = (f >= lo) & (f <= hi)
    return float(np.trapz(Pxx[mask], f[mask])) if mask.any() else 1e-12

def compute_fi(x, fs, nperseg):
    """Focus Index = β / α"""
    beta  = bandpower(x, fs, EEG_BETA[0],  EEG_BETA[1],  nperseg)
    alpha = bandpower(x, fs, EEG_ALPHA[0], EEG_ALPHA[1], nperseg)
    return beta / (alpha + 1e-12)

# ── Load EDF ──────────────────────────────────────────────────────────────────
def load_eeg_from_edf(edf_path, channels=('AF3', 'AF4')):
    with pyedflib.EdfReader(edf_path) as f:
        labels  = f.getSignalLabels()
        fs      = f.getSampleFrequency(0)
        indices = [i for i, l in enumerate(labels)
                   if any(ch.lower() == l.lower() for ch in channels)]
        if not indices:
            raise ValueError(f"Channels {channels} not found. Available: {labels}")
        data       = np.array([f.readSignal(i) for i in indices], dtype=np.float64)
        sel_labels = [labels[i] for i in indices]
    return data, sel_labels, fs

# ── Sliding-window FI ─────────────────────────────────────────────────────────
def compute_fi_timeline(data, fs, win_sec=5, step_sec=1):
    win     = int(win_sec * fs)
    step    = int(step_sec * fs)
    nperseg = min(win, 4 * int(fs))
    n_ch, n_samp = data.shape

    starts    = np.arange(0, n_samp - win + 1, step)
    t_centers = (starts + win / 2) / fs   # seconds
    fi        = np.zeros((n_ch, len(starts)))

    for j, s in enumerate(starts):
        for i in range(n_ch):
            fi[i, j] = compute_fi(data[i, s:s + win], fs, nperseg)

    return t_centers, fi

# ── Plot ──────────────────────────────────────────────────────────────────────
_WIN_COLORS = {
    'baseline':  '#7ab8e8',
    'task_odd':  '#72c472',
    'task_even': '#72c472',
    'rest':      '#b0b0b0',
    'prefocus':  '#f5d76e',
}

def plot_fi_timeline(edf_path,
                     channels=('AF3', 'AF4'),
                     win_sec=5,
                     step_sec=1,
                     status='GOOD',
                     save_path=None):
    """
    Plots FI = β/α as a continuous line chart with task-window shading.

    Args:
        edf_path:   Path to .edf file. Filename must contain task order e.g. F0-F1-F2...
        channels:   EEG channels to average for FI.
        win_sec:    Sliding window length (s) for Welch PSD.
        step_sec:   Step between windows (s).
        status:     Quality label shown in title, e.g. 'GOOD' or 'BAD'.
        save_path:  File path to save the figure, or None to show interactively.
    """
    data, ch_labels, fs = load_eeg_from_edf(edf_path, channels)
    print(f"Loaded {ch_labels} @ {fs} Hz, {data.shape[1]} samples "
          f"({data.shape[1]/fs:.1f} s)")

    windows       = get_timeline(edf_path)
    t_centers, fi = compute_fi_timeline(data, fs, win_sec=win_sec, step_sec=step_sec)
    fi_avg        = fi.mean(axis=0)
    t_min         = t_centers / 60   # seconds → minutes

    # --- rolling average smooth line ---
    smooth_window = max(1, int(60 / step_sec))   # ~60 s worth of FI samples
    kernel        = np.ones(smooth_window) / smooth_window
    fi_smooth     = np.convolve(fi_avg, kernel, mode='same')

    import matplotlib.gridspec as gridspec
    fig = plt.figure(figsize=(20, 8))
    gs  = gridspec.GridSpec(2, 1, height_ratios=[3, 1.4], hspace=0.55)
    ax  = fig.add_subplot(gs[0])

    # --- background shading ---
    for w in windows:
        if w['is_baseline']:
            color = _WIN_COLORS['baseline']
        elif w['is_interval']:
            color = _WIN_COLORS['rest']
        elif w['is_prefocus']:
            color = _WIN_COLORS['prefocus']
        else:
            label_num = int(re.search(r'\d+', w['label']).group())
            color = _WIN_COLORS['task_odd'] if label_num % 2 == 1 else _WIN_COLORS['task_even']
        ax.axvspan(w['t_start'] / 60, w['t_end'] / 60, alpha=0.45, color=color, lw=0)

    # --- raw FI line (faint background) ---
    ax.plot(t_min, fi_avg, color='#b3a2cc', lw=0.5, alpha=0.45, label='FI = β/α')

    # --- smoothed FI line ---
    ax.plot(t_min, fi_smooth, color='#4a2a6a', lw=1.8, alpha=0.95, label='FI smoothed')

    # --- per-task mean line ---
    first_mean = True
    for w in windows:
        if w['is_interval'] or w['is_prefocus']:
            continue
        mask = (t_centers >= w['t_start']) & (t_centers < w['t_end'])
        if not mask.any():
            continue
        mean_fi = fi_avg[mask].mean()
        ax.hlines(mean_fi, w['t_start'] / 60, w['t_end'] / 60,
                  colors='red', linewidths=2.5, zorder=4,
                  label='Task mean FI' if first_mean else None)
        first_mean = False

    # --- x-axis: numeric time ticks (primary) ---
    total_min = t_min[-1]
    time_ticks = np.arange(0, total_min + 1, 5)
    ax.set_xticks(time_ticks)
    ax.set_xticklabels([str(int(t)) for t in time_ticks], fontsize=8)
    ax.set_xlabel('Time (mins)', fontsize=10)

    # --- bracket double-arrows spanning each task window (below axis) ---
    for w in windows:
        if w['is_interval'] or w['is_prefocus']:
            continue
        x0 = w['t_start'] / 60
        x1 = w['t_end'] / 60
        arrow_color = '#1f5fbf' if w['is_baseline'] else '#444444'
        y = -0.06   # axes fraction below the x-axis
        # double-headed arrow
        ax.annotate('', xy=(x1, y), xytext=(x0, y),
                    xycoords=('data', 'axes fraction'),
                    arrowprops=dict(arrowstyle='<->', color=arrow_color, lw=1.2))
        # end-cap ticks
        for xc in (x0, x1):
            ax.annotate('', xy=(xc, y - 0.018), xytext=(xc, y + 0.018),
                        xycoords=('data', 'axes fraction'),
                        arrowprops=dict(arrowstyle='-', color=arrow_color, lw=1.2))

    # --- task labels as a second row below the brackets ---
    for w in windows:
        if w['is_interval'] or w['is_prefocus']:
            continue
        mid_min = (w['t_start'] + w['t_end']) / 2 / 60
        label_color = '#1f5fbf' if w['is_baseline'] else '#333333'
        ax.annotate(w['label'],
                    xy=(mid_min, 0), xycoords=('data', 'axes fraction'),
                    xytext=(0, -38), textcoords='offset points',
                    ha='center', va='top', fontsize=8,
                    color=label_color,
                    fontweight='bold' if w['is_baseline'] else 'normal')

    # --- y-axis ---
    ax.set_ylabel('FI = β/α', fontsize=10)

    # --- title ---
    basename = os.path.splitext(os.path.basename(edf_path))[0]
    ax.set_title(f'{basename} [{status}]  —  FI = β/α over time', fontsize=10)

    # --- legend with background patches ---
    legend_handles = [
        mpatches.Patch(facecolor=_WIN_COLORS['baseline'],  label='Baseline (F0, 120s)'),
        mpatches.Patch(facecolor=_WIN_COLORS['task_odd'],  label='Task (odd, 120s)'),
        mpatches.Patch(facecolor=_WIN_COLORS['task_even'], label='Task (even, 120s)'),
        mpatches.Patch(facecolor=_WIN_COLORS['rest'],      label='Rest (50s)'),
        mpatches.Patch(facecolor=_WIN_COLORS['prefocus'],  label='Pre-focus (10s)'),
    ]
    line_handles, line_labels = ax.get_legend_handles_labels()
    keep = [h for h, l in zip(line_handles, line_labels)
            if l in ('FI = β/α', 'FI smoothed', 'Task mean FI')]
    ax.legend(handles=legend_handles + keep,
              loc='upper right', fontsize=8, framealpha=0.8)

    ax.grid(True, alpha=0.2)
    ax.set_xlim(0, t_min[-1] + step_sec / 60)

    # ── Statistics table (panel 2) ────────────────────────────────────────────
    from scipy.stats import mannwhitneyu, norm

    task_segs, rest_segs, pre_segs = [], [], []
    for w in windows:
        mask = (t_centers >= w['t_start']) & (t_centers < w['t_end'])
        if not mask.any():
            continue
        seg = fi_avg[mask]
        if w['is_prefocus']:
            pre_segs.append(seg)
        elif w['is_baseline'] or w['is_interval']:
            rest_segs.append(seg)
        else:
            task_segs.append(seg)

    def _mw(a_segs, b_segs):
        a_vals = [float(np.mean(s)) for s in a_segs if len(s) > 0]
        b_vals = [float(np.mean(s)) for s in b_segs if len(s) > 0]
        out = {'a_mean': np.nanmean(a_vals) if a_vals else np.nan,
               'a_std':  np.nanstd(a_vals)  if a_vals else np.nan,
               'b_mean': np.nanmean(b_vals) if b_vals else np.nan,
               'b_std':  np.nanstd(b_vals)  if b_vals else np.nan,
               'U': np.nan, 'p': np.nan, 'sig': 'n/a', 'r': np.nan}
        if len(a_vals) >= 2 and len(b_vals) >= 2:
            try:
                U, p = mannwhitneyu(a_vals, b_vals, alternative='two-sided')
                z = abs(norm.ppf(p / 2)) if 0 < p < 1 else 0.0
                out.update({'U': U, 'p': p,
                            'sig': '***' if p < 0.001 else '**' if p < 0.01 else '*' if p < 0.05 else 'ns',
                            'r': z / np.sqrt(len(a_vals) + len(b_vals))})
            except Exception:
                pass
        return out

    def _f(v, d=4): return f'{v:.{d}f}' if not np.isnan(v) else 'n/a'

    comparisons = [
        ('Task vs Rest',      _mw(task_segs, rest_segs)),
        ('Task vs Pre-focus', _mw(task_segs, pre_segs)),
        ('Rest vs Pre-focus', _mw(rest_segs, pre_segs)),
    ]
    rows = [[comp,
             f"{_f(s['a_mean'])} ± {_f(s['a_std'])}",
             f"{_f(s['b_mean'])} ± {_f(s['b_std'])}",
             _f(s['U'], 0) if not np.isnan(s['U']) else 'n/a',
             _f(s['p'])    if not np.isnan(s['p']) else 'n/a',
             s['sig'],
             _f(s['r'], 3) if not np.isnan(s['r']) else 'n/a']
            for comp, s in comparisons]

    ax_t = fig.add_subplot(gs[1])
    ax_t.axis('off')
    ax_t.set_title('FI (β/α) — Mann-Whitney U (two-sided)', fontsize=9, pad=4)
    col_labels = ['Comparison', 'Group A mean ± SD', 'Group B mean ± SD', 'U', 'p-value', 'Sig.', 'Effect r']
    tbl = ax_t.table(cellText=rows, colLabels=col_labels, loc='center', cellLoc='center')
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.6)
    for c in range(len(col_labels)):
        tbl[0, c].set_text_props(fontweight='bold')
    for ri, row in enumerate(rows, start=1):
        cell = tbl[ri, 5]
        if row[5] in ('*', '**', '***'): cell.set_facecolor('#d4edda')
        elif row[5] == 'ns':             cell.set_facecolor('#f8d7da')

    plt.tight_layout()
    plt.subplots_adjust(bottom=0.18)

    if save_path:
        plt.savefig(save_path, dpi=150)
        print(f"Saved → {save_path}")
    else:
        plt.show()

    return t_centers, fi_avg, windows


# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    edf_path  = os.path.join(DATA_EDF_DIR, "moon_24_16_14_F0-F1-F2-F3-F4-F5-F6-F7-F8-F9-F10-F11-F12.edf")
    save_path = os.path.join(GRAPH_EEG_DIR, "moon_24_16_14_eeg_fi.png")
    os.makedirs(GRAPH_EEG_DIR, exist_ok=True)

    plot_fi_timeline(
        edf_path,
        channels=EEG_CHANNELS,
        win_sec=EEG_FI_WIN,
        step_sec=EEG_FI_STEP,
        status='GOOD',
        save_path=save_path,
    )