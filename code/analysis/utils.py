"""
utils.py — shared processing and plotting helpers for the Brain-Life pipeline.

All modality-specific analysis files import from here so logic is defined once.
"""

import csv
import glob
import json
import os
import re
from datetime import datetime, timedelta

import numpy as np
if not hasattr(np, "trapezoid"):        # NumPy < 2.0 exposes this as np.trapz
    np.trapezoid = np.trapz
from scipy.signal import butter, sosfiltfilt, welch
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


def display_stem(stem, all_stems=None):
    """Short, honest name for an output figure: just the subject.

    Brain-Life names every export `<subject>_<day>_<HH>_<MM>_F0-F1-…-F12`, where the
    trailing token is the block order from the DEVICE's own configuration. For the
    12-block corpus that token is true, and `parse_task_order` reads the timeline
    straight off it. For a battery recording it is a lie — it claims 13 blocks where
    the session ran 7, and the real, randomized order lives in the session's
    metadata.json. Carrying a wrong order in the name of every figure invites
    someone to trust it, so figure filenames drop it, along with the recording
    clock time, leaving `ban`, `minhanh`.

    The order is NOT lost: every figure still shows the true block order on its
    ruler, and the title names the session it came from. The EDF also keeps the full
    original name so it still matches its source CSV.

    Pass `all_stems` (every recording being written to the same folder) and the
    timestamp is kept for any subject that appears more than once — two sessions
    from one person must not quietly overwrite each other's figures.
    """
    def _short(s):
        s = re.sub(r"_(?:F\d+|B)(?:-(?:F\d+|B))+$", "", s)      # block-order token
        return re.sub(r"_\d{1,2}_\d{1,2}_\d{2}$", "", s)         # _day_HH_MM
    short = _short(stem)
    if all_stems:
        clashes = [s for s in all_stems if _short(s) == short]
        if len(clashes) > 1:
            return re.sub(r"_(?:F\d+|B)(?:-(?:F\d+|B))+$", "", stem)   # keep the time
    return short


# ── Signal processing ─────────────────────────────────────────────────────────

def zscore(signal):
    """Z-score normalize: (x - mean) / SD. Returns mean-centred zeros if SD==0.

    A global affine transform, so paired task-vs-rest t-stats are unchanged; it
    only rescales the display into normalized units (~±3).
    """
    s = np.asarray(signal, dtype=float)
    mean = np.nanmean(s)
    sd = np.nanstd(s)
    if sd == 0 or not np.isfinite(sd):
        return s - mean
    return (s - mean) / sd


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

def timeline_legend(windows):
    """(colour, label) pairs describing the block kinds present in `windows`.

    Durations are read back off the windows rather than from the module
    constants, so the key stays truthful whichever protocol produced them — the
    12-block corpus or a PsychoPy session with its own timing. Each kind is
    labelled with its most common duration, so one short trailing block does not
    skew the figure key.
    """
    def _kind(w):
        if w["is_baseline"]:
            return "baseline"
        if w["is_interval"]:
            return "rest"
        if w.get("is_prefocus"):
            return "prefocus"
        return "task_odd"

    durations = {}
    for w in windows:
        durations.setdefault(_kind(w), []).append(round(w["t_end"] - w["t_start"], 1))

    names = {"baseline": "Baseline", "task_odd": "Task",
             "rest": "Rest", "prefocus": "Pre-focus"}

    out = []
    for kind in ("baseline", "task_odd", "rest", "prefocus"):
        ds = durations.get(kind)
        if not ds:
            continue
        common = max(set(ds), key=ds.count)
        out.append((WIN_COLORS[kind], f"{names[kind]} ({common:g}s)"))
    return out



