"""议程 / 会议纪要 Excel 导出（v3 Phase-4）：openpyxl 生成真正的 .xlsx。

版式按反馈人的 MM 模板（`KW39 23.09.2026_SBS Sourcing Alignment Committee_MM.xlsx`，2026-09-24）：
一个零件一行，案例级单元格跨行合并；件价 / 产量 / 模具费按零件行；v3 Phase-15 起项目 / 类型 / 供应商也按零件行
（旧多零件案例的行上没有就回退到案例级值），Peak Year / LT Spend 按整个 bundle 在案例级合并；节省额写成 Excel 公式，
沿用模板的算法 —— (推荐供应商价 − CQA 价) × 产量，正数 = 高于 CQA，负数 = 低于 CQA（节省）。
Agenda 是会前文件（没有决议列，蓝色表头）；Minutes 是会后文件（多 Sourcing Decision、Notes、Action Status，
绿色表头，另带 "Actions" 表一待办一行）。周号沿用系统周（与页面一致），改 KW 见 Phase-13。
"""

from __future__ import annotations

import io
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import logic

FONT = "Arial"
TITLE_FONT = Font(name=FONT, size=14, bold=True)
NOTE_FONT = Font(name=FONT, size=9, italic=True, color="666666")
HEADER_FONT = Font(name=FONT, size=10, bold=True, color="FFFFFF")
BODY_FONT = Font(name=FONT, size=10)
THIN = Side(style="thin", color="CCCCCC")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
MONEY_INT = "#,##0"
MONEY_DEC = "#,##0.00##"
MONEY_2 = "#,##0.00"  # 模具费是整笔金额，显示 2 位小数（单元格里仍是完整数值）
# 金额列按案例币种带货币符号（反馈人模板的节省额格式：#,##0 [$€-407]）；产量列不带
CURRENCY_SUFFIX = {"EUR": "\\ [$€-407]", "USD": "\\ [$$-409]", "CNY": "\\ [$¥-804]"}
DATE_FMT = "yyyy-mm-dd"  # 会议日期 / 到期日写成真日期，Excel 里能按日期筛选排序
# 决议文案按模板写法（系统内部值是大写）
DECISION_TEXT = {"PENDING": "Pending", "APPROVED": "Approved", "CONDITIONAL APPROVAL": "Approved with conditions",
                 "REJECTED": "Rejected"}
# 两种文件在视觉上区分开：议程蓝、纪要绿（表头、标题、工作表标签同色）
THEME = {"agenda": "1F4E79", "minutes": "375623"}
KIND_TITLE = {"agenda": "Sourcing Committee Agenda", "minutes": "Sourcing Committee Meeting Minutes"}
HEADER_ROW = 4

Getter = Callable[[dict, dict], Any]
Formula = Callable[[dict[str, str], int], str]


@dataclass(frozen=True)
class Col:
    header: str
    scope: str  # "case"：案例级，跨零件行合并；"row"：每个零件行；"formula"：按行写公式
    get: Getter | None = None
    formula: Formula | None = None
    fmt: str | None = None
    money: bool = False  # True：数字格式后面加案例币种的符号


def money_fmt(col: Col, c: dict) -> str | None:
    if not (col.money and col.fmt):
        return col.fmt
    return col.fmt + CURRENCY_SUFFIX.get(str(c.get("spendCurrency") or "USD"), "")


def _money(v: Any) -> Decimal | int | None:
    """欧元文本 / 整数 → 数字单元格；空 → None。"""
    if v is None or v == "":
        return None
    return Decimal(str(v)) if "." in str(v) else int(v)


def _date(v: Any) -> date | None:
    """ISO 日期文本 → 日期单元格；其它（空、"—"、旧文本）→ None，调用方回退到原文本。"""
    try:
        return date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def _decision(c: dict) -> str:
    raw = str(c.get("meetingDecision") or "")
    return DECISION_TEXT.get(raw, raw)


def _int(v: Any) -> int | None:
    return None if v in (None, "") else int(v)


