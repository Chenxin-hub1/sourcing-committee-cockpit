"""SharePoint 建单通道：Microsoft Graph app-only（client credentials + Sites.Selected）。

设计约束与 delivery 一致：
- 未配置（tenant/client/secret/site/list 任一为空）记 "skipped"，绝不阻断确认登记；
- 失败记 "failed: …"（只带类型/状态码，详情进服务器日志），确认流程照常完成；
- 网络调用一律在调用方的写锁外执行，结果由调用方用独立短事务回填 sub["sharepoint"]。
"""

from __future__ import annotations

import asyncio
import html
import logging
import time
from urllib.parse import quote, urlsplit

import httpx

from .config import get_settings

log = logging.getLogger("cockpit.graph")

GRAPH = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
GRAPH_SCOPE = "https://graph.microsoft.com/.default"
TOKEN_EARLY_REFRESH = 300  # 令牌过期前 5 分钟即刷新
HTTP_TIMEOUT = 15

# 进程内缓存：令牌与 站点/List id 都随配置键走——改配置立即生效，无需重启。
# 键含全部相关凭据/名称，测试替身换配置时不会串台。
_token_cache: dict = {"key": "", "token": "", "expires_at": 0.0}
_site_cache: dict = {"key": "", "site_id": "", "list_id": ""}
_drive_cache: dict = {"key": "", "drive_id": "", "root_id": ""}

UPLOAD_TIMEOUT = 120  # 单块上传（最大 10 MiB）的超时


def _reset_cache() -> None:
    """测试与配置切换用：清空令牌、站点与文档库缓存。"""
    _token_cache.update(key="", token="", expires_at=0.0)
    _site_cache.update(key="", site_id="", list_id="")
    _drive_cache.update(key="", drive_id="", root_id="")


def credentials_ready() -> bool:
    """核心三项凭据齐备——发信与 Teams webhook Bearer 只看这三项（建单还需站点与 List）。"""
    s = get_settings()
    return all([s.graph_tenant_id, s.graph_client_id, s.graph_client_secret])


def configured() -> bool:
    """SharePoint 建单可用：核心凭据 + 站点地址 + List 名全部齐备。"""
    s = get_settings()
    return all([s.graph_tenant_id, s.graph_client_id, s.graph_client_secret, s.sp_site_url, s.sp_list_name])


async def access_token() -> str:
    """对外暴露的令牌获取（delivery 给 Teams webhook 附加 Bearer 用）；失败向上抛由调用方处理。"""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        return await _token(client)


async def _token(client: httpx.AsyncClient) -> str:
    """Graph 访问令牌（app-only，.default 范围 = Entra 已批准的应用权限集）。"""
    s = get_settings()
    key = f"{s.graph_tenant_id}|{s.graph_client_id}|{s.graph_client_secret}"
    if _token_cache["key"] == key and _token_cache["token"] and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"]
    resp = await client.post(TOKEN_URL.format(tenant=s.graph_tenant_id), data={
        "grant_type": "client_credentials", "client_id": s.graph_client_id,
        "client_secret": s.graph_client_secret, "scope": GRAPH_SCOPE,
    })
    if resp.status_code != 200:
        log.warning("graph token request failed: HTTP %s %s", resp.status_code, resp.text[:300])
        raise RuntimeError(f"token HTTP {resp.status_code}")
    payload = resp.json()
    if not payload.get("access_token"):
        raise RuntimeError("token response missing access_token")
    ttl = max(0, int(payload.get("expires_in", 3600)) - TOKEN_EARLY_REFRESH)
    _token_cache.update(key=key, token=payload["access_token"], expires_at=time.time() + ttl)
    return _token_cache["token"]


def _site_path(site_url: str) -> str:
    """站点 URL → Graph 寻址形式 host:/path。Sites.Selected 不能 search，只能直连寻址。"""
    parsed = urlsplit(site_url if "://" in site_url else f"https://{site_url}")
    if not parsed.hostname:
        raise RuntimeError("invalid SC_SP_SITE_URL")
    return f"{parsed.hostname}:/{parsed.path.strip('/')}"


