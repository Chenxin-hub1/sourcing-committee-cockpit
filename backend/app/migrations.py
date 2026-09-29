"""一次性数据迁移：管理员在服务器上手动运行（backend 目录下，或容器里）。

    python -m app.migrations usd-to-eur            # 预览：列出要换算的旧美元记录条数，不写库
    python -m app.migrations usd-to-eur --apply    # 按 Dashboard 汇率卡片上的 USD 汇率与口径换算
    python -m app.migrations usd-to-eur --per-eur 1.17 --basis "OP 2025 plan rates 2026" --apply

Docker 部署：docker compose exec cockpit python -m app.migrations usd-to-eur --apply
先备份 data/cockpit.db，并在没人操作时运行：服务进程里的写锁管不到这个独立进程。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal, InvalidOperation

from . import logic, service

MAX_PER_EUR = Decimal(100_000)  # 与 schemas.FxRate 的上限一致


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.migrations", description="One-off data migrations.")
    commands = parser.add_subparsers(dest="command", required=True)
    usd = commands.add_parser("usd-to-eur", help="Convert cases registered in USD before the EUR switch.")
    usd.add_argument("--per-eur", help="1 EUR = X USD (default: the USD rate set on the Dashboard)")
    usd.add_argument("--basis", help="rate basis label (default: the rate basis set on the Dashboard)")
    usd.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    return parser


def _per_eur(text: str | None) -> Decimal | None:
    try:
        value = Decimal(text) if text else None
    except InvalidOperation:
        return None
    return value if value is not None and value.is_finite() and 0 < value <= MAX_PER_EUR else None


async def run(argv: list[str], sessions) -> int:
    """返回进程退出码：0 成功，2 参数或汇率有误。sessions 是 async_sessionmaker（测试传隔离库）。"""
    args = _parser().parse_args(argv)
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
