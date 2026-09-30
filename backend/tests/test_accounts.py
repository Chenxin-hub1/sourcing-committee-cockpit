"""v3 Phase-6：个人账号取代共享管理员口令（反馈人答复问题 6）。

公司邮箱自注册（zf.com / zf-lifetec.com，测试另放 example.com）→ 默认普通用户；Sourcing 管理员在页面上
提升为 Manager 或管理员；Manager 能审批、编辑、删除案例和发提醒，不能改系统设置和账号。
v3 Phase-16（领导 2026-09-29）：只有 Sourcing 管理员用密码登录；其他人注册只填姓名 + 邮箱，凭邮箱直接登录。
提升为管理员时系统发临时密码，本人首次登录后必须先改；管理员忘记密码由另一位管理员重置。
首个管理员由 SC_BOOTSTRAP_ADMIN_* 在启动时建立。
"""

import pytest

from app import accounts, main, service
from tests.test_api import VALID_SUBMISSION

ANON = {"X-Session-Token": ""}


@pytest.fixture
def client(api_client):
    return api_client


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"X-Session-Token": r.json()["token"]}


@pytest.fixture
def admin(client):
    return _login(client, "admin@zf.com", "test-admin")


def _register(client, email, name="New Person"):
    return client.post("/api/auth/register", json={"email": email, "name": name}, headers=ANON)


def _login_by_email(client, email):
    r = client.post("/api/auth/login", json={"email": email})
    assert r.status_code == 200, r.text
    return {"X-Session-Token": r.json()["token"]}


# ---------- 密码与规则 ----------

def test_password_hash_round_trip_and_salt():
    first, second = accounts.hash_password("same-password"), accounts.hash_password("same-password")
    assert first != second and first.startswith("scrypt$")
    assert accounts.verify_password("same-password", first) and not accounts.verify_password("other-pass", first)
    assert not accounts.verify_password("x", "not-a-hash") and not accounts.verify_or_dummy("x", None)


@pytest.mark.parametrize("email,name,message", [
    ("someone@gmail.com", "Some One", "company email"),
    ("not-an-email", "Some One", "valid email"),
    ("new@zf.com", "  ", "your name"),
])
def test_registration_rules(client, email, name, message):
    r = _register(client, email, name=name)
    assert r.status_code == 422 and message in r.json()["detail"]


@pytest.mark.parametrize("password,message", [
    ("short", "at least 6"), ("aaaaaaaaaaaa", "too simple"), ("admin@zf.com", "must not be your email"),
])
def test_admin_password_rules(client, admin, password, message):
    r = client.post("/api/auth/password", json={"currentPassword": "test-admin", "newPassword": password}, headers=admin)
    assert r.status_code == 422 and message in r.json()["detail"]


def test_register_both_company_domains_login_and_duplicates(client):
    r = _register(client, "  New.Buyer@ZF-Lifetec.com ", name="New Buyer")
    assert r.status_code == 200
    assert r.json()["user"] == {**r.json()["user"], "email": "new.buyer@zf-lifetec.com", "role": "user", "roleLabel": "User", "hasPassword": False}
    assert "passwordHash" not in r.json()["user"]
    assert _register(client, "new.buyer@zf-lifetec.com").status_code == 409
    assert _register(client, "other@zf.com").status_code == 200
    # 邮箱直接登录（不分大小写），密码字段填了也不看；没注册的邮箱要先注册
    headers = _login_by_email(client, "NEW.BUYER@zf-lifetec.com")
    assert client.get("/api/bootstrap", headers=headers).json()["currentUser"]["name"] == "New Buyer"
    assert client.post("/api/auth/login", json={"email": "other@zf.com", "password": "whatever"}).status_code == 200
    r = client.post("/api/auth/login", json={"email": "nobody@zf.com"})
    assert r.status_code == 401 and "register first" in r.json()["detail"]
    # 非管理员没有密码可改、也没有密码可重置
    assert client.post("/api/auth/password", json={"currentPassword": "", "newPassword": "brand-new-pass"}, headers=headers).status_code == 403


def test_admins_log_in_with_a_password(client):
    r = client.post("/api/auth/login", json={"email": "admin@zf.com"})
    assert r.status_code == 401 and r.json()["detail"] == main.PASSWORD_REQUIRED
    r = client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "wrong"})
    assert r.status_code == 401 and r.json()["detail"] == "Wrong email or password."
    assert _login(client, "admin@zf.com", "test-admin")