async def _get_json(client: httpx.AsyncClient, path: str, params: dict | None = None) -> dict:
    resp = await client.get(f"{GRAPH}{path}", params=params,
                            headers={"Authorization": f"Bearer {await _token(client)}"})
    if resp.status_code == 403:
        # Sites.Selected 下最常见：Entra 批了权限，但管理员还没对该站点授予应用角色
        raise RuntimeError("403 — site-level grant missing for this app?")
    if resp.status_code == 404:
        raise RuntimeError("404 — check SC_SP_SITE_URL / SC_SP_LIST_NAME")
    if resp.status_code != 200:
        log.warning("graph GET %s failed: HTTP %s %s", path, resp.status_code, resp.text[:300])
        raise RuntimeError(f"HTTP {resp.status_code}")
    return resp.json()


async def _resolve_ids(client: httpx.AsyncClient) -> tuple[str, str]:
    """站点按 URL、List 按显示名解析成稳定 id（写 item 用 id，不用显示名）。"""
    s = get_settings()
    key = f"{s.sp_site_url}|{s.sp_list_name}"
    if _site_cache["key"] == key and _site_cache["site_id"] and _site_cache["list_id"]:
        return _site_cache["site_id"], _site_cache["list_id"]
    site = await _get_json(client, f"/sites/{_site_path(s.sp_site_url)}", params={"select": "id"})
    lists = (await _get_json(client, f"/sites/{site['id']}/lists",
                             params={"select": "id,displayName"}))["value"]
    wanted = s.sp_list_name.strip()
    target = next((l for l in lists if l["displayName"] == wanted), None)
    if target is None:
        target = next((l for l in lists if l["displayName"].casefold() == wanted.casefold()), None)
    if target is None:
        names = ", ".join(repr(l["displayName"]) for l in lists)
        raise RuntimeError(f"list {wanted!r} not found on site (have: {names})")
    _site_cache.update(key=key, site_id=site["id"], list_id=target["id"])
    return site["id"], target["id"]


# ============================= 文档库：演示文件（v3 Phase-5） =============================
# 权限：Sites.Selected + 站点级 write 角色即覆盖该站点的所有列表与文档库（与建单同一授权）。
# 接口按 Microsoft Graph v1.0 文档：createUploadSession 分块上传（块大小为 320 KiB 的整数倍、
# 单块 < 60 MiB，向 uploadUrl PUT 时不带 Authorization）；下载取 @microsoft.graph.downloadUrl（预认证、几分钟有效）。


def files_configured() -> bool:
    """演示文件存 SharePoint：核心凭据 + 站点地址（不需要 List 名）。"""
    s = get_settings()
    return credentials_ready() and bool(s.sp_site_url)


async def _graph(client: httpx.AsyncClient, method: str, path: str, **kwargs) -> httpx.Response:
    headers = {"Authorization": f"Bearer {await _token(client)}", **kwargs.pop("headers", {})}
    return await client.request(method, f"{GRAPH}{path}", headers=headers, **kwargs)


def _fail(what: str, resp: httpx.Response) -> RuntimeError:
    """文档库操作失败：给用户看的只有状态码与常见原因，响应体进日志。"""
    log.warning("graph %s failed: HTTP %s %s", what, resp.status_code, resp.text[:300])
    if resp.status_code in (401, 403):
        return RuntimeError(f"{what}: HTTP {resp.status_code} (site-level write permission missing for this app?)")
    if resp.status_code == 404:
        return RuntimeError(f"{what}: HTTP 404 (check SC_SP_SITE_URL / SC_SP_LIBRARY_NAME)")
    return RuntimeError(f"{what}: HTTP {resp.status_code}")