def _regions(c: dict) -> str:
    return ", ".join(part.strip() for part in str(c.get("region") or "").split("+") if part.strip())


def _decision_level(c: dict) -> str:
    return re.sub(r"^Level\s+", "L", str(c.get("decisionLevel") or ""))


def _late(c: dict) -> str:
    late = c.get("lateRegistration")
    return f"Yes — {late.get('reason', '')}".rstrip(" —") if late else ""


def _notes(c: dict) -> str:
    """纪要的 Notes / Task 列：委员会讨论 + 编号的待办（任务 — 负责人, 到期 [状态]）。"""
    parts: list[str] = []
    discussion = (c.get("committeeDiscussion") or "").strip()
    if discussion and not discussion.startswith("Pending for Sourcing Committee Review"):
        parts.append(discussion)
    if c.get("meetingDecision") != "PENDING":
        for i, t in enumerate(c.get("followUps") or [], start=1):
            parts.append(f"{i}. {t.get('task', '')} — {t.get('responsible') or '—'}, due {t.get('dueDate') or '—'} [{t.get('status') or ''}]")
    return "\n".join(parts)


def _action_status(c: dict) -> str:
    if c.get("meetingDecision") == "PENDING":
        return ""
    return "No action" if c.get("actionStatus") is None else str(c.get("actionStatus"))


def columns(kind: str) -> list[Col]:
    case = lambda key: (lambda c, r: c.get(key) or "")
    row = lambda key: (lambda c, r: r.get(key) or "")
    row_or_case = lambda key: (lambda c, r: r.get(key) or c.get(key) or "")
    cols = [
        Col("#", "case", lambda c, r: c.get("caseNumber")),
        Col("KW", "case", lambda c, r: logic.wk(int(c.get("weekNum") or 0))),
        Col("Meeting Date", "case", lambda c, r: _date(c.get("meetingDateISO")) or c.get("meetingDateLabel") or "", fmt=DATE_FMT),
        Col("Region", "case", lambda c, r: _regions(c)),
        Col("Type", "row", row_or_case("sourcingType")),
        Col("Project / Product", "row", row_or_case("project")),
        Col("Commodity", "case", case("cluster")),
        Col("Parent PF Code", "case", case("parentPF")),
        Col("SWAT ID / Bundle ID", "case", case("swatId")),
        Col("Part Description", "row", row("partDescription")),
        Col("PN", "row", row("partNumber")),
        Col("Recommended Supplier(s)", "row", row_or_case("recommendedSupplier")),
        Col("Presenter", "case", case("presenter")),
        Col("Decision Level", "case", lambda c, r: _decision_level(c)),
        Col("Peak Year Spend", "case", lambda c, r: _money(c.get("peakYearSpend") or 0), fmt=MONEY_INT, money=True),
        Col("LT Spend", "case", lambda c, r: _money(c.get("lifetimeSpend") or 0), fmt=MONEY_INT, money=True),
        Col("Currency", "case", lambda c, r: c.get("spendCurrency") or "USD"),  # 旧数据没有币种信息，当初按美元录入
        Col("Comment", "case", case("submitterComments")),
    ]
    if kind == "minutes":
        cols += [
            Col("Sourcing Decision", "case", lambda c, r: _decision(c)),
            Col("Notes / Task / Resp. / Due Date", "case", lambda c, r: _notes(c)),
        ]
    cols += [
        Col("CQA PC Price", "row", lambda c, r: _money(r.get("pcPriceCQA")), fmt=MONEY_DEC, money=True),
        Col("Rec. Supplier Landed", "row", lambda c, r: _money(r.get("supplierPriceLanded")), fmt=MONEY_DEC, money=True),
        Col("Average Volume", "row", lambda c, r: _int(r.get("averageVolume")), fmt=MONEY_INT),
        Col("LT Volume", "row", lambda c, r: _int(r.get("lifetimeVolume")), fmt=MONEY_INT),
        Col("Average Year Saving vs CQA", "formula",
            formula=lambda L, n: f"=({L['Rec. Supplier Landed']}{n}-{L['CQA PC Price']}{n})*{L['Average Volume']}{n}", fmt=MONEY_DEC, money=True),
        Col("LT Saving vs CQA", "formula",
            formula=lambda L, n: f"=({L['Rec. Supplier Landed']}{n}-{L['CQA PC Price']}{n})*{L['LT Volume']}{n}", fmt=MONEY_DEC, money=True),
        Col("CQA Tooling", "row", lambda c, r: _money(r.get("toolingCQA")), fmt=MONEY_2, money=True),
        Col("Rec. Supplier Tooling", "row", lambda c, r: _money(r.get("supplierToolingCost")), fmt=MONEY_2, money=True),
        Col("Tooling Saving vs CQA", "formula",
            formula=lambda L, n: f"={L['Rec. Supplier Tooling']}{n}-{L['CQA Tooling']}{n}", fmt=MONEY_2, money=True),
        Col("Tooling Payment", "case", case("toolingPayment")),
        Col("BPG available", "case", case("bpgAvailable")),
        Col("FRA available", "case", case("fraAvailable")),
        Col("Late Registration", "case", lambda c, r: _late(c)),
    ]
    if kind == "minutes":
        cols.append(Col("Action Status", "case", lambda c, r: _action_status(c)))
    return cols


