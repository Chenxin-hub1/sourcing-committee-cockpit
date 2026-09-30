# Seat Belt Sourcing Committee Cockpit

寻源委员会驾驶舱：沿用原始 HTML 模板的页面布局，配合 FastAPI + SQLite 保存案例、登记审批和待办，供内网团队共享使用。

## 功能

Home 搜索、Submit Case 登记、Approval 确认/退回、Database 筛选与 CSV 导出、Dashboard 管理指标与议程导出、Follow-ups 待办与提醒、案例详情和生命周期编辑。待办可由任何登录用户汇报进展并附凭证（含 Outlook 邮件），Manager（采购经理 / NPI 经理角色）approve（关闭）或 reject（写进一步要求），结果邮件通知负责人。

提交金额可按 EUR / USD / CNY 填写，按管理员在 Dashboard 维护的财务 OP 汇率（1 EUR = X 外币）折算为欧元保存（记录保留原币金额与当时汇率）；旧美元案例可一次性换算（见 DEPLOY.md）；区域可多选。Peak Year / Lifetime Spend 按整个 bundle 填一个（案例级必填）；Project / Sourcing Type / Recommended Supplier 按零件行填写，案例级自动汇总；上传的演示文件在系统里改名为 `YYYY.MM.DD 项目 零件描述 零件号, 供应商.ext`（原文件名保留可见）。

每人用公司邮箱自注册个人账号（只填姓名和邮箱，不设密码，凭邮箱登录；只有 Sourcing admin 用密码），提交登记须登录；Sourcing admin 在 Accounts 页提升 Manager / admin 角色，提升为 admin 时发临时密码（详见 DEPLOY.md 安全说明）。审批结果和待办提醒可经 SMTP / Teams 发送，并记录结果。未配置的通道显示 `skipped`。首页的 "Import weekly committee Excel"（Sourcing admin 专用）把委员会每周的 Agenda / MM Excel 导入成那一周的案例：拖入新文件，或从下拉框选随程序发布的历史周文件（`backend/app/history/`，2025 KW36 – 2026 KW39 共 36 周）；会议日期从文件名或文件夹名读，同一周重导会替换上次导入的；也可在服务器上批量跑 `python -m app.migrations import-excel <文件夹> --apply`（文件夹按 SharePoint 的 "KW39, 23.09.2026" 命名时日期从文件夹名取）。

## 本地启动

```bash
cp .env.example .env
# 编辑 .env，至少设置 SC_BOOTSTRAP_ADMIN_EMAIL / SC_BOOTSTRAP_ADMIN_PASSWORD（首个 Sourcing admin）
cd backend
uv sync --locked
uv run uvicorn app.main:app --port 8062 --reload
```

访问 `http://127.0.0.1:8062/`。应用读取项目根目录 `.env`；`backend/.env` 可覆盖同名项，进程环境变量优先级最高。

首次初始化空数据库时，默认装载 22 条案例和 1 条登记演示数据。正式使用应在首次启动前设置 `SC_SEED_ON_EMPTY=false`。初始化后删除案例或重启服务不会重新装载演示数据。

## 验证

```bash
cd backend
uv run pytest -q
uv run ruff check app tests
```

测试各自使用临时数据库，禁用真实外发通道；可以单独运行任一 API 用例。浏览器回归运行方法和本轮核验记录见 [项目核验记录](docs/project-audit-2026-09-22.md)。界面适配、鼠标/触摸/键盘滚动及对应回归脚本见 [前端滚动核验记录](docs/frontend-scroll-audit-2026-09-22.md)。

## 结构

```text
_template.html                 原始视觉参考，保留不修改
backend/app/static/index.html  当前前端实现（原生 HTML/CSS/JavaScript）
backend/app/schemas.py         请求结构、类型和输入校验
backend/app/logic.py           案例、审批和提醒业务规则
backend/app/main.py            API、按角色鉴权和提醒调度
backend/app/accounts.py        个人账号：密码哈希、公司邮箱与密码规则、角色
backend/app/feedback.py        待办反馈与关闭审批：approve / reject 规则与通知信
backend/app/service.py         状态装载、增量持久化和快照
backend/app/delivery.py        SMTP 与 Teams 投递
backend/app/seed.json          初始演示数据
backend/tests/                 API、业务、并发、持久化与配置回归
constitution-doc/              项目章程与路线图
specs/ tickets/                规格与历史工单
```

## 部署与边界

部署步骤、备份、用户权限和通道配置见 [DEPLOY.md](DEPLOY.md)。当前部署使用单容器、单 Uvicorn worker 和 SQLite；进程内互斥不支持直接扩成多个 worker。登录令牌 7 天过期，改密码、被停用或登出后失效。

页面保留模板布局，加入响应式适配、服务端管理门禁和投递状态。`index.html` 是当前实现，原始模板不再同步业务修复。同一案例同时编辑仍以最后一次保存为准；真实 Excel 导入、SSO 单点登录和跨年历史数据迁移尚未实现。
