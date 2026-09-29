"""SharePoint Graph 探索样例（Seat Belt Sourcing Committee Cockpit 专用）。

只读为主：解析站点 → 列出 List / 文档库 → 打印目标 List 的列定义和前几条 item。
可选 --write-demo：向目标 List 写入一条带明显标记的测试 item（需要 write 角色）。

认证方式：Graph app-only（client secret），权限模型 Sites.Selected——
Entra 侧批准权限后，管理员还需对目标站点单独授权，否则会 403。

凭据填在项目根目录 .env（或先 export 的环境变量，优先级更高）：
    SC_GRAPH_TENANT_ID=      # Entra 租户 ID
    SC_GRAPH_CLIENT_ID=      # 应用注册的客户端 ID
    SC_GRAPH_CLIENT_SECRET=  # 应用密钥
    SC_SP_SITE_URL=          # https://xxx.sharepoint.com/sites/站点名
    SC_SP_LIST_NAME=         # 可选；不填则只列出站点上的 List 供挑选

运行（backend 目录下；azure-identity 只是临时带上，不进项目依赖）：
    uv run --with azure-identity python scripts/explore_sharepoint_graph.py
    uv run --with azure-identity python scripts/explore_sharepoint_graph.py --write-demo
等价于 pip 环境：
    pip install httpx azure-identity && python scripts/explore_sharepoint_graph.py
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"
REQUIRED = ("SC_GRAPH_TENANT_ID", "SC_GRAPH_CLIENT_ID", "SC_GRAPH_CLIENT_SECRET", "SC_SP_SITE_URL")

COLUMN_KINDS = ("text", "note", "number", "currency", "choice", "dateTime",
                "boolean", "hyperlinkOrPicture", "personOrGroup", "lookup")


def load_env_file() -> None:
    """读项目根目录 .env（不存在则跳过）；已导出的环境变量优先，不覆盖。"""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def build_client() -> httpx.Client:
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        sys.exit(f"缺少环境变量: {', '.join(missing)} —— 填到项目根目录 .env 后重试")
    from azure.identity import ClientSecretCredential
    try:
        cred = ClientSecretCredential(
            tenant_id=os.environ["SC_GRAPH_TENANT_ID"],
            client_id=os.environ["SC_GRAPH_CLIENT_ID"],
            client_secret=os.environ["SC_GRAPH_CLIENT_SECRET"],
        )
        # app-only 固定用 .default：拿到的就是 Entra 里已批准的应用权限（Sites.Selected）
        token = cred.get_token("https://graph.microsoft.com/.default").token
    except Exception as e:  # noqa: BLE001 — 凭据错误直接给人看原因，不值得堆栈
        sys.exit(f"获取 token 失败（先核对租户 ID / 客户端 ID / 密钥）: {e}")
    return httpx.Client(base_url=GRAPH, headers={"Authorization": f"Bearer {token}"}, timeout=60)


def get(http: httpx.Client, path: str, **params) -> dict:
    r = http.get(path, params=params or None)
    if r.status_code == 403:
        # Sites.Selected 下最常见：Entra 批了权限，但管理员还没对该站点 POST /sites/{id}/permissions
        sys.exit(f"403 on {path} —— 站点级授权缺失？\n{r.text[:800]}")
    if r.status_code == 404:
        sys.exit(f"404 on {path} —— 地址或名称不对，核对 SP_SITE_URL / SP_LIST_NAME")
    r.raise_for_status()
    return r.json()


def resolve_site(http: httpx.Client) -> str:
    """按 URL 直接寻址解析站点。Sites.Selected 不能 search，只能 host:/path 直连。"""
    site_url = os.environ["SC_SP_SITE_URL"].rstrip("/")
    host, _, path = site_url.split("://", 1)[1].partition("/")
    site = get(http, f"/sites/{host}:/{path}", select="id,displayName")
    print(f"站点: {site['displayName']}  id={site['id']}\n")
    return site["id"]


def list_containers(http: httpx.Client, site_id: str) -> list[dict]:
    """列站点上的 List（genericList）与文档库（documentLibrary）。"""
    lists = get(http, f"/sites/{site_id}/lists", select="id,displayName,list")["value"]
    for lst in lists:
        print(f"list  {lst['displayName']!r:40} template={lst['list']['template']}")
    for drv in get(http, f"/sites/{site_id}/drives", select="id,name")["value"]:
        print(f"drive {drv['name']!r:40} id={drv['id']}")
    return lists


def find_list(lists: list[dict], wanted: str) -> dict:
    """按 displayName 找目标 List，拿到稳定的 id（写 item 时用 id，不用显示名）。"""
    for lst in lists:
        if lst["displayName"] == wanted:
            return lst
    for lst in lists:  # 大小写/空白不敏感兜底
        if lst["displayName"].casefold() == wanted.strip().casefold():
            return lst
    names = ", ".join(repr(l["displayName"]) for l in lists)
    sys.exit(f"没找到名为 {wanted!r} 的 List。站点上现有的: {names}")


def describe_columns(http: httpx.Client, site_id: str, list_id: str, list_name: str) -> None:
    """列定义：写 item 时 fields 用的是内部 name，不是 displayName。"""
    cols = get(http, f"/sites/{site_id}/lists/{list_id}/columns")["value"]
    print(f"\n{list_name!r} 的列:")
    for c in cols:
        if c.get("hidden") or c.get("readOnly"):
            continue
        kind = next((k for k in COLUMN_KINDS if k in c), "?")
        extra = f"  choices={c['choice']['choices']}" if kind == "choice" else ""
        required = "  REQUIRED" if c.get("required") else ""
        print(f"  name={c['name']!r:32} display={c['displayName']!r:30} type={kind}{required}{extra}")


def show_items(http: httpx.Client, site_id: str, list_id: str) -> None:
    items = get(http, f"/sites/{site_id}/lists/{list_id}/items", expand="fields", top=3)["value"]
    print(f"\n前 {len(items)} 条 item:")
    for it in items:
        print(f"  id={it['id']} fields={it['fields']}")


def write_demo_item(http: httpx.Client, site_id: str, list_id: str) -> None:
    """--write-demo：写入一条带时间戳标记的测试 item，便于事后定位删除。需要 write 角色。"""
    title = f"GRAPH-SAMPLE-TEST {datetime.now(UTC):%Y-%m-%d %H:%M:%S} UTC"
    r = http.post(f"/sites/{site_id}/lists/{list_id}/items", json={"fields": {"Title": title}})
    if r.status_code == 403:
        sys.exit(f"403 —— 该应用对这个站点只有 read 角色，写入需要 write。{r.text[:400]}")
    r.raise_for_status()
    item = r.json()
    print(f"\n已写入测试 item: id={item['id']}  Title={title!r}")
    print(f"删除命令: DELETE /sites/{site_id}/lists/{list_id}/items/{item['id']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="SharePoint Graph read-only explorer (with optional demo write)")
    parser.add_argument("--list-name", default=os.environ.get("SC_SP_LIST_NAME", ""),
                        help="目标 List 显示名；不填则只列出站点上的 List")
    parser.add_argument("--write-demo", action="store_true",
                        help="向目标 List 写入一条测试 item（需要 write 角色）")
    args = parser.parse_args()

    load_env_file()
    if args.list_name:
        os.environ.setdefault("SC_SP_LIST_NAME", args.list_name)
    http = build_client()
    site_id = resolve_site(http)
    lists = list_containers(http, site_id)

    list_name = args.list_name
    if not list_name:
        print("\n未指定 List（--list-name 或 SC_SP_LIST_NAME）——上面已列出全部 List，挑一个再跑一次。")
        return
    target = find_list(lists, list_name)
    describe_columns(http, site_id, target["id"], target["displayName"])
    show_items(http, site_id, target["id"])
    if args.write_demo:
        write_demo_item(http, site_id, target["id"])


if __name__ == "__main__":
    main()
