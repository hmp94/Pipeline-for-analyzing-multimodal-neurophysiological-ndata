"""
Passive visual observation task (PsychoPy).

A passive "watch the moving image" block: the participant simply observes
continuous motion for task_duration (default 180 s) and makes no response.

Output:  results/<participant>_<timestamp>/task.csv     (task_type == "Passive Video")
         event, time_ms      (task_start / task_end / aborted marker rows; the
         "event" value also carries the mode, e.g. "task_start:flow")
         results/<participant>_<timestamp>/metadata.json  (demographics + summary)

Stimulus:
    * If a video file (passive_video.mp4/.mov/.avi/.mkv/.webm) sits next to this
      script it is played on a loop for the whole duration.
    * Otherwise a self-contained radial optic-flow dot field is animated — this
      needs no external asset or codec, so it always runs after `pip install
      psychopy`. Drop a video file in to override it.

Run:     python passive_video_psychopy.py     (ESC aborts; SPACE = experimenter skip)
"""

import os
import sys

import numpy as np
from psychopy import visual, core, gui
from psychopy.hardware import keyboard

import content
import settings as cfg
import experiment_io as expio


# Drawing uses PsychoPy 'height' units (1.0 == window height, y from -0.5 to +0.5),
# so the layout survives any window size and macOS Retina pixel doubling.
REF_H = 1080.0  # font sizes in settings are pixels for a 1080px-tall screen

TASK_LABEL = "Passive Video"
VIDEO_BASENAME = "passive_video"
VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv", ".webm")


def h(px):
    """Pixel size -> 'height' units."""
    return px / REF_H


def make_time_bar(win, width=1.2, y=-0.45, thickness=0.016):
    """Create a depleting time bar; return update(frac) that draws it each frame."""
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
# Parameters — EDIT THESE in settings.py (cfg.PASSIVE_VIDEO): task_duration, and
# the optic-flow fallback params n_dots / flow_speed / dot_size, font sizes.
# --------------------------------------------------------------------------- #
def get_default_settings():
    """The task's default parameters (from settings.py)."""
    return cfg.defaults(cfg.PASSIVE_VIDEO)


def load_settings(settings_file=None):
    """Parameters live in settings.py (cfg.PASSIVE_VIDEO) — nothing is read from disk."""
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


def show_instructions(win, kb, settings, auto_advance_s=20.0):
    """Instruction screen; auto-advances after auto_advance_s seconds.

    A depleting time bar shows the reading time left. ESC aborts. (The participant
    presses SPACE only once, at the start of the whole session, not on each task.)
    """
    fs = settings["font_sizes"]
    white = (255, 255, 255)

    stims = [
        visual.TextStim(win, text=content.PASSIVE_VIDEO["title"], color=white, colorSpace="rgb255",
                        height=h(fs["title"]), pos=(0, 0.28), font="Arial"),
        visual.TextStim(win, text=content.PASSIVE_VIDEO["body"], color=white, colorSpace="rgb255",
                        height=h(fs["instruction"]), pos=(0, -0.02), wrapWidth=1.6, font="Arial"),
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
    """Big N..1 countdown before the block (uniform with the other tasks)."""
    stim = visual.TextStim(win, text="", color=(255, 255, 255), colorSpace="rgb255",
                           height=h(200))
    for count in range(seconds, 0, -1):
        stim.text = str(count)
        stim.draw()
        win.flip()
        core.wait(1.0)


# --------------------------------------------------------------------------- #
# Stimulus
# --------------------------------------------------------------------------- #
def find_video():
    """Path to the passive-observation video next to this script, or None.

    Uses cfg.PASSIVE_VIDEO["video_file"] if set and present; otherwise falls back
    to any passive_video.<ext> drop-in. Returns None -> the optic-flow animation.
    """
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.abspath(__file__))
    cfgname = cfg.PASSIVE_VIDEO.get("video_file")
    if cfgname:
        p = cfgname if os.path.isabs(cfgname) else os.path.join(base, cfgname)
        if os.path.exists(p):
            return p
    for ext in VIDEO_EXTS:
        path = os.path.join(base, VIDEO_BASENAME + ext)
        if os.path.exists(path):
            return path
    return None


def _drain_keys(kb, clock, events):
    """Raises AbortBlock on ESC. (SPACE no longer ends the block early.)"""
    for k in kb.getKeys(["escape"], waitRelease=False):
        if k.name == "escape":
            events.append({"task_type": TASK_LABEL, "event": "aborted",
                           "time_ms": int(round(clock.getTime() * 1000))})
            raise AbortBlock
    return False


