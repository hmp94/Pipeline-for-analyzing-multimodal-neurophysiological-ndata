# -*- coding: utf-8 -*-
"""
content.py — all participant-facing TEXT for the cognitive-task battery.

Edit the strings here to change what participants see. The task files
(run_all_experiments.py, stroop/addition/multiplication/fairy_tale_*.py) contain
only the experiment flow/structure; they pull every on-screen string from here.

Notes
-----
* Text is Vietnamese and rendered in Arial (handles the diacritics).
* {curly-brace} placeholders are filled in by the code at run time — keep them:
    {correct} {total} {n} {answer} {page}   (see each string's comment)
* Multi-line message screens are lists of lines (one string per line); "" = blank line.
* This module is display text only — it does NOT set task timings, durations, or
  colours (those live in each task's settings / defaults).
"""

# ─────────────────────────────────────────────────────────────────────────────
# Session-level screens  (run_all_experiments.py)
# ─────────────────────────────────────────────────────────────────────────────

# Welcome screen, shown once at the very start.
WELCOME = [
    "Chào mừng bạn",
    "",
    "Trước tiên là phần đo trạng thái nền (ngồi yên, mở mắt),",
    "sau đó là bốn bài tập ngắn, thực hiện lần lượt.",
    "Mọi thứ diễn ra tự động — bạn chỉ thực hiện theo",
    "hướng dẫn trên màn hình trước mỗi bài tập.",
]

# Shown just before the resting baseline block starts.
BASELINE_INTRO = [
    "Trạng thái nền", "",
    "Ngồi yên và giữ mắt mở.",
    "Thư giãn nhưng vẫn tỉnh táo. Không nhấn phím nào.",
    "Bắt đầu ghi khi dấu + xuất hiện.",
]

# Caption under the fixation cross during the baseline recording.
BASELINE_CAPTION = "Trạng thái nền — mở mắt, thư giãn, giữ yên"

# Rest screen between tasks.
REST = [
    "Nghỉ", "",
    "Ngồi yên, mở mắt, thư giãn.",
    "Bài tập tiếp theo sẽ sớm bắt đầu.",
]

# Final summary screen (first line).
FINAL_DONE = "Hoàn thành tất cả bài tập!"
FINAL_ABORTED = "Buổi đo kết thúc sớm"
FINAL_NO_TASKS = "(chưa ghi được bài tập nào)"

# Footer shown only on the final screen (SPACE to close).
FOOTER_SKIP = "Nhấn SPACE để kết thúc"

# Result word logged/shown for the baseline block.
BASELINE_RESULT = "đã ghi"

# Shared hint under every task's instruction screen (below the time bar).
INSTRUCTION_HINT = "Bài tập sẽ tự bắt đầu khi thanh thời gian kết thúc."


# ─────────────────────────────────────────────────────────────────────────────
# Stroop
# ─────────────────────────────────────────────────────────────────────────────
STROOP = {
    "title": "Bài tập Stroop",
    "body": (
        "Phản hồi theo MÀU CỦA CHỮ, không theo nghĩa của từ.\n"
        "\n"
        "Mỗi từ xuất hiện rất ngắn rồi biến mất.\n"
        "hãy chờ chữ tắt rồi nhấn phím nhanh và chính xác nhất có\n"
        "thể. Mỗi từ nhấn một phím."
    ),
    "color_prompt": "Phản hồi theo màu chữ:",
    "sample_word": "MÀU",           # the coloured sample word in the key legend
    "key_c": "=>  nhấn  C",         # blue / green -> C
    "key_m": "=>  nhấn  M",         # red / yellow -> M
    "feedback_correct": "Đúng",
    "feedback_wrong": "Sai",
    "feedback_timeout": "Phản hồi chậm",
    "done": "Hoàn thành!",
    "summary": "{correct}/{total} trả lời đúng",
    "summary_timeout": ", {n} phản hồi chậm",
}


# ─────────────────────────────────────────────────────────────────────────────
# Addition
# ─────────────────────────────────────────────────────────────────────────────
ADDITION = {
    "title": "Phép cộng",
    "body": (
        "Cộng hai số hiển thị trên màn hình.\n\n"
        "Nhập đáp án bằng các phím số.\n"
        "BACKSPACE để xóa, ENTER để xác nhận.\n\n"
        "Tiếp tục giải cho đến khi hết thời gian."
    ),
    "hint": "Nhập đáp án rồi nhấn ENTER",
    "hint_countdown": "Nhập đáp án rồi nhấn ENTER   (còn {n}s)",
    "feedback_correct": "Đúng!",
    "feedback_wrong": "Sai! Đáp án: {answer}",
    "feedback_timeout": "Phản hồi chậm — Đáp án: {answer}",
    "done": "Hoàn thành!",
    "summary": "{correct}/{total} trả lời đúng",
    "summary_timeout": ", {n} phản hồi chậm",
}


# ─────────────────────────────────────────────────────────────────────────────
# Multiplication
# ─────────────────────────────────────────────────────────────────────────────
MULTIPLICATION = {
    "title": "Phép nhân",
    "body": (
        "Nhân hai số hiển thị trên màn hình.\n\n"
        "Nhập đáp án bằng các phím số.\n"
        "BACKSPACE để xóa, ENTER để xác nhận.\n\n"
        "Tiếp tục giải cho đến khi hết thời gian."
    ),
    "hint": "Nhập đáp án rồi nhấn ENTER",
    "hint_countdown": "Nhập đáp án rồi nhấn ENTER   (còn {n}s)",
    "feedback_correct": "Đúng!",
    "feedback_wrong": "Sai! Đáp án: {answer}",
    "feedback_timeout": "Phản hồi chậm — Đáp án: {answer}",
    "done": "Hoàn thành!",
    "summary": "{correct}/{total} trả lời đúng",
    "summary_timeout": ", {n} phản hồi chậm",
}


# ─────────────────────────────────────────────────────────────────────────────
# Fairy tale (silent reading)   — the story text itself stays in
# fairy_tale_psychopy.py (with its fairy_tale.txt override); this is only the UI.
# ─────────────────────────────────────────────────────────────────────────────
FAIRY_TALE = {
    "title": "Đọc truyện",
    "body": (
        "Đọc thầm câu chuyện theo tốc độ của bạn.\n\n"
        "SPACE hoặc mũi tên phải: trang sau\n"
        "Mũi tên trái: trang trước\n\n"
        "Bài tập sẽ tự kết thúc."
    ),
    "page_hint": "SPACE / →  trang sau      ←  trang trước      ({page}/{total})",
    "done": "Hoàn thành phần đọc!",
    "summary": "{pages}/{total} trang",
}