def test_registration_is_rate_limited(client, monkeypatch):
    monkeypatch.setattr(main, "REGISTER_MAX_PER_WINDOW", 2)
    assert [_register(client, f"p{i}@zf.com").status_code for i in range(3)] == [200, 200, 429]


# ---------- 角色 ----------

def test_role_matrix(client, admin):
    _register(client, "npi.manager@zf.com", name="NPI Manager")
    r = client.put("/api/users/npi.manager@zf.com", json={"role": "npi_manager"}, headers=admin)
    assert r.status_code == 200
    npi = _login_by_email(client, "npi.manager@zf.com")
    user = {}  # 客户端默认以普通用户登录（conftest）
    settings = {"basis": "OP", "perEur": {"USD": "1.17"}}
    # 普通用户：可以提交，不能审批、不能改设置、不能管账号
    sub = client.post("/api/submissions", json=VALID_SUBMISSION)
    assert sub.status_code == 200
    sub_id = sub.json()["subId"]
    assert client.post(f"/api/submissions/{sub_id}/confirm", headers=user).status_code == 403
    assert client.put("/api/fx-settings", json=settings, headers=user).status_code == 403
    assert client.get("/api/users", headers=user).status_code == 403
    # NPI 经理：能审批、编辑、删除案例、发提醒；不能改系统设置和账号
    assert client.post(f"/api/submissions/{sub_id}/confirm", headers=npi).status_code == 200
    assert client.put("/api/fx-settings", json=settings, headers=npi).status_code == 403
    assert client.put("/api/registration-settings", json={"daysBefore": 2}, headers=npi).status_code == 403
    assert client.get("/api/users", headers=npi).status_code == 403
    assert client.delete("/api/cases/SWAT-20999", headers=npi).status_code == 200
    # Sourcing 管理员：系统设置与账号
    assert client.put("/api/fx-settings", json=settings, headers=admin).status_code == 200
    assert client.get("/api/users", headers=admin).status_code == 200
    # 未登录：什么都写不了，也不能提交
    assert client.post("/api/submissions", json=dict(VALID_SUBMISSION, caseNo="SWAT-20998"), headers=ANON).status_code == 401


def test_submitter_identity_comes_from_the_account(client):
    r = client.post("/api/submissions", json=dict(VALID_SUBMISSION, submitterName="Someone Else", submitterEmail="ceo@zf.com"))
    sub = next(s for s in r.json()["snapshot"]["submissions"] if s["subId"] == r.json()["subId"])
    assert (sub["submitterName"], sub["submitterEmail"], sub["presenter"]) == ("Test User", "test.user@zf.com", "Test User")


# ---------- 账号管理 ----------

def test_admin_manages_roles_and_keeps_one_admin(client, admin):
    _register(client, "second@zf.com", name="Second Admin")
    users = {u["email"]: u for u in client.get("/api/users", headers=admin).json()["users"]}
    assert users["test.user@zf.com"]["role"] == "user" and "passwordHash" not in users["admin@zf.com"]
    # 唯一的管理员不能把自己降级或停用
    r = client.put("/api/users/admin@zf.com", json={"role": "user"}, headers=admin)
    assert r.status_code == 422 and "at least one active Sourcing admin" in r.json()["detail"]
    assert client.put("/api/users/admin@zf.com", json={"disabled": True}, headers=admin).status_code == 422
    # 先提升别人（管理员必须有密码：提升时发临时密码，只在这次响应里），再停用 demo 管理员
    r = client.put("/api/users/second@zf.com", json={"role": "admin"}, headers=admin)
    assert r.status_code == 200
    temporary = r.json()["temporaryPassword"]
    promoted = next(u for u in r.json()["users"] if u["email"] == "second@zf.com")
    assert promoted["hasPassword"] and promoted["mustChangePassword"]
    assert client.post("/api/auth/login", json={"email": "second@zf.com"}).status_code == 401  # 现在要密码了
    r = client.put("/api/users/admin@zf.com", json={"disabled": True}, headers=admin)
    assert r.status_code == 200
    assert client.get("/api/users", headers=admin).status_code == 401  # 停用即踢下线
    r = client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    assert r.status_code == 403 and "disabled" in r.json()["detail"]
    # 第二位管理员：提升时拿到的临时密码登录，先改密码才能管账号
    second = _login(client, "second@zf.com", temporary)
    assert client.get("/api/users", headers=second).status_code == 403
    r = client.post("/api/auth/password", json={"currentPassword": temporary, "newPassword": "second-pass-123"}, headers=second)
    assert r.status_code == 200
    assert client.put("/api/users/nobody@zf.com", json={"role": "admin"}, headers=second).status_code == 404
    for bad in ({"role": "owner"}, {"disabled": "yes"}):
        assert client.put("/api/users/test.user@zf.com", json=bad, headers=second).status_code == 422


