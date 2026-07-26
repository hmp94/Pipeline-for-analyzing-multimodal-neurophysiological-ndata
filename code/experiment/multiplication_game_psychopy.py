"""
Mental arithmetic task - multiplication (PsychoPy).

PsychoPy version of the "H2 (Multiply)" task from the NEW_VALID_SUBFOCUS battery
(arithmetic_multiply/): continuously multiply two 2-digit numbers for 2 minutes.

Output:  results/<participant>_<timestamp>/task.csv     (task_type == "Multiplication")
         columns incl. num1, num2, correct_answer, response, reaction_time, correct
         results/<participant>_<timestamp>/metadata.json  (demographics + summary)

Task:    a problem "47 x 58 = ?" stays on screen while the participant types
         the answer (0-9 or numpad); BACKSPACE deletes, ENTER submits.
         Feedback ("Correct!" / "Incorrect! Answer: N") shows for 1500 ms,
         then the next problem appears, until task_duration (default 120 s)
         elapses.  reaction_time is ms from problem onset to ENTER; if the
         session timer expires mid-problem the row is logged with response
         "incomplete".

Run:     python multiplication_game_psychopy.py     (ESC aborts; partial data is saved)
"""

import os
import sys
import json
import random

from psychopy import visual, core, gui
from psychopy.hardware import keyboard

import content
import settings as cfg
import experiment_io as expio


# Drawing uses PsychoPy 'height' units (1.0 == window height, y from -0.5 to +0.5),
# so the layout survives any window size and macOS Retina pixel doubling.
REF_H = 1080.0  # font sizes in settings are pixels for a 1080px-tall screen

TASK_LABEL = "Multiplication"
OPERATOR = "\u00d7"
SETTINGS_FILE = "multiplication_settings.json"

DIGIT_KEYS = {str(d): str(d) for d in range(10)}
DIGIT_KEYS.update({f"num_{d}": str(d) for d in range(10)})
RESPONSE_KEYS = list(DIGIT_KEYS) + ["backspace", "return", "num_enter", "escape"]


def h(px):
    """Pixel size -> 'height' units."""
    return px / REF_H


