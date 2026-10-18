"""
Gợi ý viết lại câu CV (US-SV-03).

- check_rewrite: các bước kiểm tra chung cho mọi câu AI đề xuất (bước phân tích và Trình tối ưu) — không làm mất số
  thật, không đổi ngôn ngữ dòng gốc, chỉ nhắc công cụ có trong cùng dự án / nơi làm việc, chỗ trống đúng mẫu.
- draft_rewrites: Trình tối ưu soạn gợi ý riêng (một lần gọi LLM chỉ để viết lại, ngoài hạn mức 2 lần gọi của bước
  phân tích) cho mọi câu mô tả việc đã làm, rồi lọc bằng check_rewrite và guardrail grounding.
"""

import logging
import re
import uuid
from difflib import SequenceMatcher
from typing import Any

from src.services import llm
from src.services.cv_layout import layout_lines
from src.services.guardrails import check_output_grounding
from src.services.skill_matching import (
    EVIDENCE_SECTIONS,
    IMPORTANCE_LABELS,
    SECTION_LABELS,
    _edits_at_most_one,
    contains_term,
    entry_text,
    has_result_metric,
    has_vietnamese_marks,
    is_descriptive,
)

logger = logging.getLogger(__name__)

# Chỗ trống duy nhất được phép trong gợi ý, đặt ở cuối câu, để sinh viên tự điền số thật (theo ngôn ngữ dòng gốc)
PLACEHOLDER_VI, PLACEHOLDER_PLAIN, PLACEHOLDER_EN = "[kết quả đo được]", "[ket qua do duoc]", "[measurable result]"
PLACEHOLDERS = (PLACEHOLDER_VI, PLACEHOLDER_PLAIN, PLACEHOLDER_EN)
_ENGLISH_WORDS = {"the", "and", "for", "with", "using", "of", "to", "in", "on", "by", "from", "an"}
# Trình tối ưu: số câu tối đa gửi cho LLM và số gợi ý tối đa giữ lại
MAX_REWRITE_LINES = 40
MAX_REWRITES = 15
MAX_REWRITE_CHARS = 400
MAX_PROMPT_CV_CHARS = 12_000
# CV dài (30–40 câu) có lúc mất hơn 60 giây để LLM viết xong
REWRITE_TIMEOUT_SECONDS = 90.0
# Câu đề xuất chỉ khác câu gốc ở các chỗ ngắn tới mức này (ký tự) là sửa chính tả / khoảng trắng của chữ OCR
COSMETIC_EDIT_CHARS = 2
# Tối thiểu phần nội dung dòng gốc phải còn trong câu đề xuất (xem keeps_original)
MIN_KEPT_SHARE = 0.4


def fold(text: str) -> str:
    return re.sub(r"[\s\-_.]", "", text.lower())


def new_names(rewrite: str, source: str) -> list[str]:
    """
    Tên riêng / tên công cụ trong gợi ý (từ có chữ hoa, trừ từ đầu câu) không có trong đoạn CV `source` (mục chứa dòng
    gốc): dấu hiệu gợi ý tự thêm công cụ, tổ chức, sản phẩm. So khớp bỏ hoa thường và khoảng trắng (chữ OCR hay bị
    tách), chấp nhận lệch một ký tự (OCR đọc "Streamlit" thành "Streamit"). Con số mới do guardrail xử lý.
    """
    source_folded = fold(source)
    source_words = {fold(w) for w in re.findall(r"[^\W_][\w+#.\-]*", source)}
    words = [w.strip(".-") for w in re.findall(r"[^\W_][\w+#.\-]*", rewrite)]
    return [
        w
        for w in words[1:]
        if any(c.isupper() for c in w)
        and fold(w) not in source_folded
        and not any(_edits_at_most_one(fold(w), s) for s in source_words if len(s) >= 4)
    ]


def with_placeholder_of(rewrite: str, original: str) -> str:
    """Chỗ trống viết theo ngôn ngữ dòng gốc: tiếng Việt có dấu / tiếng Anh / tiếng Việt OCR mất dấu."""
    if has_vietnamese_marks(original):
        target = PLACEHOLDER_VI
    elif _ENGLISH_WORDS & set(re.findall(r"[a-z]+", f"{original} {rewrite}".lower())):
        # Xét cả câu gợi ý: dòng OCR hay dính chữ ("throughlabeling andimplemented") nên ít từ tiếng Anh rời
        target = PLACEHOLDER_EN
    else:
        target = PLACEHOLDER_PLAIN
    for placeholder in PLACEHOLDERS:
        rewrite = rewrite.replace(placeholder, target)
    return rewrite


def _letters(text: str) -> str:
    return re.sub(r"[\W_]", "", text.lower())


