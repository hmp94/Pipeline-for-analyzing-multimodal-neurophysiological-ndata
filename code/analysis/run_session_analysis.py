#!/usr/bin/env python3
"""
run_session_analysis.py — run the analysis pipeline over code/results/eeg_bl/.

Wraps run_pipeline.py for recordings made during the 7-block PsychoPy battery.
The pipeline itself is unchanged; the only difference is where the timeline comes
from. For the 12-block corpus the block order is in the filename, so
utils.get_timeline() can read it off the path. Here the order is randomized per
session and recorded in the session's metadata.json, so this driver:

  1. pairs each recording in code/results/eeg_bl/ with a session folder in
     code/results/behaviors/ (by wall-clock time — see the caveat below),
  2. builds the timeline from that session's task_order plus the battery's own
     timing (session_timeline.py),
  3. hands the windows to run_pipeline, which produces the same
     <stem>_summary.png and <stem>_FI.png figures as for the 12-block corpus.

Pairing caveat
--------------
Recordings are named by informal subject nickname ("ban", "minhanh") while
sessions are keyed by student ID, so wall-clock time is the only link between
them. A pairing is accepted only when the recording's start time falls inside a
session's span; anything ambiguous or unmatched is reported and analysed with
generic block labels rather than guessed at. Pass --map to state a pairing
explicitly and remove the guesswork.

Usage
-----
  python run_session_analysis.py                       # all recordings, auto-paired
  python run_session_analysis.py --dry-run             # print timelines, plot nothing
  python run_session_analysis.py --map ban_29_14_40_F0-F1-F2-F3-F4-F5-F6-F7-F8-F9-F10-F11-F12.csv=111240033_20260729_142915
"""

import argparse
import glob
import os
import sys

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import session_timeline as st

REPO_ROOT    = os.path.dirname(os.path.dirname(CODE_DIR))
EEG_BL_DIR   = os.path.join(REPO_ROOT, "code", "results", "eeg_bl")
BEHAVIORS_DIR = os.path.join(REPO_ROOT, "code", "results", "behaviors")
GRAPH_DIR    = os.path.join(REPO_ROOT, "graph", "eeg_bl")
EDF_DIR      = os.path.join(REPO_ROOT, "data", "derived", "eeg_bl", "edf")


def resolve_pairings(csv_paths, explicit=None, offsets=None, default_offset=0.0):
    """Attach a session (or None) to every recording.

    `offsets` maps a recording filename to an EXTRA shift in seconds applied on
    top of the assumed 10 s intro (see session_timeline.INTRO_S — the interval
    before baseline onset is operator-controlled, so it is worth overriding when a
    recording's own baseline markers disagree). `default_offset` applies to any
    recording without a specific entry.

    Returns a list of dicts: csv, stem, session, windows, note.
    """
    explicit = explicit or {}
    offsets = offsets or {}
    plans = []

    for csv_path in csv_paths:
        stem = os.path.splitext(os.path.basename(csv_path))[0]
        base = os.path.basename(csv_path)

        session, note = None, ""
        forced = explicit.get(base) or explicit.get(stem)
        if forced:
            session_dir = forced if os.path.isdir(forced) else os.path.join(BEHAVIORS_DIR, forced)
            if not os.path.isdir(session_dir):
                note = f"--map target not found: {forced}"
            else:
                session = st.load_session(session_dir)
                note = f"paired explicitly with {session['session']} (--map)"
        else:
            session, note = st.find_session_for_recording(csv_path, BEHAVIORS_DIR)

        t0 = float(offsets.get(base, offsets.get(stem, default_offset)))
        shift = f"   [t0 {t0:+.1f}s]" if t0 else ""

        if session is not None:
            measured = st.measure_block_durations(session["dir"])
            windows = st.build_session_windows(session["task_order"],
                                               measured=measured, t0=t0)
            title = (f"{stem}   —   session {session['session']}"
                     f"   (order from metadata.json){shift}")
        else:
            # No behavioural session: keep the battery's timing but label the
            # blocks generically, so nothing implies an order we cannot support.
            windows = st.build_session_windows(st.generic_task_order(), t0=t0)
            title = f"{stem}   —   NO PAIRED SESSION, block labels are generic{shift}"

        plans.append(dict(csv=csv_path, stem=stem, session=session,
                          windows=windows, note=note, title=title))
    return plans