def shade_timeline(ax, windows, x_scale=1.0, arrow_y=-0.10, label_y=-0.20, x_max=None,
                   alpha=0.35, annotate=True):
    """Colour spans + bracket arrows + labels for each task window.

    x_scale  : multiply window times (1.0 = seconds, 1/60 = minutes).
    x_max    : skip annotations for windows starting at or beyond this value
               (prevents bbox expansion for short recordings).
    alpha    : span opacity. Lower it when the shading sits behind a dense trace
               that it would otherwise compete with.
    annotate : draw the bracket arrows and block labels. Set False on stacked
               panels that share one x-axis, so the ruler is drawn once at the
               bottom rather than repeated under every panel.
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
            # 12-block labels are F1…F12; the PsychoPy battery names its blocks
            # ("Addition", "Stroop A"), so fall back when there is no number.
            num_match = re.search(r"\d+", w["label"])
            num = int(num_match.group()) if num_match else 1
            color = WIN_COLORS["task_odd"] if num % 2 == 1 else WIN_COLORS["task_even"]
        ax.axvspan(x0, x1_draw, alpha=alpha, color=color, lw=0)

        if not annotate or w["is_interval"] or w.get("is_prefocus"):
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


# ============================================================================
# Session timeline — the 7-block PsychoPy battery (was session_timeline.py)
# ============================================================================

# The helpers above recover a timeline from the FILENAME, which is right for the
# 12-block corpus. The battery randomises its block order per session and records
# it in metadata.json instead, so it needs its own builder — emitting the same
# window dicts, so every consumer below works unchanged.


# ── Nominal timing, mirroring code/experiment/settings.py SESSION ──────────────
# CAUTION on INTRO_S. It doubles as the assumed gap between the recording's t=0
# and baseline onset, and that gap is NOT fully determined by the code:
# run_all_experiments.py calls wait_for_start(), which blocks on SPACE with no
# time limit, BEFORE the 10 s BASELINE_INTRO screen. The true gap is therefore
# 10 s plus however long the operator left the welcome screen up after starting
# the headband. For ban_29_14_40 the baseline's five logged blink cues put the true
# gap at 11.95-12.15 s, and that closes against the wall clock: saved_at 15:08:25
# minus the 1650.3 s timeline puts the intro at 14:40:55, so recording t=0 lands at
# 14:40:53 — matching the 14:40 in the filename. So 10.0 s is ~2 s short here,
# about 1% of a 180 s block, and harmless. It is NOT measurable for a recording
# with no paired task.csv (minhanh_29_16_29 has no cue times to match against).
# Pass t0 (run_pipeline.py --battery --offset) when a recording's own markers disagree.
#
# Do NOT confuse this with the `offset_s` that find_session_for_recording reports.
# That is the gap from session-folder creation to recording start — 645 s for ban,
# spent on the demographics dialog and the untimed SPACE wait. Feeding it in as t0
# would misalign the timeline by nearly 11 minutes.
INTRO_S       = 10.0    # SESSION["welcome_s"]    — BASELINE_INTRO screen
BASELINE_S    = 180.0   # sum of SESSION["baseline_phases"]
REST_S        = 60.0    # SESSION["rest_s"]
COUNTDOWN_S   = 3.0     # SESSION["countdown_s"]
INSTRUCTION_S = 10.0    # show_instructions(auto_advance_s=10.0) in each task module
TASK_S        = 180.0   # <TASK>["task_duration"] = 180000 ms, all six tasks

#: instruction + countdown together form the pre-task window, the direct analogue
#: of the 12-block protocol's PREFOCUS_DUR.
PREFOCUS_S = INSTRUCTION_S + COUNTDOWN_S

BASELINE_LABEL = "Baseline"


# ── Reading a session ─────────────────────────────────────────────────────────

def load_session(session_dir):
    """Read one behaviours/<participant>_<timestamp>/ folder.

    Returns a dict with keys: dir, session, participant, task_order, completed,
    aborted, started_at (datetime), saved_at (datetime or None).
    """
    with open(os.path.join(session_dir, "metadata.json"), encoding="utf-8") as f:
        meta = json.load(f)

    session_id = meta.get("session") or os.path.basename(session_dir.rstrip(os.sep))
    started_at = None
    m = re.search(r"(\d{8}_\d{6})$", session_id)
    if m:
        started_at = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")

    saved_at = None
    if meta.get("saved_at"):
        try:
            saved_at = datetime.fromisoformat(meta["saved_at"])
        except ValueError:
            pass

    return dict(
        dir=session_dir,
        session=session_id,
        participant=meta.get("participant"),
        task_order=list(meta.get("task_order") or []),
        completed=list(meta.get("completed") or []),
        aborted=bool(meta.get("aborted")),
        started_at=started_at,
        saved_at=saved_at,
        metadata=meta,
    )


def measure_block_durations(session_dir):
    """Actual block durations in seconds, per task_type, from task.csv.

    Every block's time_ms restarts at 0, so task.csv holds BLOCK-relative times and
    no absolute clock — durations are recoverable from it, block onsets are not.
    Only the blocks that log a start and an end marker can be measured at all:
    Baseline (baseline_start → baseline_end), Fairy Tale and Passive Video
    (task_start → task_end). Addition / Multiplication / Stroop A / CPT-X record
    per-trial reaction times only, so their length is not recoverable — they are
    absent from the returned dict and callers fall back to the nominal TASK_S.

    The two measurable TASKS land within 0.12 s of nominal (Fairy Tale 180.01 s,
    Passive Video 180.12 s), which is the evidence that the nominal 180 s is safe
    for the four that cannot be measured. The BASELINE is different: it measures
    182.21 s against a nominal 180 s, because the phase list does not include the
    2 s "Mở mắt" screen that closes the eyes-closed phase. That 2.2 s is real and
    is applied when a measurement is available, so do not read the task agreement
    as licence to assume 180 s for the baseline.
    """
    path = os.path.join(session_dir, "task.csv")
    if not os.path.exists(path):
        return {}

    spans = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            label = (row.get("task_type") or "").strip()
            raw = (row.get("time_ms") or "").strip()
            if not label or not raw:
                continue
            try:
                t = float(raw)
            except ValueError:
                continue
            lo, hi = spans.get(label, (t, t))
            spans[label] = (min(lo, t), max(hi, t))

    # A single marker at t=0 is not a measurement.
    return {k: (hi - lo) / 1000.0 for k, (lo, hi) in spans.items() if hi > lo}


# ── Building the timeline ─────────────────────────────────────────────────────

def build_session_windows(task_order, measured=None, t0=0.0,
                          intro_s=INTRO_S, baseline_s=BASELINE_S, task_s=TASK_S,
                          rest_s=REST_S, prefocus_s=PREFOCUS_S):
    """Window dicts for one session, in the schema utils.build_windows() returns.

    `task_order` is metadata.json's task_order: ["Baseline", <6 task labels…>].
    `measured` optionally maps a task label to its real duration in seconds (see
    measure_block_durations); labels not present fall back to the nominal length.
    `t0` shifts the whole timeline, for when the recording started before or
    after the session did.

    Each window is dict(label, t_start, t_end, is_baseline, is_interval,
    is_prefocus). Downstream code treats `is_interval` windows as rest, skips
    `is_prefocus`, and excludes `is_baseline` from task-vs-rest pairing.
    """
    measured = measured or {}
    windows = []
    cur = float(t0)

    def add(label, dur, **flags):
        nonlocal cur
        base = dict(label=label, t_start=cur, t_end=cur + dur,
                    is_baseline=False, is_interval=False, is_prefocus=False)
        base.update(flags)
        windows.append(base)
        cur += dur

    if not task_order:
        return windows

    # The BASELINE_INTRO screen. Flagged as pre-focus so it is shaded but kept
    # out of every task-vs-rest comparison.
    if intro_s > 0:
        add("intro", intro_s, is_prefocus=True)

    head, tasks = task_order[0], task_order[1:]
    add(head, measured.get(head, baseline_s), is_baseline=True)

    for i, label in enumerate(tasks):
        if i > 0 and rest_s > 0:
            add("rest", rest_s, is_interval=True)
        if prefocus_s > 0:
            add("pre-focus", prefocus_s, is_prefocus=True)
        add(label, measured.get(label, task_s))

    return windows


def timeline_for_session(session_dir, use_measured=True, **kw):
    """Convenience: load a session folder and build its windows."""
    sess = load_session(session_dir)
    measured = measure_block_durations(session_dir) if use_measured else {}
    return build_session_windows(sess["task_order"], measured=measured, **kw), sess


def generic_task_order(n_tasks=6):
    """Fallback order when no behavioural session can be paired with a recording."""
    return [BASELINE_LABEL] + [f"Task {i}" for i in range(1, n_tasks + 1)]


def session_duration(windows):
    """End time of the last window, in seconds."""
    return windows[-1]["t_end"] if windows else 0.0


def describe_windows(windows):
    """One line per window — for logging what a recording was segmented into."""
    out = []
    for w in windows:
        kind = ("baseline" if w["is_baseline"] else
                "rest" if w["is_interval"] else
                "pre-focus" if w["is_prefocus"] else "task")
        out.append(f"  {w['t_start']:7.1f} → {w['t_end']:7.1f} s  [{kind:9s}] {w['label']}")
    return "\n".join(out)


# ── Pairing a recording with its session ──────────────────────────────────────

def parse_recording_start(csv_path, year=None, month=None):
    """Recovery of a recording's start time from its filename.

    Brain-Life exports are named `<subject>_<day>_<HH>_<MM>_F0-…-F12.csv`, where
    the time is when the recording STARTED. The year and month are absent, so
    they must be supplied (normally from the candidate session's own date).
    Returns (subject, datetime) or (subject, None) when the pattern is absent.
    """
    stem = os.path.splitext(os.path.basename(csv_path))[0]
    m = re.match(r"(?P<subject>.+?)_(?P<day>\d{1,2})_(?P<hh>\d{1,2})_(?P<mm>\d{2})(?:_|$)", stem)
    if not m:
        return stem, None
    if year is None or month is None:
        return m.group("subject"), None
    try:
        return m.group("subject"), datetime(
            int(year), int(month), int(m.group("day")),
            int(m.group("hh")), int(m.group("mm")))
    except ValueError:
        return m.group("subject"), None


def find_session_for_recording(csv_path, behaviors_dir, tolerance_min=5.0):
    """Best-effort pairing of an EEG recording with a behavioural session.

    The two are keyed differently — recordings by informal subject nickname,
    sessions by student ID — so the only available link is wall-clock time. A
    session matches when the recording's start falls inside
    [session start − tolerance, session end + tolerance]; session end is taken
    from metadata's saved_at, else estimated from the nominal timeline.

    Returns (session_dict, reason). session_dict is None when nothing matches,
    with `reason` explaining why — never guess a pairing silently.
    """
    sessions = []
    for d in sorted(glob.glob(os.path.join(behaviors_dir, "*"))):
        if os.path.isdir(d) and os.path.exists(os.path.join(d, "metadata.json")):
            try:
                sessions.append(load_session(d))
            except (OSError, ValueError, json.JSONDecodeError):
                continue

    if not sessions:
        return None, f"no behavioural sessions found in {behaviors_dir}"

    matches = []
    for sess in sessions:
        started = sess["started_at"]
        if started is None:
            continue
        subject, rec_start = parse_recording_start(
            csv_path, year=started.year, month=started.month)
        if rec_start is None:
            continue
        ended = sess["saved_at"] or (
            started + timedelta(seconds=session_duration(
                build_session_windows(sess["task_order"]))))
        pad = timedelta(minutes=tolerance_min)
        if started - pad <= rec_start <= ended + pad:
            matches.append((sess, rec_start))

    if not matches:
        return None, ("recording start does not fall inside any session's window "
                      "(recordings are keyed by nickname, sessions by student ID, "
                      "so wall-clock time is the only link)")
    if len(matches) > 1:
        names = ", ".join(s["session"] for s, _ in matches)
        return None, f"ambiguous — recording start falls inside several sessions: {names}"

    sess, rec_start = matches[0]
    offset = (rec_start - sess["started_at"]).total_seconds()
    sess = dict(sess, recording_start=rec_start, offset_s=offset)
    return sess, (f"matched {sess['session']} — recording began {offset / 60:.1f} min "
                  f"after the session folder was created")


# ── Keeping the mirrored constants honest ─────────────────────────────────────

def verify_against_experiment_settings(settings_path=None):
    """Compare the mirrored constants against code/experiment/settings.py.

    Parses the file textually rather than importing it, since importing pulls in
    PsychoPy. Returns a list of human-readable mismatches — empty when in sync,
    and empty too when the file cannot be found (this package must stay usable
    without the experiment checked out).
    """
    if settings_path is None:
        here = os.path.dirname(os.path.abspath(__file__))
        settings_path = os.path.join(os.path.dirname(here), "experiment", "settings.py")
    if not os.path.exists(settings_path):
        return []

    with open(settings_path, encoding="utf-8") as f:
        src = f.read()

    problems = []

    def scalar(name):
        m = re.search(rf'"{name}"\s*:\s*([0-9.]+)', src)
        return float(m.group(1)) if m else None

    for key, mine in (("welcome_s", INTRO_S), ("rest_s", REST_S),
                      ("countdown_s", COUNTDOWN_S)):
        theirs = scalar(key)
        if theirs is not None and abs(theirs - mine) > 1e-6:
            problems.append(f'SESSION["{key}"] is {theirs}s, utils has {mine}s')

    phases = re.search(r'"baseline_phases"\s*:\s*\[(.*?)\]', src, re.S)
    if phases:
        total = sum(float(x) for x in re.findall(r",\s*(\d+)\s*\)", phases.group(1)))
        if total and abs(total - BASELINE_S) > 1e-6:
            problems.append(f"baseline_phases sum to {total}s, utils has {BASELINE_S}s")

    durations = {float(v) for v in re.findall(r'"task_duration"\s*:\s*(\d+)', src)}
    if durations and durations != {TASK_S * 1000}:
        pretty = ", ".join(f"{d / 1000:g}s" for d in sorted(durations))
        problems.append(f"task_duration values are {{{pretty}}}, utils has {TASK_S}s")

    return problems


# ============================================================================
# Ocular artifact — detection and exclusion (was blink.py)
# ============================================================================


#: Blink and saccade energy concentrates here. The upper edge stays below alpha so
#: the detector does not key on genuine rhythms.
BLINK_BAND = (1.0, 5.0)

#: Envelope smoothing. A blink lasts 100-400 ms; this is long enough to bridge the
#: two lobes of one deflection and short enough not to merge separate events.
ENVELOPE_MS = 200.0

#: Threshold in robust SDs of the envelope. Calibrated against blink RATE, which is
#: the only external reference available: spontaneous blinking runs ~10-20/min at
#: rest and DROPS during focused visual work (reading, arithmetic), so a detector
#: firing well above 20/min is discarding EEG, not blinks. Measured on
#: ban_29_14_40 over the 24.5 min it actually screens:
#:
#:   n_sd   events/min   excluded   mean span   median gap
#:    5.0        6.6        8.5%       0.86 s      4.10 s   under - misses task blinks
#:    4.0       13.4       16.5%       0.83 s      1.81 s   conservative, defensible
#:    3.5       17.7       22.3%       0.85 s      1.18 s   <- default, top of normal band
#:    3.0       22.1       29.1%       0.89 s      0.85 s   over - above resting rate
#:    2.0       25.2       40.8%       1.09 s      0.64 s   count saturates, spans widen
#:
#: Note what happens below 3.0: the event count saturates near 600 while the
#: excluded fraction climbs to 41-47% and the mean span grows from 0.89 s to 1.33 s.
#: It stops finding new blinks and starts merging and widening the ones it has, so
#: the extra cost buys nothing. Tune with --blink-sd; 4.0 if you would rather keep
#: data than catch every event.
N_ROBUST_SD = 3.5

#: Window for the OPTIONAL local threshold (`adaptive=True`), which is OFF by
#: default. A local threshold sounds better than a global one and is worse here:
#: when a whole block is blink-dense the local level rises to meet the blinks and
#: the detector stops seeing them. Measured over ban_29_14_40's 200-220 s Addition
#: block, which is visibly full of them: global n_sd=3 finds 13 spans, adaptive
#: n_sd=3 finds 4. Keep it global unless a recording has one quiet stretch whose
#: blinks a global threshold misses.
BLINK_WINDOW_S = 30.0

#: Each supra-threshold run is widened by this much on both sides, because the
#: envelope crosses back below threshold while the deflection is still returning.
PAD_S = 0.25

#: Runs shorter than this are not blinks (single-sample spikes, quantisation).
MIN_DUR_S = 0.06


def robust_sd(x):
    """1.4826·MAD — an amplitude estimate that the artifacts themselves can't inflate."""
    finite = x[np.isfinite(x)]
    if finite.size == 0:
        return float("nan")
    return float(1.4826 * np.median(np.abs(finite - np.median(finite))))


def _envelope(x, fs, band=BLINK_BAND, smooth_ms=ENVELOPE_MS):
    sos = butter(3, band, btype="band", fs=fs, output="sos")
    band_limited = sosfiltfilt(sos, np.nan_to_num(x, nan=0.0))
    k = max(1, int(smooth_ms / 1000.0 * fs))
    kernel = np.ones(k) / k
    return np.convolve(np.abs(band_limited), kernel, mode="same")


def baseline_span(windows):
    """(start, end) of the baseline block in seconds, or None."""
    base = next((w for w in windows if w.get("is_baseline")), None)
    return (base["t_start"], base["t_end"]) if base else None


def _local_threshold(env, fs, ref, n_robust_sd, window_s):
    """Per-sample threshold: local median + n·MAD of the envelope.

    Estimated on a grid of `window_s` windows and linearly interpolated, so the
    threshold follows the recording's changing amplitude instead of being set once
    by whichever block happens to be loudest. Windows are scored using only
    reference samples (`ref`), so a skipped baseline never sets the level; windows
    with too few reference samples fall back to the global estimate.
    """
    step = max(1, int(window_s * fs))
    centres, levels = [], []
    g_med = float(np.median(env[ref])) if ref.any() else float(np.median(env))
    g_sd = robust_sd(env[ref]) if ref.any() else robust_sd(env)
    for s in range(0, len(env), step):
        e = min(len(env), s + step)
        sel = env[s:e][ref[s:e]]
        if sel.size >= step // 4:
            centres.append((s + e) / 2.0)
            levels.append(float(np.median(sel)) + n_robust_sd * robust_sd(sel))
        else:
            centres.append((s + e) / 2.0)
            levels.append(g_med + n_robust_sd * g_sd)
    if len(centres) == 1:
        return np.full(len(env), levels[0])
    return np.interp(np.arange(len(env)), centres, levels)


def detect_blinks(channels, fs, windows=None, skip_baseline=True,
                  n_robust_sd=N_ROBUST_SD, pad_s=PAD_S, min_dur_s=MIN_DUR_S,
                  window_s=BLINK_WINDOW_S, adaptive=False):
    """Find ocular-artifact spans across one or more channels.

    `channels` is a sequence of 1-D arrays sharing a time base; a span flagged on
    either channel is excluded from both, since they are simultaneous samples of
    one head and a blink is never one-sided.

    Returns (spans, info) where spans is a list of (start_s, end_s) and info
    carries the thresholds and the fraction of time excluded.
    """
    n = min(len(c) for c in channels)
    dur = n / fs
    base = baseline_span(windows or []) if skip_baseline else None

    # Estimate the threshold from non-baseline samples only, so the baseline's
    # deliberate blink and eye-movement phases do not raise the bar everywhere else.
    ref = np.ones(n, dtype=bool)
    if base:
        b0, b1 = int(base[0] * fs), int(min(base[1], dur) * fs)
        ref[b0:b1] = False

    flagged = np.zeros(n, dtype=bool)
    thresholds = {}
    for i, ch in enumerate(channels):
        env = _envelope(np.asarray(ch[:n], dtype=float), fs)
        if adaptive:
            thr = _local_threshold(env, fs, ref, n_robust_sd, window_s)
            thresholds[i] = float(np.median(thr))       # representative, for reporting
        else:
            pool = env[ref] if ref.any() else env
            thr = float(np.median(pool) + n_robust_sd * robust_sd(pool))
            thresholds[i] = thr
        flagged |= env > thr

    if base:
        b0, b1 = int(base[0] * fs), int(min(base[1], dur) * fs)
        flagged[b0:b1] = False          # the baseline's artifacts are the protocol

    # Contiguous runs -> padded, merged spans
    edges = np.diff(flagged.astype(np.int8))
    starts = list((np.flatnonzero(edges == 1) + 1))
    ends = list(np.flatnonzero(edges == -1) + 1)
    if flagged[0]:
        starts.insert(0, 0)
    if flagged[-1]:
        ends.append(n)

    spans = []
    for s, e in zip(starts, ends):
        if (e - s) / fs < min_dur_s:
            continue
        a, b = max(0.0, s / fs - pad_s), min(dur, e / fs + pad_s)
        if spans and a <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], b))
        else:
            spans.append((a, b))

    mask = spans_to_mask(spans, n, fs)
    info = dict(thresholds=thresholds, n_spans=len(spans),
                excluded_frac=float(mask.mean()),
                excluded_s=float(mask.sum() / fs),
                baseline_skipped=bool(base), duration_s=dur)
    return spans, info


