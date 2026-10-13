"""v3 Phase-20：上传区分 Meeting minutes 与 Presentation —— 演示文件自动对案例、批量挂接、上传进文件库。"""

from __future__ import annotations

import pytest

from app import logic, presentation_match
from app.config import get_settings
from tests.test_sharepoint import submission

SAMPLE = "1. 110000034978 SPR8 Tube_34235239A_ NA_CO_L2_Iron Force Huzhou_Tube_Haojie.pdf"


def _case(**over):
    base = {"id": "C1", "swatId": "110000034978", "weekNum": 15, "caseNumber": 1, "meetingYear": 2026,
            "meetingDateISO": "2026-04-08", "partNumber": "34235239A", "partDescription": "Tube"}
    return logic.mk_case({**base, **over}, [])


CASES = [
    _case(),
    _case(id="C2", swatId="110000034999", caseNumber=2, partNumber="R004D369A"),
    _case(id="C3", swatId="B/2025/00234", weekNum=39, meetingYear=2025, meetingDateISO="2025-09-24", caseNumber=2,
          partNumber="R003C250A", partNumbers=[{"partNumber": "R003C250A", "partDescription": "Cup", "sourcingId": "110000030001"},
                                               {"partNumber": "R003R123A", "partDescription": "Cup 2"}]),
    _case(id="C4", swatId="110000034978", weekNum=20, caseNumber=5, meetingDateISO="2026-05-13"),  # 同一 SWAT 后来又上会
]


@pytest.mark.parametrize("path,row,by", [
    (f"KW15, 08.04.2026/{SAMPLE}", "C1", "SWAT number"),          # 文件夹给出周：先在那一周里找
    (SAMPLE, "C4", "SWAT number"),                                 # 不知道周：同号取最近一次上会
    ("KW15, 08.04.2026/2. Motor DC.pdf", "C2", "week + case #"),
    ("Unsorted/B_2025_00234 Micro Gas Generator.pptx", "C3", "SWAT number"),
    ("Unsorted/Bundle B-2025-234 MGG.pdf", "C3", "SWAT number"),
    ("Unsorted/110000030001 part row.pdf", "C3", "SWAT number"),  # bundle 案例零件行上的 SWAT 号
    ("Unsorted/Motor R004D369A final.pdf", "C2", "part number"),
])
def test_presentations_are_matched_to_cases(path, row, by):
    m = presentation_match.match(path, CASES)
    assert (m["rowId"], m["by"]) == (row, by), m


@pytest.mark.parametrize("path", ["Unsorted/random deck.pdf", "KW16, 15.04.2026/1. nothing.pdf", "Unsorted/1. no week.pdf"])
def test_unmatched_presentations_return_none(path):
    assert presentation_match.match(path, CASES) is None


def test_match_label_and_week_folder():
    m = presentation_match.match(f"KW15, 08.04.2026/{SAMPLE}", CASES)
    assert m["label"] == "2026-KW15 · Case #1 · 110000034978"
    assert presentation_match.week_folder(CASES[0]) == "KW15, 08.04.2026"
    assert presentation_match.week_of("KW15, 08.04.2026/x.pdf") == (2026, 15)
    assert presentation_match.week_of("x.pdf") == (None, None)


# ---------- 接口 ----------


@pytest.fixture
def library(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path / "uploads"))
    root = tmp_path / "presentations"
    root.mkdir()
    monkeypatch.setattr(get_settings(), "presentation_library_dir", str(root))
    return root


async def _admin(client):
    r = await client.post("/api/auth/login", json={"email": "admin@zf.com", "password": "test-admin"})
    return {"X-Session-Token": r.json()["token"]}


async def _confirmed(client, headers, number):
    r = await client.post("/api/submissions", json=submission(number))
    assert r.status_code == 200, r.text
    return (await client.post(f"/api/submissions/{r.json()['subId']}/confirm", headers=headers)).json()["case"]