def report(plans):
    """Print what each recording was paired with and how it will be segmented."""
    for p in plans:
        print(f"\n{'=' * 72}\n{p['stem']}\n{'=' * 72}")
        print(f"  pairing : {p['note']}")
        if p["session"]:
            s = p["session"]
            print(f"  session : {s['session']}  participant={s['participant']}  "
                  f"aborted={s['aborted']}")
            print(f"  order   : {' -> '.join(s['task_order'])}")
        dur = st.session_duration(p["windows"])
        print(f"  timeline: {dur:.1f} s ({dur / 60:.1f} min) over {len(p['windows'])} windows")
        print(st.describe(p["windows"]))

        actual = _recording_seconds(p["csv"])
        if actual:
            print(f"  recording length: {actual:.1f} s ({actual / 60:.1f} min); "
                  f"timeline covers {dur:.1f} s, slack {actual - dur:+.1f} s")


def _recording_seconds(csv_path, eeg_fs=244):
    """Recording length in seconds, from the row count (one row per EEG sample)."""
    try:
        with open(csv_path, "rb") as f:
            rows = sum(1 for _ in f) - 1        # minus the header
        return rows / eeg_fs if rows > 0 else None
    except OSError:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--eeg-dir", default=EEG_BL_DIR, help="folder of Brain-Life CSVs")
    ap.add_argument("--graph-dir", default=GRAPH_DIR, help="where the PNGs go")
    ap.add_argument("--edf-dir", default=EDF_DIR, help="where intermediate EDFs go")
    ap.add_argument("--map", action="append", default=[], metavar="CSV=SESSION",
                    help="force a pairing; repeatable")
    ap.add_argument("--offset", action="append", default=[], metavar="CSV=SECONDS",
                    help="extra shift on top of the assumed 10 s intro, for a "
                         "recording that did not start at the SPACE press; repeatable")
    ap.add_argument("--offset-all", type=float, default=0.0, metavar="SECONDS",
                    help="apply an extra shift to every recording")
    ap.add_argument("--dry-run", action="store_true",
                    help="report pairings and timelines without running the pipeline")
    ap.add_argument("--only", default=None,
                    help="substring filter on the recording filename")
    args = ap.parse_args()

    explicit = {}
    for item in args.map:
        if "=" not in item:
            ap.error(f"--map needs CSV=SESSION, got {item!r}")
        k, v = item.split("=", 1)
        explicit[k.strip()] = v.strip()

    offsets = {}
    for item in args.offset:
        if "=" not in item:
            ap.error(f"--offset needs CSV=SECONDS, got {item!r}")
        k, v = item.split("=", 1)
        try:
            offsets[k.strip()] = float(v)
        except ValueError:
            ap.error(f"--offset seconds must be a number, got {v!r}")

    csv_paths = sorted(p for p in glob.glob(os.path.join(args.eeg_dir, "*.csv")))
    if args.only:
        csv_paths = [p for p in csv_paths if args.only in os.path.basename(p)]
    if not csv_paths:
        print(f"No CSV recordings found in {args.eeg_dir}")
        return 1

    drift = st.verify_against_experiment_settings()
    if drift:
        print("WARNING — session_timeline is out of sync with code/experiment/settings.py:")
        for d in drift:
            print(f"  - {d}")

    plans = resolve_pairings(csv_paths, explicit, offsets=offsets,
                             default_offset=args.offset_all)
    report(plans)

    unpaired = [p["stem"] for p in plans if p["session"] is None]
    if unpaired:
        print(f"\nWARNING — {len(unpaired)} recording(s) have no paired session, so their "
              f"block labels are generic placeholders, NOT the real task order:")
        for stem in unpaired:
            print(f"  - {stem}")

    if args.dry_run:
        print("\n--dry-run: no figures produced.")
        return 0

    # Imported late: this pulls in matplotlib and pyedflib, which --dry-run does
    # not need.
    from run_pipeline import run_pipeline

    os.makedirs(args.graph_dir, exist_ok=True)
    os.makedirs(args.edf_dir, exist_ok=True)

    all_results = []
    for p in plans:
        print(f"\n{'#' * 72}\n#  {p['stem']}\n{'#' * 72}")
        results = run_pipeline(
            csv_input=p["csv"],
            edf_output_dir=args.edf_dir,
            fnirs_plot=False,
            ppg_plot=False,
            fi_save_dir=args.graph_dir,
            summary_save_dir=args.graph_dir,
            show_summary=False,
            windows_for={p["csv"]: p["windows"]},
            title_for={p["csv"]: p["title"]},
        )
        all_results.extend(results)

    print(f"\n{'=' * 72}\nFigures written to {args.graph_dir}\n{'=' * 72}")
    for f in sorted(os.listdir(args.graph_dir)):
        print(f"  {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
