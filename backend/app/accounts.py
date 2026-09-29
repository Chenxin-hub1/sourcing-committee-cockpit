"""个人账号（v3 Phase-6）：公司邮箱自注册、密码哈希、角色。

反馈人答复（2026-09-24）：每人一个账号，公司邮箱；新账号默认普通用户，
Sourcing 管理员在页面上提升角色；共享管理员口令取消。
v3 Phase-16（领导 2026-09-29：不想要密码）：只有 Sourcing 管理员用密码登录，其他人用公司邮箱注册、
凭邮箱直接登录（不设密码）；提升为管理员时系统生成临时密码，本人首次登录后必须改。三种角色由低到高：
- user：提交登记、查看
- npi_manager（页面上显示 "Manager"，v3 Phase-15 起：采购经理也用这个角色）：另可审批登记、编辑与删除案例、记录决议与待办、发提醒、管理案例文件
- admin（Sourcing 管理员）：另可改汇率 / 登记截止 / 提醒设置、管理账号
还没有邮件通道（SMTP 待 IT），注册不做邮箱验证；管理员忘记密码由另一位管理员重置成临时密码，本人登录后必须先改。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets

ROLES = ("user", "npi_manager", "admin")
ROLE_LABELS = {"user": "User", "npi_manager": "Manager", "admin": "Sourcing admin"}
RANK = {role: i for i, role in enumerate(ROLES)}
PASSWORD_MIN = 10
PASSWORD_MAX = 128
NAME_MAX = 80
EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+\.[^@\s]+)$")

# scrypt（标准库 hashlib，OpenSSL 实现）：N=2^14、r=8、p=1 约占 16 MB 内存，单次几十毫秒
_N, _R, _P, _DKLEN = 2**14, 8, 1, 32


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt),
                                n=int(n), r=int(r), p=int(p), dklen=len(expected))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


# 账号不存在时也算一次哈希：登录失败的耗时不泄露"这个邮箱有没有注册"
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def verify_or_dummy(password: str, stored: str | None) -> bool:
    if not stored:
        verify_password(password, _DUMMY_HASH)
        return False
    return verify_password(password, stored)


def normalize_email(raw: str) -> str:
    return (raw or "").strip().lower()


def allowed_domains(setting: str) -> list[str]:
    return [d.strip().lower().lstrip("@") for d in (setting or "").split(",") if d.strip()]


def email_problem(email: str, domains: list[str]) -> str | None:
    match = EMAIL_RE.match(email)
    if not match:
        return "Enter a valid email address."
    if match.group(1) not in domains:
        return f"Use your company email address ({' or '.join('@' + d for d in domains)})."
    return None


def password_problem(password: str, email: str = "") -> str | None:
    if len(password) < PASSWORD_MIN:
        return f"The password must have at least {PASSWORD_MIN} characters."
    if len(password) > PASSWORD_MAX:
        return f"The password can have at most {PASSWORD_MAX} characters."
    if email and password.strip().lower() == email.lower():
        return "The password must not be your email address."
    if len(set(password)) < 4:
        return "The password is too simple — use a mix of different characters."
    return None


def temporary_password() -> str:
    """管理员重置用的临时密码：16 个 URL 安全字符（约 96 位随机）。"""
    return secrets.token_urlsafe(12)


def public_user(doc: dict) -> dict:
    """给浏览器看的账号信息（不含密码哈希）。"""
    return {
        "email": doc["email"], "name": doc.get("name", ""), "role": doc.get("role", "user"),
        "roleLabel": ROLE_LABELS.get(doc.get("role", "user"), "User"),
        "disabled": bool(doc.get("disabled")), "mustChangePassword": bool(doc.get("mustChangePassword")),
        "hasPassword": bool(doc.get("passwordHash")),
        "createdAt": doc.get("createdAt", ""), "lastLoginAt": doc.get("lastLoginAt", ""),
    }