def only_cosmetic(original: str, rewrite: str) -> bool:
    """
    Câu đề xuất chỉ sửa khoảng trắng, dấu câu, hoa thường và lỗi chính tả trong từ (thường gặp ở CV đọc bằng OCR):
    so phần chữ và số, mọi chỗ khác nhau đều chỉ dài tối đa COSMETIC_EDIT_CHARS ký tự ("Streamit" → "Streamlit").
    Thêm hay đổi cả một từ thì không phải sửa vặt.
    """
    a, b = _letters(original), _letters(rewrite)
    return all(
        max(i2 - i1, j2 - j1) <= COSMETIC_EDIT_CHARS
        for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
        if tag != "equal"
    )


def _trigrams(text: str) -> set[str]:
    letters = _letters(text)
    return {letters[i : i + 3] for i in range(len(letters) - 2)}


def keeps_original(original: str, rewrite: str) -> bool:
    """
    Câu đề xuất vẫn nói về nội dung của chính dòng gốc: phần lớn cụm 3 ký tự của dòng gốc còn trong câu mới (không phụ
    thuộc thứ tự từ, chịu được chữ OCR dính liền). Chặn trường hợp biến dòng tiêu đề ("Nielsen Vietnam") thành một câu
    lấy nội dung từ chỗ khác trong CV.
    """
    source = _trigrams(original)
    return not source or len(source & _trigrams(rewrite)) / len(source) >= MIN_KEPT_SHARE


def numbers(text: str) -> set[str]:
    """Các con số trong câu, bỏ dấu phân cách hàng nghìn ("3.000" = "3000")."""
    return set(re.findall(r"\d+", re.sub(r"(?<=\d)[.,](?=\d{3}\b)", "", text)))


def is_listing(text: str) -> bool:
    """
    Dòng liệt kê kỹ năng / công nghệ ("Python, Java, Weka, scikit-learn", "Technologies: Python, FastAPI, Docker"):
    từ 3 mục trở lên ngăn bởi dấu phẩy / gạch chéo, mục nào cũng chỉ 1–3 từ. Câu mô tả kèm danh sách ("Evaluated 6
    algorithms: SVM, …") không tính vì mục đầu là một câu. Không có gì để viết lại thành câu mà không bịa thêm việc.
    """
    items = [item for item in re.split(r"[,/;|]", text) if item.strip()]
    return len(items) >= 3 and all(len(item.split()) <= 3 for item in items)


def check_rewrite(line: dict[str, Any], rewrite: str, lines_by_no: dict[int, dict[str, Any]]) -> str | None:
    """
    Câu đề xuất đã chuẩn hoá chỗ trống, hoặc None nếu không đạt: trùng câu gốc, làm mất số thật, tự đặt chỗ trống
    khác mẫu (ngầm khẳng định kết quả), đổi ngôn ngữ dòng gốc, hoặc nhắc công cụ / tổ chức ngoài mục CV của dòng.
    """
    if is_listing(line["text"]):
        return None
    rewrite = with_placeholder_of(" ".join(str(rewrite or "").split()), line["text"])
    if not rewrite or rewrite.lower() == line["text"].lower() or len(rewrite) > MAX_REWRITE_CHARS:
        return None
    if numbers(line["text"]) - numbers(rewrite):
        return None
    body = rewrite.rstrip(" .")
    for placeholder in PLACEHOLDERS:
        body = body.removesuffix(placeholder)
    if "[" in body or "]" in body or (body != rewrite.rstrip(" .") and has_result_metric(line["text"])):
        return None
    if has_vietnamese_marks(line["text"]) != has_vietnamese_marks(body):
        return None
    if new_names(body, entry_text(line, lines_by_no)):
        return None
    if not keeps_original(line["text"], body):
        return None
    asks_metric = body != rewrite.rstrip(" .")
    if not asks_metric and only_cosmetic(line["text"], body):
        # Chỉ sửa chính tả / khoảng trắng (chữ OCR), không phải gợi ý viết lại. Câu chỉ thêm chỗ trống hỏi số liệu vẫn
        # giữ: dẫn SV vào bước điền số thật
        return None
    return rewrite


# ---------- Trình tối ưu: soạn gợi ý riêng ----------


