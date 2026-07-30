import os
import numpy as np
if not hasattr(np, "trapezoid"):        # NumPy < 2.0 exposes this as np.trapz
    np.trapezoid = np.trapz
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from scipy.signal import welch
import pyedflib
from metadata import (
    EEG_FS, EEG_CHANNELS, EEG_ALPHA, EEG_BETA, EEG_FI_WIN, EEG_FI_STEP,
    DATA_EDF_DIR, GRAPH_EEG_DIR,
)
from utils import (
    get_timeline, filter_outliers, paired_test, fi_pairs, fmt_paired,
    shade_timeline, timeline_legend,
)

# ── Band power ────────────────────────────────────────────────────────────────

def bandpower(x, fs, lo, hi, nperseg):
    from scipy.signal import welch
    f, Pxx = welch(x, fs=fs, nperseg=nperseg)
    mask = (f >= lo) & (f <= hi)
    return float(np.trapezoid(Pxx[mask], f[mask])) if mask.any() else 1e-12


def compute_fi(x, fs, nperseg):
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
    t_centers = (starts + win / 2) / fs
    fi        = np.zeros((n_ch, len(starts)))

    for j, s in enumerate(starts):
        for i in range(n_ch):
            fi[i, j] = compute_fi(data[i, s:s + win], fs, nperseg)

    return t_centers, fi

# ── Plot ──────────────────────────────────────────────────────────────────────

def plot_fi_timeline(edf_path,
                     channels=('AF3', 'AF4'),
                     win_sec=5,
                     step_sec=1,
                     status='GOOD',
                     save_path=None,
                     windows=None,
                     title=None):
    """FI (β/α) timeline for one EDF, with block shading and a task-vs-rest test.

    `windows` overrides the timeline; left as None it is recovered from the
    filename's F0-F1-… order, which suits the 12-block corpus. A randomized
    PsychoPy session must pass windows from session_timeline instead, since its
    block order lives in metadata.json rather than in the filename.
    """
    data, ch_labels, fs = load_eeg_from_edf(edf_path, channels)
    print(f"Loaded {ch_labels} @ {fs} Hz, {data.shape[1]} samples "
          f"({data.shape[1]/fs:.1f} s)")

    if windows is None:
        windows = get_timeline(edf_path)
    t_centers, fi = compute_fi_timeline(data, fs, win_sec=win_sec, step_sec=step_sec)

    if len(t_centers) == 0:
        print(f"  Skipping {os.path.basename(edf_path)} — too short for FI window")
        return None, None, windows

    fi_avg = filter_outliers(fi.mean(axis=0))
    t_min  = t_centers / 60
    x_max  = t_min[-1]

    smooth_window = max(1, int(60 / step_sec))
    fi_smooth     = np.convolve(fi_avg, np.ones(smooth_window) / smooth_window, mode='same')

    import matplotlib.gridspec as gridspec
    fig = plt.figure(figsize=(20, 8))
    gs  = gridspec.GridSpec(2, 1, height_ratios=[3, 1.4], hspace=0.55)
    ax  = fig.add_subplot(gs[0])

    shade_timeline(ax, windows, x_scale=1 / 60, x_max=x_max)

    ax.plot(t_min, fi_avg,    color='#b3a2cc', lw=0.5, alpha=0.45, label='FI = β/α')
    ax.plot(t_min, fi_smooth, color='#4a2a6a', lw=1.8, alpha=0.95, label='FI smoothed')

    first_mean = True
    for w in windows:
        if w['is_interval'] or w.get('is_prefocus'):
            continue
        mask = (t_centers >= w['t_start']) & (t_centers < w['t_end'])
        if not mask.any():
            continue
        m_fi  = fi_avg[mask].mean()
        sd_fi = fi_avg[mask].std()
        x0, x1 = w['t_start'] / 60, w['t_end'] / 60
        ax.errorbar((x0 + x1) / 2, m_fi, yerr=sd_fi, fmt='o', ms=4, color='black',
                    capsize=5, capthick=1.5, elinewidth=1.5, zorder=6,
                    label='Task mean ± SD' if first_mean else None)
        first_mean = False

    time_ticks = np.arange(0, x_max + 1, 5)
    ax.set_xticks(time_ticks)
    ax.set_xticklabels([str(int(t)) for t in time_ticks], fontsize=8)
    ax.set_xlabel('Time (mins)', fontsize=10)
    ax.set_xlim(0, x_max)
    ax.set_ylim(0, 10)
    ax.set_ylabel('FI = β/α', fontsize=10)

    basename = os.path.splitext(os.path.basename(edf_path))[0]
    ax.set_title(f'{title or basename} [{status}]  —  FI = β/α over time', fontsize=10)

    legend_handles = [
        mpatches.Patch(facecolor=color, label=label)
        for color, label in timeline_legend(windows)
    ]
    line_handles, line_labels_list = ax.get_legend_handles_labels()
    keep = [h for h, l in zip(line_handles, line_labels_list)
            if l in ('FI = β/α', 'FI smoothed', 'Task mean ± SD')]
    ax.legend(handles=legend_handles + keep, loc='upper right', fontsize=8, framealpha=0.8)
    ax.grid(True, alpha=0.2)

    # ── Stats table — paired t-test ───────────────────────────────────────────
    tr_pairs = fi_pairs(t_centers, fi_avg, windows)
    stats_rows = [
        fmt_paired('Task vs Rest', paired_test(tr_pairs)),
    ]

    ax_t = fig.add_subplot(gs[1])
    ax_t.axis('off')
    ax_t.set_title(
        'FI (β/α) — Paired t-test (individual data points, task vs adjacent rest)',
        fontsize=9, pad=4,
    )
    col_labels = ['Comparison', 'Task mean ± SD', 'Control mean ± SD',
                  't statistic', 'p-value', 'Sig.', 'Effect r']
    tbl = ax_t.table(cellText=stats_rows, colLabels=col_labels, loc='center', cellLoc='center')
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)
    tbl.scale(1, 1.6)
    for c in range(len(col_labels)):
        tbl[0, c].set_text_props(fontweight='bold')
    for ri, row in enumerate(stats_rows, start=1):
        cell = tbl[ri, 5]
        if row[5] in ('*', '**', '***'): cell.set_facecolor('#d4edda')
        elif row[5] == 'ns':             cell.set_facecolor('#f8d7da')

    plt.tight_layout()
    plt.subplots_adjust(bottom=0.18)

    if save_path:
        plt.savefig(save_path, dpi=150, bbox_inches='tight')
        print(f"  Saved → {save_path}")
    else:
        plt.show()
    plt.close(fig)

    return t_centers, fi_avg, windows


# ── Run all subjects ──────────────────────────────────────────────────────────

if __name__ == '__main__':
    os.makedirs(GRAPH_EEG_DIR, exist_ok=True)

    edf_files = sorted([
        f for f in os.listdir(DATA_EDF_DIR)
        if f.endswith('.edf')
        and 'Minh' not in f
        and '(' not in f
    ])

    for fname in edf_files:
        edf_path  = os.path.join(DATA_EDF_DIR, fname)
        base      = os.path.splitext(fname)[0]
        save_path = os.path.join(GRAPH_EEG_DIR, f"{base}_FI.png")
        print(f"\nProcessing {fname}")
        try:
            plot_fi_timeline(
                edf_path,
                channels=EEG_CHANNELS,
                win_sec=EEG_FI_WIN,
                step_sec=EEG_FI_STEP,
                status='GOOD',
                save_path=save_path,
            )
        except Exception as e:
            print(f"  ERROR: {e}")
