"""
run_all_experiments.py — single-session runner for the focus-state protocol.

This is a self-contained 6-task experiment. Its timeline follows the participant
instruction document ("Hướng dẫn thực hiện thử nghiệm trạng thái tập trung"); it
is NOT the acquisition software behind the 12-task battery that code/analysis/
processes, so it does not read from or need to match code/analysis/metadata.py.

Shows ONE demographics dialog, opens ONE window, then runs:

    baseline (3 min continuous: signal-check -> eyes-open -> blinks ->
              horizontal eye moves -> vertical eye moves -> eyes-closed)
      -> countdown (5 s) -> task 1 (~180 s)
      -> rest (60 s) -> countdown (5 s) -> task 2 (~180 s)
      -> rest (60 s) -> countdown (5 s) -> task 3 ...

The six cognitive tasks (Passive Video, Fairy Tale, Addition, CPT-X,
Multiplication, Stroop) run in a RANDOMIZED order; each lasts ~180 s (Stroop
300 s). There is NO rest before the first task (the baseline flows straight into
the first countdown), and NO rest after the last.

Transitions are automatic: after the demographics dialog the participant never
has to press a key to advance — each screen counts down and moves on by itself.
SPACE is only an optional early-skip for the experimenter; ESC aborts the whole
session (all data collected so far is saved).

Because every task shares the one window, the screen never flashes between
tasks — useful when EEG/fNIRS/PPG are recording continuously.

Output — one folder per session:
  results/<participant>_<timestamp>/
    metadata.json   demographics + session info (order, completion, scores)
    task.csv        every task's trials in one table, keyed by the task_type column
                    (the baseline logs baseline_start/baseline_end marker rows)

Run:  python run_all_experiments.py
"""

import os
import sys
import random

from psychopy import visual, core, gui
from psychopy.hardware import keyboard

# Sibling task modules live next to this file.
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import content
import settings as cfg
import experiment_io as expio
import stroop_game_psychopy as stroop
import addition_game_psychopy as addition
import multiplication_game_psychopy as multiplication
import fairy_tale_psychopy as fairy_tale
import passive_video_psychopy as passive_video
import cpt_x_psychopy as cpt_x


REF_H = 1080.0                            # font sizes below are pixels for a 1080px-tall screen
# Session-level durations (seconds) — edit in settings.py (cfg.SESSION).
# The 3-min baseline schedule lives in cfg.SESSION["baseline_phases"].
REST_S = cfg.SESSION["rest_s"]                        # rest between tasks, 1 min
WELCOME_S = cfg.SESSION["welcome_s"]                  # auto-advancing welcome screen
FINAL_S = cfg.SESSION["final_s"]                      # final summary screen (SPACE closes early)

# The six tasks. Order is randomized per session.
TASKS = [passive_video, fairy_tale, addition, cpt_x, multiplication, stroop]

# Each task module defines its own AbortBlock class; collect them so the runner
# can catch "ESC pressed" from any task with a single except clause.
ABORT_EXCEPTIONS = tuple({m.AbortBlock for m in TASKS})


def h(px):
    """Pixel size -> 'height' units."""
    return px / REF_H


class AbortSession(Exception):
    """ESC pressed on one of the runner's own transition screens."""


# --------------------------------------------------------------------------- #
# Startup dialog (shown once)
# --------------------------------------------------------------------------- #
def get_session_info():
    """Demographics dialog for the whole session. Returns (participant, demographics) or None."""
    info = {
        "MSSV": "",
        "Age": "",
        "Gender": ["Female", "Male", "Other"],
        "Handedness": ["Right", "Left", "Ambidextrous"],
    }
    order = ["MSSV", "Age", "Gender", "Handedness"]
    dlg = gui.DlgFromDict(info, title="Cognitive Task Session", order=order)
    if not dlg.OK:
        return None

    participant = (info["MSSV"] or "anonymous").strip() or "anonymous"
    demographics = {
        "participant": participant,
        "age": str(info["Age"]).strip(),
        "gender": info["Gender"],
        "handedness": info["Handedness"],
    }
    return participant, demographics