def _style(cell, value: Any, fmt: str | None, *, wrap: bool) -> None:
    cell.font = BODY_FONT
    cell.border = BORDER
    cell.alignment = Alignment(vertical="top", wrap_text=wrap)
    if fmt and value is not None:
        cell.number_format = fmt


def _write_text_or_number(ws, r: int, col: int, value: Any, fmt: str | None) -> None:
    cell = ws.cell(row=r, column=col)
    cell.value = value
    if isinstance(value, str) and cell.data_type == "f":
        cell.data_type = "s"  # 以 "=" 开头的文本按文本存，Excel 不会当公式执行
    _style(cell, value, fmt, wrap=isinstance(value, str) and (len(value) > 40 or "\n" in value))


def _write_formula(ws, r: int, col: int, formula: str, fmt: str | None) -> None:
    cell = ws.cell(row=r, column=col)
    cell.value = formula  # 这里要的就是公式
    _style(cell, formula, fmt, wrap=False)


def _sorted(cases: list[dict]) -> list[dict]:
    return sorted(cases, key=lambda c: (int(c.get("weekNum") or 0), int(c.get("caseNumber") or 0), str(c.get("swatId") or "")))


def _header(ws, kind: str, title: str, note: str, headers: list[str]) -> None:
    color = THEME[kind]
    ws["A1"] = title
    ws["A1"].font = Font(name=FONT, size=14, bold=True, color=color)
    ws["A2"] = note
    ws["A2"].font = NOTE_FONT
    ws.sheet_properties.tabColor = color
    fill = PatternFill("solid", fgColor=color)
    for i, name in enumerate(headers, start=1):
        cell = ws.cell(row=HEADER_ROW, column=i, value=name)
        cell.font, cell.fill, cell.border = HEADER_FONT, fill, BORDER
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    ws.freeze_panes = ws.cell(row=HEADER_ROW + 1, column=1)


def _finish(ws, headers: list[str], widths: dict[int, int], last_row: int) -> None:
    for i, w in widths.items():
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.auto_filter.ref = f"A{HEADER_ROW}:{get_column_letter(len(headers))}{max(HEADER_ROW + 1, last_row)}"


def _note(kind: str, when: datetime) -> str:
    what = "Agenda (pre-meeting)" if kind == "agenda" else "Meeting minutes (post-meeting)"
    return (f"{what} generated {logic.fmt_when(when)} from the Seat Belt Sourcing Committee Cockpit. "
            "One row per part number; case-level cells are merged (Peak Year / LT Spend are per bundle). Amounts in the Currency column "
            "(EUR for cases registered after the EUR switch). Savings follow the SBS template: "
            "(recommended supplier − CQA) × volume, so a negative value means below CQA. "
            "Week numbers are ISO calendar weeks (KW).")


