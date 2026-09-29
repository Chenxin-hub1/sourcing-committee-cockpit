FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv

WORKDIR /app

# 依赖层：uv.lock 锁定，可复现构建
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 应用层
COPY app ./app

# 非 root 运行；uid 固定 1000 与常规登录用户一致，宿主机 ./data 目录用同一身份创建即可写
RUN useradd --system --uid 1000 --no-create-home appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app
USER appuser

ENV PATH="/app/.venv/bin:$PATH" \
    SC_DATABASE_URL="sqlite+aiosqlite:////app/data/cockpit.db" \
    SC_PUBLIC_URL="http://localhost:8062/"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
