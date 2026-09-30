"""模板 _template.html 内嵌 JS 业务逻辑的忠实移植。

字段名、取值、嵌套结构、校验文案与模板逐字一致 —— 前端因此零适配。
所有对案例/提交的修改都以 dict 操作完成，持久化由 service 层负责。
"""

from __future__ import annotations

import calendar
import re
import uuid
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from urllib.parse import quote, urlsplit
from zoneinfo import ZoneInfo

from .config import get_settings

# ============================= 常量（与模板 DATA MODEL 一致） =============================

ACTION_TAGS = ["Cost", "Volume", "Timing", "Quality", "Capacity", "Commercial Terms", "Compliance / Documentation"]
# 反馈 PPT 第 4 页：待办的固定分类（编辑页只提供这八个；ACTION_TAGS 是种子数据里的旧标签，旧任务上保留显示）
ACTION_CATEGORIES = ["CQA", "Volume", "Technical", "Timing", "Supplier strategy", "BPG", "Saving", "Further VAVE"]
CONTACTS = {
    "W. Chen": "w.chen@zf.com", "M. Okafor": "m.okafor@zf.com", "L. Novak": "l.novak@zf.com",
    "R. Fischer": "r.fischer@zf.com", "S. Iyer": "s.iyer@zf.com", "J. Park": "j.park@zf.com",
    "A. Baptiste": "a.baptiste@zf.com", "H. Meyer": "h.meyer@zf.com", "K. Reyes": "k.reyes@zf.com",
}
REMINDER_DEFAULTS: dict[str, Any] = {
    "enabled": True, "daysBefore": 0, "onDueDate": True, "overdueEveryDays": 1,
    "channel": "Email + Teams", "alwaysCc": "", "lastRunDate": None, "lastRun": None,
}

# 登记截止（反馈 PPT 第 2 页）：会议固定周三，截止 = 会前 daysBefore 天的 cutoffTime；timezone 空 = 服务器时区。
# 默认沿用模板：周一 23:59 —— 管理员可在 Dashboard 改成如 "会前 1 天 18:00 Europe/Berlin"
REGISTRATION_DEFAULTS: dict[str, Any] = {"daysBefore": 2, "cutoffTime": "23:59", "timezone": "", "updatedAt": ""}
MEETING_WEEKDAY = 2  # 周三（Mon=0）

# 汇率表按财务 OP 表的记法（v3 Phase-12）：perEur 里存 "1 EUR = X 外币" 的十进制文本（如 {"USD": "1.17"}），
# 折算用除法；欧元恒为 1。早期存的是 rates（"1 外币 = r EUR"），读出时由 normalize_fx_settings 换算
FX_DEFAULTS: dict[str, Any] = {"basis": "", "perEur": {}, "updatedAt": ""}
# 折算后的记录上与金额相关的字段；登记确认成案例时原样带过去
SPEND_META_KEYS = ("spendCurrency", "fx", "peakYearSpendEntered", "lifetimeSpendEntered")

# 反馈 PPT 第 2、3 页：商务字段。金额类按提交币种填写、折算欧元后存文本（保留 4 位小数），原币存 *Entered
BPG_THRESHOLD_EUR = 3_000_000  # Lifetime Spend 超过这个数（欧元）必须有 BPG
# 反馈人 MM 模板（2026-09-24）：件价、模具费、产量按零件行记录；单零件记录同时放在顶层
# （与 partNumber / peakYearSpend 的模板约定一致），多零件记录顶层置 None、以行为准。
ROW_MONEY_KEYS = ("pcPriceCQA", "supplierPriceLanded", "toolingCQA", "supplierToolingCost")
# v3 Phase-15：项目 / 寻源类型 / 推荐供应商按零件行；金额（Peak Year / Lifetime Spend）按整个 bundle 在案例级
ROW_BUNDLE_KEYS = ("project", "sourcingType", "recommendedSupplier")
ROW_SPEND_KEYS = ("peakYearSpend", "lifetimeSpend", "peakYearSpendEntered", "lifetimeSpendEntered")
ROW_INT_KEYS = ("averageVolume", "lifetimeVolume")
ROW_COMMERCIAL_KEYS = (*ROW_MONEY_KEYS, *(f"{k}Entered" for k in ROW_MONEY_KEYS), *ROW_INT_KEYS)
COMMERCIAL_MONEY_KEYS = (*ROW_MONEY_KEYS, "amortizationTotal")
COMMERCIAL_KEYS = (
    *COMMERCIAL_MONEY_KEYS, *(f"{k}Entered" for k in COMMERCIAL_MONEY_KEYS), *ROW_INT_KEYS,
    "toolingPayment", "bpgAvailable", "fraAvailable", "belowCQA", "cqaJustification", "strategicSupplier",
    "ltaAvailable", "fotLeadTimeWeeks", "ppapLeadTimeWeeks", "amortizationPcs", "amortizationPerPc",
    "usmcaEligible", "annualCapacity", "lifetimeCapacity",
)

URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_http_url(value: str) -> bool:
    """只接受带主机名的 HTTP(S) 链接，不将浏览器会重新解释的控制字符视为 URL。"""
    if not URL_RE.fullmatch(value) or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return False
    if any(ch in value for ch in '\\<>"'):
        return False
    try:
        parsed = urlsplit(value)
        return bool(parsed.hostname) and (parsed.port is None or 0 < parsed.port <= 65535)
    except ValueError:
        return False


def _days_until_due(today: str, due: Any) -> int | None:
    if not isinstance(due, str) or not ISO_DATE_RE.fullmatch(due):
        return None
    try:
        return days_between_iso(today, due)
    except ValueError:
        # 历史版本只检验字符串形状；一条不存在的日期不能中断整批提醒。
        return None

