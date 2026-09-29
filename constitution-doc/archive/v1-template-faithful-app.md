# v1 — 一比一还原模板并持久化上线

## Charter

以领导给的单文件 HTML 模板（`_template.html`）为唯一视觉与功能规范，一比一复刻页面，并加上持久化后端：多人共用同一份数据，刷新/重启不丢失。交付后由用户推送到 git，在服务器上拉取并以 Docker 部署。本版本不含：真实邮件/Teams 发送（先记日志）、账号登录/SSO、数据库迁移工具（首次 schema 变更时再引入 Alembic）。

## Acceptance

- 与模板并排打开六个页面（Home / Submit / Approval / Database / Dashboard / Follow-ups），UI 无可见差异，首次启动演示数据一致。
- 提交案例 → 审批确认 → Database 出现 Sourcing Decision = Pending 的新案例；重启服务、刷新浏览器后数据仍在。
- 详情编辑的三条校验规则生效：非 Pending 决议必须填 Sourcing Presentation Link；Pending 案例不能有待办；全部待办 Closed 必须填 Final Document Link（且均为完整 URL）。
- Follow-ups 手动提醒写入共享日志；自动提醒由服务端每日检查（到期/逾期每 N 天），日志全员可见。
- Dashboard 的 CSV 导出与会议议程导出可用。
- 服务器上 `git pull` 后 `docker compose up -d --build` 一条命令可访问。
- 窗口缩放与浏览器缩放视觉效果良好：桌面宽度与模板逐字一致，≤700px 走响应式补丁（顶栏不重叠、内容单列）。

## Phase-1: 持久化后端

Status: `closed`

Description: FastAPI + SQLite 数据模型、种子数据装载、全部命令式端点与每小时自动提醒检查。

Spec: specs/v1-backend.md

## Phase-2: 前端接入 API

Status: `closed`

Description: 模板前端外科手术式改造——数据层换为服务端快照，UI 与交互零改动。

Spec: specs/v1-frontend-wiring.md

## Phase-3: 本地验证

Status: `closed`

Description: Playwright 全流程验收 + 截图比对 UI 一致性；核心 API pytest。

Spec: non-spec

## Phase-4: 部署包

Status: `closed`

Description: Dockerfile、docker-compose（数据卷）、DEPLOY.md 部署说明，供服务器 git pull 后一键运行。

Spec: non-spec
