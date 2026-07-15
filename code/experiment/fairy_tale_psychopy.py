"""
Story reading task - fairy tale (PsychoPy).

PsychoPy version of the "L2 (Story)" task from the NEW_VALID_SUBFOCUS battery,
which opened a Vietnamese fairy tale web page (Nguyen Khoa Dang) to read for
2 minutes.  Here the story is shown as pages of text in a PsychoPy window.

Output:  ./results/"Game Result - <participant> Fairy Tale.csv"
         event, page, time_ms      (task_start / page_view / task_end rows)
         ./results/"Game Result - <participant> Fairy Tale info.json"  (demographics)

Task:    read silently.  SPACE or RIGHT arrow -> next page, LEFT -> previous.
         The task ends automatically after task_duration (default 120 s).
         To use a different story, put a fairy_tale.txt next to this script:
         first non-empty line = title, then blank-line-separated paragraphs.

Run:     python fairy_tale_psychopy.py     (ESC aborts; the event log is saved)
"""

import os
import sys
import csv
import json
from datetime import datetime

from psychopy import visual, core, gui
from psychopy.hardware import keyboard


# Drawing uses PsychoPy 'height' units (1.0 == window height, y from -0.5 to +0.5),
# so the layout survives any window size and macOS Retina pixel doubling.
REF_H = 1080.0  # font sizes in settings are pixels for a 1080px-tall screen

TASK_LABEL = "Fairy Tale"
SETTINGS_FILE = "fairy_tale_settings.json"
STORY_FILE = "fairy_tale.txt"

DEFAULT_TITLE = "Nguyễn Khoa Đăng"