# --------------------------------------------------------------------------- #
# Screens
# --------------------------------------------------------------------------- #
def show_message(win, kb, lines, seconds, allow_skip=True, skip_hint=False):
    """Auto-advancing message screen (no countdown shown).

    Displays `lines` (a list of strings) for `seconds`, then returns. No timer or
    countdown is shown. SPACE does NOT skip content screens; it only closes the
    final summary screen early (the one shown with skip_hint=True, which draws a
    "Nhấn SPACE để kết thúc" footer). ESC raises AbortSession.
    """
    body = visual.TextStim(win, text="\n".join(lines), color=(255, 255, 255),
                           colorSpace="rgb255", height=h(60), pos=(0, 0.06),
                           wrapWidth=1.6, alignText="center", font="Arial")
    footer = visual.TextStim(win, text=content.FOOTER_SKIP, color=(160, 160, 160),
                             colorSpace="rgb255", height=h(34), pos=(0, -0.40), font="Arial")

    kb.clearEvents()
    clock = core.Clock()
    while True:
        remaining = seconds - clock.getTime()
        if remaining <= 0:
            return
        body.draw()
        if skip_hint and allow_skip:
            footer.draw()
        win.flip()

        for k in kb.getKeys(["space", "escape"], waitRelease=False):
            if k.name == "escape":
                raise AbortSession
            if k.name == "space" and skip_hint:   # only the final summary closes on SPACE
                return


def beep(freq=None, ms=None):
    """Audible 'open your eyes' cue for the end of the eyes-closed baseline.

    Cross-platform, no extra dependency: Windows plays a tone via winsound.Beep;
    macOS plays a system sound via afplay (cfg.SESSION["beep_sound_mac"]). On any
    other platform / on failure it is a silent no-op — never raises. Tone/sound
    are set in settings.py.
    """
    try:
        if sys.platform == "win32":
            import winsound
            winsound.Beep(int(freq or cfg.SESSION["beep_freq_hz"]),
                          int(ms or cfg.SESSION["beep_ms"]))
        elif sys.platform == "darwin":
            import subprocess
            subprocess.Popen(["afplay", cfg.SESSION["beep_sound_mac"]])
    except Exception:
        pass


def _baseline_abort(kb, rows_out, phase, clock):
    """Raise AbortSession (logging a marker) if ESC was pressed during baseline."""
    for k in kb.getKeys(["escape"], waitRelease=False):
        if k.name == "escape":
            rows_out.append({"task_type": "Baseline", "event": f"{phase}_aborted",
                             "time_ms": int(round(clock.getTime() * 1000))})
            raise AbortSession


