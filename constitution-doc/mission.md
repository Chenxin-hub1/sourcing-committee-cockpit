# Mission

## Background

寻源委员会（Sourcing Committee）的案例每周靠 Excel 周报传递：查一个历史案例要逐周翻文件，提交、登记确认、待办跟踪全靠邮件与人工记忆。领导给出单文件 HTML 原型模板（`_template.html`，含完整 UI 与演示数据），要求一比一实现并部署到公司内网服务器，供团队日常使用。

## Target Audience

- **采购/寻源工程师（提交人）** — 在线提交案例登记，替代每周填 Excel
- **SBS Procurement 审批人** — 确认或退回登记（Admin 模式）
- **寻源委员会成员** — 会前查议程、会后记录决议与待办
- **管理层** — 驾驶舱看审批/行动状态与分布

## Solution

以模板 UI 为唯一视觉规范的单页应用 + 轻量持久化后端：案例库（筛选/搜索/CSV/议程导出）、在线提交与登记确认、案例详情与生命周期时间线、待办追踪与自动提醒（v1 模拟发送记日志）、管理驾驶舱。Docker 部署于内网 Linux 服务器，数据落 SQLite（连接串可换 PostgreSQL）。

## Goals

- 页面 UI 与模板一比一一致，六个页面并排打开无可感知差异
- 提交、审批、编辑、待办全部持久化：多人共享同一份数据，刷新/重启不丢失
- 核心闭环可用：提交 → 登记确认 → 委员会决议记录 → 待办跟踪 → 案例关闭
- 服务器上 `git pull` + `docker compose up -d --build` 即完成部署

## Versions

| Version | Status |
| --- | --- |
| [v3-user-feedback-round1](roadmap/v3-user-feedback-round1.md) | `in-progress` |