DEFAULT_STORY = """
Ngày xưa, có một vị quan tên là Nguyễn Khoa Đăng, nổi tiếng thông minh chính trực, xét xử công minh, được nhân dân khắp nơi kính phục.

Một hôm, có anh hàng dầu gánh hàng ra chợ bán. Trong lúc mải đong dầu cho khách, anh bị kẻ gian thò tay vào bị lấy trộm tiền. Khi biết mình mất tiền, anh hàng dầu nhớ lại lúc ấy chỉ có một người mù quanh quẩn bên gánh hàng, liền sinh nghi, giữ người ấy lại nhờ quan phân xử.

Người mù một mực kêu oan, nói rằng mình bị vu oan. Quan Nguyễn Khoa Đăng ngẫm nghĩ một lát rồi sai lính múc một chậu nước trong, bảo người mù bỏ hết tiền trong túi vào chậu. Lát sau, trên mặt nước nổi lên một lớp váng dầu loang loáng. Thì ra tiền ấy đúng là tiền của anh hàng dầu: tay anh quanh năm dính dầu nên đồng tiền cũng dính dầu theo. Kẻ gian hết đường chối cãi.

Quan lại nghi người ấy giả mù, bèn sai lính nọc ra đánh. Mới được vài roi, hắn đau quá, vội mở cả hai mắt van xin tha tội. Trước chứng cứ rõ ràng, hắn đành cúi đầu nhận tội. Dân chúng ai nấy đều khen quan xử án như thần.

Thuở ấy, ở phía nam có một vùng truông rậm rạp gọi là truông nhà Hồ, bọn cướp hung dữ tụ tập, người qua lại thường bị cướp bóc, ai nấy đều khiếp sợ. Nguyễn Khoa Đăng quyết trừ cho được bọn cướp này. Ông sai đóng những chiếc hòm gỗ kín có lỗ thông hơi, vừa một người ngồi, rồi chọn các võ sĩ giỏi nhất cho ngồi vào hòm mang theo vũ khí. Đoạn ông sai quân lính ăn mặc giả làm dân thường khiêng hòm đi qua truông, lại phao tin rằng có quan lớn sắp qua truông với nhiều hòm của cải quý giá.

Quả nhiên bọn cướp mắc mưu, đổ ra khiêng các hòm về tận sào huyệt. Về đến nơi, vừa đặt hòm xuống, các võ sĩ trong hòm nhất loạt tung nắp nhảy ra, đánh cho bọn cướp không kịp trở tay. Quân triều đình theo dấu hiệu đã hẹn trước cũng ập đến vây kín, bắt gọn cả bọn.

Dẹp xong bọn cướp, Nguyễn Khoa Đăng còn cho khai khẩn đất hoang hai bên truông, lập làng lập xóm, từ đó con đường qua truông nhà Hồ trở nên yên bình, dân cư ngày một đông đúc.

Người đời sau còn truyền lại câu ca:
"Thương em anh cũng muốn vô,
Sợ truông nhà Hồ, sợ phá Tam Giang.
Phá Tam Giang ngày rày đã cạn,
Truông nhà Hồ, Nội tán cấm nghiêm."

Nhờ tài trí và lòng thương dân, Nguyễn Khoa Đăng được nhân dân đời đời nhớ ơn, tiếng thơm còn lưu mãi đến ngày nay.
"""


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
        "task_duration": 120000,   # ms
        "chars_per_page": 650,
        "font_sizes": {
            "title": 72,
            "body": 42,
            "instruction": 56,
            "hint": 30,
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
# Story
# --------------------------------------------------------------------------- #
def load_story(story_file=STORY_FILE):
    """(title, body) from fairy_tale.txt if present, else the built-in story."""
    if getattr(sys, "frozen", False):
        story_path = os.path.join(os.path.dirname(sys.executable), story_file)
    else:
        story_path = resource_path(story_file)
    try:
        with open(story_path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        title, _, body = text.partition("\n")
        if body.strip():
            return title.strip(), body.strip()
        return DEFAULT_TITLE, text
    except FileNotFoundError:
        return DEFAULT_TITLE, DEFAULT_STORY.strip()


def paginate(text, chars_per_page):
    """Split blank-line-separated paragraphs into pages of roughly equal length."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    pages, current = [], ""
    for p in paragraphs:
        if current and len(current) + len(p) > chars_per_page:
            pages.append(current)
            current = p
        else:
            current = f"{current}\n\n{p}" if current else p
    if current:
        pages.append(current)
    return pages or [text]


# --------------------------------------------------------------------------- #
# Results
# --------------------------------------------------------------------------- #
def write_results_csv(events, participant_name="anonymous", results_dir_name="results"):
    """Write the page-view event log to ./results/."""
    try:
        base_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
        results_dir = os.path.join(base_dir, results_dir_name)
        os.makedirs(results_dir, exist_ok=True)

        filepath = os.path.join(results_dir, f"Game Result - {participant_name} {TASK_LABEL}.csv")

        fieldnames = ["event", "page", "time_ms"]
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for ev in (events or []):
                writer.writerow({k: ev.get(k) for k in fieldnames})
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


def show_instructions(win, kb, settings):
    """Instruction screen. SPACE continues, ESC aborts."""
    fs = settings["font_sizes"]
    white = (255, 255, 255)

    stims = [
        visual.TextStim(win, text="Story Reading", color=white, colorSpace="rgb255",
                        height=h(fs["title"]), pos=(0, 0.32)),
        visual.TextStim(win,
                        text=("Read the story silently at your own pace.\n\n"
                              "SPACE or RIGHT arrow: next page\n"
                              "LEFT arrow: previous page\n\n"
                              "The task ends automatically."),
                        color=white, colorSpace="rgb255", height=h(fs["instruction"]),
                        pos=(0, 0.0), wrapWidth=1.6),
        visual.TextStim(win, text="Press SPACE to start...", color=white,
                        colorSpace="rgb255", height=h(fs["instruction"]),
                        pos=(0, -0.38), wrapWidth=1.6),
    ]

    kb.clearEvents()
    while True:
        for s in stims:
            s.draw()
        win.flip()

        for k in kb.getKeys(["space", "escape"], waitRelease=False):
            if k.name == "escape":
                raise AbortBlock
            if k.name == "space":
                return


# --------------------------------------------------------------------------- #
# Reading loop
# --------------------------------------------------------------------------- #
def run_reading(win, kb, title, pages, settings, events):
    """Show the story pages until task_duration elapses; raises AbortBlock on ESC."""
    fs = settings["font_sizes"]
    duration_s = settings["task_duration"] / 1000.0

    title_stim = visual.TextStim(win, text=title, color=(255, 215, 0), colorSpace="rgb255",
                                 height=h(fs["title"]), pos=(0, 0.40), font="Arial", bold=True)
    body_stim = visual.TextStim(win, text="", color=(255, 255, 255), colorSpace="rgb255",
                                height=h(fs["body"]), pos=(0, -0.02), wrapWidth=1.5,
                                alignText="left", font="Arial")
    hint_stim = visual.TextStim(win, text="", color=(150, 150, 150), colorSpace="rgb255",
                                height=h(fs["hint"]), pos=(0, -0.46), font="Arial")

    task_clock = core.Clock()
    events.append({"event": "task_start", "page": "", "time_ms": 0})

    page_idx = 0
    shown_page = None
    kb.clearEvents()
    while task_clock.getTime() < duration_s:
        if page_idx != shown_page:
            body_stim.text = pages[page_idx]
            hint_stim.text = f"SPACE / →  next page      ←  previous      ({page_idx + 1}/{len(pages)})"
            events.append({"event": "page_view", "page": page_idx + 1,
                           "time_ms": int(round(task_clock.getTime() * 1000))})
            shown_page = page_idx

        title_stim.draw()
        body_stim.draw()
        hint_stim.draw()
        win.flip()

        for k in kb.getKeys(["space", "right", "left", "escape"], waitRelease=False):
            if k.name == "escape":
                events.append({"event": "aborted", "page": page_idx + 1,
                               "time_ms": int(round(task_clock.getTime() * 1000))})
                raise AbortBlock
            if k.name in ("space", "right"):
                page_idx = min(page_idx + 1, len(pages) - 1)
            elif k.name == "left":
                page_idx = max(page_idx - 1, 0)

    events.append({"event": "task_end", "page": page_idx + 1,
                   "time_ms": int(round(task_clock.getTime() * 1000))})


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    settings = ensure_settings_defaults(load_settings())
    title, body = load_story()
    pages = paginate(body, settings["chars_per_page"])

    # Dialog first, window second: a dialog opened after the OpenGL window can end
    # up behind it on macOS and never take focus, which looks like a hang.
    session = get_session_info()
    if session is None:
        core.quit()
    participant, demographics = session

    win = visual.Window(size=(1400, 900), fullscr=False, color=(0, 0, 0),
                        colorSpace="rgb255", units="height", allowGUI=True)
    kb = keyboard.Keyboard()

    events = []
    try:
        show_instructions(win, kb, settings)
        run_reading(win, kb, title, pages, settings, events)
    except AbortBlock:
        pass  # keep the event log collected so far

    write_results_csv(events, participant)
    write_participant_info(demographics, participant)

    done = visual.TextStim(win, text="Story Complete!", color=(255, 255, 255),
                           colorSpace="rgb255", height=h(72))
    done.draw()
    win.flip()
    core.wait(2.0)

    win.close()
    core.quit()


if __name__ == "__main__":
    main()
