# Tech stack

单页应用（模板原生 JS 原样保留）+ Python 异步 API，Docker 单容器部署于公司内网 Linux 服务器。

## Core

| Layer | Choice | Rationale |
| --- | --- | --- |
| Frontend | 模板 `_template.html` 原样（零框架） | 领导要求一比一还原，模板自带完整 UI/交互；引入框架只会引入偏差 |
| Language | Python 3.12+ / TypeScript 无 | 后端逻辑是模板 JS 的忠实移植，单一语言降低漂移风险 |
| API | FastAPI + pydantic v2（请求体建模） | 栈默认；命令式端点 + 全量快照响应，前端零状态同步成本 |
| Data | SQLite（aiosqlite，WAL），SQLAlchemy 2.0 async | 团队规模小、单容器；表按文档 JSON 保真存整案例，`SC_DATABASE_URL` 接缝可换 PostgreSQL（届时引 Alembic；v1 空库 create_all） |
| Testing | pytest（API 层）+ Playwright（人工验收 UI 一致性） | 规则文案与模板逐字一致，端到端比对靠浏览器 |
| Tooling | uv、ruff | 栈默认 |
| Excel 导出 | openpyxl（v3 Phase-4 起） | 议程 / 纪要要给委员会当真正的 Excel 用；之前的 HTML 表格假 .xls 打开有兼容性警告，openpyxl 是纯 Python、无外部依赖、能写数字格式与冻结表头 |

## Deployment

Dockerfile（uv 安装依赖、非 root 运行）+ docker-compose：`./data` 卷挂 SQLite，`SC_PUBLIC_URL` 指定对外地址（提醒消息里的案例链接前缀），内网 HTTP 直连宿主机 8062 端口（映射到容器内 8000，避开常被占用的 8000）。部署流程：服务器 `git pull` → `docker compose up -d --build`。

## Ruled out

- SSO（Entra ID 单点登录）— 2026-09-24 反馈人决定改用个人账号（公司邮箱自注册 + 自设密码，角色由管理员提升，v3 Phase-6），共享管理员口令随之下线；SSO 仍是升级路径
- 真实邮件/Teams 发送 — **v2 已实现**（SMTP 中继 + Teams webhook，环境变量配置，未配置通道优雅降级为仅记日志）；线上真实外发只差 IT 提供参数
- PostgreSQL — 单容器小团队写入量，SQLite 足够；连接串接缝保留升级路径
- React/Vite 等前端框架 — 与”一比一还原”目标冲突
