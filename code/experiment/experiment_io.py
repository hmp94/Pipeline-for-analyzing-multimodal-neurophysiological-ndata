"""
experiment_io.py — shared results output for the cognitive task battery.

Every run (a full session via run_all_experiments.py, or a single task on its
own) produces ONE folder per session containing exactly two files:

    results/behaviors/<participant>_<timestamp>/
        metadata.json   # demographics + session info (order, completion, scores)
        task.csv        # every task's trials in one table, keyed by task_type

The combined task.csv uses a fixed column order; columns a given task does not
use are left blank for that task's rows. Group by the task_type column to split
the tasks back apart.
"""

import os
import sys
import csv
import json
from datetime import datetime


# Fixed column order for the combined task.csv. Any unexpected keys are appended
# after these so nothing is ever silently dropped.
CANONICAL_COLUMNS = [
    "task_type", "trial_number",
    "stimulus", "word", "color",                                  # Stroop
    "num1", "num2", "correct_answer",                             # arithmetic
    "response", "reaction_time", "reaction_time_from_onset", "correct",
    "event", "page", "time_ms",                                   # reading
]

# Behavioural sessions get their own subfolder of results/, so they stay separate
# from the EEG recordings that are copied in by hand from the two headsets
# (results/eeg_bl/ for the Brain-Life band, results/eeg_natus/ for the Natus system).
BEHAVIOR_SUBDIR = "behaviors"


def _results_base(results_dir_name="results"):
    """Base folder for results.

    Fixed relative to this file, NOT the working directory, so a session always
    writes to the same place no matter where it was launched from. This module is
    code/experiment/experiment_io.py, so the parent of experiment/ is code/ —
    results therefore land in `code/results/` (a sibling of experiment/), with
    behavioural sessions under its `behaviors/` subfolder.
    Frozen builds (PyInstaller) write next to the executable instead.
    """
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, results_dir_name)


def make_session_dir(participant, results_dir_name="results", when=None):
    """Create results/behaviors/<participant>_<timestamp>/, return (session_id, path)."""
    when = when or datetime.now()
    session_id = f"{participant}_{when.strftime('%Y%m%d_%H%M%S')}"
    path = os.path.join(_results_base(results_dir_name), BEHAVIOR_SUBDIR, session_id)
    os.makedirs(path, exist_ok=True)
    return session_id, path


def _fieldnames(rows):
    present = {k for r in rows for k in r}
    ordered = [c for c in CANONICAL_COLUMNS if c in present]
    extra = [k for k in present if k not in CANONICAL_COLUMNS]
    return ordered + sorted(extra)


def write_task_csv(session_dir, rows):
    """Write all task rows to <session_dir>/task.csv (blank for unused columns)."""
    path = os.path.join(session_dir, "task.csv")
    fieldnames = _fieldnames(rows) or list(CANONICAL_COLUMNS)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval="")
        writer.writeheader()
        for r in (rows or []):
            writer.writerow(r)
    print(f"Saved: {path}")
    return path


def write_metadata(session_dir, metadata):
    """Write the session metadata dict to <session_dir>/metadata.json."""
    path = os.path.join(session_dir, "metadata.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    print(f"Saved: {path}")
    return path


def build_metadata(session_id, demographics, task_order, completed, aborted, results):
    """Assemble the standard session metadata dict."""
    return {
        "session": session_id,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "task_order": list(task_order),
        "completed": list(completed),
        "aborted": bool(aborted),
        "results": dict(results),
        **(demographics or {}),
    }


def save_session(session_dir, rows, metadata):
    """Write both session files. Safe to call repeatedly (overwrites in place)."""
    write_task_csv(session_dir, rows)
    write_metadata(session_dir, metadata)