def run_flow(win, kb, settings, events, duration_s):
    """Radial optic-flow dot field: dots stream outward from the centre.

    Self-contained (no asset/codec). If the GPU path (ElementArrayStim) is
    unavailable, degrades to a static fixation held for the full duration so the
    block never crashes the session.
    """
    n = int(settings["n_dots"])
    speed = float(settings["flow_speed"])
    base = float(settings["dot_size"])
    try:
        aspect = float(win.size[0]) / float(win.size[1])
    except Exception:
        aspect = 16.0 / 9.0
    half_w = 0.5 * aspect

    xs = np.random.uniform(-half_w, half_w, n)
    ys = np.random.uniform(-0.5, 0.5, n)

    try:
        field = visual.ElementArrayStim(
            win, nElements=n, units="height", elementTex=None, elementMask="circle",
            xys=np.column_stack([xs, ys]), sizes=base, colors=(1, 1, 1))
    except Exception:
        # No shader/GPU support for ElementArrayStim — hold a fixation instead.
        fixation = visual.TextStim(win, text="+", color=(255, 255, 255),
                                   colorSpace="rgb255", height=h(100))
        events.append({"task_type": TASK_LABEL, "event": "task_start:static", "time_ms": 0})
        clock = core.Clock()
        kb.clearEvents()
        while clock.getTime() < duration_s:
            fixation.draw()
            win.flip()
            if _drain_keys(kb, clock, events):
                break
        events.append({"task_type": TASK_LABEL, "event": "task_end",
                       "time_ms": int(round(clock.getTime() * 1000))})
        return

    events.append({"task_type": TASK_LABEL, "event": "task_start:flow", "time_ms": 0})
    clock = core.Clock()
    last = 0.0
    kb.clearEvents()
    while clock.getTime() < duration_s:
        now = clock.getTime()
        dt = now - last
        last = now

        grow = 1.0 + speed * dt
        xs *= grow
        ys *= grow
        out = (np.abs(xs) > half_w) | (np.abs(ys) > 0.5)
        k = int(out.sum())
        if k:
            xs[out] = np.random.uniform(-0.04, 0.04, k)
            ys[out] = np.random.uniform(-0.04, 0.04, k)

        field.xys = np.column_stack([xs, ys])
        r = np.sqrt(xs * xs + ys * ys)
        field.sizes = base * (1.0 + 3.0 * r)   # nearer (larger r) dots look bigger
        field.draw()
        win.flip()

        if _drain_keys(kb, clock, events):
            break

    events.append({"task_type": TASK_LABEL, "event": "task_end",
                   "time_ms": int(round(clock.getTime() * 1000))})


def run_movie(win, kb, path, events, duration_s):
    """Play a looping video for the block. Returns False if it could not start."""
    try:
        # norm units + size (2, 2) stretch the video to fill the whole window,
        # regardless of screen resolution. (units="pix" left it at native size,
        # so a 720p clip showed small and centred on a 1080p screen.)
        movie = visual.MovieStim(win, filename=path, loop=True, units="norm", size=(2, 2))
    except Exception:
        return False

    events.append({"task_type": TASK_LABEL, "event": "task_start:video", "time_ms": 0})
    clock = core.Clock()
    kb.clearEvents()
    try:
        movie.play()
        while clock.getTime() < duration_s:
            movie.draw()
            win.flip()
            if _drain_keys(kb, clock, events):
                break
        try:
            movie.stop()
        except Exception:
            pass
    except Exception:
        return False

    events.append({"task_type": TASK_LABEL, "event": "task_end",
                   "time_ms": int(round(clock.getTime() * 1000))})
    return True


# --------------------------------------------------------------------------- #
# Session entry points
# --------------------------------------------------------------------------- #
def run(win, kb, participant, demographics, settings=None, rows_out=None):
    """Run the passive-observation block in an existing window.

    Shared-window entry point used by the session runner: it does not open a
    dialog, manage the window, or write files. Marker rows are appended to
    rows_out (tagged with task_type); a short summary string is returned. On ESC
    it raises AbortBlock after the collected markers have been placed in rows_out.
    """
    if settings is None:
        settings = ensure_settings_defaults(load_settings())

    duration_s = settings["task_duration"] / 1000.0
    events = []
    try:
        show_instructions(win, kb, settings)
        show_countdown(win, settings, seconds=cfg.SESSION["countdown_s"])
        video = find_video()
        if not (video and run_movie(win, kb, video, events, duration_s)):
            run_flow(win, kb, settings, events, duration_s)
    finally:
        for r in events:
            r.setdefault("task_type", TASK_LABEL)
        if rows_out is not None:
            rows_out.extend(events)

    return content.PASSIVE_VIDEO["summary"]


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

    done = visual.TextStim(win, text=content.PASSIVE_VIDEO["done"], color=(255, 255, 255),
                           colorSpace="rgb255", height=h(72), font="Arial")
    done.draw()
    win.flip()
    core.wait(2.0)

    win.close()
    core.quit()


if __name__ == "__main__":
    main()