async def _drive(client: httpx.AsyncClient) -> tuple[str, str]:
    """文档库 id 与根文件夹 id：SC_SP_LIBRARY_NAME 为空取站点默认库，否则按显示名匹配。"""
    s = get_settings()
    key = f"{s.sp_site_url}|{s.sp_library_name}"
    if _drive_cache["key"] == key and _drive_cache["drive_id"]:
        return _drive_cache["drive_id"], _drive_cache["root_id"]
    site = await _get_json(client, f"/sites/{_site_path(s.sp_site_url)}", params={"select": "id"})
    wanted = s.sp_library_name.strip()
    if not wanted:
        drive_id = (await _get_json(client, f"/sites/{site['id']}/drive", params={"select": "id"}))["id"]
    else:
        drives = (await _get_json(client, f"/sites/{site['id']}/drives", params={"select": "id,name"}))["value"]
        match = next((d for d in drives if d["name"].casefold() == wanted.casefold()), None)
        if match is None:
            names = ", ".join(repr(d["name"]) for d in drives)
            raise RuntimeError(f"document library {wanted!r} not found on site (have: {names})")
        drive_id = match["id"]
    root_id = (await _get_json(client, f"/drives/{drive_id}/root", params={"select": "id"}))["id"]
    _drive_cache.update(key=key, drive_id=drive_id, root_id=root_id)
    return drive_id, root_id


async def _ensure_folder(client: httpx.AsyncClient, drive_id: str, parent_id: str, name: str, path: str) -> str:
    """在 parent 下建文件夹（已存在则取它）；path 是从库根起的完整路径，已存在时按路径取 id。"""
    resp = await _graph(client, "POST", f"/drives/{drive_id}/items/{parent_id}/children",
                        json={"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"})
    if resp.status_code in (200, 201):
        return resp.json()["id"]
    if resp.status_code != 409:
        raise _fail("create folder", resp)
    existing = await _graph(client, "GET", f"/drives/{drive_id}/root:/{quote(path)}", params={"select": "id"})
    if existing.status_code != 200:
        raise _fail("open folder", existing)
    return existing.json()["id"]


async def upload_file(path, name: str, size: int, folders: list[str], chunk_bytes: int) -> dict:
    """把本地文件分块传到文档库 folders 路径下（同名自动改名）。返回 {driveId, itemId, webUrl, name}。

    失败抛 RuntimeError（文案可直接给用户看）；中途失败会取消上传会话。"""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        drive_id, parent_id = await _drive(client)
        walked = []
        for folder in folders:
            walked.append(folder)
            parent_id = await _ensure_folder(client, drive_id, parent_id, folder, "/".join(walked))
        resp = await _graph(client, "POST", f"/drives/{drive_id}/items/{parent_id}:/{quote(name)}:/createUploadSession",
                            json={"item": {"@microsoft.graph.conflictBehavior": "rename", "name": name}})
        if resp.status_code != 200:
            raise _fail("create upload session", resp)
        upload_url = resp.json()["uploadUrl"]
        try:
            item = None
            fh = await asyncio.to_thread(open, path, "rb")  # 磁盘读放到线程里，不卡住事件循环
            try:
                start = 0
                while start < size:
                    block = await asyncio.to_thread(fh.read, chunk_bytes)
                    end = start + len(block) - 1
                    # 预认证地址：不带 Authorization（带了反而可能 401）
                    put = await client.put(upload_url, content=block, timeout=UPLOAD_TIMEOUT,
                                           headers={"Content-Range": f"bytes {start}-{end}/{size}"})
                    if put.status_code in (200, 201):
                        item = put.json()
                    elif put.status_code != 202:
                        raise _fail("upload", put)
                    start = end + 1
            finally:
                fh.close()
            if item is None:
                raise RuntimeError("upload: SharePoint did not confirm the file")
        except Exception:
            try:
                await client.delete(upload_url)
            except httpx.HTTPError:
                pass
            raise
        return {"driveId": drive_id, "itemId": item["id"], "webUrl": item.get("webUrl", ""), "name": item.get("name", name)}


async def download_url(drive_id: str, item_id: str) -> str:
    """文件的预认证下载地址（几分钟内有效，浏览器直接下载，不需要 SharePoint 权限）。"""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await _graph(client, "GET", f"/drives/{drive_id}/items/{item_id}",
                            params={"select": "id,@microsoft.graph.downloadUrl"})
        if resp.status_code != 200:
            raise _fail("get download link", resp)
        url = resp.json().get("@microsoft.graph.downloadUrl")
        if not url:
            raise RuntimeError("get download link: SharePoint returned no download URL")
        return url


