import argparse
import glob
import os

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from scipy.signal import welch
import pyedflib
from matplotlib.backends.backend_pdf import PdfPages
from metadata import (
    EEG_FS, EEG_CHANNELS, EEG_ALPHA, EEG_BETA, EEG_FI_WIN, EEG_FI_STEP,
    DATA_EDF_DIR, GRAPH_EEG_DIR,
    EEG_BL_DIR, BEHAVIORS_DIR, BATTERY_EDF_DIR, BATTERY_GRAPH_DIR,
)
from utils import (
    get_timeline, filter_outliers, paired_test, fi_pairs, fmt_paired,
    shade_timeline, timeline_legend, robust_sd,
    build_session_windows, generic_task_order, measure_block_durations,
    find_session_for_recording, detect_blinks, spans_to_mask, describe_blinks,
    N_ROBUST_SD,
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
    PsychoPy session must pass windows from utils.build_session_windows instead, since its
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


def run_fi_batch():
    """Original behaviour: FI charts for every EDF in the 12-block corpus."""
    os.makedirs(GRAPH_EEG_DIR, exist_ok=True)
    edf_files = sorted([
        f for f in os.listdir(DATA_EDF_DIR)
        if f.endswith('.edf') and 'Minh' not in f and '(' not in f
    ])
    for fname in edf_files:
        edf_path = os.path.join(DATA_EDF_DIR, fname)
        base = os.path.splitext(fname)[0]
        print(f"\nProcessing {fname}")
        try:
            plot_fi_timeline(edf_path, channels=EEG_CHANNELS,
                             win_sec=EEG_FI_WIN, step_sec=EEG_FI_STEP,
                             status='GOOD',
                             save_path=os.path.join(GRAPH_EEG_DIR, f"{base}_FI.png"))
        except Exception as e:
            print(f"  ERROR: {e}")


# ==============================================================================
# Processed-EEG trace figures (was plot_eeg.py / plot_eeg_windows.py)
# ==============================================================================
# The FI chart above reduces a recording to one beta/alpha ratio. These show the
# EEG the analysis actually consumes - metadata.EEG_CHANNELS, read back from the
# exported EDF - so a recording can be judged before its derived numbers are
# trusted.

#: Two channels = categorical identity, same hue for the same channel in every
#: panel. Validated categorical slots 1-2 (CVD dE 24.7 vs 8 target, normal-vision
#: dE 33.6 vs 15 floor, both >= 3:1 on the light surface).
CH_COLORS   = {"AF3": "#2a78d6", "AF4": "#eb6834"}
SHADE_ALPHA = 0.16      # recessive: the blocks are context, the trace is data
INK         = "#52514e"  # axis/grid ink, kept off pure black
ARTIFACT    = "#e34948"  # status:critical - reserved, never a series hue


def find_battery_edf(stem):
    """The EDF for one battery recording, plus the quality folder it landed in."""
    for sub in ("good", "good_denoised", "bad_denoised"):
        p = os.path.join(BATTERY_EDF_DIR, sub, stem + ".edf")
        if os.path.exists(p):
            return p, sub
    return None, None


def read_edf(path):
    with pyedflib.EdfReader(path) as f:
        labels = f.getSignalLabels()
        fs = float(f.getSampleFrequency(0))
        sig = {l: f.readSignal(i) for i, l in enumerate(labels)}
    return sig, fs


def envelope(x, fs, n_cols=4000):
    """Min/max decimation, so no sample is skipped when 405k points meet 4k pixels."""
    n = len(x)
    if n <= n_cols * 2:
        return np.arange(n) / fs, x, x
    step = int(np.ceil(n / n_cols))
    blocks = x[:(n // step) * step].reshape(-1, step)
    t = (np.arange(blocks.shape[0]) * step + step / 2) / fs
    return t, np.nanmin(blocks, axis=1), np.nanmax(blocks, axis=1)


def robust_ylim(x, pct=99.7, pad=1.15):
    finite = x[np.isfinite(x)]
    v = float(np.nanpercentile(np.abs(finite), pct)) * pad if finite.size else 1.0
    return (-v, v) if v > 0 else (-1.0, 1.0)


def band_power_window(x, fs, lo, hi):
    """Band power over one segment, reusing bandpower() with a 4 s Welch window."""
    if len(x) < int(4 * fs):
        return np.nan
    return bandpower(x, fs, lo, hi, nperseg=int(4 * fs))


def alpha_reactivity(proc, fs, windows):
    """Eyes-closed vs eyes-open relative alpha inside the baseline, per channel.

    The baseline runs eyes-open 10-70 s and eyes-closed 120-180 s of its own span,
    so this is the one built-in physiological check these recordings carry. A ratio
    at or below 1 means alpha did not rise on eye closure and nothing derived from
    the recording - least of all a beta/alpha focus index - should be trusted.
    Computed per channel: concatenating AF3 and AF4 before Welch would take the PSD
    across the splice and let the noisier channel decide the answer.
    """
    base = next((w for w in windows if w["is_baseline"]), None)
    if base is None:
        return {}

    def rel(ch, t0, t1):
        a, b = int((base["t_start"] + t0) * fs), int((base["t_start"] + t1) * fs)
        seg = proc[ch][a:b]
        tot = band_power_window(seg, fs, 2, 40)
        al = band_power_window(seg, fs, EEG_ALPHA[0], EEG_ALPHA[1])
        return al / tot if tot and np.isfinite(tot) else np.nan

    out = {}
    for ch in ("AF3", "AF4"):
        eo, ec = rel(ch, 10, 70), rel(ch, 120, 180)
        out[ch] = float(ec / eo) if eo and np.isfinite(eo) else float("nan")
    return out


def _battery_windows(csv_path):
    """(windows, title_suffix) for a battery recording, paired if possible."""
    session, note = find_session_for_recording(csv_path, BEHAVIORS_DIR)
    if session is not None:
        windows = build_session_windows(
            session["task_order"], measured=measure_block_durations(session["dir"]))
        return windows, f"session {session['session']}", note
    return (build_session_windows(generic_task_order()),
            "NO PAIRED SESSION, block labels are generic", note)


def plot_eeg_traces(stem, edf_path, windows, title, save_path,
                    zoom_at=None, zoom_len=8.0, blink_sd=None):
    """Three panels: each channel across the session, then a legible zoom."""
    import matplotlib.gridspec as gridspec

    sig, fs = read_edf(edf_path)
    proc = {ch: sig[f"{ch}_processed"] for ch in ("AF3", "AF4")}
    dur = len(proc["AF3"]) / fs
    blocks = [w for w in windows
              if not w["is_interval"] and not w.get("is_prefocus")]

    if zoom_at is None:
        first = next((w for w in blocks if not w["is_baseline"]), None)
        zoom_at = (first["t_start"] + first["t_end"]) / 2 if first else dur / 2
    zoom_at = max(0.0, min(float(zoom_at), max(0.0, dur - zoom_len)))

    alpha = alpha_reactivity(proc, fs, windows)
    ok = all(np.isfinite(v) and v > 1.15 for v in alpha.values()) if alpha else False
    banner = ("eyes-closed alpha reactivity  "
              + "  ".join(f"{ch} {v:.2f}x" for ch, v in alpha.items())
              + ("   -> PASS, alpha rises on eye closure" if ok else
                 "   -> FAIL: alpha does not rise on eye closure, so beta/alpha "
                 "here is not interpretable as focus"))

    kw = {} if blink_sd is None else dict(n_robust_sd=blink_sd)
    spans, binfo = detect_blinks([proc["AF3"], proc["AF4"]], fs,
                                 windows=windows, skip_baseline=True, **kw)

    fig = plt.figure(figsize=(20, 11))
    fig.suptitle(f"{title}   -   PROCESSED EEG  ({', '.join(EEG_CHANNELS)})",
                 fontsize=11, fontweight="bold")
    fig.text(0.5, 0.945, banner, ha="center", fontsize=9.5, fontweight="bold",
             color="#14532d" if ok else "#7f1d1d")
    gs = gridspec.GridSpec(3, 1, height_ratios=[3, 3, 2.6], hspace=0.75)

    for i, ch in enumerate(("AF3", "AF4")):
        ax = fig.add_subplot(gs[i])
        x = proc[ch]
        t, lo, hi = envelope(x, fs)
        shade_timeline(ax, windows, x_scale=1.0, x_max=dur,
                       alpha=SHADE_ALPHA, annotate=(i == 1))
        ax.fill_between(t, lo, hi, color=CH_COLORS[ch], lw=0, zorder=3)
        for a, b in spans:
            ax.axvspan(a, b, ymin=0.94, ymax=1.0, color=ARTIFACT, lw=0, zorder=5)
        ax.set_xlim(0, dur)
        ylo, yhi = robust_ylim(x)
        ax.set_ylim(ylo, yhi)
        off = float(np.mean(np.abs(x) > yhi)) * len(x) / fs
        ax.set_title(f"{ch}_processed        robust SD {robust_sd(x):.0f} uV   "
                     f"(RMS {np.std(x):.0f} uV - inflated by transients)        "
                     f"range {np.nanmin(x):,.0f} ... {np.nanmax(x):,.0f} uV, "
                     f"{off:.1f} s clipped off-screen",
                     fontsize=9, color="#0b0b0b", loc="left")
        ax.set_ylabel("uV", fontsize=8, color=INK)
        if i == 1:
            ax.set_xlabel("Time (s)", fontsize=8, color=INK)
        else:
            ax.tick_params(labelbottom=False)
        ax.grid(True, axis="y", alpha=0.18, lw=0.6, zorder=0)
        ax.tick_params(labelsize=7, colors=INK)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        for s in ("left", "bottom"):
            ax.spines[s].set_color(INK)
            ax.spines[s].set_linewidth(0.6)

    ax3 = fig.add_subplot(gs[2])
    s0, s1 = int(zoom_at * fs), int((zoom_at + zoom_len) * fs)
    tz = np.arange(s0, min(s1, len(proc["AF3"]))) / fs
    for ch in ("AF3", "AF4"):
        seg = proc[ch][s0:s1][:len(tz)]
        ax3.plot(tz, seg, lw=1.0, color=CH_COLORS[ch], zorder=4,
                 label=f"{ch}_processed", solid_capstyle="round")
        ax3.annotate(ch, xy=(tz[-1], seg[-1]), xytext=(4, 0),
                     textcoords="offset points", va="center", fontsize=8,
                     fontweight="bold", color=CH_COLORS[ch], annotation_clip=False)
    label = next((w["label"] for w in windows
                  if w["t_start"] <= zoom_at < w["t_end"]), "?")
    ax3.set_xlim(tz[0], tz[-1])
    ax3.set_title(f"Zoom - {zoom_len:g} s from t={zoom_at:.0f} s, inside \u201c{label}\u201d",
                  fontsize=9, color="#0b0b0b", loc="left")
    ax3.set_xlabel("Time (s)", fontsize=8, color=INK)
    ax3.set_ylabel("uV", fontsize=8, color=INK)
    ax3.legend(loc="upper right", fontsize=7, ncol=2, frameon=False)
    ax3.grid(True, axis="y", alpha=0.18, lw=0.6, zorder=0)
    ax3.tick_params(labelsize=7, colors=INK)
    for s in ("top", "right"):
        ax3.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax3.spines[s].set_color(INK)
        ax3.spines[s].set_linewidth(0.6)

    handles = [mpatches.Patch(facecolor=c, alpha=0.5, label=l)
               for c, l in timeline_legend(windows)]
    handles.append(mpatches.Patch(
        facecolor=ARTIFACT,
        label=f"blink/ocular span ({binfo['n_spans']}, "
              f"{binfo['excluded_frac'] * 100:.0f}% of time; rug at panel top)"))
    fig.legend(handles=handles, loc="lower center", ncol=len(handles),
               fontsize=8, framealpha=0.8, bbox_to_anchor=(0.5, 0.005))
    plt.subplots_adjust(bottom=0.09)

    os.makedirs(os.path.dirname(save_path) or ".", exist_ok=True)
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved -> {save_path}")
    return dict(stem=stem, fs=fs, dur=dur,
                rms={c: float(np.std(proc[c])) for c in proc},
                robust={c: robust_sd(proc[c]) for c in proc},
                alpha_ratio=alpha, alpha_pass=ok, blink=binfo)


# ==============================================================================
# Windowed strip chart (was plot_eeg_windows.py)
# ==============================================================================
# A 28-minute recording on one axis is ~340 samples per pixel, so a full-session
# plot shows only the envelope and reads as a solid chunked band. Individual
# waveforms need roughly 20 s per axis. This renders the recording the way EEG is
# actually read: short windows at fixed scale, stacked down the page, paginated.

def _block_at(windows, t):
    for w in windows:
        if w["t_start"] <= t < w["t_end"]:
            return "rest" if w["is_interval"] else w["label"]
    return "—"


def _draw_window_page(proc, fs, spans, windows, t0, win, strips, scale,
                      title, subtitle):
    """One page of `strips` consecutive windows of `win` seconds each."""
    fig, axes = plt.subplots(strips, 1, figsize=(19, 1.15 * strips + 1.6))
    if strips == 1:
        axes = [axes]
    fig.suptitle(title, fontsize=11, fontweight="bold", y=0.995)
    fig.text(0.5, 0.972, subtitle, ha="center", fontsize=8.5, color=INK)

    offset = scale                 # AF3 up, AF4 down, so the traces never cross
    n = len(proc["AF3"])
    for k, ax in enumerate(axes):
        a, b = t0 + k * win, t0 + (k + 1) * win
        s0, s1 = int(a * fs), int(min(b * fs, n))
        if s0 >= n:
            ax.axis("off")
            continue
        t = np.arange(s0, s1) / fs
        for sa, sb in spans:
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
        ax.annotate(f"{a:.0f}–{b:.0f} s   {_block_at(windows, (a + b) / 2)}",
                    xy=(0.002, 0.97), xycoords="axes fraction", va="top",
                    fontsize=7.5, color="#0b0b0b", fontweight="bold")

    axes[-1].set_xlabel("Time (s)", fontsize=8.5, color=INK)
    fig.legend(handles=[mpatches.Patch(
        facecolor=ARTIFACT, alpha=0.4,
        label="blink / ocular span (excluded from statistics; baseline not screened)")],
        loc="lower center", ncol=1, fontsize=8, frameon=False,
        bbox_to_anchor=(0.5, 0.002))
    fig.tight_layout(rect=(0, 0.02, 1, 0.965))
    return fig


def plot_eeg_windows(stem, edf_path, windows, who, graph_dir,
                     win=20.0, strips=12, scale=None, t_from=0.0, t_to=None,
                     png_page=None, blink_sd=None):
    """Multi-page strip chart for one recording. Returns the PDF path."""
    sig, fs = read_edf(edf_path)
    proc = {ch: sig[f"{ch}_processed"] for ch in ("AF3", "AF4")}

    kw = {} if blink_sd is None else dict(n_robust_sd=blink_sd)
    spans, binfo = detect_blinks([proc["AF3"], proc["AF4"]], fs,
                                 windows=windows, skip_baseline=True, **kw)
    print(f"  {describe_blinks(binfo)}")

    scale = scale or 6.0 * max(robust_sd(proc[ch]) for ch in proc)
    dur = len(proc["AF3"]) / fs
    t_end = min(t_to, dur) if t_to else dur
    page_len = win * strips
    n_pages = int(np.ceil((t_end - t_from) / page_len))
    print(f"  {win:g} s strips x {strips} per page -> {n_pages} pages, "
          f"±{scale:.0f} µV per channel")

    if png_page is None:                 # default: first page holding a task block
        first_task = next((w["t_start"] for w in windows
                           if not w["is_baseline"] and not w["is_interval"]
                           and not w.get("is_prefocus")), t_from)
        png_page = int((first_task - t_from) // page_len) + 1

    os.makedirs(graph_dir, exist_ok=True)
    pdf_path = os.path.join(graph_dir, stem + "_windows.pdf")
    with PdfPages(pdf_path) as pdf:
        for pg in range(n_pages):
            t0 = t_from + pg * page_len
            fig = _draw_window_page(
                proc, fs, spans, windows, t0, win, strips, scale,
                f"{stem}   —   {who}   —   {', '.join(EEG_CHANNELS)}",
                f"page {pg + 1}/{n_pages}   ·   {t0:.0f}–{min(t0 + page_len, t_end):.0f} s"
                f"   ·   ±{scale:.0f} µV per channel   ·   "
                f"{binfo['n_spans']} ocular spans, {binfo['excluded_frac'] * 100:.1f}% of time")
            pdf.savefig(fig, dpi=110)
            if pg + 1 == png_page:
                png = os.path.join(graph_dir, f"{stem}_windows_p{pg + 1}.png")
                fig.savefig(png, dpi=110, bbox_inches="tight")
                print(f"  Saved -> {png}")
            plt.close(fig)
    print(f"  Saved -> {pdf_path}  ({n_pages} pages)")
    return pdf_path


def run_battery_plots(mode, only=None, graph_dir=None, **kw):
    """Trace figures and/or strip charts for the battery recordings in eeg_bl/."""
    graph_dir = graph_dir or BATTERY_GRAPH_DIR
    paths = sorted(glob.glob(os.path.join(EEG_BL_DIR, "*.csv")))
    if only:
        paths = [p for p in paths if only in os.path.basename(p)]
    if not paths:
        print(f"No recordings in {EEG_BL_DIR}")
        return []

    rows = []
    for csv_path in paths:
        stem = os.path.splitext(os.path.basename(csv_path))[0]
        edf_path, quality = find_battery_edf(stem)
        print(f"\n{stem}")
        if edf_path is None:
            print("  no EDF — run run_pipeline.py --battery first")
            continue
        print(f"  EDF: {quality}/")
        windows, who, note = _battery_windows(csv_path)
        print(f"  pairing: {note}")

        if mode in ("traces", "both"):
            rows.append(plot_eeg_traces(
                stem, edf_path, windows, f"{stem}   —   {who}",
                os.path.join(graph_dir, stem + "_eeg.png"),
                zoom_at=kw.get("zoom_at"), zoom_len=kw.get("zoom_len", 8.0),
                blink_sd=kw.get("blink_sd")))
        if mode in ("windows", "both"):
            plot_eeg_windows(stem, edf_path, windows, who, graph_dir,
                             win=kw.get("win", 20.0), strips=kw.get("strips", 12),
                             scale=kw.get("scale"), t_from=kw.get("t_from", 0.0),
                             t_to=kw.get("t_to"), png_page=kw.get("png_page"),
                             blink_sd=kw.get("blink_sd"))

    if rows:
        print(f"\n{'=' * 78}\nProcessed-EEG summary\n{'=' * 78}")
        for r in rows:
            a = "  ".join(f"{c} {v:.2f}x" for c, v in r["alpha_ratio"].items())
            print(f"  {r['stem'][:30]:30s} robust SD "
                  f"AF3 {r['robust']['AF3']:6.1f} AF4 {r['robust']['AF4']:6.1f} µV "
                  f"(RMS {r['rms']['AF3']:.0f}/{r['rms']['AF4']:.0f})  alpha {a}  "
                  f"{'PASS' if r['alpha_pass'] else 'FAIL'}")
            print(f"      {describe_blinks(r['blink'])}")
    return rows


def _parse_args():
    p = argparse.ArgumentParser(
        description="EEG Focus-Index charts, plus processed-trace and strip-chart "
                    "views of the 7-block battery recordings.")
    p.add_argument("--traces", action="store_true",
                   help="processed-EEG trace figure per battery recording")
    p.add_argument("--windows", action="store_true",
                   help="paginated strip chart per battery recording")
    p.add_argument("--only", default=None, help="substring filter on the filename")
    p.add_argument("--blink-sd", type=float, default=None, dest="blink_sd",
                   help=f"blink threshold in robust SDs (default {N_ROBUST_SD}); "
                        f"lower is more sensitive")
    p.add_argument("--win", type=float, default=20.0, help="seconds per strip")
    p.add_argument("--strips", type=int, default=12, help="strips per page")
    p.add_argument("--scale", type=float, default=None,
                   help="µV half-height per channel (default 6x robust SD)")
    p.add_argument("--from", dest="t_from", type=float, default=0.0)
    p.add_argument("--to", dest="t_to", type=float, default=None)
    p.add_argument("--png-page", type=int, default=None, dest="png_page")
    p.add_argument("--zoom-at", type=float, default=None, dest="zoom_at")
    p.add_argument("--zoom-len", type=float, default=8.0, dest="zoom_len")
    return p.parse_args()


if __name__ == '__main__':
    args = _parse_args()
    if args.traces or args.windows:
        mode = "both" if (args.traces and args.windows) else (
            "traces" if args.traces else "windows")
        run_battery_plots(mode, only=args.only, blink_sd=args.blink_sd,
                          win=args.win, strips=args.strips, scale=args.scale,
                          t_from=args.t_from, t_to=args.t_to,
                          png_page=args.png_page, zoom_at=args.zoom_at,
                          zoom_len=args.zoom_len)
    else:
        run_fi_batch()          # unchanged default: the 12-block corpus
