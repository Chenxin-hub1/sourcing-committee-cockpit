"""把驾驶舱打包成一个离线演示 HTML（没上服务器时拿给领导看）。

    uv run python scripts/build_demo_page.py --from-url http://127.0.0.1:8062 --out ../.design/demo/cockpit-demo.html
    uv run python scripts/build_demo_page.py --snapshot snap.json --exclude-swat SWAT-9900 --exclude-sub SUB-0002

做法：读 app/static/index.html，把当前快照（/api/bootstrap 的 JSON）嵌进页面，并在页面里替换 fetch：
GET /api/bootstrap 回嵌入的数据、登录 / 登出 / 账号列表回一个演示管理员、其它写操作一律回 503 并说明
"这是只读演示副本"。页面本身没有外链依赖，双击打开就能用，所有页面可点，改动不会保存。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

INDEX = Path(__file__).resolve().parents[1] / "app" / "static" / "index.html"
DEMO_USER = {"email": "demo.viewer@zf.com", "name": "Demo Viewer", "role": "admin", "roleLabel": "Sourcing admin",
             "disabled": False, "mustChangePassword": False, "createdAt": "", "lastLoginAt": ""}
# Accounts 页的示例账号（模板演示数据里的人名，纯虚构）
DEMO_ACCOUNTS = [DEMO_USER,
                 {**DEMO_USER, "email": "l.novak@zf.com", "name": "L. Novak", "role": "npi_manager", "roleLabel": "NPI manager"},
                 {**DEMO_USER, "email": "j.martinez@zf.com", "name": "J. Martinez", "role": "user", "roleLabel": "User"}]
MESSAGE = ("This is a read-only demo copy of the Cockpit — nothing is saved here. "
           "In the live Cockpit this action is saved on the server and visible to everyone.")


def load_snapshot(args) -> dict:
    if args.snapshot:
        return json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    with urllib.request.urlopen(args.from_url.rstrip("/") + "/api/bootstrap", timeout=15) as resp:
        return json.load(resp)


def clean(snap: dict, exclude_swat: set[str], exclude_sub: set[str]) -> dict:
    cases = [c for c in snap["cases"] if c.get("swatId") not in exclude_swat]
    kept = {c["swatId"] for c in cases}
    subs = [s for s in snap["submissions"] if s.get("subId") not in exclude_sub
            and s.get("caseId") not in exclude_swat and s.get("approvedSwatId") not in exclude_swat]
    log = [e for e in snap.get("autoLog") or [] if e.get("swatId") in kept]
    return {"cases": cases, "submissions": subs, "autoLog": log,
            "reminderSettings": snap.get("reminderSettings"), "fxSettings": snap.get("fxSettings"),
            "registrationSettings": snap.get("registrationSettings"), "serverTimezone": snap.get("serverTimezone"),
            "allowedEmailDomains": snap.get("allowedEmailDomains") or ["zf.com", "zf-lifetec.com"]}


DOCUMENT_TAGS = re.compile(r"<!DOCTYPE[^>]*>|</?html[^>]*>|</?head>|</?body[^>]*>", re.IGNORECASE)


def build(html: str, snap: dict, as_of: str, artifact: bool = False) -> str:
    """artifact=True：去掉文档骨架标签（claude.ai Artifact 发布时会自己套一层），标题不带 "— Demo"。"""
    data = json.dumps(snap, ensure_ascii=False).replace("</", "<\\/")
    head = f"""
<script>
/* Offline demo copy: embedded data snapshot + fake API (no server). Built {as_of}. */
window.__DEMO_SNAPSHOT__ = {data};
window.__DEMO_USER__ = {json.dumps(DEMO_USER)};
window.__DEMO_ACCOUNTS__ = {json.dumps(DEMO_ACCOUNTS)};
window.__DEMO_MESSAGE__ = {json.dumps(MESSAGE)};
(function(){{
  const json = (status, body) => new Response(JSON.stringify(body), {{status, headers: {{'Content-Type': 'application/json'}}}});
  const realFetch = window.fetch.bind(window);
  window.fetch = function(input, init){{
    const url = typeof input === 'string' ? input : input.url;
    let path = '';
    try {{ path = new URL(url, location.href).pathname; }} catch (e) {{ path = String(url); }}
    // Windows 上 file:///C:/... 会把 /api/x 解析成 /C:/api/x：按 "/api/" 出现的位置截取
    const at = path.indexOf('/api/');
    if (at < 0) return realFetch(input, init);
    path = path.slice(at);
    const method = ((init && init.method) || 'GET').toUpperCase();
    if (path === '/api/bootstrap') return Promise.resolve(json(200, Object.assign({{}}, window.__DEMO_SNAPSHOT__, {{currentUser: window.__DEMO_USER__}})));
    if (path === '/api/health') return Promise.resolve(json(200, {{ok: true}}));
    if (path === '/api/auth/login' || path === '/api/auth/register') return Promise.resolve(json(200, {{ok: true, token: 'demo', user: window.__DEMO_USER__}}));
    if (path === '/api/auth/logout') return Promise.resolve(json(200, {{ok: true}}));
    if (path === '/api/users' && method === 'GET') return Promise.resolve(json(200, {{ok: true, users: window.__DEMO_ACCOUNTS__}}));
    return Promise.resolve(json(503, {{detail: window.__DEMO_MESSAGE__}}));
  }};
}})();
</script>
<style>#demoBadge{{position:fixed;left:12px;bottom:12px;z-index:400;background:#1F2937;color:#fff;font:600 11.5px/1.4 -apple-system,'Segoe UI',system-ui,sans-serif;padding:7px 12px;border-radius:20px;box-shadow:0 4px 14px rgba(0,0,0,.25);opacity:.92;pointer-events:none;}}</style>
</head>"""
    tail = f"""
<div id="demoBadge">Demo copy · data as of {as_of} · read-only</div>
<script>
// Uploads go through XMLHttpRequest, not fetch — block them with the same message.
uploadFile = function(){{ return Promise.reject(Object.assign(new Error(window.__DEMO_MESSAGE__), {{status: 503, detail: window.__DEMO_MESSAGE__}})); }};
</script>
</body>"""
    assert html.count("</head>") == 1 and html.count("</body>") == 1
    if not artifact:
        html = html.replace("<title>Sourcing Committee Cockpit</title>", "<title>Sourcing Committee Cockpit — Demo</title>")
    html = html.replace("</head>", head, 1).replace("</body>", tail, 1)
    return DOCUMENT_TAGS.sub("", html) if artifact else html


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--from-url", default="http://127.0.0.1:8062", help="running Cockpit to take the snapshot from")
    ap.add_argument("--snapshot", help="use a saved /api/bootstrap JSON instead of --from-url")
    ap.add_argument("--out", required=True, help="output HTML path")
    ap.add_argument("--exclude-swat", nargs="*", default=[], help="SWAT ids to leave out (test leftovers)")
    ap.add_argument("--exclude-sub", nargs="*", default=[], help="submission ids to leave out")
    ap.add_argument("--artifact", action="store_true", help="build for publishing as a claude.ai Artifact (no document skeleton tags)")
    ap.add_argument("--as-of", default=datetime.now(tz=UTC).date().isoformat(), help="label shown in the demo badge")
    args = ap.parse_args()
    snap = clean(load_snapshot(args), set(args.exclude_swat), set(args.exclude_sub))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(INDEX.read_text(encoding="utf-8"), snap, args.as_of, args.artifact), encoding="utf-8")
    print(f"{out} — {len(snap['cases'])} case rows, {len(snap['submissions'])} submissions, {out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
