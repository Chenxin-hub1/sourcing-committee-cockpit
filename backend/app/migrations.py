"""一次性数据迁移：管理员在服务器上手动运行（backend 目录下，或容器里）。

    python -m app.migrations usd-to-eur            # 预览：列出要换算的旧美元记录条数，不写库
    python -m app.migrations usd-to-eur --apply    # 按 Dashboard 汇率卡片上的 USD 汇率与口径换算
    python -m app.migrations usd-to-eur --per-eur 1.17 --basis "OP 2025 plan rates 2026" --apply
    python -m app.migrations import-excel "D:\\weekly\\KW39, 23.09.2026" --apply   # v3 Phase-17：周会 Excel 批量导入
    python -m app.migrations normalize-clusters            # v3 Phase-18：预览 Commodity 原文 → Cluster / Commodity 的归一表
    python -m app.migrations normalize-clusters --apply    # 写回（服务启动时也会按词表版本自动做一次）
    python -m app.migrations graph-check                   # SharePoint / Graph 连通检查（只读，不打印密钥）
    python -m app.migrations graph-check --write-test      # 另在文档库传一个小文件再删掉，验证 write 权限

Docker 部署：docker compose exec cockpit python -m app.migrations usd-to-eur --apply
先备份 data/cockpit.db，并在没人操作时运行：服务进程里的写锁管不到这个独立进程。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import commodities, excel_import, logic, service

MAX_PER_EUR = Decimal(100_000)  # 与 schemas.FxRate 的上限一致


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.migrations", description="One-off data migrations.")
    commands = parser.add_subparsers(dest="command", required=True)
    usd = commands.add_parser("usd-to-eur", help="Convert cases registered in USD before the EUR switch.")
    usd.add_argument("--per-eur", help="1 EUR = X USD (default: the USD rate set on the Dashboard)")
    usd.add_argument("--basis", help="rate basis label (default: the rate basis set on the Dashboard)")
    usd.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    xl = commands.add_parser("import-excel", help="Import weekly committee Excel files (agenda / minutes) as cases.")
    xl.add_argument("paths", nargs="+", help=".xlsx files or folders (a folder is scanned recursively)")
    xl.add_argument("--source-url", default="", help="SharePoint folder link stored as the presentation link of decided cases")
    xl.add_argument("--apply", action="store_true", help="write the cases (default: dry run, prints the report only)")
    nc = commands.add_parser("normalize-clusters", help="Map the Commodity text of imported cases to the fixed Clusters.")
    nc.add_argument("--apply", action="store_true", help="write the changes (default: dry run, prints the mapping table)")
    gc = commands.add_parser("graph-check", help="Check the SharePoint / Graph settings in .env (read-only by default).")
    gc.add_argument("--write-test", action="store_true", help="also upload a small test file to the document library and delete it")
    return parser


def _per_eur(text: str | None) -> Decimal | None:
    try:
        value = Decimal(text) if text else None
    except InvalidOperation:
        return None
    return value if value is not None and value.is_finite() and 0 < value <= MAX_PER_EUR else None


def _excel_files(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            out.extend(sorted(f for f in p.rglob("*.xlsx") if not f.name.startswith("~$")))
        elif p.is_file():
            out.append(p)
        else:
            print(f"skip (not found): {raw}", file=sys.stderr)
    return out


def _meeting_date_for(path: Path):
    """文件名猜不到日期时，退回到它所在文件夹的名字（SharePoint 里是 "KW39, 23.09.2026"）。"""
    _, day = excel_import.meeting_from_name(path.name)
    if day is None:
        _, day = excel_import.meeting_from_name(path.parent.name)
    return day


async def _import_excel(args, sessions) -> int:
    paths = _excel_files(args.paths)
    if not paths:
        print("no .xlsx files found", file=sys.stderr)
        return 2
    async with sessions() as session:
        state = await service.load_state(session)
        added = replaced = failed = 0
        for path in paths:
            day = _meeting_date_for(path)
            try:
                report = excel_import.parse_workbook(path.read_bytes(), path.name, state["fx"], meeting_date=day,
                                                     source_url=args.source_url, imported_by="import-excel",
                                                     when=logic.fmt_when(logic.na_now()))
            except Exception as exc:  # noqa: BLE001 —— 一份文件坏了不影响其它文件
                failed += 1
                print(f"FAIL  {path.name}: {exc}")
                continue
            old = excel_import.previously_imported(state["cases"], report["meetingYear"], report["weekNum"])
            print(f"{'OK   ' if args.apply else 'DRY  '}{path.name}: {report['meetingYear']}-KW{report['weekNum']:02d} "
                  f"{report['meetingDateISO']} cases={len(report['cases'])} rows={report['rows']} "
                  f"replaces={len(old)} warnings={len(report['warnings'])}")
            for w in report["warnings"]:
                print(f"       - {w}")
            if not args.apply or not report["cases"]:
                continue
            old_ids = {c["id"] for c in old}
            state["cases"] = [c for c in state["cases"] if c["id"] not in old_ids]
            new_cases = []
            for c in report["cases"]:
                c["id"] = logic.next_case_row_id(state["cases"] + new_cases)
                new_cases.append(c)
            await service.delete_cases_by_ids(session, sorted(old_ids))
            await service.insert_cases(session, new_cases)
            await session.flush()
            state["cases"].extend(new_cases)
            added += len(new_cases)
            replaced += len(old_ids)
        if args.apply:
            await session.commit()
        print(f"{'applied' if args.apply else 'dry run'}: {len(paths)} files, {added} cases added, {replaced} replaced, {failed} failed")
    return 1 if failed else 0


async def _normalize_clusters(args, sessions) -> int:
    """归一表：原文 → Cluster / Commodity × 条数；认不出的单独列出，由领导补词表（app/commodities.py）。"""
    from collections import Counter
    from copy import deepcopy

    async with sessions() as session:
        state = await service.load_state(session)
        preview = deepcopy(state["cases"])
        changed = service.normalize_commodities(preview)
        table: Counter = Counter()
        unknown: Counter = Counter()
        for c in preview:
            raw = c.get("commodityRaw") or ""
            if not raw:
                continue
            result = commodities.classify(raw)
            table[(raw, c["cluster"], c.get("commodity") or "")] += 1
            if not result["known"]:
                unknown[raw] += 1
        for (raw, cluster, commodity), n in sorted(table.items(), key=lambda kv: (kv[0][1], kv[0][2], -kv[1])):
            print(f"{n:4d}  {raw[:48]:48} -> {cluster[:26]:26} | {commodity}")
        if unknown:
            print("not in the vocabulary (kept as written): " + ", ".join(f"{k} ({n})" for k, n in unknown.most_common()))
        print(f"{'applied' if args.apply else 'dry run'}: {len(changed)} of {len(preview)} case rows "
              f"{'updated' if args.apply else 'would change'} (vocabulary version {commodities.VERSION}).")
        if not args.apply:
            return 0
        for c in changed:
            await service.upsert_case(session, c)
        await service._set_kv(session, service.COMMODITY_KEY, {"version": commodities.VERSION})
        await session.commit()
    return 0


def _mask(value: str) -> str:
    return f"set ({len(value)} chars)" if value else "MISSING"


async def _graph_check(args) -> int:
    """v3 IT 开通 Graph 后的连通检查：令牌 → 站点 → 列表与文档库 → 建单列表的列 →（可选）文档库写入。
    用的是系统自己的 app.graph 代码，服务器免安装环境也能跑；任何输出都不含密钥。"""
    import tempfile

    import httpx

    from . import files, graph
    from .config import get_settings

    s = get_settings()
    print("Settings from .env:")
    print(f"  SC_GRAPH_TENANT_ID      {_mask(s.graph_tenant_id)}")
    print(f"  SC_GRAPH_CLIENT_ID      {_mask(s.graph_client_id)}")
    print(f"  SC_GRAPH_CLIENT_SECRET  {_mask(s.graph_client_secret)}")
    print(f"  SC_SP_SITE_URL          {s.sp_site_url or 'MISSING'}")
    print(f"  SC_SP_LIST_NAME         {s.sp_list_name or '(empty — creating SharePoint items stays off)'}")
    print(f"  SC_SP_LIBRARY_NAME      {s.sp_library_name or '(empty — site default library)'}")
    if not graph.credentials_ready() or not s.sp_site_url:
        print("\nFill in the three SC_GRAPH_* values and SC_SP_SITE_URL in .env, then run this again.")
        return 2
    async with httpx.AsyncClient(timeout=graph.HTTP_TIMEOUT) as client:
        try:
            await graph._token(client)
            print("\n[1/5] Token ............ OK (tenant / client ID / secret accepted)")
        except Exception as exc:  # noqa: BLE001 —— 给人看原因
            print(f"\n[1/5] Token ............ FAILED: {exc}\n      Check tenant ID, client ID and secret (and that the secret has not expired).")
            return 1
        try:
            site = await graph._get_json(client, f"/sites/{graph._site_path(s.sp_site_url)}", params={"select": "id,displayName,webUrl"})
            print(f"[2/5] Site ............. OK: {site.get('displayName')} ({site.get('webUrl')})")
        except Exception as exc:  # noqa: BLE001
            print(f"[2/5] Site ............. FAILED: {exc}\n      403 = IT has not granted this app on the site yet (Sites.Selected needs a per-site grant).")
            return 1
        lists = (await graph._get_json(client, f"/sites/{site['id']}/lists", params={"select": "id,displayName,list"}))["value"]
        drives = (await graph._get_json(client, f"/sites/{site['id']}/drives", params={"select": "id,name,webUrl"}))["value"]
        print(f"[3/5] Lists on the site ({len(lists)}):")
        for item in lists:
            print(f"        - {item['displayName']}  [{(item.get('list') or {}).get('template', '')}]")
        print(f"      Document libraries ({len(drives)}): " + ", ".join(d["name"] for d in drives))
        if s.sp_list_name:
            try:
                _site_id, list_id = await graph._resolve_ids(client)
                cols = (await graph._get_json(client, f"/sites/{site['id']}/lists/{list_id}/columns", params={"select": "name"}))["value"]
                have = {c["name"] for c in cols}
                wanted = list(graph.item_fields({}).keys())
                missing = [w for w in wanted if w not in have]
                print(f"[4/5] List '{s.sp_list_name}' ... OK; columns missing for item creation: {', '.join(missing) or 'none'}")
            except Exception as exc:  # noqa: BLE001
                print(f"[4/5] List '{s.sp_list_name}' ... FAILED: {exc}")
        else:
            print("[4/5] List ............. skipped (SC_SP_LIST_NAME empty)")
        if not args.write_test:
            print("[5/5] Write test ....... skipped (add --write-test to upload and delete one small file)")
            return 0
        with tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False) as fh:
            fh.write(b"Sourcing Cockpit connection test - safe to delete.\n")
            tmp = Path(fh.name)
        try:
            item = await graph.upload_file(tmp, "cockpit-connection-test.txt", tmp.stat().st_size,
                                           [s.sp_folder, "_connection-test"], files.CHUNK_BYTES)
            await graph.delete_file(item["driveId"], item["itemId"])
            # 测试文件夹一起删掉，不在文档库里留空文件夹（"Sourcing Cockpit" 本身留着，系统以后就往里放文件）
            from urllib.parse import quote
            await graph._graph(client, "DELETE", f"/drives/{item['driveId']}/root:/{quote(s.sp_folder + '/_connection-test')}")
            print(f"[5/5] Write test ....... OK (uploaded to {s.sp_folder}/_connection-test and deleted again)")
        except Exception as exc:  # noqa: BLE001
            print(f"[5/5] Write test ....... FAILED: {exc}\n      The site grant may be 'read' instead of 'write'.")
            return 1
        finally:
            tmp.unlink(missing_ok=True)
    return 0


async def run(argv: list[str], sessions) -> int:
    """返回进程退出码：0 成功，2 参数或汇率有误。sessions 是 async_sessionmaker（测试传隔离库）。"""
    args = _parser().parse_args(argv)
    if args.command == "import-excel":
        return await _import_excel(args, sessions)
    if args.command == "normalize-clusters":
        return await _normalize_clusters(args, sessions)
    if args.command == "graph-check":
        return await _graph_check(args)
    async with sessions() as session:
        fx_settings = (await service.load_state(session))["fx"]
        per_eur = _per_eur(args.per_eur or fx_settings["perEur"].get("USD"))
        if per_eur is None:
            print("No valid USD rate: set the USD rate on the Dashboard, or pass --per-eur (1 EUR = X USD).",
                  file=sys.stderr)
            return 2
        basis = fx_settings.get("basis", "") if args.basis is None else args.basis
        snapshot = {"currency": "USD", "perEur": logic.rate_text(per_eur), "basis": basis}
        counts = await service.convert_legacy_usd(session, snapshot, apply=args.apply)
        print(f"{counts['cases']} case rows and {counts['submissions']} submissions in USD to convert "
              f"at 1 EUR = {snapshot['perEur']} USD{f' ({basis})' if basis else ''}.")
        if not args.apply:
            print("Dry run — nothing was changed. Add --apply to convert.")
            return 0
        await session.commit()
        print("Converted. The original USD amounts are kept on each record as the entered amounts.")
        return 0


if __name__ == "__main__":
    from .db import SessionLocal

    sys.exit(asyncio.run(run(sys.argv[1:], SessionLocal)))