def run_baseline(win, kb, rows_out):
    """3-minute CONTINUOUS baseline for EEG / eye-artifact calibration.

    One uninterrupted recording, split into timed sub-phases read from
    cfg.SESSION["baseline_phases"]:
        signal_check -> eyes_open -> blinks -> h_move -> v_move -> eyes_closed
    The intro is shown by the caller. On-screen cues guide the active phases
    (blinks, eye movements); resting phases show only "+". A <phase>_start marker
    is logged at each boundary (plus blink_N / <phase>_stepN sub-markers). Ends
    with a beep + "Mở mắt". SPACE cannot skip; ESC raises AbortSession.
    """
    phases = cfg.SESSION["baseline_phases"]
    n_blinks = int(cfg.SESSION.get("baseline_n_blinks", 5))

    fixation = visual.TextStim(win, text="+", color=(255, 255, 255), colorSpace="rgb255",
                               height=h(100), pos=(0, 0.02))
    dot = visual.Circle(win, radius=0.028, units="height", fillColor=(255, 255, 255),
                        lineColor=None, colorSpace="rgb255")
    cap = visual.TextStim(win, text="", color=(160, 160, 160), colorSpace="rgb255",
                          height=h(46), pos=(0, -0.36), wrapWidth=1.6, font="Arial")
    big = visual.TextStim(win, text="", color=(255, 255, 255), colorSpace="rgb255",
                          height=h(96), font="Arial")

    # Eye-movement guide-dot amplitudes (height units): reach ~90% toward the
    # screen edges. Horizontal has far more room than vertical on a wide screen,
    # so they differ — horizontal is derived from the window aspect ratio (x edge
    # = aspect/2), vertical from the fixed y edge (0.5). Leaves a small margin so
    # the dot isn't clipped on any display.
    try:
        aspect = float(win.size[0]) / float(win.size[1])
    except Exception:
        aspect = 16.0 / 9.0
    hamp = min(0.82, aspect / 2.0 * 0.9)
    vamp = 0.44

    rows_out.append({"task_type": "Baseline", "event": "baseline_start", "time_ms": 0})
    kb.clearEvents()
    block = core.Clock()

    def mark(event):
        rows_out.append({"task_type": "Baseline", "event": event,
                         "time_ms": int(round(block.getTime() * 1000))})

    def hold(stims, seconds, phase):
        pc = core.Clock()
        while pc.getTime() < seconds:
            for s in stims:
                s.draw()
            win.flip()
            _baseline_abort(kb, rows_out, phase, block)

    for name, secs in phases:
        mark(f"{name}_start")
        if name in ("signal_check", "eyes_open"):
            hold([fixation], secs, name)                          # resting: "+" only
        elif name == "eyes_closed":
            big.text = content.BASELINE_CLOSE_EYES
            hold([big], min(3.0, secs), name)                     # cue them to close eyes
            hold([fixation], max(0.0, secs - 3.0), name)          # then hold (eyes closed)
        elif name == "blinks":
            cap.text = content.BASELINE_BLINK_CAP
            per = secs / max(1, n_blinks)
            for b in range(n_blinks):
                hold([fixation, cap], per * 0.65, name)
                mark(f"blink_{b + 1}")
                big.text = content.BASELINE_BLINK_CUE
                hold([big, cap], per * 0.35, name)                # "Chớp mắt" -> blink now
        elif name in ("h_move", "v_move"):
            seq = ([(-hamp, 0), (0, 0), (hamp, 0), (0, 0)]        # left-centre-right-centre
                   if name == "h_move" else
                   [(0, vamp), (0, 0), (0, -vamp), (0, 0)])       # up-centre-down-centre
            cap.text = content.BASELINE_MOVE_CAP
            cap.pos = (0, -0.28)   # above the DOWN dot (which now sits near the edge) so no overlap
            per = secs / len(seq)
            for i, pos in enumerate(seq):
                dot.pos = pos
                mark(f"{name}_step{i + 1}")
                hold([dot, cap], per, name)                       # follow the guide dot

    beep()
    big.text = content.BASELINE_OPEN_EYES
    big.draw()
    win.flip()
    core.wait(2.0)
    mark("baseline_end")
    return content.BASELINE_RESULT


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    # Dialog first, window second: a dialog opened after the OpenGL window can end
    # up behind it on macOS and never take focus, which looks like a hang.
    session = get_session_info()
    if session is None:
        core.quit()
    participant, demographics = session

    order = TASKS[:]
    random.shuffle(order)
    task_labels = [m.TASK_LABEL for m in order]
    order_labels = ["Baseline"] + task_labels
    print(f"Session order: {' -> '.join(order_labels)}")

    # One folder per session: results/<participant>_<timestamp>/{metadata.json, task.csv}
    session_id, session_dir = expio.make_session_dir(participant)
    all_rows = []           # every task's trials/events, combined; keyed by task_type
    summaries = []          # (label, summary string) per completed task
    completed_labels = []
    aborted = False

    def save():
        expio.save_session(session_dir, all_rows, expio.build_metadata(
            session_id, demographics, order_labels, completed_labels,
            aborted, dict(summaries)))

    win = visual.Window(size=(1400, 900), fullscr=True, color=(0, 0, 0),
                        colorSpace="rgb255", units="height", allowGUI=True)
    kb = keyboard.Keyboard()

    try:
        show_message(win, kb, content.WELCOME, seconds=WELCOME_S)

        # F0 resting baseline — first, no rest before it.
        show_message(win, kb, content.BASELINE_INTRO, seconds=WELCOME_S)
        summaries.append(("Baseline", run_baseline(win, kb, all_rows)))
        completed_labels.append("Baseline")
        save()

        for i, module in enumerate(order):
            label = module.TASK_LABEL
            if i > 0:
                # Rest only BETWEEN tasks (never before the first). The pre-focus
                # countdown (settings.SESSION["countdown_s"]) is each task's own,
                # shown inside module.run.
                show_message(win, kb, content.REST, seconds=REST_S)
            summary = module.run(win, kb, participant, demographics, rows_out=all_rows)
            summaries.append((label, summary))
            completed_labels.append(label)
            save()          # persist after each task so a crash never loses data
    except (AbortSession,) + ABORT_EXCEPTIONS:
        aborted = True

    save()

    final_lines = [content.FINAL_ABORTED if aborted else content.FINAL_DONE, ""]
    final_lines += [f"{label}:  {summary}" for label, summary in summaries] or [content.FINAL_NO_TASKS]
    try:
        show_message(win, kb, final_lines, seconds=FINAL_S, allow_skip=True, skip_hint=True)
    except AbortSession:
        pass

    win.close()
    core.quit()


if __name__ == "__main__":
    main()
