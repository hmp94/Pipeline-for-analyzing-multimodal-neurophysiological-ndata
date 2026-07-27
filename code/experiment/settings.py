# -*- coding: utf-8 -*-
"""
settings.py — all TIMING and NUMERIC parameters for the cognitive-task battery.

The companion of content.py: content.py holds every participant-facing STRING,
this file holds every tunable NUMBER. Edit values here to retune the battery —
task/block durations, stimulus and response intervals, trial counts, target
ratio, animation params, ink colours, font sizes, and the session-level
baseline/rest durations. Each task reads its defaults from the matching dict
below (via its get_default_settings()).

Units
-----
* Task times are in MILLISECONDS, EXCEPT SESSION values which end in _s (seconds).
* colours are (R, G, B), 0-255.  font sizes are pixels at a 1080px-tall screen.

Per-task JSON override (Addition / Multiplication / Fairy Tale only)
-------------------------------------------------------------------
Those three tasks still honour an optional <name>_settings.json dropped next to
the script; its keys overlay the defaults here. Stroop / CPT-X / Passive Video
read only from this file.
"""

import copy


def defaults(section):
    """Return a deep copy of a settings section, so callers can mutate freely."""
    return copy.deepcopy(section)


# ─────────────────────────────────────────────────────────────────────────────
# Session-level (run_all_experiments.py) — SECONDS
# ─────────────────────────────────────────────────────────────────────────────
SESSION = {
    # 3-minute continuous baseline, run as timed sub-phases (name, seconds).
    # signal_check -> eyes_open -> blinks -> h_move (horizontal) -> v_move (vertical)
    # -> eyes_closed.  Sum should be 180 s.  (One continuous recording.)
    "baseline_phases": [
        ("signal_check", 10),    # 0-10s   fixation "+", experimenter checks signal
        ("eyes_open", 60),       # 10-70s  eyes-open resting (fixation "+")
        ("blinks", 20),          # 70-90s  controlled eye blinks (n = baseline_n_blinks)
        ("h_move", 15),          # 90-105s horizontal eye movements (left-centre-right-centre)
        ("v_move", 15),          # 105-120 vertical eye movements (up-centre-down-centre)
        ("eyes_closed", 60),     # 120-180 eyes-closed resting (alpha check)
    ],
    "baseline_n_blinks": 5,      # number of guided blinks in the blink phase
    "rest_s": 60.0,              # rest between tasks (1 min)
    "countdown_s": 3,           # short "3..1" countdown after the SPACE-to-start instruction, before the task
    "welcome_s": 10.0,           # baseline-intro screen duration (welcome itself waits for SPACE)
    "final_s": 8.0,             # final summary screen (SPACE closes early)
    # "Open your eyes" audio cue at the end of the eyes-closed baseline.
    # Plays beep_file (a WAV next to the scripts) — Windows via winsound, else afplay.
    # If beep_file is missing, falls back to a winsound tone / macOS system sound.
    "beep_file": "beep.wav",    # trimmed beep (silence removed) played on all platforms
    "beep_freq_hz": 1000,       # fallback Windows tone frequency (Hz), 37..32767
    "beep_ms": 500,             # fallback Windows tone duration (ms)
    "beep_sound_mac": "/System/Library/Sounds/Ping.aiff",  # fallback macOS system sound
}


# ─────────────────────────────────────────────────────────────────────────────
# Stroop — ms
# ─────────────────────────────────────────────────────────────────────────────
STROOP = {
    "task_duration": 180000,        # 3 min — whole block (time-based), same as the other tasks
    "num_trials": 24,               # balanced set size (12 congruent + 12 incongruent)
    "fixation_time": 250,           # fixation "+" duration
    "stimulus_time": 250,           # word on-screen duration
    "response_time_limit": 2000,    # response window AFTER the word disappears
    "inter_trial_interval": 500,    # feedback / gap between trials
    "words": {                      # on-screen WORD per colour (Vietnamese)
        "red": "ĐỎ", "blue": "XANH DƯƠNG", "green": "XANH LÁ", "yellow": "VÀNG",
    },
    "colors": {                     # ink colours (R,G,B). Respond C = blue/green, M = red/yellow
        "red": (255, 0, 0), "blue": (0, 0, 255), "green": (0, 255, 0), "yellow": (255, 255, 0),
    },
    "font_sizes": {
        "title": 144, "stimulus": 120, "feedback": 100, "input": 48,
        "instruction": 72, "counter": 36, "settings": 80, "settings_value": 64,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# CPT-X — ms
# ─────────────────────────────────────────────────────────────────────────────
CPT = {
    "task_duration": 180000,   # 3 min
    "stimulus_time": 250,      # letter flash duration
    "soa": 1500,               # onset-to-onset interval (fixed pace); response window
    "target_ratio": 0.30,      # fraction of trials that are the target letter X
    "feedback_ms": 400,        # how long "Đúng"/"Sai" feedback shows after a response
    "font_sizes": {
        "title": 144, "stimulus": 160, "feedback": 120, "instruction": 56, "prompt": 44, "hint": 36,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Passive video — ms (+ optic-flow animation params)
# ─────────────────────────────────────────────────────────────────────────────
PASSIVE_VIDEO = {
    "task_duration": 180000,   # 3 min
    "video_file": "cloud_5min.mp4",  # played (looped) next to the script; None/missing -> optic flow
    "n_dots": 220,             # dots in the optic-flow FALLBACK field (used if no video)
    "flow_speed": 0.75,        # radial expansion per second (larger = faster)
    "dot_size": 0.006,         # base dot size in 'height' units
    "font_sizes": {"instruction": 56, "title": 96},
}


# ─────────────────────────────────────────────────────────────────────────────
# Addition — ms
# ─────────────────────────────────────────────────────────────────────────────
ADDITION = {
    "task_duration": 180000,     # 3 min, whole session
    "feedback_time": 1500,
    "response_window": None,     # ms per problem; None = no per-problem limit
    "min_operand": 100,
    "max_operand": 999,
    "max_input_digits": 5,
    "font_sizes": {
        "title": 144, "stimulus": 110, "feedback": 100,
        "input": 64, "instruction": 56, "hint": 36,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Multiplication — ms
# ─────────────────────────────────────────────────────────────────────────────
MULTIPLICATION = {
    "task_duration": 180000,     # 3 min, whole session
    "feedback_time": 1500,
    "response_window": None,     # no per-problem limit (like Addition) — solve continuously until task_duration
    "min_operand": 10,
    "max_operand": 99,
    "max_input_digits": 5,
    "font_sizes": {
        "title": 144, "stimulus": 110, "feedback": 100,
        "input": 64, "instruction": 56, "hint": 36,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Fairy tale (silent reading) — ms
# ─────────────────────────────────────────────────────────────────────────────
FAIRY_TALE = {
    "task_duration": 180000,     # 3 min
    "chars_per_page": 450,       # kept low so pages with many short (dialogue) paragraphs
                                 # don't overflow the screen vertically
    "font_sizes": {"title": 72, "body": 42, "instruction": 56, "hint": 30},
}
