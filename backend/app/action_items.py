"""v3 Phase-23：把会议纪要里的编号任务拆成待办草稿（领导 2026-10-12 要求：自动列出 1、2、3…，她只补邮箱和具体日期）。

纪要的写法（来自 Excel 的 Notes/Task/Resp./Due Date 列与 Cockpit 里录入的 Committee Discussion）：
- 主任务 "1." "2." …，按行分开；或者挤在一行里，编号直接接在上一条后面
- 子任务：行首 "a." "b." …，或行内 "1)" "2)" …
- 负责人写在最后一个 "--" 后面（历史纪要里也常见单个 " - "：没有 "--" 时取最后一个 " - "），截止日期跟在负责人前后（"SP Melisa by 09.10.2026"、"Rafal Nov 2026"、"Jan 2027, …"），
  也可能写在任务文字里（"list to be distributed KW40"）
- 不带编号的行（"Agreement on …"、"Carrie to approve."）是上一条任务的补充说明

只出草稿，不写库：页面上勾选后加进待办列表，邮箱由人填（不按姓名猜邮箱）。
"""

from __future__ import annotations

import calendar
import re
from datetime import date

from . import logic

RESPONSIBLE_MAX = 500  # 与 schemas.Text 的上限一致

# 主编号 "1." 后面要跟空白，"08.10.2026"、"2026.--" 这类不会被当成编号
_MAIN = re.compile(r"(?:^|(?<=\s))(\d{1,2})\.(?=\s+\S)")
_MAIN_AT_LINE_START = re.compile(r"^[ \t]*(\d{1,2})\.(?=\s+\S)", re.MULTILINE)
_LETTER_SUB = re.compile(r"^[ \t]*([a-z])[.)](?=\s+\S)", re.MULTILINE)
_PAREN_SUB = re.compile(r"(?:^|(?<=\s))(\d{1,2})\)(?=\s+\S)")
_OWNER_SEPARATOR = re.compile(r"\s*(?:-{2,}|\s[–—])\s*")
_SPACED_DASH = re.compile(r"\s+-\s+")
_TRAILING_REMARK = re.compile(r"\(([^()]*)\)[\s.]*$")  # "Summer Chen. CW38. (Markus approves once complete)"

_LEAD = r"(?:(?:by|until|till|due|before|end of|mid of|mid|beginning of)\s+)?"
_EXACT = re.compile(_LEAD + r"\b(\d{1,2})[./](\d{1,2})[./](\d{4}|\d{2})\b", re.IGNORECASE)
_ISO = re.compile(_LEAD + r"\b(\d{4})-(\d{2})-(\d{2})\b", re.IGNORECASE)
_WEEK = re.compile(_LEAD + r"\b(?:KW|CW|WK)\s?(\d{1,2})\b(?:\s*[/,.-]?\s*(\d{4})\b)?", re.IGNORECASE)
_MONTH = re.compile(
    _LEAD + r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|"
    r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s*,?\s*(\d{4})\b", re.IGNORECASE)
_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}


def extract(text: str, meeting: date | None = None) -> list[dict]:
    """纪要 → 待办草稿列表（按纪要顺序）。没有 "1." 开头的编号就返回空列表。

    每条：ref（"3"、"6a"、"2.1"）、task、responsible、dueDate（YYYY-MM-DD 或空）、dueText（原文写法）、
    dueEstimated（KW / 月份推算的为 True）、notes（不带编号的补充行；推算的日期在这里提示核对）。"""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    drafts: list[dict] = []
    for number, body in _split(text, _main_markers(text)):
        parent, subs = _split_subs(body)
        drafts.append(_draft(number, parent, meeting))
        for sub, sub_body in subs:  # 子任务编号：6a、6b … / 2.1、2.2 …
            drafts.append(_draft(f"{number}.{sub}" if sub.isdigit() else number + sub, sub_body, meeting))
    return drafts


# ---------- 拆分 ----------


def _sequential(matches, first: str, step) -> list[re.Match]:
    """只认按顺序出现的编号（1、2、3… / a、b、c…）：句子里的 "Level 2." 这类数字不会打断任务。"""
    expected, picked = first, []
    for m in matches:
        if m.group(1) == expected:
            picked.append(m)
            expected = step(expected)
    return picked


def _main_markers(text: str) -> list[re.Match]:
    # 至少两条编号在行首 → 纪要按行分好，只认行首编号；否则编号挤在一行里，行内的也认
    at_line_start = _sequential(_MAIN_AT_LINE_START.finditer(text), "1", lambda n: str(int(n) + 1))
    if len(at_line_start) >= 2:
        return at_line_start
    return _sequential(_MAIN.finditer(text), "1", lambda n: str(int(n) + 1))


