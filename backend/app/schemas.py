"""API 请求边界校验；字段名与前端保持一致，业务规则仍由 logic/main 执行。"""

import calendar
import re
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

MAX_SAFE_INTEGER = 2**53 - 1
EMAIL_RE = re.compile(r'^[^@\s<>,;:"\\]+@[^@\s<>,;:"\\]+\.[^@\s<>,;:"\\]+$')


def _calendar_date(value: str) -> str:
    if value:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Enter a valid date in YYYY-MM-DD format.")
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("Enter a valid calendar date.") from exc
    return value


def _due_date(value: str) -> str:
    return value if value == "—" else _calendar_date(value)


def _email(value: str) -> str:
    if value and not EMAIL_RE.fullmatch(value):
        raise ValueError("Enter a valid email address.")
    return value


REGION_CODES = ("AP", "EU", "NA")


def _regions(value: object) -> str:
    """多区域：接受 "EU"、"EU + NA" 或 ["NA", "EU"]，统一存成固定顺序的 "EU + NA"。

    存文本而不是列表：旧的单区域数据无需迁移，SharePoint 的单行文本列也能原样写入。"""
    if isinstance(value, str):
        parts = value.split("+")
    elif isinstance(value, list) and all(isinstance(p, str) for p in value):
        parts = value
    else:
        raise ValueError("Region must be text or a list of regions.")
    picked = {p.strip() for p in parts if p.strip()}
    unknown = picked - set(REGION_CODES)
    if unknown:
        raise ValueError(f"Unknown region: {', '.join(sorted(unknown))}. Use AP, EU or NA.")
    return " + ".join(code for code in REGION_CODES if code in picked)


def _blank_to_none(value: object) -> object:
    """表单留空传 "" —— 可选数值字段视为未填。"""
    return None if value == "" else value


def _single_line(value: str) -> str:
    if "\r" in value or "\n" in value:
        raise ValueError("Recipient fields must not contain line breaks.")
    return value


# 长度上限只是加固（防止超大请求撑爆 JSON 文档），不是业务规则：短字段 500，长文本 5000
Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=5000)]
Email = Annotated[Text, AfterValidator(_email)]
RecipientText = Annotated[str, AfterValidator(_single_line), StringConstraints(strip_whitespace=True, max_length=500)]
CalendarDate = Annotated[Text, AfterValidator(_calendar_date)]
Spend = Annotated[int, Field(strict=True, ge=0, le=MAX_SAFE_INTEGER)]
Region = Annotated[str, BeforeValidator(_regions)]
Cluster = Literal["", "Chemical", "Metal", "Electronics, EA and Pyro"]
SourcingType = Literal["", "New", "C/O", "GCS"]
DecisionLevel = Literal["", "Level 2", "Level 3", "Level 4"]
YesNo = Literal["", "Yes", "No"]
Channel = Literal["Email", "Teams", "Email + Teams"]
Currency = Literal["EUR", "USD", "CNY"]
ToolingPayment = Literal["", "Lumpsum", "MPC"]
# 单价 / 模具费 / 摊销额：十进制，最多 4 位小数（0,02 EUR/pc 这类件价必须保留小数），按提交币种填写
Money = Annotated[Decimal, Field(ge=0, le=MAX_SAFE_INTEGER, decimal_places=4)]
Weeks = Annotated[int, Field(strict=True, ge=0, le=520)]
Count = Annotated[int, Field(strict=True, ge=1, le=MAX_SAFE_INTEGER)]
# 可选数值：留空（""）视为未填；BeforeValidator 必须包在 "X | None" 外面，否则 "" 会先撞上 Decimal / int 校验
OptMoney = Annotated[Money | None, BeforeValidator(_blank_to_none)]
OptWeeks = Annotated[Weeks | None, BeforeValidator(_blank_to_none)]
OptCount = Annotated[Count | None, BeforeValidator(_blank_to_none)]
# 产量（件）：可以为 0
Volume = Annotated[int, Field(strict=True, ge=0, le=MAX_SAFE_INTEGER)]
OptVolume = Annotated[Volume | None, BeforeValidator(_blank_to_none)]
# 财务 OP 记法 "1 EUR = X 外币"：正数，最多 6 位小数（Decimal 精确保存，不走浮点）
FxRate = Annotated[Decimal, Field(gt=0, le=100_000, max_digits=12, decimal_places=6)]


class In(BaseModel):
    model_config = ConfigDict(extra="ignore", validate_default=True)


