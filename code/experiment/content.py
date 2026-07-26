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
    "Chào mừng bạn!",
    "",
    "Hôm nay chúng ta sẽ có 7 nhiệm vụ.",
    "Đầu tiên là đo trạng thái nền (khoảng 3 phút):",
    "Hãy nhìn dấu \"+\" theo hướng dẫn trên màn hình",
    "",
    "Tiếp theo là sáu bài tập ngắn, thực hiện lần lượt theo chỉ dẫn",
]

# Shown ONCE before the 3-minute baseline block (explains the whole sequence).
BASELINE_INTRO = [
    "Trạng thái nền (3 phút)", "",
    "Hãy làm theo hướng dẫn trên màn hình và GIỮ ĐẦU CỐ ĐỊNH:",
    "nhìn dấu +, chớp mắt theo hiệu lệnh,",
    "đưa mắt nhìn theo chấm (ngang rồi dọc),",
    "cuối cùng nhắm mắt cho đến khi nghe tiếng bíp.",
]

# Caption under the fixation "+" during the resting sub-phases.
BASELINE_CAPTION = "Trạng thái nền — mở mắt, thư giãn, giữ yên"

# --- Cues shown DURING the 3-minute baseline sub-phases --------------------
BASELINE_BLINK_CAP = "Chớp mắt mỗi khi màn hình hiện chữ (5 lần)"  # caption during the blink phase
BASELINE_BLINK_CUE = "Chớp mắt"                                    # flashing blink prompt
BASELINE_MOVE_CAP = "Nhìn theo chấm — giữ đầu cố định"             # caption during the eye-movement phases
BASELINE_CLOSE_EYES = "Nhắm mắt lại"                              # prompt at start of the eyes-closed phase

# (kept for the standalone Stroop baseline / older references)
BASELINE_CLOSED_INTRO = [
    "Trạng thái nền — nhắm mắt", "",
    "Bây giờ hãy NHẮM MẮT lại và thư giãn.",
    "Không suy nghĩ hay thực hiện bất kỳ chuyển động nào.",
    "Sẽ có âm thanh báo khi bạn cần mở mắt.",
]
BASELINE_CLOSED_CAPTION = "Trạng thái nền — nhắm mắt, thư giãn, giữ yên"

# Big prompt shown when the eyes-closed phase ends.
BASELINE_OPEN_EYES = "Mở mắt"

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

# Hint on the opening welcome screen — the ONE SPACE press that starts the session.
START_HINT = "Nhấn phím cách (SPACE) để bắt đầu"

# Result word logged/shown for the baseline block.
BASELINE_RESULT = "đã ghi"

# Shared hint under every task's instruction screen (below the time bar).
INSTRUCTION_HINT = "Bài tập sẽ bắt đầu khi thanh thời gian kết thúc."


# ─────────────────────────────────────────────────────────────────────────────
# Stroop
# ─────────────────────────────────────────────────────────────────────────────
STROOP = {
    "title": "Bài tập Stroop",
    "body": (
        "Phản hồi theo MÀU của từ, không quan tâm đến nghĩa của từ.\n"
        "\n"
     "hãy nhấn nhanh nhất có thể khi từ xuất hiện"
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
        "Bài tập sẽ tự kết thúc khi hết thời gian."
    ),
    "page_hint": "SPACE / →  trang sau      ←  trang trước      ({page}/{total})",
    "done": "Hoàn thành phần đọc!",
    "summary": "{pages}/{total} trang",
}


# ─────────────────────────────────────────────────────────────────────────────
# Passive video (passive visual observation — no response)
# ─────────────────────────────────────────────────────────────────────────────
PASSIVE_VIDEO = {
    "title": "Quan sát video",
    "body": (
        "Trên màn hình sẽ hiển thị hình ảnh chuyển động liên tục.\n\n"
        "Hãy thư giãn và quan sát cho đến khi hết thời gian.\n"
        "Không cần phản hồi hay thao tác gì."
    ),
    "done": "Hoàn thành!",
    "summary": "đã xem",
}


# ─────────────────────────────────────────────────────────────────────────────
# CPT-X (sustained attention: respond to the letter X)
# ─────────────────────────────────────────────────────────────────────────────
CPT = {
    "title": "Bài tập chú ý (CPT-X)",
    "body": (
        "Các chữ cái sẽ xuất hiện lần lượt, thời gian hiển thị mỗi chữ rất ngắn.\n\n"
        "Nếu là chữ  X  → nhấn  C\n"
        "Nếu là chữ khác → nhấn  SPACE\n\n"
        "Hãy phản hồi nhanh và chính xác nhất có thể."
    ),
    "target_prompt": "X  =>  nhấn C            chữ khác  =>  nhấn SPACE",
    "feedback_correct": "Đúng",
    "feedback_wrong": "Sai",
    "done": "Hoàn thành!",
    "summary": "{correct}/{total} đúng",
    "summary_missed": ", {n} bỏ lỡ",
}
