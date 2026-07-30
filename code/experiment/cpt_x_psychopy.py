"""
CPT-X sustained-attention task (PsychoPy).

Output:  results/behaviors/<participant>_<timestamp>/task.csv     (task_type == "CPT-X")
         columns incl. stimulus (the letter), response, reaction_time, correct
         results/behaviors/<participant>_<timestamp>/metadata.json  (demographics + summary)

Task:    single uppercase letters appear one at a time, each flashed for
         stimulus_time (default 250 ms) then blank until the next onset.
         Respond to EVERY letter:
             X            -> press C
             any other    -> press SPACE
         reaction_time is ms from letter ONSET; no response within the trial
         window is logged as response "none" (an omission, scored incorrect).
         The onset-to-onset interval is fixed (soa) so the stream is steady;
         the block runs for task_duration (default 180 s).  There is no
         per-trial feedback — this is a sustained-attention task.

Run:     python cpt_x_psychopy.py     (ESC aborts; partial data is saved)
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

TASK_LABEL = "CPT-X"

# Non-target letters. X is the target; "C" is excluded so the stimulus letter
# never collides visually with the "C" response key.
NON_TARGETS = list("ABDEFGHJKLMNOPRSTUVZ")
TARGET = "X"


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


# --------------------------------------------------------------------------- #
# Parameters — EDIT THESE in settings.py (cfg.CPT): task_duration, stimulus_time
# (letter flash), soa (pace), target_ratio (fraction of X), font sizes.
# --------------------------------------------------------------------------- #
def get_default_settings():
    """The task's default parameters (from settings.py)."""
    return cfg.defaults(cfg.CPT)


def load_settings(settings_file=None):
    """Parameters live in settings.py (cfg.CPT) — nothing is read from disk."""
    return get_default_settings()


def ensure_settings_defaults(settings):
    """Merge loaded settings over defaults so required keys always exist."""
    defaults = get_default_settings()
    merged = {**defaults, **(settings or {})}
    merged["font_sizes"] = {**defaults["font_sizes"], **merged.get("font_sizes", {})}
    return merged


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


def show_instructions(win, kb, settings, auto_advance_s=10.0):
    """Instruction screen; auto-advances after auto_advance_s seconds.

    A depleting time bar (not a number) shows how much reading time is left;
    when it empties the task starts. ESC aborts. (The participant presses SPACE
    only once, at the start of the whole session, not on each task.)
    """
    fs = settings["font_sizes"]
    white = (255, 255, 255)

    stims = [
        visual.TextStim(win, text=content.CPT["title"], color=white, colorSpace="rgb255",
                        height=h(fs["title"]), pos=(0, 0.34), font="Arial"),
        visual.TextStim(win, text=content.CPT["body"], color=white, colorSpace="rgb255",
                        height=h(fs["instruction"]), pos=(0, 0.02), wrapWidth=1.6, font="Arial"),
        visual.TextStim(win, text=content.CPT["target_prompt"], color=(200, 200, 200),
                        colorSpace="rgb255", height=h(fs["prompt"]), pos=(0, -0.24), font="Arial"),
    ]
    hint = visual.TextStim(win, text=content.INSTRUCTION_HINT,
                           color=(160, 160, 160), colorSpace="rgb255",
                           height=h(34), pos=(0, -0.38), font="Arial")
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
    """Big N..1 countdown before the task starts."""
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
def next_letter(settings):
    """Pick the next stimulus letter: X with prob target_ratio, else a non-target."""
    if random.random() < settings["target_ratio"]:
        return TARGET
    return random.choice(NON_TARGETS)


def run_trial(win, kb, letter, trial_number, settings):
    """One CPT trial: flash the letter, collect the first C/SPACE within the SOA.

    Fixed pace: the letter is shown for stimulus_time then the screen is blank
    until `soa` ms after onset, so onset-to-onset spacing is constant regardless
    of when (or whether) the participant responds. Returns a result dict; raises
    AbortBlock on ESC.
    """
    fs = settings["font_sizes"]
    stim_s = settings["stimulus_time"] / 1000.0
    soa_s = settings["soa"] / 1000.0
    is_target = (letter == TARGET)

    glyph = visual.TextStim(win, text=letter, color=(255, 255, 255), colorSpace="rgb255",
                            height=h(fs["stimulus"]))
    fb_correct = visual.TextStim(win, text=content.CPT["feedback_correct"], color=(0, 255, 0),
                                 colorSpace="rgb255", height=h(fs["feedback"]), font="Arial")
    fb_wrong = visual.TextStim(win, text=content.CPT["feedback_wrong"], color=(255, 68, 68),
                               colorSpace="rgb255", height=h(fs["feedback"]), font="Arial")
    feedback_s = settings.get("feedback_ms", 400) / 1000.0

    trial_data = {
        "trial_number": trial_number,
        "stimulus": letter,
        "response": None,
        "reaction_time": None,     # ms from letter ONSET
        "correct": None,
    }

    kb.clearEvents()
    kb.clock.reset()               # t = 0 at letter onset -> RT origin
    clock = core.Clock()
    fb_until = -1.0                # show "Đúng"/"Sai" until this time (set on response)
    while clock.getTime() < soa_s:
        t = clock.getTime()
        if t < stim_s:
            glyph.draw()           # the letter flash
        elif t < fb_until:
            (fb_correct if trial_data["correct"] else fb_wrong).draw()  # brief feedback
        win.flip()                 # otherwise blank until the next onset
        for k in kb.getKeys(["c", "space", "escape"], waitRelease=False):
            if k.name == "escape":
                raise AbortBlock
            if trial_data["response"] is None and k.name in ("c", "space"):
                trial_data["response"] = k.name
                trial_data["reaction_time"] = int(round(k.rt * 1000))
                trial_data["correct"] = (k.name == "c") if is_target else (k.name == "space")
                fb_until = clock.getTime() + feedback_s

    if trial_data["response"] is None:
        trial_data["response"] = "none"          # omission
        trial_data["correct"] = False

    return trial_data


# --------------------------------------------------------------------------- #
# Session entry points
# --------------------------------------------------------------------------- #
def run(win, kb, participant, demographics, settings=None, rows_out=None):
    """Run the CPT-X task in an existing window.

    Shared-window entry point used by the session runner: it does not open a
    dialog, manage the window, or write files. Each trial is appended to
    rows_out (tagged with task_type) so the caller can save it; a short summary
    string is returned. On ESC it raises AbortBlock after the collected trials
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
            trial_results.append(run_trial(win, kb, next_letter(settings),
                                           trial_number, settings))
    finally:
        for r in trial_results:
            r.setdefault("task_type", TASK_LABEL)
        if rows_out is not None:
            rows_out.extend(trial_results)

    correct = sum(1 for tr in trial_results if tr.get("correct"))
    missed = sum(1 for tr in trial_results if tr.get("response") == "none")
    summary = content.CPT["summary"].format(correct=correct, total=len(trial_results))
    if missed:
        summary += content.CPT["summary_missed"].format(n=missed)
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

    done = visual.TextStim(win, text=f"{content.CPT['done']}\n{summary}",
                           color=(255, 255, 255), colorSpace="rgb255", height=h(72),
                           font="Arial")
    done.draw()
    win.flip()
    core.wait(2.0)

    win.close()
    core.quit()


if __name__ == "__main__":
    main()