def spans_to_mask(spans, n, fs):
    """Boolean array, True where a sample falls inside an artifact span."""
    mask = np.zeros(n, dtype=bool)
    for a, b in spans:
        mask[max(0, int(a * fs)):min(n, int(b * fs))] = True
    return mask


def clean_segments(mask, fs, min_len_s):
    """(start, end) sample indices of artifact-free runs at least min_len_s long."""
    keep = ~mask
    edges = np.diff(keep.astype(np.int8))
    starts = list(np.flatnonzero(edges == 1) + 1)
    ends = list(np.flatnonzero(edges == -1) + 1)
    if keep[0]:
        starts.insert(0, 0)
    if keep[-1]:
        ends.append(len(keep))
    need = int(min_len_s * fs)
    return [(s, e) for s, e in zip(starts, ends) if e - s >= need]


def band_power_clean(x, fs, mask, lo, hi, nperseg_s=4.0):
    """Band power over the artifact-free parts of x.

    One Welch PSD per clean segment, averaged weighted by segment length. Deleting
    the flagged samples and running a single Welch would splice the survivors
    together and put a step at every join — broadband energy that lands mostly in
    the band this is trying to measure.
    """
    x = np.asarray(x, dtype=float)
    segs = clean_segments(mask[:len(x)], fs, nperseg_s)
    if not segs:
        return float("nan")
    nperseg = int(nperseg_s * fs)
    total, weight = 0.0, 0.0
    for s, e in segs:
        seg = x[s:e]
        if len(seg) < nperseg:
            continue
        fr, P = welch(seg, fs=fs, nperseg=nperseg)
        m = (fr >= lo) & (fr <= hi)
        if not m.any():
            continue
        total += float(np.trapezoid(P[m], fr[m])) * len(seg)
        weight += len(seg)
    return total / weight if weight else float("nan")


def describe_blinks(info, per_block=None):
    """One-line description of what was excluded."""
    s = (f"{info['n_spans']} artifact spans, {info['excluded_s']:.0f} s excluded "
         f"({info['excluded_frac'] * 100:.1f}% of {info['duration_s']:.0f} s)")
    if info.get("baseline_skipped"):
        s += "; baseline left intact (its blinks and eye movements are the protocol)"
    return s