async def test_upload_into_library_files_by_matched_week_and_attach_all(async_client, library):
    admin = await _admin(async_client)
    case = await _confirmed(async_client, admin, 50001)  # SWAT-50001，2026-KW41（2026-10-07）
    body = {"Content-Type": "application/pdf"}
    # 普通用户不能往库里传
    assert (await async_client.post("/api/presentation-library/files", params={"name": "1. SWAT-50001 deck.pdf"}, content=b"x", headers=body)).status_code == 403
    r = await async_client.post("/api/presentation-library/files", params={"name": "1. SWAT-50001 deck.pdf"}, content=b"deck", headers={**admin, **body})
    assert r.status_code == 200, r.text
    assert r.json()["path"] == "KW41, 07.10.2026/1. SWAT-50001 deck.pdf"  # 按案例所在周建文件夹
    # 案例号 "SWAT-50001" 整体出现在文件名里也算对上
    assert r.json()["file"]["match"]["rowId"] == case["id"] and r.json()["file"]["match"]["attached"] is False
    r = await async_client.post("/api/presentation-library/files", params={"name": "random.pdf"}, content=b"r", headers={**admin, **body})
    assert r.json()["path"] == "Unsorted/random.pdf" and r.json()["file"]["match"] is None
    r = await async_client.post("/api/presentation-library/files", params={"name": "random.pdf"}, content=b"r2", headers={**admin, **body})
    assert r.json()["path"] == "Unsorted/random (2).pdf"  # 同名不覆盖
    assert (library / "Unsorted" / "random.pdf").read_bytes() == b"r"
    # 批量挂接：对上的挂、对不上的说明原因；再挂一次提示已挂过
    paths = ["KW41, 07.10.2026/1. SWAT-50001 deck.pdf", "Unsorted/random.pdf", "../etc/passwd"]
    r = await async_client.post("/api/presentation-library/attach", headers=admin, json={"paths": paths})
    assert r.status_code == 200, r.text
    assert [a["path"] for a in r.json()["attached"]] == [paths[0]]
    assert [s["path"] for s in r.json()["skipped"]] == paths[1:]
    assert "No matching case" in r.json()["skipped"][0]["reason"]
    saved = next(c for c in r.json()["snapshot"]["cases"] if c["id"] == case["id"])
    assert [f["originalName"] for f in saved["files"]] == ["1. SWAT-50001 deck.pdf"]
    listing = (await async_client.get("/api/presentation-library", headers=admin)).json()["files"]
    assert next(f for f in listing if f["name"] == "1. SWAT-50001 deck.pdf")["match"]["attached"] is True
    r = await async_client.post("/api/presentation-library/attach", headers=admin, json={"paths": paths[:1]})
    assert r.json()["attached"] == [] and "Already attached" in r.json()["skipped"][0]["reason"]
    assert (await async_client.post("/api/presentation-library/attach", json={"paths": paths[:1]})).status_code == 403
    assert (await async_client.post("/api/presentation-library/attach", headers=admin, json={"paths": []})).status_code == 422


async def test_upload_into_library_respects_folder_and_types(async_client, library):
    admin = await _admin(async_client)
    body = {**admin, "Content-Type": "application/pdf"}
    r = await async_client.post("/api/presentation-library/files", params={"name": "a.pdf", "folder": "KW15, 08.04.2026"}, content=b"a", headers=body)
    assert r.json()["path"] == "KW15, 08.04.2026/a.pdf"
    r = await async_client.post("/api/presentation-library/files", params={"name": "b.pdf", "folder": "../../x"}, content=b"b", headers=body)
    assert r.status_code == 200 and "/" not in r.json()["path"].rsplit("/", 1)[0]  # 斜杠被替换，不会跳出库目录
    assert (await async_client.post("/api/presentation-library/files", params={"name": "tool.exe"}, content=b"x", headers=body)).status_code == 422
    r = await async_client.post("/api/presentation-library/files", params={"name": "KW15 MM.xlsx"}, content=b"x", headers=body)
    assert r.status_code == 422 and "PDF or PowerPoint" in r.json()["detail"]  # 周会 Excel 走 Meeting minutes，不进演示文件库
    assert not list((library.parent / "uploads" / ".incoming").glob("*"))


# ---------- IT 开通 Graph 后的连通检查命令（2026-10-12） ----------


async def test_graph_check_reports_missing_settings_without_secrets(capsys, monkeypatch):
    from app import migrations

    monkeypatch.setattr(get_settings(), "graph_client_secret", "")
    assert await migrations.run(["graph-check"], None) == 2
    assert "SC_GRAPH_CLIENT_SECRET  MISSING" in capsys.readouterr().out


async def test_graph_check_never_prints_the_secret_and_explains_token_failure(capsys, monkeypatch):
    from app import graph, migrations

    s = get_settings()
    for key, value in {"graph_tenant_id": "tenant-123", "graph_client_id": "client-456",
                       "graph_client_secret": "super-secret-value", "sp_site_url": "https://x.sharepoint.com/sites/y"}.items():
        monkeypatch.setattr(s, key, value)

    async def bad_token(client):
        raise RuntimeError("token HTTP 401")

    monkeypatch.setattr(graph, "_token", bad_token)
    assert await migrations.run(["graph-check"], None) == 1
    out = capsys.readouterr().out
    assert "super-secret-value" not in out and "SC_GRAPH_CLIENT_SECRET  set (18 chars)" in out
    assert "[1/5] Token ............ FAILED: token HTTP 401" in out