class PartNumberIn(In):
    partNumber: Text = ""
    partDescription: Text = ""
    # v3 Phase-15：项目 / 寻源类型 / 推荐供应商按零件行（一个 bundle 可混不同项目、GCS / New、不同供应商）；
    # 留空时沿用请求里的案例级值（旧客户端），提交时每行必须有（logic.bundle_rows 判定）
    project: Text = ""
    sourcingType: SourcingType = ""
    recommendedSupplier: Text = ""
    # 反馈人 MM 模板：件价、模具费、产量按零件行填写（提交时四个价格每行必填，由 logic.validate_commercial 判定）
    pcPriceCQA: OptMoney = None
    supplierPriceLanded: OptMoney = None
    toolingCQA: OptMoney = None
    supplierToolingCost: OptMoney = None
    averageVolume: OptVolume = None
    lifetimeVolume: OptVolume = None


PartNumbers = Annotated[list[PartNumberIn], Field(max_length=50)]


class CommercialIn(In):
    """反馈 PPT 第 2、3 页的案例级商务字段：提交与案例编辑共用；哪些必填由 logic.validate_commercial 决定。
    件价 / 模具费 / 产量在 PartNumberIn 上按零件行填写。"""

    toolingPayment: ToolingPayment = ""
    bpgAvailable: YesNo = ""  # Lifetime Spend > 3 Mio EUR 时必答且须为 Yes
    fraAvailable: YesNo = ""  # Level 2 时必答且须为 Yes
    belowCQA: YesNo = ""
    cqaJustification: LongText = ""
    strategicSupplier: YesNo = ""
    ltaAvailable: YesNo = ""
    fotLeadTimeWeeks: OptWeeks = None
    ppapLeadTimeWeeks: OptWeeks = None
    amortizationTotal: OptMoney = None
    amortizationPcs: OptCount = None
    usmcaEligible: YesNo = ""
    annualCapacity: OptCount = None
    lifetimeCapacity: OptCount = None


COMMERCIAL_INPUT_FIELDS = tuple(CommercialIn.model_fields)


class SubmissionIn(CommercialIn):
    submitterName: Text = ""
    submitterEmail: Email = ""
    caseNo: Text = ""
    partNumbers: PartNumbers = Field(default_factory=list)
    # v3 Phase-15：金额按整个 bundle 填一个（领导要求，buyer 不用按零件号拆），必填且大于 0（main._validate_submission）
    peakYearSpend: Spend = 0
    lifetimeSpend: Spend = 0
    region: Region = ""
    project: Text = ""
    family: Text = ""
    cluster: Cluster = ""
    parentPF: Text = ""
    partFamilyCode: Text = ""
    sourcingType: SourcingType = "New"
    recommendedSupplier: Text = ""
    decisionLevel: DecisionLevel = "Level 2"
    meetingDateISO: CalendarDate = ""
    meetingDateLabel: Text = ""
    meetingWeekNum: Annotated[int, Field(strict=True, ge=1, le=53)] | None = None
    comments: LongText = ""
    # 金额按这个币种填写，服务端按管理员维护的汇率折算成欧元
    currency: Currency = "EUR"
    isFamilyCase: YesNo = ""
    familyAligned: YesNo = ""
    involvesECM: YesNo = ""
    ccbApproved: YesNo = ""
    # 过了登记截止仍要登记本周会议：申请例外并说明理由，由 Sourcing 管理员确认登记时批准
    lateException: Annotated[bool, Field(strict=True)] = False
    lateReason: LongText = ""

    @model_validator(mode="after")
    def _meeting_fields(self) -> "SubmissionIn":
        if self.meetingDateISO:
            meeting_date = date.fromisoformat(self.meetingDateISO)
            # v3 Phase-13：ISO 周（德国 KW）；原模板按 1 月 1 日起每七天划周
            self.meetingWeekNum = meeting_date.isocalendar().week
            self.meetingDateLabel = (f"{calendar.day_abbr[meeting_date.weekday()]}, "
                                     f"{calendar.month_abbr[meeting_date.month]} {meeting_date.day}, {meeting_date.year}")
        return self


class RejectIn(In):
    reason: LongText = ""


class FollowUpIn(In):
    id: Annotated[Text, Field(min_length=1)]
    task: LongText = ""
    responsible: Text = ""
    dueDate: Annotated[Text, AfterValidator(_due_date)] = ""
    notes: LongText = ""
    status: Literal["Open", "Overdue", "Closed"] = "Open"
    tags: Annotated[list[Text], Field(max_length=20)] = Field(default_factory=list)
    notify: Text = ""
    notifyEmail: Email = ""
    cc: RecipientText = ""
    # 空值沿用自动提醒设置；旧种子任务尚未选择自己的通道。
    channel: Literal["", "Email", "Teams", "Email + Teams"] = ""