def merge_wrapped(lines: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """
    Gộp gạch ý bị ngắt xuống dòng khi trích PDF ("• Developed APIs … metadata" + "management.") thành một câu, dùng
    đúng cách nhận dòng nối của mẫu trình bày CV (cv_layout: "cont"). Mỗi câu giữ số dòng đầu (line_no) và các dòng nối
    (extra_line_nos): áp dụng gợi ý thì câu mới thay cả gạch ý.
    """
    layout = layout_lines(text)
    units: list[dict[str, Any]] = []
    for line in lines:
        if layout.get(line["line_no"], {}).get("cont") and units and not line["is_heading"]:
            unit = units[-1]
            unit["text"] = f"{unit['text']} {line['text']}"
            unit["extra_line_nos"].append(line["line_no"])
            continue
        units.append({**line, "extra_line_nos": []})
    return units


def wrapped_line_nos(lines: list[dict[str, Any]], text: str) -> set[int]:
    """Số dòng thuộc một gạch ý bị ngắt xuống dòng (dòng đầu và các dòng nối)."""
    return {n for u in merge_wrapped(lines, text) if u["extra_line_nos"] for n in (u["line_no"], *u["extra_line_nos"])}


def rewrite_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Câu mô tả việc đã làm trong Kinh nghiệm / Dự án / Học vấn / Hoạt động (cùng điều kiện bằng chứng khi chấm)."""
    return [
        line
        for line in lines
        if is_descriptive(line) and line.get("block") in EVIDENCE_SECTIONS and not is_listing(line["text"])
    ][:MAX_REWRITE_LINES]


def _cv_block(lines: list[dict[str, Any]], targets: set[int]) -> str:
    out, total = [], 0
    for line in lines:
        mark = "*" if line["line_no"] in targets else " "
        language = ""
        if line["line_no"] in targets:
            language = " (tiếng Việt)" if has_vietnamese_marks(line["text"]) else " (giữ ngôn ngữ, không dấu)"
        row = (
            f"{mark}[{line['line_no']}|{SECTION_LABELS.get(line['section'], line['section'])}{language}] {line['text']}"
        )
        total += len(row)
        if total > MAX_PROMPT_CV_CHARS:
            break
        out.append(row)
    return "\n".join(out)


def _requirements_block(requirements: list[dict[str, Any]]) -> str:
    status = {"matched": "CV đã có", "partial": "CV mới liệt kê", "missing": "CV chưa có"}
    return "\n".join(
        f"- {r['skill']} ({IMPORTANCE_LABELS.get(r['importance'], r['importance'])}; {status.get(r['status'], '')})"
        for r in requirements
    )


def _prompt(
    lines: list[dict[str, Any]], targets: list[dict[str, Any]], requirements: list[dict[str, Any]], job: str
) -> str:
    return (
        f"Bạn là chuyên gia viết CV, giúp sinh viên viết rõ hơn các câu mô tả việc đã làm cho vị trí {job}.\n\n"
        "=== CV (dòng đánh dấu * là câu cần xem xét; trong ngoặc là ngôn ngữ BẮT BUỘC của câu đề xuất) ===\n"
        f"{_cv_block(lines, {t['line_no'] for t in targets})}\n\n"
        "=== YÊU CẦU CỦA JD (kèm kết quả phân tích) ===\n"
        f"{_requirements_block(requirements)}\n\n"
        "=== NHIỆM VỤ ===\n"
        "Xem TỪNG dòng đánh dấu * và đề xuất đúng 1 câu thay thế cho mỗi câu mô tả việc đã làm còn có thể viết thuyết "
        "phục hơn với nhà tuyển dụng; phần lớn câu trong CV sinh viên đều viết tốt hơn được. Chỉ ghi vào kept khi dòng "
        "là tiêu đề / chức danh / dòng liệt kê công nghệ, hoặc câu đã có đủ: động từ hành động, việc cụ thể, kỹ năng "
        "hoặc công cụ, và kết quả. Ưu tiên làm rõ kỹ năng JD cần mà dòng đó thật sự thể hiện.\n"
        "Cách cải thiện (một hoặc nhiều): mở đầu bằng động từ hành động; nêu rõ việc / bài toán và mục đích đã có trong "
        "dòng; nêu kỹ năng, công cụ đã dùng (có trong cùng mục); tách rõ phần việc của chính sinh viên; câu chưa có kết "
        "quả thì thêm chỗ trống ở cuối để sinh viên tự điền số thật.\n"
        "CV có thể được đọc từ ảnh scan nên dính chữ, sai chính tả: khi viết lại thì sửa luôn các lỗi này, nhưng câu "
        "CHỈ sửa khoảng trắng / chính tả / dấu câu thì không tính là gợi ý.\n"
        "RÀNG BUỘC (vi phạm thì câu bị loại):\n"
        "- Giữ đúng sự thật và ngôn ngữ của chính dòng đó (tiếng Anh viết tiếng Anh, tiếng Việt không dấu viết không "
        "dấu); giữ nguyên mọi con số đã có.\n"
        "- Chỉ nhắc công cụ có trong chính dòng đó hoặc cùng dự án / nơi làm việc; KHÔNG lấy từ mục Kỹ năng, dự án "
        "khác, hay kỹ năng JD mà CV chưa có.\n"
        "- KHÔNG thêm việc, số liệu, thành tích, quy mô, đối tượng; không tự khẳng định kết quả (tăng, giảm, cải "
        "thiện...).\n"
        '- Dòng chưa có số liệu thì có thể thêm đúng MỘT chỗ trống ở cuối câu: "[kết quả đo được]" (câu tiếng Anh: '
        '"[measurable result]"; câu không dấu: "[ket qua do duoc]"). Dòng đã có số liệu thì không thêm chỗ trống.\n'
        "- skill: tên một yêu cầu JD ở trên mà câu mới làm rõ (để trống nếu không có). reason: 1 câu tiếng Việt cho "
        "sinh viên, nói câu mới rõ hơn ở điểm nào.\n"
        "CHỈ trả về JSON hợp lệ:\n"
        '{"rewrites": [{"line": 5, "skill": "...", "rewrite": "...", "reason": "..."}], "kept": [7]}'
    )


def _skill_of(
    raw: Any, line: dict[str, Any], lines_by_no: dict[int, dict[str, Any]], usable: list[dict[str, Any]]
) -> str:
    """Kỹ năng JD mà gợi ý làm rõ: tên LLM ghi (nếu là yêu cầu CV đã có), không thì yêu cầu nhắc trong cùng mục CV."""
    name = str(raw or "").strip().lower()
    for r in usable:
        if r["skill"].lower() == name:
            return r["skill"]
    entry = entry_text(line, lines_by_no)
    return next((r["skill"] for r in usable if contains_term(r["skill"], entry)), "")


async def draft_rewrites(
    lines: list[dict[str, Any]], requirements: list[dict[str, Any]], job: str, cv_raw: str
) -> dict[str, Any]:
    """
    Gợi ý viết lại cho mọi câu mô tả của CV: {"items": [...], "kept": số câu LLM cho là đã rõ}. Mỗi item cùng dạng
    gợi ý của bước phân tích (id, skill, line_no, original_text, suggested_text, reason). Lỗi LLM thì ném ngoại lệ để
    phiên tối ưu ghi trạng thái "failed" (SV bấm Thử lại).
    """
    physical = {line["line_no"]: line for line in lines}
    # Gạch ý bị ngắt dòng được gửi và viết lại như một câu
    lines = merge_wrapped(lines, cv_raw)
    targets = rewrite_lines(lines)
    if not targets:
        return {"items": [], "kept": 0}
    # Cổng gateway che thông tin cá nhân trong CV trước khi gửi; invoke_json đổi mã ẩn trong câu đề xuất về chữ thật
    # (câu còn sót mã ẩn bị check_rewrite loại vì có dấu "[")
    data = await llm.invoke_json(
        _prompt(lines, targets, requirements, job), temperature=0.0, timeout=REWRITE_TIMEOUT_SECONDS
    )
    by_no = {line["line_no"]: line for line in lines}
    allowed = {t["line_no"] for t in targets}
    # Gợi ý không được gắn với kỹ năng CV chưa có (AI không tự thêm kỹ năng vào CV)
    usable = [r for r in requirements if r.get("status") != "missing"]
    items: list[dict[str, Any]] = []
    for raw in data.get("rewrites") or []:
        if not isinstance(raw, dict):
            continue
        try:
            line = by_no[int(raw.get("line"))]
        except (KeyError, TypeError, ValueError):
            continue
        if line["line_no"] not in allowed or any(i["line_no"] == line["line_no"] for i in items):
            continue
        rewrite = check_rewrite(line, str(raw.get("rewrite") or ""), physical)
        if rewrite is None:
            continue
        skill = _skill_of(raw.get("skill"), line, by_no, usable)
        grounding = check_output_grounding(
            {"skill": skill or "General", "evidence_span": line["text"], "suggested_revision": rewrite}, cv_raw
        )
        if not grounding["passed"]:
            continue
        items.append(
            {
                "id": f"rw_{uuid.uuid4().hex[:12]}",
                "skill": skill,
                "line_no": line["line_no"],
                # Dòng nối của gạch ý (bị ngắt khi trích PDF): bỏ khi áp dụng câu mới
                "extra_line_nos": line["extra_line_nos"],
                "original_text": line["text"],
                "suggested_text": rewrite,
                "reason": " ".join(str(raw.get("reason") or "").split())[:300],
            }
        )
        if len(items) >= MAX_REWRITES:
            break
    kept = len({int(n) for n in data.get("kept") or [] if str(n).isdigit() and int(n) in allowed})
    return {"items": items, "kept": kept}