def test_reset_password_forces_a_change_before_anything_else(client, admin):
    _register(client, "forgetful@zf.com")
    assert client.post("/api/users/forgetful@zf.com/reset-password", headers=admin).status_code == 422  # 普通账号没有密码
    r = client.put("/api/users/forgetful@zf.com", json={"role": "admin"}, headers=admin)
    first_temporary = r.json()["temporaryPassword"]
    old_session = _login(client, "forgetful@zf.com", first_temporary)
    r = client.post("/api/users/forgetful@zf.com/reset-password", headers=admin)
    assert r.status_code == 200
    temporary = r.json()["temporaryPassword"]
    assert len(temporary) >= 16 and temporary != first_temporary
    assert client.get("/api/bootstrap", headers=old_session).json()["currentUser"] is None  # 旧会话失效
    assert client.post("/api/auth/login", json={"email": "forgetful@zf.com", "password": first_temporary}).status_code == 401
    headers = _login(client, "forgetful@zf.com", temporary)
    assert client.get("/api/bootstrap", headers=headers).json()["currentUser"]["mustChangePassword"] is True
    r = client.post("/api/submissions", json=dict(VALID_SUBMISSION, caseNo="SWAT-20997"), headers=headers)
    assert r.status_code == 403 and "temporary password" in r.json()["detail"]
    # 改密码：当前密码要对、新密码要合规且不同
    bad = client.post("/api/auth/password", json={"currentPassword": "wrong", "newPassword": "brand-new-pass"}, headers=headers)
    assert bad.status_code == 422
    same = client.post("/api/auth/password", json={"currentPassword": temporary, "newPassword": temporary}, headers=headers)
    assert same.status_code == 422
    r = client.post("/api/auth/password", json={"currentPassword": temporary, "newPassword": "brand-new-pass"}, headers=headers)
    assert r.status_code == 200 and r.json()["user"]["mustChangePassword"] is False
    assert client.post("/api/submissions", json=dict(VALID_SUBMISSION, caseNo="SWAT-20997"), headers=headers).status_code == 200
    _login(client, "forgetful@zf.com", "brand-new-pass")
    assert client.post("/api/auth/password", json={"currentPassword": "x", "newPassword": "y" * 12}, headers=ANON).status_code == 401
    # 降回 Manager：又是邮箱登录，也不再被"先改密码"拦住
    assert client.put("/api/users/forgetful@zf.com", json={"role": "npi_manager"}, headers=admin).status_code == 200
    headers = _login_by_email(client, "forgetful@zf.com")
    assert client.get("/api/bootstrap", headers=headers).json()["currentUser"]["mustChangePassword"] is False


# ---------- 首个管理员 ----------

async def test_bootstrap_admin_is_created_once_and_restores_access(async_client, monkeypatch):
    async with main.SessionLocal() as session:
        admin = await service.get_user(session, "admin@zf.com")
        assert admin["role"] == "admin" and admin["passwordHash"].startswith("scrypt$")
        # 已有可用管理员：改了配置也不动它
        monkeypatch.setattr(service.get_settings(), "bootstrap_admin_password", "changed-pass-1")
        await service.init_db(session)
        assert accounts.verify_password("test-admin", (await service.get_user(session, "admin@zf.com"))["passwordHash"])
        # 管理员全被停用：重启时按配置恢复成可用管理员（密码为配置里的新值）
        await service.save_user(session, {**admin, "disabled": True})
        await session.commit()
        await service.init_db(session)
        restored = await service.get_user(session, "admin@zf.com")
        assert restored["disabled"] is False and accounts.verify_password("changed-pass-1", restored["passwordHash"])