def build(kind: str, cases: list[dict], label: str, when: datetime | None = None) -> bytes:
    """议程或纪要工作簿；label 进标题，如 "2026-KW39" 或 "Database export, 12 cases (Sep 24, 2:00 PM)"。"""
    cols = columns(kind)
    headers = [col.header for col in cols]
    letters = {col.header: get_column_letter(i) for i, col in enumerate(cols, start=1)}
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = "Agenda" if kind == "agenda" else "Minutes"
    _header(ws, kind, f"{KIND_TITLE[kind]} — {label}", _note(kind, when or logic.na_now()), headers)
    widths = {i: len(h) + 2 for i, h in enumerate(headers, start=1)}
    r = HEADER_ROW + 1
    for c in _sorted(cases):
        rows = logic.part_number_lines(c)
        first, last = r, r + len(rows) - 1
        for line in rows:
            for i, col in enumerate(cols, start=1):
                if col.formula is not None:
                    _write_formula(ws, r, i, col.formula(letters, r), money_fmt(col, c))
                    continue
                if col.scope == "case" and r != first:
                    _style(ws.cell(row=r, column=i), None, None, wrap=False)  # 合并区域内的格子只补边框
                    continue
                value = col.get(c, line) if col.get else None
                _write_text_or_number(ws, r, i, value, money_fmt(col, c))
                widths[i] = max(widths[i], min(48, len(str(value if value is not None else "")) + 2))
            r += 1
        if last > first:
            for i, col in enumerate(cols, start=1):
                if col.scope == "case":
                    ws.merge_cells(start_row=first, end_row=last, start_column=i, end_column=i)
    _finish(ws, headers, widths, r - 1)
    if kind == "minutes":
        _actions_sheet(wb.create_sheet("Actions"), cases, label)
    return _bytes(wb)


def build_agenda(cases: list[dict], week_label: str, when: datetime | None = None) -> bytes:
    return build("agenda", cases, week_label, when)


def build_minutes(cases: list[dict], week_label: str, when: datetime | None = None) -> bytes:
    return build("minutes", cases, week_label, when)


ACTION_HEADERS = ["#", "SWAT Case Number", "Part Description", "Sourcing Decision", "Task", "Category", "Owner",
                  "Due Date", "Status", "Reminder to", "CC", "Notes"]


def _actions_sheet(ws, cases: list[dict], label: str) -> None:
    """纪要第二个表：已有决议案例的每个待办一行。"""
    _header(ws, "minutes", f"Follow-up Actions — {label}",
            "One row per follow-up task of the decided cases; Pending cases carry no actions yet.", ACTION_HEADERS)
    widths = {i: len(h) + 2 for i, h in enumerate(ACTION_HEADERS, start=1)}
    r, n = HEADER_ROW + 1, 0
    for c in _sorted(cases):
        if c.get("meetingDecision") == "PENDING":
            continue
        for t in c.get("followUps") or []:
            n += 1
            recipient = logic.task_recipient(t)
            values = [n, c.get("swatId", ""), c.get("partDescription", ""), _decision(c), t.get("task", ""),
                      ", ".join(t.get("tags") or []), t.get("responsible", ""), _date(t.get("dueDate")) or t.get("dueDate", ""),
                      t.get("status") or "", recipient["email"], recipient["cc"], t.get("notes") or ""]
            for i, value in enumerate(values, start=1):
                _write_text_or_number(ws, r, i, value, DATE_FMT if ACTION_HEADERS[i - 1] == "Due Date" else None)
                widths[i] = max(widths[i], min(48, len(str(value)) + 2))
            r += 1
    _finish(ws, ACTION_HEADERS, widths, r - 1)


def _bytes(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def filename(kind: str, label: str) -> str:
    return f"Sourcing_Committee_{'Agenda' if kind == 'agenda' else 'Minutes'}_{label}.xlsx"
