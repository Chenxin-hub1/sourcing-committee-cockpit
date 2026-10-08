"""演示文件自动对案例（v3 Phase-20）。

SharePoint 周文件夹里的演示文件命名大致是 `1. 110000034978 SPR8 Tube_34235239A_ NA_CO_L2_Iron Force Huzhou_Tube_Haojie.pdf`：
开头是该周的案例序号，后面跟 SWAT 号（或 bundle 号 B/2025/00234，文件名里斜杠写成 _ / - / 空格）、零件号、区域、类型等。
文件夹名（"KW15, 08.04.2026"）给出会议周。

对案例的依据按可靠程度依次是：SWAT / bundle 号 → 零件号 → 周 + 案例序号。知道会议周时先在那一周里找，
找不到再放宽到全部案例（同一号码多次上会时取最近的一次）。都对不上返回 None，由经理在案例页手工挂。
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from . import excel_import, logic

_SWAT_RE = re.compile(r"(?<!\d)(\d{9,12})(?!\d)")
_BUNDLE_RE = re.compile(r"(?<![A-Za-z0-9])B[\s_\-/]?(20\d{2})[\s_\-/]?(\d{3,5})(?!\d)", re.IGNORECASE)
_LEADING_NO_RE = re.compile(r"^\s*(\d{1,2})\s*[.)_\-]")  # "1. 110000…" → 案例序号 1
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _norm_bundle(year: str, number: str) -> str:
    return f"B/{year}/{int(number):05d}"


def _case_ids(case: dict) -> set[str]:
    """案例的全部号码：案例号本身，加上零件行上的 SWAT 数字号（bundle 案例的 sourcingId）。"""
    ids = {str(case.get("swatId") or "").strip().upper()}
    for row in logic.part_number_lines(case):
        if row.get("sourcingId"):
            ids.add(str(row["sourcingId"]).strip().upper())
    if case.get("sourcingId"):
        ids.add(str(case["sourcingId"]).strip().upper())
    ids.discard("")
    return ids


def _alnum(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def _part_numbers(case: dict) -> set[str]:
    return {str(r.get("partNumber") or "").strip().upper() for r in logic.part_number_lines(case) if len(str(r.get("partNumber") or "").strip()) >= 6}


def week_of(rel_path: str) -> tuple[int | None, int | None]:
    """(年份, KW)：先看文件夹名（"KW15, 08.04.2026"），再看文件名；都猜不出返回 (None, None)。"""
    path = PurePosixPath(rel_path)
    for text in [*reversed([p for p in path.parent.parts if p not in ("", ".")]), path.stem]:
        _kw, day = excel_import.meeting_from_name(text)
        if day is not None:
            return day.isocalendar().year, day.isocalendar().week
    return None, None


def match(rel_path: str, cases: list[dict]) -> dict | None:
    """库里一份文件 → {"rowId", "swatId", "label", "by"}；对不上返回 None。"""
    name = PurePosixPath(rel_path).name
    stem = PurePosixPath(name).stem
    upper = stem.upper()
    year, week = week_of(rel_path)
    in_week = [c for c in cases if year and int(c.get("weekNum") or 0) == week and logic.case_year(c) == year]

    swats = set(_SWAT_RE.findall(stem)) | {_norm_bundle(y, n) for y, n in _BUNDLE_RE.findall(stem)}
    tokens = {t.upper() for t in _TOKEN_RE.findall(stem)}
    squeezed = _alnum(stem)

    def same_id(c: dict) -> bool:
        ids = _case_ids(c)
        # 数字 SWAT 号 / bundle 号精确对上；其它写法的案例号（如 "SWAT-50001"）整体出现在文件名里也算
        return bool(swats & ids) or any(len(_alnum(i)) >= 6 and not i.isdigit() and _alnum(i) in squeezed for i in ids)
    leading = _LEADING_NO_RE.match(stem)

    def pick(pool: list[dict], test) -> dict | None:
        hits = [c for c in pool if test(c)]
        if not hits:
            return None
        return max(hits, key=lambda c: (logic.case_year(c) or 0, int(c.get("weekNum") or 0), int(c.get("caseNumber") or 0)))

    rules = [
        ("SWAT number", same_id),
        ("part number", lambda c: any(pn in tokens or pn in upper for pn in _part_numbers(c))),
    ]
    for pool in ([in_week, cases] if in_week else [cases]):
        for by, test in rules:
            found = pick(pool, test)
            if found:
                return _result(found, by)
    if leading and in_week:
        number = int(leading.group(1))
        found = next((c for c in in_week if int(c.get("caseNumber") or 0) == number), None)
        if found:
            return _result(found, "week + case #")
    return None


def _result(case: dict, by: str) -> dict:
    return {"rowId": case["id"], "swatId": case.get("swatId", ""), "by": by,
            "label": f"{logic.week_label(case)} · Case #{case.get('caseNumber')} · {case.get('swatId', '')}"}


def attached_to(name: str, case: dict) -> bool:
    """这份库文件是否已经挂在案例上（按原文件名判断，挂接时原名存在 originalName）。"""
    return any((f.get("originalName") or f.get("name")) == name for f in case.get("files") or [])


def week_folder(case: dict) -> str:
    """案例所在周在库里的文件夹名，与 SharePoint 一致："KW15, 08.04.2026"。"""
    iso = case.get("meetingDateISO") or ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", iso):
        y, m, d = iso.split("-")
        return f"KW{int(case.get('weekNum') or 0):02d}, {d}.{m}.{y}"
    return f"KW{int(case.get('weekNum') or 0):02d}"
