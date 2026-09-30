"""一次性数据迁移：管理员在服务器上手动运行（backend 目录下，或容器里）。

    python -m app.migrations usd-to-eur            # 预览：列出要换算的旧美元记录条数，不写库
    python -m app.migrations usd-to-eur --apply    # 按 Dashboard 汇率卡片上的 USD 汇率与口径换算
    python -m app.migrations usd-to-eur --per-eur 1.17 --basis "OP 2025 plan rates 2026" --apply
    python -m app.migrations import-excel "D:\\weekly\\KW39, 23.09.2026" --apply   # v3 Phase-17：周会 Excel 批量导入

Docker 部署：docker compose exec cockpit python -m app.migrations usd-to-eur --apply
先备份 data/cockpit.db，并在没人操作时运行：服务进程里的写锁管不到这个独立进程。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import excel_import, logic, service

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


async def run(argv: list[str], sessions) -> int:
    """返回进程退出码：0 成功，2 参数或汇率有误。sessions 是 async_sessionmaker（测试传隔离库）。"""
    args = _parser().parse_args(argv)
    if args.command == "import-excel":
        return await _import_excel(args, sessions)
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