async def delete_file(drive_id: str, item_id: str) -> None:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        resp = await _graph(client, "DELETE", f"/drives/{drive_id}/items/{item_id}")
        if resp.status_code not in (204, 404):
            raise _fail("delete file", resp)


def item_fields(sub: dict, base_url: str = "") -> dict:
    """提交登记 → SharePoint List 的字段映射（提交时案例尚未建立，字段以提交单为准）。

    列契约（内部列名与类型）见 DEPLOY.md；建列时用无空格名称，保证内部名与显示名一致。
    Status 只反映提交时状态，后续审批/决议不回写（一期边界，见 DEPLOY.md）。
    """
    pns = sub.get("partNumbers") or []
    more = f" (+{len(pns) - 1})" if len(pns) > 1 else ""
    screening = "; ".join(filter(None, [
        f"Family case: {sub.get('isFamilyCase')}" if sub.get("isFamilyCase") else "",
        f"aligned: {sub.get('familyAligned')}" if sub.get("isFamilyCase") == "Yes" else "",
        f"ECM: {sub.get('involvesECM')}" if sub.get("involvesECM") else "",
        f"CCB2: {sub.get('ccbApproved')}" if sub.get("involvesECM") == "Yes" else "",
    ]))
    return {
        "Title": f"{sub.get('caseId', '')} — {sub.get('partDescription', '')}",
        "SubId": sub.get("subId", ""),
        "SWATId": sub.get("caseId", ""),
        "PartNumber": (sub.get("partNumber", "") or "") + more,
        "PartDescription": sub.get("partDescription", ""),
        "RecommendedSupplier": sub.get("recommendedSupplier", ""),
        "Region": sub.get("region", ""), "Project": sub.get("project", ""),
        "Cluster": sub.get("cluster", ""), "SourcingType": sub.get("sourcingType", ""),
        "DecisionLevel": sub.get("decisionLevel", ""),
        "PeakYearSpend": int(sub.get("peakYearSpend") or 0),
        "LifetimeSpend": int(sub.get("lifetimeSpend") or 0),
        "Status": sub.get("status", ""),
        "Submitter": sub.get("submitterName", ""),
        "SubmitterEmail": sub.get("submitterEmail", ""),
        "SubmittedAt": sub.get("submittedAt", ""),
        "MeetingDate": sub.get("meetingDateLabel") or "",
        "Screening": screening,
        "Comments": sub.get("committeeDiscussion", ""),
        # 确认登记后此链接生效（案例以同一 SWAT 号登场）；被退回则不会有对应案例
        "CaseLink": base_url.rstrip("/") + "/#case/" + quote(str(sub.get("caseId", "")), safe=""),
    }


async def create_submission_item(sub: dict, base_url: str = "") -> tuple[str, str]:
    """提交登记后在 SharePoint List 建单。返回 (result, itemId)。

    result: created / skipped / failed: …；失败细节只进日志（响应体可能含内部路径）。
    """
    if not configured():
        return "skipped", ""
    anchor = sub.get("subId", "") or sub.get("caseId", "")
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            site_id, list_id = await _resolve_ids(client)
            resp = await client.post(
                f"{GRAPH}/sites/{site_id}/lists/{list_id}/items",
                json={"fields": item_fields(sub, base_url)},
                headers={"Authorization": f"Bearer {await _token(client)}"},
            )
            if resp.status_code == 403:
                log.warning("graph create item 403 for %s: %s", anchor, resp.text[:300])
                return "failed: 403 (site write permission missing?)", ""
            if resp.status_code == 400:
                # 常见原因：List 缺列或列类型不匹配（内部列名须与 DEPLOY.md 契约一致）
                log.warning("graph create item 400 for %s: %s", anchor, resp.text[:500])
                return "failed: 400 (list columns missing/mismatched — see server log)", ""
            if resp.status_code not in (200, 201):
                log.warning("graph create item HTTP %s for %s", resp.status_code, anchor)
                return f"failed: HTTP {resp.status_code}", ""
            return "created", str(resp.json().get("id", ""))
    except RuntimeError as e:  # 本模块抛出的、面向用户的配置类提示（403/404/找不到 List 等）
        log.warning("graph create failed (%s): %s", anchor, e)
        return f"failed: {e}", ""
    except Exception as e:  # noqa: BLE001 — 建单失败必须被记录而不是中断提交
        log.warning("graph create failed (%s): %s", anchor, e)
        return f"failed: {type(e).__name__}", ""


