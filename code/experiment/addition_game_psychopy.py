"""
Mental arithmetic task - addition (PsychoPy).

PsychoPy version of the "H1 (Sum)" task from the NEW_VALID_SUBFOCUS battery
(arithmetic/): continuously sum two 3-digit numbers for 2 minutes.

Output:  ./results/"Game Result - <participant> Addition.csv"
         trial_number, num1, num2, correct_answer, response, reaction_time, correct
         ./results/"Game Result - <participant> Addition info.json"  (demographics)

Task:    a problem "473 + 258 = ?" stays on screen while the participant types
         the answer (0-9 or numpad); BACKSPACE deletes, ENTER submits.
         Feedback ("Correct!" / "Incorrect! Answer: N") shows for 1500 ms,
         then the next problem appears, until task_duration (default 120 s)
         elapses.  reaction_time is ms from problem onset to ENTER; if the
         session timer expires mid-problem the row is logged with response
         "incomplete".

Run:     python addition_game_psychopy.py     (ESC aborts; partial data is saved)
"""

import os
import sys
import csv
import json
import random
from datetime import datetime

from psychopy import visual, core, gui
from psychopy.hardware import keyboard


# Drawing uses PsychoPy 'height' units (1.0 == window height, y from -0.5 to +0.5),
# so the layout survives any window size and macOS Retina pixel doubling.
REF_H = 1080.0  # font sizes in settings are pixels for a 1080px-tall screen

TASK_LABEL = "Addition"
OPERATOR = "+"
SETTINGS_FILE = "addition_settings.json"

DIGIT_KEYS = {str(d): str(d) for d in range(10)}
DIGIT_KEYS.update({f"num_{d}": str(d) for d in range(10)})
RESPONSE_KEYS = list(DIGIT_KEYS) + ["backspace", "return", "num_enter", "escape"]


def h(px):
    """Pixel size -> 'height' units."""
    return px / REF_H


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def resource_path(relative_path):
    """Absolute path to a bundled resource (also works under PyInstaller)."""
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


def get_default_settings():
    return {
        "task_duration": 120000,     # ms, whole session
        "feedback_time": 1500,       # ms
        "response_window": None,     # ms per problem; None = no per-problem limit
        "min_operand": 100,
        "max_operand": 999,
        "max_input_digits": 5,
        "font_sizes": {
            "title": 144,
            "stimulus": 110,
            "feedback": 100,
            "input": 64,
            "instruction": 56,
            "hint": 36,
        },
    }


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
def write_results_csv(trial_results, participant_name="anonymous", results_dir_name="results"):
    """Write one row per problem to ./results/."""
    try:
        base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
        results_dir = os.path.join(base_dir, results_dir_name)
        os.makedirs(results_dir, exist_ok=True)

        filepath = os.path.join(results_dir, f"Game Result - {participant_name} {TASK_LABEL}.csv")

        fieldnames = ["task_type", "trial_number", "num1", "num2", "correct_answer", "response",
                      "reaction_time", "correct"]
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for tr in (trial_results or []):
                row = {k: tr.get(k) for k in fieldnames}
                row["task_type"] = TASK_LABEL
                writer.writerow(row)
        print(f"Saved: {filepath}")
    except Exception as e:
        print(f"Failed to write results CSV: {e}")


def write_participant_info(demographics, participant_name="anonymous", task_label=TASK_LABEL,
                           results_dir_name="results"):
    """Write the demographics entered at startup next to the results CSV."""
    try:
        base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
        results_dir = os.path.join(base_dir, results_dir_name)
        os.makedirs(results_dir, exist_ok=True)

        filepath = os.path.join(results_dir, f"Game Result - {participant_name} {task_label} info.json")
        payload = {"task": task_label, "saved_at": datetime.now().isoformat(timespec="seconds"),
                   **(demographics or {})}
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"Saved: {filepath}")
    except Exception as e:
        print(f"Failed to write participant info: {e}")


# --------------------------------------------------------------------------- #
# Screens
# --------------------------------------------------------------------------- #
class AbortBlock(Exception):
    """Participant pressed ESC during the task."""


def get_session_info():
    """Startup dialog (demographics only). Returns (participant, demographics), or None if cancelled."""
    info = {
        "Participant": "",
        "Age": "",
        "Gender": ["Female", "Male", "Other"],
        "Handedness": ["Right", "Left", "Ambidextrous"],
    }
    order = ["Participant", "Age", "Gender", "Handedness"]
    dlg = gui.DlgFromDict(info, title=f"{TASK_LABEL} Task", order=order)
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


