"""
run_all_experiments.py — single-session runner for the four cognitive tasks.

Shows ONE demographics dialog, opens ONE window, then runs all four tasks
(Stroop, Addition, Multiplication, Fairy Tale) back-to-back in a RANDOMIZED
order. Transitions are automatic: after the demographics dialog the participant
never has to press a key to advance — each screen counts down and moves on by
itself. SPACE is only an optional early-skip for the experimenter; ESC aborts
the whole session (all data collected so far is saved).

Because every task shares the one window, the screen never flashes between
tasks — useful when EEG/fNIRS/PPG are recording continuously.

Output (in ./results/):
  Game Result - <participant> <Task>.csv        one per task (as when run alone)
  Game Result - <participant> <Task> info.json  one per task
  Game Result - <participant> Session.json      session manifest (order + status)

Run:  python run_all_experiments.py
"""

import os
import sys
import json
import random
from datetime import datetime

from psychopy import visual, core, gui
from psychopy.hardware import keyboard

# Sibling task modules live next to this file.
CODE_DIR = os.path.dirname(os.path.abspath(__file__))
if CODE_DIR not in sys.path:
    sys.path.insert(0, CODE_DIR)

import stroop_game_psychopy as stroop
import addition_game_psychopy as addition
import multiplication_game_psychopy as multiplication
import fairy_tale_psychopy as fairy_tale


REF_H = 1080.0                 # font sizes below are pixels for a 1080px-tall screen
INTER_TASK_REST_S = 5.0        # auto-advancing gap shown before each task
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


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
def write_session_manifest(participant, demographics, order_labels,
                           completed=None, aborted=False, results=None,
                           results_dir_name="results"):
    """Write/overwrite the session manifest recording the randomized order and status."""
    try:
        base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
        results_dir = os.path.join(base_dir, results_dir_name)
        os.makedirs(results_dir, exist_ok=True)

        filepath = os.path.join(results_dir, f"Game Result - {participant} Session.json")
        payload = {
            "session": "cognitive-battery",
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "task_order": order_labels,
            "completed": completed if completed is not None else [],
            "aborted": aborted,
            "results": results if results is not None else {},
            **(demographics or {}),
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"Saved: {filepath}")
    except Exception as e:
        print(f"Failed to write session manifest: {e}")


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
    order_labels = [m.TASK_LABEL for m in order]
    print(f"Session order: {' -> '.join(order_labels)}")
    write_session_manifest(participant, demographics, order_labels)

    win = visual.Window(size=(1400, 900), fullscr=False, color=(0, 0, 0),
                        colorSpace="rgb255", units="height", allowGUI=True)
    kb = keyboard.Keyboard()

    summaries = []          # (label, summary string) per completed task
    completed_labels = []
    aborted = False
    try:
        show_message(
            win, kb,
            ["Welcome",
             "",
             "Four short tasks will run one after another.",
             "They begin automatically — just follow the",
             "instructions shown before each task."],
            seconds=WELCOME_S,
        )
        for i, module in enumerate(order):
            label = module.TASK_LABEL
            show_message(
                win, kb,
                [f"Task {i + 1} of {len(order)}", "", f"Next: {label}", "Get ready…"],
                seconds=INTER_TASK_REST_S,
            )
            summary = module.run(win, kb, participant, demographics)
            summaries.append((label, summary))
            completed_labels.append(label)
    except (AbortSession,) + ABORT_EXCEPTIONS:
        aborted = True

    write_session_manifest(participant, demographics, order_labels,
                           completed=completed_labels, aborted=aborted,
                           results=dict(summaries))

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
