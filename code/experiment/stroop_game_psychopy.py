"""
Stroop task (PsychoPy).

Output:  ./results/"Game Result - <participant> Stroop A.csv"
         trial_number, stimulus, word, color, response, reaction_time, correct
         ./results/"Game Result - <participant> Stroop A info.json"  (demographics)

Task:    fixation -> word shown 250 ms -> 2000 ms response window -> feedback.
         Keys are accepted only after the word disappears.
         Respond to the INK COLOUR: C = blue/green, M = red/yellow.
         reaction_time is ms from stimulus OFFSET; a timeout logs 2000.
         The startup dialog collects demographics only; trial count and
         timings come from settings.json.

Run:     python stroop_game_psychopy.py     (ESC aborts a block; partial data is saved)
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


TASK_LABEL = "Stroop A"


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
        "words": ["RED", "BLUE", "GREEN", "YELLOW"],
        "colors": {
            "red": (255, 0, 0),
            "blue": (0, 0, 255),
            "green": (0, 255, 0),
            "yellow": (255, 255, 0),
        },
        "num_trials": 24,
        "stimulus_time": 250,
        "inter_trial_interval": 500,
        "fixation_time": 250,
        "response_time_limit": 2000,
        "font_sizes": {
            "title": 144,
            "stimulus": 120,
            "feedback": 100,
            "input": 48,
            "instruction": 72,
            "counter": 36,
            "settings": 80,
            "settings_value": 64,
        },
    }


def load_settings(settings_file="settings.json"):
    """Load settings.json if present, else use defaults."""
    if getattr(sys, "frozen", False):
        settings_path = os.path.join(os.path.dirname(sys.executable), settings_file)
    else:
        settings_path = resource_path(settings_file)
    try:
        with open(settings_path, "r") as f:
            settings = json.load(f)
        settings["colors"] = {k: tuple(v) for k, v in settings["colors"].items()}
        return settings
    except FileNotFoundError:
        print(f"Settings file not found: {settings_path} (using defaults)")
        return get_default_settings()


def ensure_settings_defaults(settings):
    """Merge loaded settings over defaults so required keys always exist."""
    defaults = get_default_settings()
    merged = {**defaults, **(settings or {})}
    merged["colors"] = {**defaults["colors"], **merged.get("colors", {})}
    merged["font_sizes"] = {**defaults["font_sizes"], **merged.get("font_sizes", {})}
    return merged


# --------------------------------------------------------------------------- #
# Stimuli
# --------------------------------------------------------------------------- #
def create_stimuli(words, colors):
    """Congruent (word matches ink) and incongruent stimuli, keyed "WORD_ink"."""
    congruent_stimuli = {}
    incongruent_stimuli = {}
    color_names = list(colors.keys())

    for word in words:
        for color_name in color_names:
            if word.upper() == color_name.upper():
                congruent_stimuli[f"{word}_{color_name}"] = (word, colors[color_name])
            else:
                incongruent_stimuli[f"{word}_{color_name}"] = (word, colors[color_name])

    return {"congruent": congruent_stimuli, "incongruent": incongruent_stimuli}


def create_trial_order(stimuli, num_trials):
    """Per 24 trials: 12 congruent + 12 incongruent, evenly spread, then shuffled."""
    congruent_keys = list(stimuli["congruent"].keys())
    incongruent_keys = list(stimuli["incongruent"].keys())
    all_stimuli = {**stimuli["congruent"], **stimuli["incongruent"]}

    trial_order = []
    for _ in range(max(1, num_trials // 24)):
        set_trials = []
        for keys, per_set in ((congruent_keys, 12), (incongruent_keys, 12)):
            each, remainder = divmod(per_set, len(keys))
            for i, key in enumerate(keys):
                set_trials.extend([key] * (each + (1 if i < remainder else 0)))
        random.shuffle(set_trials)
        trial_order.extend(set_trials)

    return all_stimuli, trial_order


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
def write_results_csv(trial_results, participant_name="anonymous", results_dir_name="results"):
    """Write one row per trial to ./results/."""
    try:
        base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
        results_dir = os.path.join(base_dir, results_dir_name)
        os.makedirs(results_dir, exist_ok=True)

        filepath = os.path.join(results_dir, f"Game Result - {participant_name} Stroop A.csv")

        fieldnames = ["trial_number", "stimulus", "word", "color", "response", "reaction_time", "correct"]
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for tr in (trial_results or []):
                writer.writerow({k: tr.get(k) for k in fieldnames})
        print(f"Saved: {filepath}")
    except Exception as e:
        print(f"Failed to write results CSV: {e}")


def write_participant_info(demographics, participant_name="anonymous", task_label="Stroop A",
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
    """Participant pressed ESC during a block."""


def get_session_info():
    """Startup dialog (demographics only). Returns (participant, demographics), or None if cancelled."""
    info = {
        "Participant": "",
        "Age": "",
        "Gender": ["Female", "Male", "Other"],
        "Handedness": ["Right", "Left", "Ambidextrous"],
    }
    order = ["Participant", "Age", "Gender", "Handedness"]
    dlg = gui.DlgFromDict(info, title="Stroop Test", order=order)
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

    rows = [
        ((0, 0, 255), "=> press C", 0.16),
        ((0, 255, 0), "=> press C", 0.06),
        ((255, 0, 0), "=> press M", -0.04),
        ((255, 255, 0), "=> press M", -0.14),
    ]
    gap = 0.012

    footer = visual.TextStim(win, text="", color=white, colorSpace="rgb255",
                             height=h(fs["instruction"]), pos=(0, -0.40), wrapWidth=1.6)
    stims = [
        visual.TextStim(win, text="Instructions", color=white, colorSpace="rgb255",
                        height=h(fs["title"]), pos=(0, 0.36)),
    ]
    for colour, tail, y in rows:
        stims.append(visual.TextStim(win, text="COLOR", color=colour, colorSpace="rgb255",
                                     height=h(fs["instruction"]), anchorHoriz="right",
                                     alignText="right", pos=(-gap, y)))
        stims.append(visual.TextStim(win, text=tail, color=white, colorSpace="rgb255",
                                     height=h(fs["instruction"]), anchorHoriz="left",
                                     alignText="left", pos=(gap, y)))

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


def show_countdown(win, settings, seconds=3):
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
def run_trial(win, kb, stimuli, stim_key, trial_number, settings):
    """
    One trial: fixation -> stimulus -> response -> feedback.

    Returns a result dict; raises AbortBlock on ESC.
    """
    fs = settings["font_sizes"]
    fixation_time = settings["fixation_time"] / 1000.0
    stimulus_time = settings["stimulus_time"] / 1000.0
    iti = settings["inter_trial_interval"] / 1000.0
    response_limit = settings["response_time_limit"] / 1000.0

    word_text, word_color = stimuli[stim_key]

    fixation = visual.TextStim(win, text="+", color=(255, 255, 255), colorSpace="rgb255",
                               height=h(100))
    word = visual.TextStim(win, text=word_text.upper(), color=word_color,
                           colorSpace="rgb255", height=h(fs["stimulus"]))

    trial_data = {
        "trial_number": trial_number + 1,
        "stimulus": stim_key,
        "word": word_text,
        "color": stim_key.split("_")[1],
        "response": None,
        "reaction_time": None,
        "correct": None,
    }

    def abort_if_escape():
        if kb.getKeys(["escape"], waitRelease=False):
            raise AbortBlock

    # --- Fixation ---
    fixation.draw()
    win.flip()
    core.wait(fixation_time)
    abort_if_escape()

    # --- Stimulus ---
    word.draw()
    win.flip()
    core.wait(stimulus_time)

    # --- Response ---
    win.flip()                # word disappears here
    kb.clearEvents()          # drop presses made while the word was up
    kb.clock.reset()          # t = 0 at stimulus offset -> RT origin
    while True:
        keys = kb.getKeys(["c", "m", "escape"], waitRelease=False)
        for k in keys:
            if k.name == "escape":
                raise AbortBlock
            if k.name in ("c", "m"):
                trial_data["response"] = k.name
                trial_data["reaction_time"] = int(round(k.rt * 1000))
                color_name = trial_data["color"]
                if k.name == "c":
                    trial_data["correct"] = color_name in ("blue", "green")
                else:
                    trial_data["correct"] = color_name in ("red", "yellow")
                break
        if trial_data["response"] is not None:
            break
        if kb.clock.getTime() > response_limit:
            trial_data["response"] = "timeout"
            trial_data["reaction_time"] = settings["response_time_limit"]
            trial_data["correct"] = False
            break

    # --- Feedback / ITI ---
    if trial_data["response"] != "timeout":
        fb = visual.TextStim(win, text="Correct" if trial_data["correct"] else "Wrong",
                             color=(255, 255, 255), colorSpace="rgb255",
                             height=h(fs["feedback"]))
        fb.draw()
    win.flip()
    core.wait(iti)
    abort_if_escape()

    return trial_data


# --------------------------------------------------------------------------- #
# Session entry points
# --------------------------------------------------------------------------- #
def run(win, kb, participant, demographics, settings=None):
    """Run the Stroop task in an existing window and write results.

    Shared-window entry point used by the session runner: it does not open a
    dialog or manage the window. Returns a short summary string. On ESC it
    raises AbortBlock after the collected trials have been saved.
    """
    if settings is None:
        settings = ensure_settings_defaults(load_settings())

    words = settings.get("words", ["RED", "BLUE", "GREEN", "YELLOW"])
    stimuli_dict = create_stimuli(words, settings["colors"])
    stimuli, trial_order = create_trial_order(stimuli_dict, settings["num_trials"])

    trial_results = []
    try:
        show_instructions(win, kb, settings)
        show_countdown(win, settings, seconds=3)
        for i, stim_key in enumerate(trial_order):
            trial_results.append(
                run_trial(win, kb, stimuli, stim_key, i, settings)
            )
    finally:
        write_results_csv(trial_results, participant)
        write_participant_info(demographics, participant, task_label=TASK_LABEL)

    correct = sum(1 for tr in trial_results if tr.get("correct"))
    return f"{correct}/{len(trial_results)} correct"


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

    try:
        run(win, kb, participant, demographics, settings)
    except AbortBlock:
        pass  # partial data already saved in run()

    done = visual.TextStim(win, text=f"{TASK_LABEL} Complete!", color=(255, 255, 255),
                           colorSpace="rgb255", height=h(72))
    done.draw()
    win.flip()
    core.wait(2.0)

    win.close()
    core.quit()


if __name__ == "__main__":
    main()