class CaseEditIn(CommercialIn):
    partNumbers: Annotated[PartNumbers, Field(min_length=1)]
    # bundle 金额按案例原币填写；不带时原值不动
    peakYearSpend: Spend | None = None
    lifetimeSpend: Spend | None = None
    region: Region = ""
    project: Text = ""
    family: Text = ""
    cluster: Cluster = ""
    parentPF: Text = ""
    partFamilyCode: Text = ""
    sourcingType: SourcingType = ""
    recommendedSupplier: Text = ""
    presenter: Text = ""
    decisionLevel: DecisionLevel = ""
    leadTime: Text = ""
    committeeDiscussion: LongText = ""
    meetingDecision: Literal["PENDING", "APPROVED", "REJECTED", "CONDITIONAL APPROVAL"]
    sourcingPresentationLink: Text = ""
    finalDocLink: Text = ""
    followUps: Annotated[list[FollowUpIn], Field(max_length=100)] = Field(default_factory=list)

    @field_validator("partNumbers")
    @classmethod
    def _complete_part_numbers(cls, parts: list[PartNumberIn]) -> list[PartNumberIn]:
        if any(not part.partNumber or not part.partDescription for part in parts):
            raise ValueError("Fill in Part Number and Part Description for every part number row.")
        return parts

    @field_validator("followUps")
    @classmethod
    def _unique_task_ids(cls, tasks: list[FollowUpIn]) -> list[FollowUpIn]:
        if len({task.id for task in tasks}) != len(tasks):
            raise ValueError("Follow-up task IDs must be unique.")
        return tasks


class ManualReminderIn(In):
    taskId: Annotated[Text, Field(min_length=1)]
    name: Text = ""
    email: Email = ""
    cc: RecipientText = ""
    channel: Channel = "Email + Teams"


class FeedbackIn(In):
    """待办反馈（v3 Phase-14）：文字必填，附件随后另传。"""

    text: LongText = ""


class FeedbackDecisionIn(In):
    decision: Literal["approved", "rejected"]
    remark: LongText = ""
    # 关闭最后一条开放待办时须给出（与编辑页规则 2 一致）；已有则可省
    finalDocLink: Text = ""


class ReminderSettingsIn(In):
    enabled: Annotated[bool, Field(strict=True)] = True
    overdueEveryDays: Annotated[int, Field(strict=True, ge=1)] = 1
    channel: Channel = "Email + Teams"
    alwaysCc: RecipientText = ""


def _timezone(value: str) -> str:
    if value:
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Use a valid IANA timezone, such as Europe/Berlin, or leave blank for the server timezone.") from exc
    return value


class RegistrationSettingsIn(In):
    """登记截止：会前几天、几点、哪个时区（空 = 服务器时区）。"""

    daysBefore: Annotated[int, Field(strict=True, ge=1, le=6)] = 2
    cutoffTime: Annotated[Text, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")] = "23:59"
    timezone: Annotated[Text, AfterValidator(_timezone)] = ""


class FxRatesIn(In):
    USD: FxRate | None = None
    CNY: FxRate | None = None


class FxSettingsIn(In):
    basis: Annotated[Text, Field(max_length=60)] = ""  # 汇率口径，如 "OP 2025 plan rates 2026"
    perEur: FxRatesIn = Field(default_factory=FxRatesIn)

    @model_validator(mode="before")
    @classmethod
    def _refuse_early_notation(cls, data):
        # 没刷新的旧页面仍发 rates（"1 外币 = r EUR"）；extra="ignore" 会把它当成空表、清掉全部汇率
        if isinstance(data, dict) and "rates" in data:
            raise ValueError("This page uses the old exchange-rate format. Reload the page and enter the rates again.")
        return data


class ExportSelectionIn(In):
    """Database 页导出：前端把当前筛选结果的案例行 id 按页面顺序传来。"""

    ids: Annotated[list[Annotated[Text, Field(min_length=1)]], Field(max_length=5000)] = Field(default_factory=list)


class LoginIn(In):
    email: Annotated[str, Field(max_length=254)] = ""
    password: Annotated[str, Field(max_length=256)] = ""


class RegisterIn(LoginIn):
    name: Annotated[Text, Field(max_length=80)] = ""


class PasswordChangeIn(In):
    currentPassword: Annotated[str, Field(max_length=256)] = ""
    newPassword: Annotated[str, Field(max_length=256)] = ""


class UserUpdateIn(In):
    """管理员改账号：只改带了的字段（exclude_unset）。"""

    role: Literal["user", "npi_manager", "admin"] | None = None
    disabled: Annotated[bool, Field(strict=True)] | None = None
    name: Annotated[Text, Field(min_length=1, max_length=80)] | None = None
