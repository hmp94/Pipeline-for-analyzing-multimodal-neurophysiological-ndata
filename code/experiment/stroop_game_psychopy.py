"""
Stroop task (PsychoPy).

Output:  results/<participant>_<timestamp>/task.csv     (task_type == "Stroop A")
         columns incl. stimulus, word, color, response,
         reaction_time, reaction_time_from_onset, correct
         results/<participant>_<timestamp>/metadata.json  (demographics + summary)

Task:    fixation -> word shown 250 ms -> 2000 ms response window -> feedback.
         Keys are accepted only after the word disappears.
         Respond to the INK COLOUR: C = blue/green, M = red/yellow.
         reaction_time is ms from stimulus OFFSET (word disappears); a timeout
         logs 2000.  reaction_time_from_onset is ms from stimulus ONSET (word
         appears) = reaction_time + stimulus_time, the standard Stroop RT.
         The block runs for task_duration (default 120 s) — trials are drawn
         from balanced 24-trial sets (12 congruent + 12 incongruent), regenerated
         as needed, until the timer expires; a trial already in progress finishes.
         The startup dialog collects demographics only; durations come from
         settings.json.

Run:     python stroop_game_psychopy.py     (ESC aborts a block; partial data is saved)
"""

import os
import sys
import json
import random

from psychopy import visual, core, gui
from psychopy.hardware import keyboard

import experiment_io as expio


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
        "task_duration": 120000,  # ms, whole block; overrides num_trials as the stop rule
        "num_trials": 24,         # size of each balanced set drawn from during the block
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


def show_instructions(win, kb, settings, auto_advance_s=30.0):
    """Instruction screen; auto-advances after auto_advance_s seconds.

    No key press is required to proceed and no countdown is shown. SPACE skips
    ahead; ESC aborts.
    """
    white = (255, 255, 255)

    # (ink colour, key label, y) — the "COLOR" word is printed in that ink.
    rows = [
        ((0, 0, 255),   "=>  press  C", -0.09),
        ((0, 255, 0),   "=>  press  C", -0.15),
        ((255, 0, 0),   "=>  press  M", -0.21),
        ((255, 255, 0), "=>  press  M", -0.27),
    ]
    gap = 0.012

    stims = [
        visual.TextStim(win, text="Stroop Task", color=white, colorSpace="rgb255",
                        height=h(88), pos=(0, 0.44)),
        visual.TextStim(
            win,
            text=("Respond to the COLOUR OF THE INK, not the word.\n"
                  "\n"
                  "Each word flashes briefly, then disappears.\n"
                  "Keys are ignored while the word is on screen — wait for\n"
                  "it to disappear, then press as fast and accurately as\n"
                  "you can. Give one key press per word."),
            color=white, colorSpace="rgb255", height=h(42),
            pos=(0, 0.20), wrapWidth=1.5, alignText="center"),
        visual.TextStim(win, text="Respond to the ink colour:", color=(200, 200, 200),
                        colorSpace="rgb255", height=h(38), pos=(0, -0.02)),
        visual.TextStim(win, text="The task starts automatically.  Press SPACE to begin now.",
                        color=(160, 160, 160), colorSpace="rgb255", height=h(34),
                        pos=(0, -0.44), wrapWidth=1.7),
    ]
    for colour, tail, y in rows:
        stims.append(visual.TextStim(win, text="COLOR", color=colour, colorSpace="rgb255",
                                     height=h(52), anchorHoriz="right",
                                     alignText="right", pos=(-gap, y)))
        stims.append(visual.TextStim(win, text=tail, color=white, colorSpace="rgb255",
                                     height=h(52), anchorHoriz="left",
                                     alignText="left", pos=(gap, y)))

    kb.clearEvents()
    clock = core.Clock()
    while True:
        if clock.getTime() >= auto_advance_s:
            return
        for s in stims:
            s.draw()
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
        "reaction_time": None,           # ms from stimulus OFFSET (word disappears)
        "reaction_time_from_onset": None,  # ms from stimulus ONSET (word appears)
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
                trial_data["reaction_time_from_onset"] = (
                    trial_data["reaction_time"] + settings["stimulus_time"]
                )
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
            trial_data["reaction_time_from_onset"] = (
                trial_data["reaction_time"] + settings["stimulus_time"]
            )
            trial_data["correct"] = False
            break

    # --- Feedback / ITI ---
    if trial_data["response"] == "timeout":
        fb = visual.TextStim(win, text="No response", color=(255, 200, 0),
                             colorSpace="rgb255", height=h(fs["feedback"]))
    else:
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
def run(win, kb, participant, demographics, settings=None, rows_out=None):
    """Run the Stroop task in an existing window.

    Shared-window entry point used by the session runner: it does not open a
    dialog, manage the window, or write files. Each trial is appended to
    rows_out (tagged with task_type) so the caller can save it; a short summary
    string is returned. On ESC it raises AbortBlock after the collected trials
    have been placed in rows_out.
    """
    if settings is None:
        settings = ensure_settings_defaults(load_settings())

    words = settings.get("words", ["RED", "BLUE", "GREEN", "YELLOW"])
    stimuli_dict = create_stimuli(words, settings["colors"])
    stimuli, trial_order = create_trial_order(stimuli_dict, settings["num_trials"])

    duration_s = settings.get("task_duration", 120000) / 1000.0

    trial_results = []
    try:
        show_instructions(win, kb, settings)
        show_countdown(win, settings, seconds=10)
        # Run for a fixed duration rather than a fixed trial count: draw from the
        # balanced set, regenerating a fresh shuffled set whenever it runs out.
        # The timer is checked between trials, so the last trial finishes cleanly.
        task_clock = core.Clock()
        pool, pool_idx, i = list(trial_order), 0, 0
        while task_clock.getTime() < duration_s:
            if pool_idx >= len(pool):
                _, pool = create_trial_order(stimuli_dict, settings["num_trials"])
                pool_idx = 0
            stim_key = pool[pool_idx]
            pool_idx += 1
            trial_results.append(run_trial(win, kb, stimuli, stim_key, i, settings))
            i += 1
    finally:
        for r in trial_results:
            r.setdefault("task_type", TASK_LABEL)
        if rows_out is not None:
            rows_out.extend(trial_results)

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

    done = visual.TextStim(win, text=f"{TASK_LABEL} Complete!", color=(255, 255, 255),
                           colorSpace="rgb255", height=h(72))
    done.draw()
    win.flip()
    core.wait(2.0)

    win.close()
    core.quit()


if __name__ == "__main__":
    main()
