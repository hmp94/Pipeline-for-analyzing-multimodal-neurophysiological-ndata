"""
run_all_experiments.py — single-session runner for the focus-state protocol.

This is a self-contained 4-task experiment. Its timeline follows the participant
instruction document ("Hướng dẫn thực hiện thử nghiệm trạng thái tập trung"); it
is NOT the acquisition software behind the 12-task battery that code/analysis/
processes, so it does not read from or need to match code/analysis/metadata.py.

Shows ONE demographics dialog, opens ONE window, then runs:

    baseline (eyes open, 120 s)
      -> countdown (10 s) -> task 1 (120 s)
      -> rest (60 s) -> countdown (10 s) -> task 2 (120 s)
      -> rest (60 s) -> countdown (10 s) -> task 3 ...

The four cognitive tasks (Stroop, Addition, Multiplication, Fairy Tale) run in a
RANDOMIZED order; each lasts ~120 s. There is NO rest before the first task (the
baseline flows straight into the first countdown), and NO rest after the last.

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

import experiment_io as expio
import stroop_game_psychopy as stroop
import addition_game_psychopy as addition
import multiplication_game_psychopy as multiplication
import fairy_tale_psychopy as fairy_tale


REF_H = 1080.0                 # font sizes below are pixels for a 1080px-tall screen
BASELINE_S = 120.0             # resting baseline, eyes open (per the instruction doc)
REST_S = 60.0                  # rest between tasks, 1 min (per the instruction doc)
WELCOME_S = 6.0                # auto-advancing welcome screen
FINAL_S = 8.0                  # final summary screen (SPACE closes early)

# The four tasks. Order is randomized per session.
TASKS = [stroop, addition, multiplication, fairy_tale]

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
        "Participant": "",
        "Age": "",
        "Gender": ["Female", "Male", "Other"],
        "Handedness": ["Right", "Left", "Ambidextrous"],
    }
    order = ["Participant", "Age", "Gender", "Handedness"]
    dlg = gui.DlgFromDict(info, title="Cognitive Task Session", order=order)
    if not dlg.OK:
        return None

    participant = (info["Participant"] or "anonymous").strip() or "anonymous"
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
def show_message(win, kb, lines, seconds, countdown=True, allow_skip=True):
    """Auto-advancing message screen.

    Displays `lines` (a list of strings) for `seconds`, then returns. With
    countdown=True a live "Continuing in N…" footer shows the remaining time.
    SPACE returns early when allow_skip is set; ESC raises AbortSession.
    """
    body = visual.TextStim(win, text="\n".join(lines), color=(255, 255, 255),
                           colorSpace="rgb255", height=h(60), pos=(0, 0.06),
                           wrapWidth=1.6, alignText="center")
    footer = visual.TextStim(win, text="", color=(160, 160, 160), colorSpace="rgb255",
                             height=h(34), pos=(0, -0.40))

    kb.clearEvents()
    clock = core.Clock()
    while True:
        remaining = seconds - clock.getTime()
        if remaining <= 0:
            return
        if countdown:
            footer.text = f"Continuing in {int(remaining) + 1}…"
        elif allow_skip:
            footer.text = "Press SPACE to finish"
        body.draw()
        if footer.text:
            footer.draw()
        win.flip()

        for k in kb.getKeys(["space", "escape"], waitRelease=False):
            if k.name == "escape":
                raise AbortSession
            if k.name == "space" and allow_skip:
                return


def run_baseline(win, kb, rows_out, seconds=BASELINE_S):
    """Resting baseline: eyes open, no task, for `seconds`.

    Shows a fixation cross with a short reminder and holds for the full duration.
    SPACE is an experimenter early-skip; ESC raises AbortSession. Logs
    baseline_start / baseline_end marker rows into rows_out.
    """
    fixation = visual.TextStim(win, text="+", color=(255, 255, 255),
                               colorSpace="rgb255", height=h(100), pos=(0, 0.02))
    caption = visual.TextStim(win, text="Baseline — eyes open, relax, stay still",
                              color=(160, 160, 160), colorSpace="rgb255",
                              height=h(40), pos=(0, -0.34))

    events = [{"task_type": "Baseline", "event": "baseline_start", "time_ms": 0}]
    kb.clearEvents()
    clock = core.Clock()
    skipped = False
    while clock.getTime() < seconds:
        fixation.draw()
        caption.draw()
        win.flip()
        for k in kb.getKeys(["space", "escape"], waitRelease=False):
            if k.name == "escape":
                events.append({"task_type": "Baseline", "event": "baseline_aborted",
                               "time_ms": int(round(clock.getTime() * 1000))})
                rows_out.extend(events)
                raise AbortSession
            if k.name == "space":
                skipped = True
        if skipped:
            break

    events.append({"task_type": "Baseline", "event": "baseline_end",
                   "time_ms": int(round(clock.getTime() * 1000))})
    rows_out.extend(events)
    return "recorded"


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

    win = visual.Window(size=(1400, 900), fullscr=False, color=(0, 0, 0),
                        colorSpace="rgb255", units="height", allowGUI=True)
    kb = keyboard.Keyboard()

    try:
        show_message(
            win, kb,
            ["Welcome",
             "",
             "First a short baseline (sit still, eyes open),",
             "then four short tasks, one after another.",
             "Everything begins automatically — just follow",
             "the instructions shown before each task."],
            seconds=WELCOME_S,
        )

        # F0 resting baseline — first, no rest before it.
        show_message(
            win, kb,
            ["Baseline", "",
             "Sit still and keep your eyes open.",
             "Relax but stay awake. Do not press any key.",
             "Recording starts when the + appears."],
            seconds=WELCOME_S,
        )
        summaries.append(("Baseline", run_baseline(win, kb, all_rows)))
        completed_labels.append("Baseline")
        save()

        for i, module in enumerate(order):
            label = module.TASK_LABEL
            if i > 0:
                # Rest only BETWEEN tasks (never before the first). The 10 s
                # pre-focus is each task's own countdown, shown inside module.run.
                show_message(
                    win, kb,
                    ["Rest", "",
                     "Sit still, eyes open, relax.",
                     "The next task will start shortly."],
                    seconds=REST_S,
                )
            summary = module.run(win, kb, participant, demographics, rows_out=all_rows)
            summaries.append((label, summary))
            completed_labels.append(label)
            save()          # persist after each task so a crash never loses data
    except (AbortSession,) + ABORT_EXCEPTIONS:
        aborted = True

    save()

    final_lines = ["Session ended early" if aborted else "All tasks complete!", ""]
    final_lines += [f"{label}:  {summary}" for label, summary in summaries] or ["(no tasks recorded)"]
    try:
        show_message(win, kb, final_lines, seconds=FINAL_S, countdown=False, allow_skip=True)
    except AbortSession:
        pass

    win.close()
    core.quit()


if __name__ == "__main__":
    main()
