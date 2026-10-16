"""v3 Phase-29：待办负责人统一显示全名，职能跟着人走。

负责人（responsible）是自由文本：手填的多是邮箱，从会议纪要提取的是人名。页面、导出与提醒文字统一用全名：
- 填的是邮箱：有注册账号就用账号名字，没有就从邮箱推出名字（andreas.huber1@… → Andreas Huber）；
- 本来写的是人名：照原样（只把多余空格合并）。
算出的全名存在待办的 ownerName 上（保存、改账号名、注册、启动时重算），提醒收件邮箱（notifyEmail）不受影响。

职能（ownerFunction）按人归并：同一个全名就是同一个人。改了某条待办的职能，这个人所有待办的职能一起改；
一个人只有一种职能时，他职能空着的待办自动补上。几条待办职能互相矛盾（旧数据）时不猜，等有人改一处再统一。
"""

import re

# 邮箱：与 schemas 的写法一致的宽松判断（这里只决定"按邮箱还是按人名显示"，不做校验）
_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
# 邮箱里不是名字的部分：公司给外部人员的 .external 后缀
_NOT_NAME = {"external", "ext"}
# 启动时按 SC_BOOTSTRAP_ADMIN_* 建的账号默认叫这个，不是真人名字，不拿来显示
_PLACEHOLDER_NAMES = {"sourcing admin"}


def name_from_email(email: str) -> str:
    """从邮箱推出名字：andreas.huber1@zf-lifetec.com → Andreas Huber；推不出（全是数字等）就原样返回邮箱。"""
    local = email.split("@", 1)[0]
    words = []
    for token in re.split(r"[._\-+]+", local):
        token = token.rstrip("0123456789")
        if token and token.lower() not in _NOT_NAME:
            words.append(token[:1].upper() + token[1:].lower())
    return " ".join(words) or email


def account_names(users: list[dict]) -> dict[str, str]:
    """注册账号的 邮箱（小写）→ 名字；占位名字和空名字不算。"""
    out = {}
    for u in users:
        name = " ".join((u.get("name") or "").split())
        if u.get("email") and name and name.casefold() not in _PLACEHOLDER_NAMES:
            out[u["email"].lower()] = name
    return out


def display_name(owner: str, names: dict[str, str]) -> str:
    """负责人文本 → 全名。几个邮箱用逗号 / 分号隔开时逐个换成名字；混着人名和别的文字的保持原样。"""
    text = " ".join((owner or "").split())
    parts = [p.strip() for p in re.split(r"[;,]", text) if p.strip()]
    if parts and all(_EMAIL_RE.match(p) for p in parts):
        return ", ".join(names.get(p.lower()) or name_from_email(p) for p in parts)
    return text


def person_key(name: str) -> str:
    """同一个人的判断：全名忽略大小写与多余空格。"""
    return " ".join(name.split()).casefold()


def _add(changed: list[dict], case: dict) -> None:
    """按对象身份去重（案例 dict 内容可能相同，不能用 ==）。"""
    if all(case is not c for c in changed):
        changed.append(case)


def _tasks(cases: list[dict]):
    for c in cases:
        for t in c.get("followUps") or []:
            yield c, t


def known_functions(cases: list[dict], names: dict[str, str], skip: frozenset[str] = frozenset()) -> dict[str, str]:
    """每个人的职能：只收录职能唯一的人（几条待办写了不同职能的旧数据不收）。skip：不计入的待办 id。"""
    seen: dict[str, set[str]] = {}
    for _, t in _tasks(cases):
        if t.get("id") in skip:
            continue
        name = display_name(t.get("responsible", ""), names)
        fn = (t.get("ownerFunction") or "").strip()
        if name and fn:
            seen.setdefault(person_key(name), set()).add(fn)
    return {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}


def spread_function(cases: list[dict], name: str, function: str, names: dict[str, str]) -> list[dict]:
    """把这个人所有待办的职能改成 function；返回改了的案例。"""
    key, changed = person_key(name), []
    for c, t in _tasks(cases):
        if (t.get("ownerFunction") or "") != function and person_key(display_name(t.get("responsible", ""), names)) == key:
            t["ownerFunction"] = function
            _add(changed, c)
    return changed


def refresh(cases: list[dict], names: dict[str, str]) -> list[dict]:
    """重算每条待办的 ownerName，并给职能空着、但这个人职能已知的待办补上；返回改了的案例。"""
    functions = known_functions(cases, names)
    changed = []
    for c, t in _tasks(cases):
        before = (t.get("ownerName"), t.get("ownerFunction"))
        name = display_name(t.get("responsible", ""), names)
        if name:
            t["ownerName"] = name
        else:
            t.pop("ownerName", None)
        if name and not (t.get("ownerFunction") or "").strip() and person_key(name) in functions:
            t["ownerFunction"] = functions[person_key(name)]
        if (t.get("ownerName"), t.get("ownerFunction")) != before:
            _add(changed, c)
    return changed


def apply_edits(cases: list[dict], edited: list[dict], before: dict[str, tuple[str, str]],
                names: dict[str, str]) -> list[dict]:
    """保存了一些待办之后：职能新填或改过的，推到这个人的全部待办；再整体 refresh。

    edited：这次保存的待办（已写回案例）；before：保存前 {待办 id: (负责人全名, 职能)}，新待办不在里面。
    只换了负责人、职能框没动的：那是上一个人的职能，换成新负责人已知的职能（新负责人还没有职能就保留，当作他的职能）。
    返回被改动的案例（调用方连同被编辑的案例一起写库）。"""
    others = known_functions(cases, names, skip=frozenset(str(t.get("id") or "") for t in edited))
    changed: list[dict] = []
    for t in edited:
        name = display_name(t.get("responsible", ""), names)
        fn = (t.get("ownerFunction") or "").strip()
        if not name or not fn:
            continue
        old_name, old_fn = before.get(str(t.get("id") or ""), ("", ""))
        moved = t.get("id") in before and person_key(name) != person_key(old_name)
        if moved and fn == old_fn:
            if person_key(name) in others:
                t["ownerFunction"] = others[person_key(name)]
            continue
        if fn != old_fn or moved:
            for c in spread_function(cases, name, fn, names):
                _add(changed, c)
    for c in refresh(cases, names):
        _add(changed, c)
    return changed


def task_owner(t: dict) -> str:
    """显示用的负责人：全名优先，旧数据还没算过时退回原文。"""
    return t.get("ownerName") or t.get("responsible") or ""