def show_instructions(win, kb, settings, auto_advance_s=7.0):
    """Instruction screen; auto-advances after auto_advance_s seconds.

    No key press is required to proceed. SPACE skips the wait early; ESC aborts.
    """
    fs = settings["font_sizes"]
    white = (255, 255, 255)

    footer = visual.TextStim(win, text="", color=white, colorSpace="rgb255",
                             height=h(fs["instruction"]), pos=(0, -0.38), wrapWidth=1.6)
    stims = [
        visual.TextStim(win, text=TASK_LABEL, color=white, colorSpace="rgb255",
                        height=h(fs["title"]), pos=(0, 0.32)),
        visual.TextStim(win,
                        text=("Add the two numbers shown on screen.\n\n"
                              "Type your answer with the number keys.\n"
                              "BACKSPACE deletes a digit, ENTER submits.\n\n"
                              "Keep solving problems until the time runs out."),
                        color=white, colorSpace="rgb255", height=h(fs["instruction"]),
                        pos=(0, 0.0), wrapWidth=1.6),
    ]

    kb.clearEvents()
    clock = core.Clock()
    while True:
        remaining = auto_advance_s - clock.getTime()
        if remaining <= 0:
            return
        footer.text = f"Starting in {int(remaining) + 1}…"
        for s in stims:
            s.draw()
        footer.draw()
        win.flip()

        for k in kb.getKeys(["space", "escape"], waitRelease=False):
            if k.name == "escape":
                raise AbortBlock
            if k.name == "space":
                return


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
    return num1, num2, num1 + num2


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
    hint = visual.TextStim(win, text="Type answer and press ENTER",
                           color=(204, 204, 204), colorSpace="rgb255",
                           height=h(fs["hint"]), pos=(0, -0.30))

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
            hint.text = f"Type answer and press ENTER   ({int(remaining) + 1}s left)"
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
        fb_text, fb_color = f"No response — Answer: {answer}", (255, 200, 0)
    elif trial_data["correct"]:
        fb_text, fb_color = "Correct!", (0, 255, 0)
    else:
        fb_text, fb_color = f"Incorrect! Answer: {answer}", (255, 68, 68)
    fb = visual.TextStim(win, text=fb_text, color=fb_color, colorSpace="rgb255",
                         height=h(fs["feedback"]))
    fb.draw()
    win.flip()
    core.wait(settings["feedback_time"] / 1000.0)
    if kb.getKeys(["escape"], waitRelease=False):
        raise AbortBlock

    return trial_data, False


# --------------------------------------------------------------------------- #
# Session entry points
# --------------------------------------------------------------------------- #
def run(win, kb, participant, demographics, settings=None):
    """Run the task in an existing window and write results.

    Shared-window entry point used by the session runner: it does not open a
    dialog or manage the window. Returns a short summary string. On ESC it
    raises AbortBlock after the collected problems have been saved.
    """
    if settings is None:
        settings = ensure_settings_defaults(load_settings())

    duration_s = settings["task_duration"] / 1000.0
    trial_results = []
    try:
        show_instructions(win, kb, settings)
        show_countdown(win, settings, seconds=10)
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
        write_results_csv(trial_results, participant)
        write_participant_info(demographics, participant)

    correct = sum(1 for tr in trial_results if tr.get("correct"))
    no_resp = sum(1 for tr in trial_results if tr.get("response") == "timeout")
    summary = f"{correct}/{len(trial_results)} correct"
    if no_resp:
        summary += f", {no_resp} no response"
    return summary


def main():
    settings = ensure_settings_defaults(load_settings())

    # Dialog first, window second: a dialog opened after the OpenGL window can end
    # up behind it on macOS and never take focus, which looks like a hang.
    session = get_session_info()
    if session is None:
        core.quit()
    participant, demographics = session

    win = visual.Window(size=(1400, 900), fullscr=False, color=(0, 0, 0),
                        colorSpace="rgb255", units="height", allowGUI=True)
    kb = keyboard.Keyboard()

    summary = ""
    try:
        summary = run(win, kb, participant, demographics, settings)
    except AbortBlock:
        pass  # partial data already saved in run()

    done = visual.TextStim(win, text=f"{TASK_LABEL} Complete!\n{summary}",
                           color=(255, 255, 255), colorSpace="rgb255", height=h(72))
    done.draw()
    win.flip()
    core.wait(2.0)

    win.close()
    core.quit()


if __name__ == "__main__":
    main()