def make_time_bar(win, width=1.2, y=-0.45, thickness=0.016):
    """Create a depleting time bar; return update(frac) that draws it each frame.

    frac is the fraction of time REMAINING (1.0 = full, 0.0 = empty). The bar
    shrinks from full width toward the left as time runs out and turns red when
    nearly empty (running low = out of time). Call update(frac) before win.flip().
    """
    left = -width / 2.0
    bg = visual.Rect(win, width=width, height=thickness, pos=(0, y),
                     fillColor=(70, 70, 70), lineColor=None, colorSpace="rgb255")
    fg = visual.Rect(win, width=width, height=thickness, pos=(0, y),
                     fillColor=(120, 200, 120), lineColor=None, colorSpace="rgb255")

    def update(frac):
        frac = min(1.0, max(0.0, frac))
        w = max(1e-4, width * frac)
        fg.width = w
        fg.pos = (left + w / 2.0, y)
        fg.fillColor = (210, 120, 120) if frac <= 0.2 else (120, 200, 120)
        bg.draw()
        fg.draw()

    return update


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def resource_path(relative_path):
    """Absolute path to a bundled resource (also works under PyInstaller)."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def get_default_settings():
    """Default parameters (from settings.py, cfg.MULTIPLICATION). A
    multiplication_settings.json dropped next to this script overlays these
    (see load_settings)."""
    return cfg.defaults(cfg.MULTIPLICATION)


def load_settings(settings_file=SETTINGS_FILE):
    """Load the settings file if present, else use defaults."""
    if getattr(sys, "frozen", False):
        settings_path = os.path.join(os.path.dirname(sys.executable), settings_file)
    else:
        settings_path = resource_path(settings_file)
    try:
        with open(settings_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Settings file not found: {settings_path} (using defaults)")
        return get_default_settings()


def ensure_settings_defaults(settings):
    """Merge loaded settings over defaults so required keys always exist."""
    defaults = get_default_settings()
    merged = {**defaults, **(settings or {})}
    merged["font_sizes"] = {**defaults["font_sizes"], **merged.get("font_sizes", {})}
    return merged


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# Screens
# --------------------------------------------------------------------------- #
class AbortBlock(Exception):
    """Participant pressed ESC during the task."""


def get_session_info():
    """Startup dialog (demographics only). Returns (participant, demographics), or None if cancelled."""
    info = {
        "MSSV": "",
        "Age": "",
        "Gender": ["Female", "Male", "Other"],
        "Handedness": ["Right", "Left", "Ambidextrous"],
    }
    order = ["MSSV", "Age", "Gender", "Handedness"]
    dlg = gui.DlgFromDict(info, title=f"{TASK_LABEL} Task", order=order)
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


def show_instructions(win, kb, settings, auto_advance_s=30.0):
    """Instruction screen; auto-advances after auto_advance_s seconds.

    A depleting time bar (not a number) shows how much reading time is left;
    when it empties the task starts. ESC aborts. (The participant presses SPACE
    only once, at the start of the whole session, not on each task.)
    """
    fs = settings["font_sizes"]
    white = (255, 255, 255)

    stims = [
        visual.TextStim(win, text=content.MULTIPLICATION["title"], color=white, colorSpace="rgb255",
                        height=h(fs["title"]), pos=(0, 0.32), font="Arial"),
        visual.TextStim(win, text=content.MULTIPLICATION["body"],
                        color=white, colorSpace="rgb255", height=h(fs["instruction"]),
                        pos=(0, 0.0), wrapWidth=1.6, font="Arial"),
    ]
    hint = visual.TextStim(win, text=content.INSTRUCTION_HINT,
                           color=(160, 160, 160), colorSpace="rgb255",
                           height=h(34), pos=(0, -0.36), font="Arial")
    update_time_bar = make_time_bar(win)

    kb.clearEvents()
    clock = core.Clock()
    while True:
        remaining = auto_advance_s - clock.getTime()
        if remaining <= 0:
            return
        for s in stims:
            s.draw()
        hint.draw()
        update_time_bar(remaining / auto_advance_s)
        win.flip()

        for k in kb.getKeys(["escape"], waitRelease=False):
            if k.name == "escape":
                raise AbortBlock


def show_countdown(win, settings, seconds=10):
    """3-2-1 countdown."""
    stim = visual.TextStim(win, text="", color=(255, 255, 255), colorSpace="rgb255",
                           height=h(200))
    for count in range(seconds, 0, -1):
        stim.text = str(count)
        stim.draw()
        win.flip()
        core.wait(1.0)


# --------------------------------------------------------------------------- #
# Trial
# --------------------------------------------------------------------------- #
def make_problem(settings):
    num1 = random.randint(settings["min_operand"], settings["max_operand"])
    num2 = random.randint(settings["min_operand"], settings["max_operand"])
    return num1, num2, num1 * num2


def run_problem(win, kb, trial_number, settings, task_clock, duration_s):
    """
    One problem: display -> typed response -> feedback.

    Returns (result dict, timed_out flag); raises AbortBlock on ESC.
    """
    fs = settings["font_sizes"]
    num1, num2, answer = make_problem(settings)

    problem = visual.TextStim(win, text=f"{num1} {OPERATOR} {num2} = ?",
                              color=(255, 255, 255), colorSpace="rgb255",
                              height=h(fs["stimulus"]), pos=(0, 0.14))
    box = visual.Rect(win, width=0.34, height=0.10, pos=(0, -0.06),
                      lineColor=(255, 255, 255), fillColor=(51, 51, 51),
                      colorSpace="rgb255", lineWidth=2)
    entry = visual.TextStim(win, text="", color=(255, 255, 255), colorSpace="rgb255",
                            height=h(fs["input"]), pos=(0, -0.06))
    hint = visual.TextStim(win, text=content.MULTIPLICATION["hint"],
                           color=(204, 204, 204), colorSpace="rgb255",
                           height=h(fs["hint"]), pos=(0, -0.30), font="Arial")

    trial_data = {
        "trial_number": trial_number,
        "num1": num1,
        "num2": num2,
        "correct_answer": answer,
        "response": None,
        "reaction_time": None,
        "correct": None,
    }

    response_window = settings.get("response_window")
    resp_limit_s = response_window / 1000.0 if response_window else None

    kb.clearEvents()
    problem_clock = core.Clock()
    user_input = ""
    while True:
        if resp_limit_s is not None:
            remaining = max(0, resp_limit_s - problem_clock.getTime())
            hint.text = content.MULTIPLICATION["hint_countdown"].format(n=int(remaining) + 1)
        problem.draw()
        box.draw()
        entry.text = user_input
        entry.draw()
        hint.draw()
        win.flip()

        for k in kb.getKeys(RESPONSE_KEYS, waitRelease=False):
            if k.name == "escape":
                raise AbortBlock
            if k.name == "backspace":
                user_input = user_input[:-1]
            elif k.name in ("return", "num_enter"):
                if user_input:
                    trial_data["response"] = user_input
                    trial_data["reaction_time"] = int(round(problem_clock.getTime() * 1000))
                    trial_data["correct"] = (int(user_input) == answer)
            elif k.name in DIGIT_KEYS and len(user_input) < settings["max_input_digits"]:
                user_input += DIGIT_KEYS[k.name]

        if trial_data["response"] is not None:
            break
        if task_clock.getTime() >= duration_s:
            trial_data["response"] = "incomplete"
            trial_data["reaction_time"] = int(round(problem_clock.getTime() * 1000))
            trial_data["correct"] = False
            return trial_data, True
        if resp_limit_s is not None and problem_clock.getTime() >= resp_limit_s:
            trial_data["response"] = "timeout"
            trial_data["reaction_time"] = int(round(problem_clock.getTime() * 1000))
            trial_data["correct"] = False
            break

    # --- Feedback ---
    if trial_data["response"] == "timeout":
        # Neutral gray, not amber, so "no response" never reads as a colour cue.
        fb_text, fb_color = content.MULTIPLICATION["feedback_timeout"].format(answer=answer), (180, 180, 180)
    elif trial_data["correct"]:
        fb_text, fb_color = content.MULTIPLICATION["feedback_correct"], (0, 255, 0)
    else:
        fb_text, fb_color = content.MULTIPLICATION["feedback_wrong"].format(answer=answer), (255, 68, 68)
    fb = visual.TextStim(win, text=fb_text, color=fb_color, colorSpace="rgb255",
                         height=h(fs["feedback"]), font="Arial")
    fb.draw()
    win.flip()
    core.wait(settings["feedback_time"] / 1000.0)
    if kb.getKeys(["escape"], waitRelease=False):
        raise AbortBlock

    return trial_data, False


# --------------------------------------------------------------------------- #
# Session entry points
# --------------------------------------------------------------------------- #
def run(win, kb, participant, demographics, settings=None, rows_out=None):
    """Run the task in an existing window.

    Shared-window entry point used by the session runner: it does not open a
    dialog, manage the window, or write files. Each problem is appended to
    rows_out (tagged with task_type) so the caller can save it; a short summary
    string is returned. On ESC it raises AbortBlock after the collected problems
    have been placed in rows_out.
    """
    if settings is None:
        settings = ensure_settings_defaults(load_settings())

    duration_s = settings["task_duration"] / 1000.0
    trial_results = []
    try:
        show_instructions(win, kb, settings)
        show_countdown(win, settings, seconds=cfg.SESSION["countdown_s"])
        task_clock = core.Clock()
        trial_number = 0
        while task_clock.getTime() < duration_s:
            trial_number += 1
            result, timed_out = run_problem(win, kb, trial_number, settings,
                                            task_clock, duration_s)
            trial_results.append(result)
            if timed_out:
                break
    finally:
        for r in trial_results:
            r.setdefault("task_type", TASK_LABEL)
        if rows_out is not None:
            rows_out.extend(trial_results)

    correct = sum(1 for tr in trial_results if tr.get("correct"))
    no_resp = sum(1 for tr in trial_results if tr.get("response") == "timeout")
    summary = content.MULTIPLICATION["summary"].format(correct=correct, total=len(trial_results))
    if no_resp:
        summary += content.MULTIPLICATION["summary_timeout"].format(n=no_resp)
    return summary


def main():
    settings = ensure_settings_defaults(load_settings())

    # Dialog first, window second: a dialog opened after the OpenGL window can end
    # up behind it on macOS and never take focus, which looks like a hang.
    session = get_session_info()
    if session is None:
        core.quit()
    participant, demographics = session

    win = visual.Window(size=(1400, 900), fullscr=True, color=(0, 0, 0),
                        colorSpace="rgb255", units="height", allowGUI=True)
    win.mouseVisible = False   # hide the mouse cursor during the task
    kb = keyboard.Keyboard()

    rows, summary, aborted = [], "", False
    try:
        summary = run(win, kb, participant, demographics, settings, rows_out=rows)
    except AbortBlock:
        aborted = True

    session_id, session_dir = expio.make_session_dir(participant)
    expio.save_session(session_dir, rows, expio.build_metadata(
        session_id, demographics, task_order=[TASK_LABEL],
        completed=[] if aborted else [TASK_LABEL], aborted=aborted,
        results={TASK_LABEL: summary}))

    done = visual.TextStim(win, text=f"{content.MULTIPLICATION['done']}\n{summary}",
                           color=(255, 255, 255), colorSpace="rgb255", height=h(72),
                           font="Arial")
    done.draw()
    win.flip()
    core.wait(2.0)

    win.close()
    core.quit()


if __name__ == "__main__":
    main()