def _split(text: str, markers: list[re.Match]) -> list[tuple[str, str]]:
    if not markers:
        return []
    ends = [m.start() for m in markers[1:]] + [len(text)]
    return [(m.group(1), text[m.end():end].strip()) for m, end in zip(markers, ends, strict=True)]


def _split_subs(body: str) -> tuple[str, list[tuple[str, str]]]:
    """子任务：行首 a. b. …，或 1) 2) …；至少两条才算（单个 "1)" 多半是正文里的列举）。"""
    for pattern, first, step in ((_LETTER_SUB, "a", lambda c: chr(ord(c) + 1)),
                                 (_PAREN_SUB, "1", lambda n: str(int(n) + 1))):
        markers = _sequential(pattern.finditer(body), first, step)
        if len(markers) >= 2:
            return body[:markers[0].start()].strip(), _split(body, markers)
    return body, []


# ---------- 单条任务 ----------


def _draft(ref: str, body: str, meeting: date | None) -> dict:
    first, *rest = body.split("\n")
    extra = " ".join(line.strip() for line in rest if line.strip())
    task, owner = _split_owner(first)
    remark = _TRAILING_REMARK.search(owner)
    if remark:
        owner = owner[:remark.start()]
    due, written, estimated, owner = _due_date(owner, meeting, remove=True)
    if not due:
        due, written, estimated, _ = _due_date(task, meeting, remove=False)
    notes = f'Due date estimated from "{written}" — please confirm.' if estimated else ""
    return {
        "ref": ref,
        "task": task.strip().rstrip(" -–—,;:").strip(),
        "responsible": _clean_owner(owner)[:RESPONSIBLE_MAX],
        "dueDate": due, "dueText": written, "dueEstimated": estimated,
        "notes": " ".join(filter(None, [notes, extra, remark.group(1).strip() if remark else ""])),
    }


def _split_owner(line: str) -> tuple[str, str]:
    """任务文字与负责人：以最后一个 "--" 为准；没有就用最后一个 " - "。"""
    parts = _OWNER_SEPARATOR.split(line)
    if len(parts) > 1:
        return " -- ".join(parts[:-1]), parts[-1]
    dashes = list(_SPACED_DASH.finditer(line))
    if dashes and line[:dashes[-1].start()].strip():
        return line[:dashes[-1].start()], line[dashes[-1].end():]
    return line, ""


def _clean_owner(owner: str) -> str:
    owner = re.sub(r"\s+", " ", owner).strip(" ,;:-–—")
    owner = re.sub(r"\.(?:\s*\.)+", ".", owner)  # 日期取走后剩下的 "Chen. ."
    owner = re.sub(r"\s+\.$", "", owner)  # 日期取走后剩下的 "Melisa ."
    owner = re.sub(r"\s+(?:by|until|due)$", "", owner, flags=re.IGNORECASE).strip(" ,;:")
    return re.sub(r"(?<=\w\w)\.$", "", owner)  # 句末的点去掉，"Daniel U." 这种姓名缩写保留


def _due_date(segment: str, meeting: date | None, *, remove: bool) -> tuple[str, str, bool, str]:
    """在一段文字里找截止日期：精确日期 > ISO 日期 > KW（取那周周五，推算）> 月份（取月底，推算）。

    返回 (YYYY-MM-DD 或空, 原文写法, 是否推算, 去掉日期后的文字)。"""
    for pattern, to_date, estimated in ((_EXACT, _exact_date, False), (_ISO, _iso_date, False),
                                        (_WEEK, _week_date, True), (_MONTH, _month_date, True)):
        for m in pattern.finditer(segment):
            found = to_date(m, meeting)
            if found:
                rest = (segment[:m.start()] + " " + segment[m.end():]) if remove else segment
                return found.isoformat(), m.group(0).strip(), estimated, rest
    return "", "", False, segment


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _exact_date(m: re.Match, _meeting) -> date | None:
    day, month, year = (int(g) for g in m.groups())
    return _safe_date(year + 2000 if year < 100 else year, month, day)


def _iso_date(m: re.Match, _meeting) -> date | None:
    year, month, day = (int(g) for g in m.groups())
    return _safe_date(year, month, day)


def _week_date(m: re.Match, meeting: date | None) -> date | None:
    week = int(m.group(1))
    if m.group(2):
        year = int(m.group(2))
    else:
        year, meeting_week, _ = (meeting or logic.na_now().date()).isocalendar()
        if week < meeting_week - 26:  # 年底开会说 "KW3" 指明年
            year += 1
    try:
        return date.fromisocalendar(year, week, 5)
    except ValueError:
        return None


def _month_date(m: re.Match, _meeting) -> date | None:
    month = _MONTHS[m.group(1)[:3].lower()]
    year = int(m.group(2))
    return date(year, month, calendar.monthrange(year, month)[1])
