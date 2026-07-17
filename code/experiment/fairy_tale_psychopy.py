"""
Story reading task - fairy tale (PsychoPy).

PsychoPy version of the "L2 (Story)" task from the NEW_VALID_SUBFOCUS battery,
which opened a Vietnamese fairy tale web page (Nguyen Khoa Dang) to read for
2 minutes.  Here the story is shown as pages of text in a PsychoPy window.

Output:  results/<participant>_<timestamp>/task.csv     (task_type == "Fairy Tale")
         event, page, time_ms      (task_start / page_view / task_end rows)
         results/<participant>_<timestamp>/metadata.json  (demographics + summary)

Task:    read silently.  SPACE or RIGHT arrow -> next page, LEFT -> previous.
         The task ends automatically after task_duration (default 120 s).
         To use a different story, put a fairy_tale.txt next to this script:
         first non-empty line = title, then blank-line-separated paragraphs.

Run:     python fairy_tale_psychopy.py     (ESC aborts; the event log is saved)
"""

import os
import sys
import json

from psychopy import visual, core, gui
from psychopy.hardware import keyboard

import content
import experiment_io as expio


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


def show_instructions(win, kb, settings, auto_advance_s=30.0):
    """Instruction screen; auto-advances after auto_advance_s seconds.

    A depleting time bar (not a number) shows how much reading time is left;
    when it empties the task starts. SPACE is an experimenter early-skip; ESC aborts.
    """
    fs = settings["font_sizes"]
    white = (255, 255, 255)

    stims = [
        visual.TextStim(win, text=content.FAIRY_TALE["title"], color=white, colorSpace="rgb255",
                        height=h(fs["title"]), pos=(0, 0.32), font="Arial"),
        visual.TextStim(win, text=content.FAIRY_TALE["body"],
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

        for k in kb.getKeys(["space", "escape"], waitRelease=False):
            if k.name == "escape":
                raise AbortBlock
            if k.name == "space":
                return


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
            hint_stim.text = content.FAIRY_TALE["page_hint"].format(page=page_idx + 1, total=len(pages))
            events.append({"event": "page_view", "page": page_idx + 1,
                           "time_ms": int(round(task_clock.getTime() * 1000))})
            shown_page = page_idx

        if page_idx == 0:
            title_stim.draw()      # yellow title shown on the first page only
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
# Session entry points
# --------------------------------------------------------------------------- #
def run(win, kb, participant, demographics, settings=None, rows_out=None):
    """Run the reading task in an existing window.

    Shared-window entry point used by the session runner: it does not open a
    dialog, manage the window, or write files. Each page-view event is appended
    to rows_out (tagged with task_type) so the caller can save it; a short
    summary string is returned. On ESC it raises AbortBlock after the collected
    events have been placed in rows_out.
    """
    if settings is None:
        settings = ensure_settings_defaults(load_settings())
    title, body = load_story()
    pages = paginate(body, settings["chars_per_page"])

    events = []
    try:
        show_instructions(win, kb, settings)
        show_countdown(win, settings, seconds=10)
        run_reading(win, kb, title, pages, settings, events)
    finally:
        for r in events:
            r.setdefault("task_type", TASK_LABEL)
        if rows_out is not None:
            rows_out.extend(events)

    pages_read = max((e.get("page") or 0 for e in events if e["event"] == "page_view"),
                     default=0)
    return content.FAIRY_TALE["summary"].format(pages=pages_read, total=len(pages))


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

    done = visual.TextStim(win, text=content.FAIRY_TALE["done"], color=(255, 255, 255),
                           colorSpace="rgb255", height=h(72), font="Arial")
    done.draw()
    win.flip()
    core.wait(2.0)

    win.close()
    core.quit()


if __name__ == "__main__":
    main()
