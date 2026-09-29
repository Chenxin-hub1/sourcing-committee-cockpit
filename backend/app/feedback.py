"""待办反馈与关闭审批（v3 Phase-14，反馈 PPT 第 4、11 页）。

待办的关闭之前靠邮件跟进：负责人汇报进展、附上邮件凭证，由 Sourcing admin 或采购经理确认。
现在挂在每条待办上的 ``feedback`` 列表记录这条链：

    {id, when, by, byEmail, text, files: [文件记录], status: pending | approved | rejected,
     notify: {when, to, result},                       # 提交时给 NPI 经理 / 管理员的通知
     decision: {when, by, byEmail, remark, notify}}    # NPI 经理及以上的 approve / reject

approve 把待办置 Closed，并在待办上留下 ``closure = {when, by, feedbackId}``；
reject 必须写进一步要求，待办保持开放。任何登录用户都能提交反馈（负责人目前只存姓名，
无法可靠对应账号），审批只有 NPI 经理及以上。
"""

from __future__ import annotations

import secrets

from . import logic

MAX_FEEDBACK_PER_TASK = 50
PENDING, APPROVED, REJECTED = "pending", "approved", "rejected"


def find_task(cases: list[dict], task_id: str) -> tuple[dict | None, dict | None]:
    for c in cases:
        for t in c.get("followUps") or []:
            if t.get("id") == task_id:
                return c, t
    return None, None


def find_feedback(task: dict | None, fb_id: str) -> dict | None:
    for fb in (task or {}).get("feedback") or []:
        if fb.get("id") == fb_id:
            return fb
    return None


def new_feedback(user: dict, text: str) -> dict:
    return {"id": f"FB-{secrets.token_hex(6)}", "when": logic.fmt_when(logic.na_now()),
            "by": user["name"], "byEmail": user["email"], "text": text, "files": [],
            "status": PENDING, "notify": None, "decision": None}


def is_author(fb: dict, user: dict | None) -> bool:
    return bool(user) and (fb.get("byEmail") or "").lower() == user["email"].lower()


def decide(case: dict, task: dict, fb: dict, user: dict, decision: str, remark: str, final_doc_link: str) -> str | None:
    """approve / reject 一条反馈；返回文案表示拒绝（422），None 表示已改写 case / task / fb。"""
    if fb.get("status") != PENDING:
        return f"This feedback was already {fb.get('status')} — reload the page to see the current state."
    remark = remark.strip()
    final_doc_link = final_doc_link.strip()
    if decision == REJECTED and not remark:
        return "Add a remark saying what is still needed, so the owner knows how to follow up."
    if decision == APPROVED:
        if final_doc_link and not logic.valid_http_url(final_doc_link):
            return "The Final PPT / Supporting Document Link must be a full URL (starting with http:// or https://)."
        others_closed = all(t.get("status") == "Closed" for t in case.get("followUps") or [] if t is not task)
        if others_closed and not (final_doc_link or (case.get("finalDocLink") or "").strip()):
            return ("Approving this closes the last open follow-up, which closes the case — "
                    "enter the Final PPT / Supporting Document Link first.")
        if final_doc_link:
            case["finalDocLink"] = final_doc_link
        task["status"] = "Closed"
        task["closure"] = {"when": logic.fmt_when(logic.na_now()), "by": user["name"], "feedbackId": fb["id"]}
        case["actionStatus"] = None if case.get("meetingDecision") == "PENDING" else logic.rollup_action_status(case["followUps"])
    fb["status"] = decision
    fb["decision"] = {"when": logic.fmt_when(logic.na_now()), "by": user["name"], "byEmail": user["email"],
                      "remark": remark, "notify": None}
    return None


# ---------- 通知信（与 reminder_message 同一风格：不打开驾驶舱也有足够上下文） ----------


def _head(case: dict, task: dict, base_url: str) -> tuple[list[str], str]:
    pns = case.get("partNumbers")
    more = f" (+{len(pns) - 1} more)" if pns and len(pns) > 1 else ""
    head = [
        "Part Description: " + (case.get("partDescription") or "—"),
        "Part Number: " + (case.get("partNumber") or "—") + more,
        "SWAT Case: " + case.get("swatId", ""),
        "",
        "Follow-up Task: " + (task.get("task") or "—"),
        "Owner: " + (task.get("responsible") or "—"),
        "Due Date: " + (task.get("dueDate") or "—"),
    ]
    return head, logic.case_link(case, base_url)


def feedback_email(case: dict, task: dict, fb: dict, base_url: str = "") -> tuple[str, str]:
    head, link = _head(case, task, base_url)
    subject = f"Follow-up feedback to approve — Sourcing Case {case.get('swatId', '')}"
    body = "\n".join([
        "Follow-up Feedback — Awaiting Your Decision",
        "",
        *head,
        "",
        f"Feedback from {fb.get('by') or '—'} ({fb.get('byEmail') or '—'}) on {fb.get('when') or '—'}:",
        fb.get("text") or "—",
        "",
        "Please approve (the follow-up is closed) or reject it with a remark on the case page.",
        "Any attachments are listed there as well.",
        "",
        "Open Action Case: " + link,
    ])
    return subject, body


def decision_email(case: dict, task: dict, fb: dict, base_url: str = "") -> tuple[str, str]:
    head, link = _head(case, task, base_url)
    d = fb.get("decision") or {}
    approved = fb.get("status") == APPROVED
    swat = case.get("swatId", "")
    subject = (f"Follow-up closed — Sourcing Case {swat}" if approved
               else f"Follow-up feedback not accepted — Sourcing Case {swat}")
    outcome = ([f"The feedback was approved by {d.get('by') or '—'} on {d.get('when') or '—'}; this follow-up is now Closed."]
               if approved else
               [f"The feedback was not accepted by {d.get('by') or '—'} on {d.get('when') or '—'}; the follow-up stays open.",
                "Further action: " + (d.get("remark") or "—")])
    if approved and d.get("remark"):
        outcome.append("Remark: " + d["remark"])
    body = "\n".join([
        "Follow-up Feedback — " + ("Approved" if approved else "Rejected"),
        "",
        *head,
        "",
        f"Feedback from {fb.get('by') or '—'} on {fb.get('when') or '—'}:",
        fb.get("text") or "—",
        "",
        *outcome,
        "",
        "Open Action Case: " + link,
    ])
    return subject, body


def decision_recipients(task: dict, fb: dict) -> tuple[str, str]:
    """结果邮件：收件人是待办的提醒收件人（没有就发给反馈人），反馈人抄送。"""
    to = (task.get("notifyEmail") or "").strip() or (fb.get("byEmail") or "")
    cc = fb.get("byEmail") or ""
    return to, ("" if cc.lower() == to.lower() else cc)