# ============================= 时间与格式 =============================


def app_tz() -> ZoneInfo:
    """参考时区可配（SC_TIMEZONE，默认北美东部，模板原设定）。"""
    return ZoneInfo(get_settings().timezone)


def na_now() -> datetime:
    return datetime.now(app_tz())


def today_iso() -> str:
    d = na_now()
    return f"{d.year}-{d.month:02d}-{d.day:02d}"


def days_between_iso(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _month_abbr(d: datetime) -> str:
    return calendar.month_name[d.month][:3]


def _clock(d: datetime) -> str:
    h = d.hour % 12 or 12
    return f"{h}:{d.minute:02d} {'AM' if d.hour < 12 else 'PM'}"


def fmt_when(d: datetime) -> str:
    """日志时间戳，对应 JS toLocaleString({month:'short',day:'numeric',hour:'numeric',minute:'2-digit'})。"""
    return f"{_month_abbr(d)} {d.day}, {_clock(d)}"


def fmt_submitted_at(d: datetime) -> str:
    """提交时间戳，对应 JS toLocaleString({month:'short',day:'numeric',year:'numeric',hour,minute})。"""
    return f"{_month_abbr(d)} {d.day}, {d.year}, {_clock(d)}"


def _cutoff_tz(settings: dict) -> ZoneInfo:
    return ZoneInfo(settings.get("timezone") or get_settings().timezone)


def registration_cutoff(meeting_date: date, settings: dict) -> datetime:
    """某次会议的登记截止时刻（带时区）。"""
    hh, mm = (int(x) for x in str(settings.get("cutoffTime") or "23:59").split(":"))
    cutoff_date = meeting_date - timedelta(days=int(settings.get("daysBefore") or 2))
    return datetime.combine(cutoff_date, time(hh, mm), tzinfo=_cutoff_tz(settings))


def registration_open(meeting_date: date, settings: dict, now: datetime | None = None) -> bool:
    """截止那一分钟内仍算开放（now <= cutoff）。"""
    return (now or na_now()) <= registration_cutoff(meeting_date, settings)


def cutoff_label(settings: dict) -> str:
    """给人看的规则文本，如 "Monday 23:59 (America/New_York)"。"""
    weekday = (MEETING_WEEKDAY - int(settings.get("daysBefore") or 2)) % 7
    return f"{calendar.day_name[weekday]} {settings.get('cutoffTime') or '23:59'} ({_cutoff_tz(settings).key})"


def cutoff_moment_label(meeting_date: date, settings: dict) -> str:
    """某次会议截止时刻的文本，如 "Mon, Sep 28, 2026 23:59 (America/New_York)"。"""
    c = registration_cutoff(meeting_date, settings)
    return f"{calendar.day_abbr[c.weekday()]}, {calendar.month_abbr[c.month]} {c.day}, {c.year} {c:%H:%M} ({c.tzinfo.key})"


def wk(w: int) -> str:
    # ISO 周（KW）标签，如 "2026-KW40"。年份随当前日期走（原硬编码 2026，跨年后生成的周标签全部错位）
    return f"{na_now().year}-KW{w:02d}"


def iso_week_of_record(record: dict) -> int:
    """v3 Phase-13：把按模板周（1 月 1 日起每 7 天）存的记录换成 ISO 周号。

    有会议日期（meetingDateISO，或 "Wed, Oct 7, 2026" 这样的 meetingDateLabel）按日期算；没有日期的
    是模板演示数据（2026 年，1 月 1 日是周四），模板第 w 周的周三落在 ISO 第 w + 1 周，上限 53。"""
    meeting = _meeting_date(record)
    if meeting is not None:
        return meeting.isocalendar().week
    return min(int(record.get("weekNum") or 1) + 1, 53)


def _meeting_date(record: dict) -> date | None:
    iso = record.get("meetingDateISO") or ""
    if ISO_DATE_RE.match(iso):
        try:
            return date.fromisoformat(iso)
        except ValueError:
            pass
    try:
        return datetime.strptime(record.get("meetingDateLabel") or "", "%a, %b %d, %Y").date()  # noqa: DTZ007 只取日期，不涉及时刻
    except ValueError:
        return None

# ============================= 基础规则 =============================


def rate_text(rate: Decimal) -> str:
    """汇率存成不带多余 0 的十进制文本：Decimal("0.9200") → "0.92"，Decimal("1.0") → "1"。"""
    return format(rate.normalize(), "f")


@dataclass(frozen=True)
class Fx:
    """一条折算规则。per_eur 是财务 OP 记法 "1 EUR = X 外币"，按除法折算（汇率表与新记录都用它）；
    legacy_rate 是 v3 Phase-2 早期记录上的 "1 外币 = r EUR"，按乘法，只为读这些记录。"""

    per_eur: Decimal = Decimal(1)
    legacy_rate: Decimal | None = None

    def eur(self, amount: Decimal) -> Decimal:
        """未取整的欧元金额；取整由调用方决定（支出取整欧元，件价保留 4 位小数）。"""
        if self.legacy_rate is not None:
            return amount * self.legacy_rate
        return amount / self.per_eur


EUR_FX = Fx()


def fx_rate(fx_settings: dict, currency: str) -> Fx | None:
    """按汇率表取 currency 的折算规则；欧元恒为 1，未设置汇率时返回 None。"""
    if currency == "EUR":
        return EUR_FX
    per_eur = (fx_settings.get("perEur") or {}).get(currency)
    return Fx(per_eur=Decimal(per_eur)) if per_eur else None


def fx_of(snapshot: dict | None) -> Fx:
    """记录上的汇率快照 → 折算规则。没有快照（旧美元数据）按 1 处理，金额原样。"""
    if not snapshot:
        return EUR_FX
    if snapshot.get("perEur"):
        return Fx(per_eur=Decimal(snapshot["perEur"]))
    if snapshot.get("rate"):
        return Fx(legacy_rate=Decimal(snapshot["rate"]))
    return EUR_FX


def normalize_fx_settings(doc: dict) -> dict:
    """早期汇率表（rates："1 外币 = r EUR"，6 位小数的倒数）换成 OP 记法，取 4 位小数（0.854701 → 1.17）。"""
    if "perEur" in doc or not doc.get("rates"):
        return {k: v for k, v in doc.items() if k != "rates"}
    per_eur = {code: rate_text((1 / Decimal(rate)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
               for code, rate in doc["rates"].items() if rate}
    return {**{k: v for k, v in doc.items() if k != "rates"}, "perEur": per_eur}


def to_eur(amount: int, fx: Fx) -> int:
    """折算到整欧元，四舍五入（ROUND_HALF_UP）；用 Decimal 计算，避免 8.3 这类汇率的浮点误差。"""
    return int(fx.eur(Decimal(amount)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def convert_spend(parts: list[dict], fx: Fx, peak: int, life: int) -> dict:
    """v3 Phase-15：Peak Year / Lifetime Spend 按整个 bundle 填一个（原币），折算成欧元，原币另存为 *Entered；
    零件行只折算件价 / 模具费，不再带金额（旧记录行上的金额由 convert_legacy_record 处理）。"""
    converted = [{**{k: v for k, v in p.items() if k not in ROW_SPEND_KEYS}, **_row_amounts(p, fx)} for p in parts]
    return {
        "partNumbers": converted,
        "peakYearSpend": to_eur(peak, fx), "lifetimeSpend": to_eur(life, fx),
        "peakYearSpendEntered": peak, "lifetimeSpendEntered": life,
    }


def _convert_legacy_rows(parts: list[dict], fx: Fx) -> dict:
    """Phase-15 之前的记录：金额在零件行上，逐行折算、合计取各行欧元之和（明细与合计逐行对得上）。"""
    converted = []
    for p in parts:
        peak, life = int(p.get("peakYearSpend") or 0), int(p.get("lifetimeSpend") or 0)
        converted.append({**p, "peakYearSpend": to_eur(peak, fx), "lifetimeSpend": to_eur(life, fx),
                          "peakYearSpendEntered": peak, "lifetimeSpendEntered": life, **_row_amounts(p, fx)})
    return {
        "partNumbers": converted,
        "peakYearSpend": sum(p["peakYearSpend"] for p in converted),
        "lifetimeSpend": sum(p["lifetimeSpend"] for p in converted),
        "peakYearSpendEntered": sum(p["peakYearSpendEntered"] for p in converted),
        "lifetimeSpendEntered": sum(p["lifetimeSpendEntered"] for p in converted),
    }


def bundle_rows(rows: list[dict], defaults: dict) -> list[dict]:
    """零件行的项目 / 寻源类型 / 推荐供应商：行上留空的沿用案例级值（旧客户端只填案例级）。"""
    return [{**p, **{k: (p.get(k) or "").strip() or (defaults.get(k) or "").strip() for k in ROW_BUNDLE_KEYS}} for p in rows]


def bundle_summary(rows: list[dict]) -> dict:
    """案例级的项目 / 寻源类型 / 推荐供应商 = 各零件行去重后按出现顺序用 ", " 连接（页面列表、搜索与导出回退用）。"""
    out: dict[str, str] = {}
    for key in ROW_BUNDLE_KEYS:
        seen: list[str] = []
        for p in rows:
            v = (p.get(key) or "").strip()
            if v and v not in seen:
                seen.append(v)
        out[key] = ", ".join(seen)
    return out


def bundle_rows_error(rows: list[dict]) -> str | None:
    if any(not p.get(k) for p in rows for k in ROW_BUNDLE_KEYS):
        return "⚠ Please fill in Project, Sourcing Type and Recommended Supplier for every part number row before submitting."
    return None


def _row_amounts(p: dict, fx: Fx) -> dict:
    """零件行上的件价 / 模具费折算欧元存文本（4 位小数），原币另存 *Entered；产量原样。"""
    out: dict[str, Any] = {}
    for key in ROW_MONEY_KEYS:
        raw = p.get(key)
        amount = Decimal(str(raw)) if raw not in (None, "") else None
        out[key] = money_text(convert_money(amount, fx)) if amount is not None else None
        out[f"{key}Entered"] = money_text(amount) if amount is not None else None
    for key in ROW_INT_KEYS:
        out[key] = p.get(key) if p.get(key) not in (None, "") else None
    return out


def part_number_lines(record: dict) -> list[dict]:
    """记录的零件行：多零件用 partNumbers；单零件（案例上 partNumbers 为 None）由顶层字段拼出一行。"""
    lines = record.get("partNumbers")
    if lines:
        return lines
    keys = ("partNumber", "partDescription", *ROW_BUNDLE_KEYS, *ROW_SPEND_KEYS, *ROW_COMMERCIAL_KEYS)
    return [{k: record.get(k) for k in keys if k in record}]


def sync_row_commercial(record: dict, rows: list[dict]) -> None:
    """单零件：行上的件价 / 模具费 / 产量同时放到记录顶层；多零件：顶层置 None，以行为准。"""
    single = rows[0] if len(rows) == 1 else None
    for key in ROW_COMMERCIAL_KEYS:
        record[key] = deepcopy(single.get(key)) if single is not None else None


def money_text(amount: Decimal) -> str:
    """金额存成不带多余 0 的十进制文本：Decimal("9.6600") → "9.66"，Decimal("1500.00") → "1500"。"""
    return format(amount.normalize(), "f")


def convert_money(amount: Decimal, fx: Fx) -> Decimal:
    """件价 / 模具费折算欧元：保留 4 位小数，ROUND_HALF_UP。"""
    return fx.eur(amount).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def validate_commercial(b: dict, lifetime_spend_eur: int) -> str | None:
    """商务字段门禁；返回 None 表示通过。文案与前端提交页一致。"""
    rows = b.get("partNumbers") or []
    if not rows or any(row.get(k) in (None, "") for row in rows for k in ROW_MONEY_KEYS):
        return ("⚠ Please fill in Pc Price CQA, Supplier Price (landed), Tooling CQA and Supplier Tooling Cost "
                "for every part number row before submitting (enter 0 if not applicable).")
    if not b.get("toolingPayment"):
        return "⚠ Please select the Tooling Payment (Lumpsum or MPC) before submitting."
    if lifetime_spend_eur > BPG_THRESHOLD_EUR:
        if not b.get("bpgAvailable"):
            return "⚠ Lifetime Spend is above 3 Mio EUR — please answer whether a BPG is available."
        if b.get("bpgAvailable") == "No":
            return "⚠ This case cannot be registered: Lifetime Spend above 3 Mio EUR requires an available BPG."
    if b.get("decisionLevel") == "Level 2":
        if not b.get("fraAvailable"):
            return "⚠ Please answer whether an FRA is available (required for Level 2 cases)."
        if b.get("fraAvailable") == "No":
            return "⚠ This case cannot be registered: a Level 2 case requires an available FRA."
    if b.get("belowCQA") == "No" and not (b.get("cqaJustification") or "").strip():
        return "⚠ Please provide a justification when the price is not below CQA."
    return None


def validate_commercial_state(c: dict) -> str | None:
    """案例编辑后的商务门槛：明确答 No 的拒绝，留空放行（没有这些字段的旧案例仍可编辑）。

    与 validate_commercial 的区别：提交时四个价格与 Tooling Payment 必填，编辑时不强求，
    否则登记在商务字段之前的案例连决议都记录不了。"""
    if (c.get("spendCurrency") == "EUR" and int(c.get("lifetimeSpend") or 0) > BPG_THRESHOLD_EUR
            and c.get("bpgAvailable") == "No"):
        return "⚠ Lifetime Spend above 3 Mio EUR requires an available BPG — set BPG available to Yes, or leave it blank."
    if c.get("decisionLevel") == "Level 2" and c.get("fraAvailable") == "No":
        return "⚠ A Level 2 case requires an available FRA — set FRA available to Yes, or leave it blank."
    if c.get("belowCQA") == "No" and not (c.get("cqaJustification") or "").strip():
        return "⚠ Please provide a justification when the price is not below CQA."
    return None


def commercial_fields(b: dict, fx: Fx) -> dict:
    """把请求里的案例级商务字段整理成记录字段：金额折算欧元存文本、原币另存，摊销单价按欧元总额 / 件数算出。
    零件行上的件价 / 模具费由 convert_spend 处理，再由 sync_row_commercial 同步到顶层。"""
    out: dict[str, Any] = {}
    for key in ("amortizationTotal",):
        raw = b.get(key)
        amount = Decimal(str(raw)) if raw is not None else None
        out[key] = money_text(convert_money(amount, fx)) if amount is not None else None
        out[f"{key}Entered"] = money_text(amount) if amount is not None else None
    for key in ("toolingPayment", "bpgAvailable", "fraAvailable", "belowCQA", "strategicSupplier",
                "ltaAvailable", "usmcaEligible"):
        out[key] = b.get(key) or ""
    out["cqaJustification"] = (b.get("cqaJustification") or "").strip()
    for key in ("fotLeadTimeWeeks", "ppapLeadTimeWeeks", "amortizationPcs", "annualCapacity", "lifetimeCapacity"):
        out[key] = b.get(key) if b.get(key) is not None else None
    out["amortizationPerPc"] = amortization_per_pc(out["amortizationTotal"], out["amortizationPcs"])
    return out


def amortization_per_pc(total_eur: str | None, pcs: int | None) -> str:
    """摊销单价 = 欧元总额 / 件数，4 位小数；缺一项时为空文本。"""
    if total_eur is None or not pcs:
        return ""
    return money_text((Decimal(total_eur) / pcs).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def convert_legacy_record(record: dict, fx_snapshot: dict, when: str) -> bool:
    """v3 Phase-12：旧美元记录（没有 spendCurrency）一次性换算成欧元；已有币种的返回 False、原样不动。

    与新提交同一套规则：逐行折算、合计 = 各行欧元之和，原美元金额留在 *Entered；记录带上汇率快照
    与换算时间（when），之后编辑按美元填写、沿用这个汇率（apply_case_edit）。"""
    if record.get("spendCurrency"):
        return False
    fx = fx_of(fx_snapshot)
    has_rows = bool(record.get("partNumbers"))
    spend = _convert_legacy_rows(part_number_lines(record), fx)
    if has_rows:
        record["partNumbers"] = spend["partNumbers"]
    # 单零件的金额在记录顶层：案例的 partNumbers 为 None，模板演示数据里的提交单干脆没有这个键
    for key in ("peakYearSpend", "lifetimeSpend", "peakYearSpendEntered", "lifetimeSpendEntered"):
        record[key] = spend[key]
    sync_row_commercial(record, spend["partNumbers"])
    amortization = record.get("amortizationTotal")
    if amortization not in (None, ""):
        entered = Decimal(str(amortization))
        record["amortizationTotal"] = money_text(convert_money(entered, fx))
        record["amortizationTotalEntered"] = money_text(entered)
        record["amortizationPerPc"] = amortization_per_pc(record["amortizationTotal"], record.get("amortizationPcs"))
    record["spendCurrency"] = "EUR"
    record["fx"] = {**fx_snapshot, "convertedAt": when}
    return True


def rollup_action_status(follow_ups: list[dict] | None) -> str | None:
    if not follow_ups:
        return None
    statuses = [t.get("status") for t in follow_ups]
    if "Overdue" in statuses:
        return "Overdue"
    if "Open" in statuses:
        return "Open"
    return "Closed"


def email_for(name: str | None) -> str:
    if not name:
        return ""
    if name in CONTACTS:
        return CONTACTS[name]
    if "@" in name:
        return name.strip()
    # 不按姓名猜地址：猜出的域名常常不对（如 zf-lifetec.com），宁可显示 "no email on file"
    return ""


def task_recipient(t: dict) -> dict:
    notify = t.get("notify") or t.get("responsible") or ""
    return {
        "name": notify,
        "email": t.get("notifyEmail") or email_for(notify),
        "cc": t.get("cc") or "",
        "channel": t.get("channel") or "Email + Teams",
    }


def case_link(c: dict, base_url: str = "") -> str:
    """提醒 / 通知信里的 "Open Action Case" 链接。"""
    return base_url.rstrip("/") + "/#case/" + quote(c.get("swatId", ""), safe="")


def reminder_message(c: dict, t: dict, base_url: str = "") -> str:
    """Email/Teams 共用的一封信 —— 不打开驾驶舱也有足够上下文采取行动。"""
    pns = c.get("partNumbers")
    more = f" (+{len(pns) - 1} more)" if pns and len(pns) > 1 else ""
    return "\n".join([
        "Follow-up Task for Sourcing Case",
        "",
        "Part Description: " + (c.get("partDescription") or "—"),
        "Part Number: " + (c.get("partNumber") or "—") + more,
        "SWAT Case: " + c.get("swatId", ""),
        "",
        "Follow-up Task: " + (t.get("task") or "—"),
        "Note: " + (t.get("notes") or "—"),
        "",
        "Due Date: " + (t.get("dueDate") or "—"),
        "Owner: " + (t.get("responsible") or "—"),
        "",
        "Open Action Case: " + case_link(c, base_url),
    ])


def decision_email(sub: dict, approved: bool, base_url: str = "") -> tuple[str, str]:
    """审批结果邮件（确认/退回）—— 提交页承诺的 "You'll be notified by email"。
    与 reminder_message 同一信件风格：不打开驾驶舱也有足够上下文。"""
    pns = sub.get("partNumbers")
    more = f" (+{len(pns) - 1} more)" if pns and len(pns) > 1 else ""
    cid = sub.get("approvedSwatId") or sub.get("caseId") or "—"
    head = [
        "Part Description: " + (sub.get("partDescription") or "—"),
        "Part Number: " + (sub.get("partNumber") or "—") + more,
        "SWAT Case: " + cid,
        "Recommended Supplier: " + (sub.get("recommendedSupplier") or "—"),
        "Submitted: " + (sub.get("submittedAt") or "—") + " by " + (sub.get("submitterName") or "—"),
    ]
    if approved:
        subject = f"Registration Confirmed — Sourcing Case {cid}"
        body = "\n".join([
            "Sourcing Case Registration — Confirmed",
            "",
            *head,
            "",
            "Your registration was confirmed by the SBS Procurement approver. The case now enters",
            "the Database with Sourcing Decision = Pending; the Sourcing Committee will decide later.",
            "",
            "Open Case: " + base_url.rstrip("/") + "/#case/" + quote(str(cid), safe=""),
        ])
    else:
        subject = f"Registration Returned — Sourcing Case {cid}"
        body = "\n".join([
            "Sourcing Case Registration — Returned",
            "",
            *head,
            "",
            "Your registration was returned by the SBS Procurement approver.",
            "",
            "Reason for return:",
            sub.get("rejectReason") or "—",
            "",
            "Please revise the registration and submit it again from the Submit page:",
            base_url.rstrip("/"),
        ])
    return subject, body


def normalize_case_no(v: str | None) -> str:
    v = (v or "").strip()
    m = re.match(r"^swat[\s-]*(\d+)$", v, re.IGNORECASE)
    return f"SWAT-{m.group(1)}" if m else v


def case_no_status(cases: list[dict], v: str | None) -> dict | None:
    cid = normalize_case_no(v)
    if not cid:
        return None
    n = sum(1 for c in cases if c.get("swatId") == cid)
    return {"id": cid, "existing": n > 0, "priorEntries": n}


def next_sub_id(submissions: list[dict]) -> str:
    nums = [int(str(s["subId"]).replace("SUB-", "")) for s in submissions if str(s.get("subId", "")).replace("SUB-", "").isdigit()]
    return f"SUB-{(max(nums) if nums else 0) + 1:04d}"


def next_swat_id(cases: list[dict], submissions: list[dict]) -> str:
    nums = [int(str(c["swatId"]).replace("SWAT-", "")) for c in cases if str(c.get("swatId", "")).replace("SWAT-", "").isdigit()]
    nums += [int(str(s["approvedSwatId"]).replace("SWAT-", "")) for s in submissions
             if s.get("approvedSwatId") and str(s["approvedSwatId"]).replace("SWAT-", "").isdigit()]
    return f"SWAT-{(max(nums) if nums else 10000) + 1}"


def next_case_row_id(cases: list[dict]) -> str:
    nums = [int(c["id"][1:]) for c in cases if str(c.get("id", "")).startswith("C") and str(c["id"][1:]).isdigit()]
    return f"C{(max(nums) if nums else 0) + 1:04d}"

# ============================= 案例构造与种子补齐 =============================


def mk_case(o: dict, all_cases: list[dict]) -> dict:
    """对应 JS mkCase：默认值 + 覆盖；行号自动递增、永不复用。"""
    base: dict[str, Any] = {
        "id": next_case_row_id(all_cases),
        "weekNum": 1, "caseNumber": 1, "swatId": "", "partNumber": "", "partDescription": "",
        "region": "AP", "project": "", "family": "", "cluster": "", "parentPF": "", "partFamilyCode": "",
        "sourcingType": "New", "recommendedSupplier": "", "presenter": "", "decisionLevel": "Level 2",
        "peakYearSpend": 0, "leadTime": "", "lifetimeSpend": 0,
        "committeeDiscussion": "", "meetingDecision": "APPROVED",
        "caseStatus": "Open", "actionStatus": None,
        "meetingDateLabel": None, "partNumbers": None, "createdDate": None, "submitterComments": "",
        "finalDocLink": "",  # 案例最终 PPT/支撑文件链接；全部待办 Closed 时必填
        "sourcingPresentationLink": "",  # 寻源演示文稿链接；记录任何非 Pending 决议时必填
        "followUps": [],
        "closure": {"status": "Open", "closureDate": "—", "closureComment": "—", "closureEvidence": "—"},
        "meetingLink": "#",
    }
    base.update(o)
    return base


def normalize_pending_cases(cases: list[dict]) -> None:
    for c in cases:
        if c.get("meetingDecision") == "PENDING":
            c["actionStatus"] = None
            c["followUps"] = []
            if not c.get("committeeDiscussion") or re.search(r"deferred|pending", c.get("committeeDiscussion", ""), re.IGNORECASE):
                c["committeeDiscussion"] = "Pending for Sourcing Committee Review"


def seed_final_doc_links(cases: list[dict]) -> None:
    for c in cases:
        if c.get("actionStatus") == "Closed" and not c.get("finalDocLink"):
            c["finalDocLink"] = f"https://zf.sharepoint.com/sites/SourcingCommittee/{wk(c['weekNum'])}/{c['swatId']}_Final.pptx"


def seed_presentation_links(cases: list[dict]) -> None:
    for c in cases:
        if c.get("meetingDecision") != "PENDING" and not c.get("sourcingPresentationLink"):
            c["sourcingPresentationLink"] = f"https://zf.sharepoint.com/sites/SourcingCommittee/{wk(c['weekNum'])}/{c['swatId']}_SourcingPresentation.pptx"

# ============================= 详情编辑：三条规则与合并 =============================


def validate_case_edit(b: dict, *, imported: bool = False) -> str | None:
    """三条规则，文案与模板 saveCaseBtn 完全一致；返回 None 表示通过。

    imported=True（v3 Phase-17，从周会 Excel 导入的历史案例）：Excel 里没有演示文稿链接，规则 1 不强求。"""
    presentation = (b.get("sourcingPresentationLink") or "").strip()
    final_doc = (b.get("finalDocLink") or "").strip()
    follow_ups = b.get("followUps") or []
    # 规则 1：记录任何非 Pending 决议必须有寻源演示文稿链接。
    if b.get("meetingDecision") != "PENDING" and not presentation and not imported:
        return ("A Sourcing Decision cannot be saved without the Sourcing Presentation Link. "
                "Enter the link, then save the decision.")
    if presentation and not valid_http_url(presentation):
        return "The Sourcing Presentation Link must be a full URL (starting with http:// or https://)."
    # 反馈 #2：区域至少一个（前端也拦，服务端是权威）。
    if not (b.get("region") or "").strip():
        return "Select at least one Region."
    # 规则 0（模板称 Rule 0）：Pending 案例尚未评审，不能携带会后待办。
    if b.get("meetingDecision") == "PENDING" and follow_ups:
        return ("A case that is Pending for Sourcing Committee Review cannot have follow-up tasks. "
                "Record the Sourcing Decision first, or remove the tasks.")
    # 反馈 #8：未关闭的待办必须有收件邮箱，提醒才发得出去（系统不再按姓名猜邮箱）。
    for i, task in enumerate(follow_ups, start=1):
        if task.get("status") != "Closed" and not (task.get("notifyEmail") or "").strip():
            return f'Follow-up task {i}: enter a valid "Send reminder to" email, so the reminder reaches someone.'
    # 规则 2：全部待办 Closed（案例闭环）必须有最终文件链接。
    if rollup_action_status(follow_ups) == "Closed" and not final_doc:
        return ("All follow-up actions are now Closed, which closes the case — "
                "enter the Final PPT / Supporting Document Link first.")
    if final_doc and not valid_http_url(final_doc):
        return "The Final PPT / Supporting Document Link must be a full URL (starting with http:// or https://)."
    return None


def apply_case_edit(c: dict, b: dict, commercial: dict | None = None) -> None:
    """对应模板 saveCaseBtn 的 Object.assign 段：合并字段、汇总金额、重算 actionStatus。

    commercial：请求里带了商务字段时才传（按原币填写，沿用案例的汇率折算）；不带则原值不动。"""
    # 零件行上的项目 / 类型 / 供应商：行上留空的沿用请求的案例级值，再沿用案例原值
    part_numbers = bundle_rows(b.get("partNumbers") or [], {k: b.get(k) or c.get(k, "") for k in ROW_BUNDLE_KEYS})
    fx = c.get("fx")
    if commercial is not None:
        c.update(commercial_fields(commercial, fx_of(fx)))
    # 编辑页按原币填写；沿用提交时记录的汇率，之后管理员改汇率不会悄悄改动这个案例。
    # 旧数据没有汇率：按 1 处理，金额原样，也不留 *Entered 痕迹。
    # bundle 金额不带时原值不动（按原币：有汇率的案例用 *Entered）
    peak_in = b.get("peakYearSpend")
    life_in = b.get("lifetimeSpend")
    if peak_in is None:
        peak_in = int((c.get("peakYearSpendEntered") if fx else c.get("peakYearSpend")) or 0)
    if life_in is None:
        life_in = int((c.get("lifetimeSpendEntered") if fx else c.get("lifetimeSpend")) or 0)
    spend = convert_spend(part_numbers, fx_of(fx), int(peak_in), int(life_in))
    part_numbers = spend["partNumbers"]
    if fx:
        c["peakYearSpendEntered"] = spend["peakYearSpendEntered"]
        c["lifetimeSpendEntered"] = spend["lifetimeSpendEntered"]
    else:
        c.pop("peakYearSpendEntered", None)
        c.pop("lifetimeSpendEntered", None)
        for p in part_numbers:
            for key in (f"{k}Entered" for k in ROW_MONEY_KEYS):
                p.pop(key, None)
    total_peak, total_life = spend["peakYearSpend"], spend["lifetimeSpend"]
    summary = bundle_summary(part_numbers)
    existing_tasks = {t.get("id"): t for t in c.get("followUps") or []}
    follow_ups = deepcopy(b.get("followUps") or [])
    today = today_iso()
    for task in follow_ups:
        previous = existing_tasks.get(task.get("id"), {})
        # 浏览器可能携带过期快照；投递记录、每日去重标记、反馈与关闭记录（v3 Phase-14）以当前数据库为准。
        for key in ("lastReminder", "lastAutoReminderDate", "feedback", "closure"):
            task.pop(key, None)
            if key in previous:
                task[key] = deepcopy(previous[key])
        days_until = _days_until_due(today, task.get("dueDate"))
        if task.get("status") in ("Open", "Overdue") and days_until is not None:
            task["status"] = "Overdue" if days_until < 0 else "Open"
    c.update({
        "partNumber": part_numbers[0].get("partNumber", ""),
        "partDescription": part_numbers[0].get("partDescription", ""),
        "partNumbers": part_numbers if len(part_numbers) > 1 else None,
        "region": b.get("region", c["region"]), "project": summary["project"],
        "family": b.get("family", c["family"]), "cluster": b.get("cluster", c["cluster"]),
        "parentPF": b.get("parentPF", c.get("parentPF", "")),
        "partFamilyCode": b.get("partFamilyCode", c.get("partFamilyCode", "")),
        "sourcingType": summary["sourcingType"],
        "recommendedSupplier": summary["recommendedSupplier"],
        "presenter": b.get("presenter", c.get("presenter", "")),
        "decisionLevel": b.get("decisionLevel", c["decisionLevel"]),
        "peakYearSpend": total_peak, "leadTime": b.get("leadTime", c.get("leadTime", "")),
        "lifetimeSpend": total_life,
        "committeeDiscussion": b.get("committeeDiscussion", c.get("committeeDiscussion", "")),
        "meetingDecision": b.get("meetingDecision", c["meetingDecision"]),
        "sourcingPresentationLink": (b.get("sourcingPresentationLink") or "").strip(),
        "finalDocLink": (b.get("finalDocLink") or "").strip(),
        "followUps": follow_ups,
    })
    sync_row_commercial(c, part_numbers)
    c["actionStatus"] = None if c["meetingDecision"] == "PENDING" else rollup_action_status(c["followUps"])

# ============================= 登记：确认 / 退回 / 删除 =============================


def confirm_submission(sub: dict, cases: list[dict]) -> dict:
    """确认登记：提交置 Confirmed，建一条 PENDING 案例登场记录。"""
    sub["status"] = "Registration Confirmed"
    sub["approvedSwatId"] = sub.get("caseId") or sub.get("existingSwatId") or next_swat_id(cases, [sub])
    w = sub.get("meetingWeekNum") or (max(c["weekNum"] for c in cases) if cases else 1)
    same_week = [c["caseNumber"] for c in cases if c["weekNum"] == w]
    case_number = (max(same_week) + 1) if same_week else 1
    part_numbers = sub.get("partNumbers")
    meeting_date = sub.get("meetingDateISO") or ""
    meeting_year = int(meeting_date[:4]) if _days_until_due(today_iso(), meeting_date) is not None else None
    case = mk_case({
        "weekNum": w, "caseNumber": case_number,
        "swatId": sub["approvedSwatId"],
        "partNumber": sub.get("partNumber", ""), "partDescription": sub.get("partDescription", ""),
        "partNumbers": part_numbers if part_numbers and len(part_numbers) > 1 else None,
        "region": sub.get("region", ""), "project": sub.get("project", ""),
        "family": sub.get("family", ""), "cluster": sub.get("cluster", ""),
        "parentPF": sub.get("parentPF", ""), "partFamilyCode": sub.get("partFamilyCode", ""),
        "sourcingType": sub.get("sourcingType", ""), "recommendedSupplier": sub.get("recommendedSupplier", ""),
        "presenter": sub.get("presenter", ""), "decisionLevel": sub.get("decisionLevel", ""),
        "peakYearSpend": sub.get("peakYearSpend") or 0, "leadTime": sub.get("leadTime") or "",
        "lifetimeSpend": sub.get("lifetimeSpend") or 0,
        "committeeDiscussion": "Pending for Sourcing Committee Review",
        "submitterComments": sub.get("committeeDiscussion") or "",
        "meetingDecision": "PENDING", "caseStatus": "Open", "actionStatus": None,
        "meetingDateLabel": sub.get("meetingDateLabel") or None,
        "meetingDateISO": meeting_date, "meetingYear": meeting_year,
        "files": deepcopy(sub.get("files") or []),  # v3 Phase-5：提交时上传的演示文件随登记带进案例
        "createdDate": sub.get("submittedAt") or None,
        "followUps": [],
        "closure": {"status": "Open", "closureDate": "—", "closureComment": "Awaiting committee review.", "closureEvidence": "—"},
    }, cases)
    for key in (*SPEND_META_KEYS, *COMMERCIAL_KEYS, "lateRegistration"):  # 旧提交单没有这些字段，案例也就不带
        if key in sub:
            case[key] = deepcopy(sub[key])
    return case


def delete_case_by_swat(cases: list[dict], submissions: list[dict], swat_id: str) -> bool:
    """管理员删除：移除该 SWAT 全部登场行；指向它的提交级联置 Deleted，不留孤儿。"""
    if not any(c.get("swatId") == swat_id for c in cases):
        return False
    cases[:] = [c for c in cases if c.get("swatId") != swat_id]
    for s in submissions:
        if s.get("approvedSwatId") == swat_id:
            s["status"] = "Deleted"
            s["rejectReason"] = f"Case {swat_id} was deleted by an admin."
    return True

# ============================= 提醒引擎（每日检查 + 手动发送） =============================


def run_daily_reminder_check(cases: list[dict], settings: dict, log: list[dict], *,
                             force: bool = False, base_url: str = "") -> dict:
    """对应模板 runDailyReminderCheck：逾期标记、按规则发送（v1 模拟——写日志不外发）。

    log 为最新在前；每任务每日最多一次（lastAutoReminderDate 守卫）；PENDING 案例不参与。
    返回值 changed 为本次被修改的案例 id 列表 —— 持久层据此做按行增量写，不再全表重写。
    """
    now = na_now()
    today = now.date().isoformat()
    overdue_marked = sent = 0
    changed: set[str] = set()
    days_before = int(settings.get("daysBefore") or 0)
    overdue_every = int(settings.get("overdueEveryDays") or 0)
    for c in cases:
        if c.get("meetingDecision") == "PENDING":
            continue
        for t in c.get("followUps") or []:
            if t.get("status") not in ("Open", "Overdue"):
                continue
            days_until = _days_until_due(today, t.get("dueDate"))
            if days_until is None:
                continue
            if days_until < 0 and t.get("status") == "Open":
                t["status"] = "Overdue"
                overdue_marked += 1
                changed.add(c["id"])
            elif days_until >= 0 and t.get("status") == "Overdue":
                t["status"] = "Open"
                changed.add(c["id"])
            if not settings.get("enabled"):
                continue
            if t.get("lastAutoReminderDate") == today:
                continue
            trigger = None
            if days_until == days_before and days_before > 0:
                trigger = f"Due in {days_before} days"
            elif days_until == 0 and settings.get("onDueDate"):
                trigger = "Due today"
            elif days_until < 0 and overdue_every > 0 and (-days_until) % overdue_every == 0:
                trigger = f"Overdue by {-days_until} days"
            if not trigger:
                continue
            rc = task_recipient(t)
            cc = ", ".join(x for x in [rc["cc"], settings.get("alwaysCc")] if x)
            channel = t.get("channel") or settings.get("channel")
            entry = {
                # id：外发完成后按它回填 delivery（外发不占用数据库事务，见 main._run_check_if_due）
                "id": uuid.uuid4().hex,
                "when": fmt_when(now), "trigger": trigger, "swatId": c["swatId"], "task": t["task"],
                "to": rc["email"] or "(no email on file)", "cc": cc, "channel": channel,
                "message": reminder_message(c, t, base_url),
            }
            log.insert(0, entry)
            t["lastAutoReminderDate"] = today
            t["lastReminder"] = {"when": entry["when"], "channel": channel, "to": entry["to"],
                                 "message": entry["message"], "auto": True}
            sent += 1
            changed.add(c["id"])
        rolled = rollup_action_status(c.get("followUps") or [])
        if rolled != c.get("actionStatus"):
            c["actionStatus"] = rolled
            changed.add(c["id"])
    overdue_total = open_total = 0
    for c in cases:
        if c.get("meetingDecision") == "PENDING":
            continue
        for t in c.get("followUps") or []:
            if t.get("status") == "Overdue":
                overdue_total += 1
            elif t.get("status") == "Open":
                open_total += 1
    settings["lastRunDate"] = today
    settings["lastRun"] = {"when": fmt_when(now), "auto": not force, "overdueMarked": overdue_marked,
                           "sent": sent, "overdueTotal": overdue_total, "openTotal": open_total}
    return {"overdueMarked": overdue_marked, "sent": sent, "overdueTotal": overdue_total, "openTotal": open_total,
            "changed": sorted(changed)}


def send_manual_reminder(cases: list[dict], *, task_id: str, name: str, email: str,
                         cc: str, channel: str, base_url: str = "") -> bool:
    """手动提醒：更新收件人与 lastReminder。与模板一致——手动发送不写自动日志（行内 Sent ✓ 展示）。"""
    for c in cases:
        for t in c.get("followUps") or []:
            if t.get("id") == task_id:
                t["notify"] = name or t.get("responsible") or ""
                t["notifyEmail"] = email
                t["cc"] = cc
                t["channel"] = channel or "Email + Teams"
                t["lastReminder"] = {"when": fmt_when(na_now()), "channel": t["channel"], "to": email,
                                     "message": reminder_message(c, t, base_url)}
                return True
    return False