async def send_mail(to: str, subject: str, body: str, cc: str = "") -> str:
    """Graph sendMail（Mail.Send 应用权限）—— SMTP 未配置时的邮件兜底通道。

    返回 sent / failed: …，与 SMTP 同一套结果语义。发件邮箱（SC_GRAPH_SENDER）必须是
    应用有权以其发送的邮箱（IT 侧建议用应用访问策略限定到该邮箱）；saveToSentItems=false，
    共享发件箱不留已发送副本。
    """
    s = get_settings()
    if not s.graph_sender:
        return "skipped"
    from .delivery import clean_addresses  # 函数内导入：delivery 顶层依赖本模块，顶层互导会循环

    to_list = [a for a in clean_addresses(to).split(", ") if a]
    cc_list = [a for a in clean_addresses(cc).split(", ") if a]
    if not to_list:
        return "failed: no valid recipient address"
    message: dict = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body},
        "toRecipients": [{"emailAddress": {"address": a}} for a in to_list],
    }
    if cc_list:
        message["ccRecipients"] = [{"emailAddress": {"address": a}} for a in cc_list]
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{GRAPH}/users/{quote(s.graph_sender)}/sendMail",
                json={"message": message, "saveToSentItems": False},
                headers={"Authorization": f"Bearer {await _token(client)}"},
            )
            if resp.status_code == 403:
                log.warning("graph sendMail 403 as %s: %s", s.graph_sender, resp.text[:300])
                return "failed: 403 (Mail.Send missing or app not allowed to send as this mailbox)"
            if resp.status_code not in (200, 201, 202):
                log.warning("graph sendMail HTTP %s: %s", resp.status_code, resp.text[:300])
                return f"failed: HTTP {resp.status_code}"
            return "sent"
    except Exception as e:  # noqa: BLE001 — 发信失败必须被记录而不是中断调用方
        log.warning("graph sendMail failed: %s", e)
        return f"failed: {type(e).__name__}"


def channel_message_ready() -> bool:
    """Teams Graph 直发可用：核心凭据 + 团队/频道 ID 齐备。"""
    s = get_settings()
    return credentials_ready() and bool(s.teams_graph_team_id and s.teams_graph_channel_id)


async def send_channel_message(text: str) -> str:
    """Graph 直发 Teams 频道消息（ChannelMessage.Send 应用权限）—— Teams 通道的优先路径。

    已知边界（用户知情取舍，见 DEPLOY.md）：微软将应用权限直发频道消息定位为迁移场景，
    未来可能按量计费；webhook 路径保留为兜底，清空两个 ID 配置即切换。
    纯文本按 HTML 投递：转义 + 换行转 <br>，Teams 的 text 模式对换行渲染不稳定。
    """
    s = get_settings()
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{GRAPH}/teams/{quote(s.teams_graph_team_id)}/channels/{quote(s.teams_graph_channel_id)}/messages",
                json={"body": {"contentType": "html",
                               "content": html.escape(text).replace("\n", "<br>")}},
                headers={"Authorization": f"Bearer {await _token(client)}"},
            )
            if resp.status_code == 403:
                log.warning("graph channel message 403: %s", resp.text[:300])
                return "failed: 403 (ChannelMessage.Send missing or restricted for this app/team)"
            if resp.status_code == 404:
                log.warning("graph channel message 404: team/channel id wrong")
                return "failed: 404 — check SC_TEAMS_TEAM_ID / SC_TEAMS_CHANNEL_ID"
            if resp.status_code not in (200, 201):
                log.warning("graph channel message HTTP %s: %s", resp.status_code, resp.text[:300])
                return f"failed: HTTP {resp.status_code}"
            return "sent"
    except Exception as e:  # noqa: BLE001 — 发送失败必须被记录而不是中断提醒流程
        log.warning("graph channel message failed: %s", e)
        return f"failed: {type(e).__name__}"
