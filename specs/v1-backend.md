# Spec v1 — 持久化后端（Phase-1）

以 `_template.html` 内嵌 JS 逻辑为规范移植。数据形状与模板完全一致（字段名、取值、嵌套 `followUps`/`partNumbers`/`closure` 原样），前端零适配成本。

## 原则

- 服务端是唯一事实源：所有写操作经命令端点落库；每个写端点返回**全量快照** `{cases, submissions, reminderSettings, autoLog}`（数据量 ~100KB，内网可忽略），前端整体替换后重渲染。
- 校验双轨：前端保留模板原有即时校验（交互体验不变），服务端以同文案同规则再校验一遍（422 `{detail}` → 前端映射到模板既有的错误展示位）。
- 提醒发送 v1 模拟：只写日志，不外发；消息体、收件人、渠道与模板逐字一致。

## 数据模型（SQLAlchemy 2.0 async + aiosqlite；连接串走 `SC_DATABASE_URL` 接缝，可换 PG）

| 表 | 列 | 说明 |
| --- | --- | --- |
| `cases` | `id`(PK, 模板行号 C0001…)、`swat_id`、`week_num`、`case_number`（索引列）、`doc` JSON | 案例每周登场记录，整文档 JSON 保真存储 |
| `submissions` | `sub_id`(PK)、`status`(索引)、`doc` JSON | 在线登记提交 |
| `reminder_log` | `seq`(PK 自增)、`doc` JSON | 提醒日志，保留最新 200 条 |
| `kv` | `key`(PK)、`doc` JSON | 目前仅 `reminder_settings` |

首次启动且库为空时装载 `seed.json`（由模板 JS 原样导出：22 案例 + 1 提交）。

## 端点（均返回快照；写操作失败 422）

- `GET /api/bootstrap` — 先跑“每日检查（如今天未跑）”，再返回快照。
- `POST /api/submissions` — 校验必填项与 Family/ECM 门禁（同模板文案）；分配 `SUB-####`（取现有最大+1，永不复用）；`caseId` 归一化（`swat 10482`→`SWAT-10482`）；重复待审提交拦截。响应附 `subId`。
- `POST /api/submissions/{sub_id}/confirm` — 移植模板确认逻辑：状态置 Confirmed、`approvedSwatId`、按 `meetingWeekNum`（缺省取最大周）建 `PENDING` 案例行（`committeeDiscussion='Pending for Sourcing Committee Review'`、`submitterComments`、无待办），行号取该周 `max(caseNumber)+1`。响应附 `submission`。
- `POST /api/submissions/{sub_id}/reject` `{reason}` — 必填原因；状态置 Rejected。
- `DELETE /api/cases/{swat_id}` — 删除该 SWAT 全部登场行；级联：`approvedSwatId` 指向它的提交置 `Deleted` 并写退回原因。
- `PUT /api/cases/{row_id}` — 详情编辑保存。服务端执行三条规则（见下）与字段合并、金额汇总、`actionStatus` 重算。
- `POST /api/reminders/manual` `{taskId, name, email, cc, channel}` — 邮箱格式校验；更新任务收件人字段与 `lastReminder`；写日志。
- `PUT /api/reminder-settings` `{enabled, overdueEveryDays, channel, alwaysCc}` — 保存并立即强制跑一次每日检查。
- `POST /api/legacy-upload` — 模板遗留 Excel 上传模拟：生成 18 条第 34 周案例（随机种子取时间），normalize+补链接后入库。

## 详情编辑三条规则（模板原文文案）

1. 决议 ≠ PENDING 必须有 Sourcing Presentation Link（完整 URL）。
2. PENDING 案例不得携带任何待办任务。
3. 全部待办 Closed（即案件闭环）必须有 Final PPT/Supporting Document Link（完整 URL）。

## 每日提醒检查（启动时 + 每小时；结果以 ET 日期守卫每日一次，设置保存可强制重跑）

- 逾期标记：`Open` 且 `daysUntil<0` → `Overdue`。
- 触发：提前 N 天（`daysBefore`>0 时）、到期当天、逾期每 `overdueEveryDays` 天；每任务每日最多一次（`lastAutoReminderDate` 守卫）；PENDING 案例不参与。
- 每次触发写日志（when/trigger/swatId/task/to/cc/channel/message），消息体 = 模板 `reminderMessage`（案例链接前缀取 `SC_PUBLIC_URL` 设置）。
- 收尾重算各案例 `actionStatus`，记录 `lastRun` 摘要。

## 静态托管

`GET /` 服务 `app/static/index.html`；API 前缀 `/api` 与其互不干扰。
