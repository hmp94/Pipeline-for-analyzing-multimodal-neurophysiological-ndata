"""
session_timeline.py — build an analysis timeline for the 7-block PsychoPy battery.

The rest of code/analysis/ was written for the 12-block protocol, where the block
order is encoded in the filename (`..._F0-F1-…-F12.csv`) and every block has the
same length, so `utils.get_timeline()` can recover the timeline from the filename
alone. The battery in code/experiment/ works differently:

  * the block order is RANDOMIZED per session and recorded in the session's
    metadata.json (`task_order`), not in the recording's filename;
  * blocks are named ("Addition", "Stroop A", …) rather than F1…F12;
  * the timing differs — 180 s blocks, a 3-min baseline, and a 13 s
    instruction+countdown screen before every task.

This module builds the same window dicts `utils.build_windows()` produces, so
every downstream consumer (shade_timeline, sig_pairs, fi_pairs, rmssd_windows)
works unchanged. Nothing here mutates the 12-block constants in metadata.py, so
the original corpus keeps analysing exactly as before.

Session structure — mirrors run_all_experiments.main() step for step:

    intro         10 s   BASELINE_INTRO screen (SESSION["welcome_s"])
    Baseline     180 s   run_baseline(), six timed sub-phases
    for each task in task_order[1:]:
        rest      60 s   SESSION["rest_s"] — between tasks only, never before the first
        prefocus  13 s   instruction screen (10 s) + countdown (SESSION["countdown_s"], 3 s)
        task     180 s   <task>["task_duration"], 180000 ms for all six

Total 1648 s (27.5 min), which is why these recordings run ~28 min against the
37-39 min of the 12-block corpus.

Timing constants are mirrored from code/experiment/settings.py rather than
imported, so this package stays runnable on a machine that has no PsychoPy
installed. Keep them in sync — `verify_against_experiment_settings()` checks them
against the real file when it is reachable.
"""

import csv
import glob
import json
import os
import re
from datetime import datetime, timedelta

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
# Pass t0 (run_session_analysis --offset) when a recording's own markers disagree.
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


def describe(windows):
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
            problems.append(f'SESSION["{key}"] is {theirs}s, session_timeline has {mine}s')

    phases = re.search(r'"baseline_phases"\s*:\s*\[(.*?)\]', src, re.S)
    if phases:
        total = sum(float(x) for x in re.findall(r",\s*(\d+)\s*\)", phases.group(1)))
        if total and abs(total - BASELINE_S) > 1e-6:
            problems.append(f"baseline_phases sum to {total}s, session_timeline has {BASELINE_S}s")

    durations = {float(v) for v in re.findall(r'"task_duration"\s*:\s*(\d+)', src)}
    if durations and durations != {TASK_S * 1000}:
        pretty = ", ".join(f"{d / 1000:g}s" for d in sorted(durations))
        problems.append(f"task_duration values are {{{pretty}}}, session_timeline has {TASK_S}s")

    return problems


if __name__ == "__main__":
    issues = verify_against_experiment_settings()
    print("\n".join(issues) if issues
          else "timing constants are in sync with code/experiment/settings.py")

    here = os.path.dirname(os.path.abspath(__file__))
    behaviors = os.path.join(os.path.dirname(here), "results", "behaviors")
    for d in sorted(glob.glob(os.path.join(behaviors, "*"))):
        if not os.path.isdir(d):
            continue
        windows, sess = timeline_for_session(d)
        print(f"\n{sess['session']}  ({session_duration(windows):.1f} s total)")
        print(describe(windows))
