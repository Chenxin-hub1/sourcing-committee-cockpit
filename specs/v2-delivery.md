# Spec v2 — 提醒真实外发（Phase-2）

## 通道与配置（全部环境变量，未配置=该通道 skip）

| 通道 | 配置 | 行为 |
| --- | --- | --- |
| Email | `SC_SMTP_HOST` / `SC_SMTP_PORT`(25) / `SC_SMTP_USER` / `SC_SMTP_PASSWORD` / `SC_SMTP_STARTTLS`(false) / `SC_SMTP_FROM` | aiosmtplib 发送；主题 `Follow-up Task for Sourcing Case <SWAT id>`，正文 = 模板 reminderMessage 原文，收件人 to、抄送 cc |
| Teams | `SC_TEAMS_WEBHOOK_URL` / `SC_TEAMS_WEBHOOK_FORMAT`(teams\|flow) | teams 格式 POST `{"text": message}`（频道 Incoming Webhook）；flow 格式 POST `{"to": email, "subject":..., "text":...}`（Power Automate 流按收件人私发，契约见 DEPLOY.md） |

## 投递挂接

- 每日检查（含设置保存后的强制重跑）与手动 Send reminder：对**新产生的**日志条目逐条执行已启用通道的投递；每通道结果写进条目 `delivery: {"email": "sent"|"skipped"|"failed: …", "teams": …}`，与消息一起持久化。
- 频道选择沿用任务自身的 `channel` 字段（Email / Teams / Email + Teams）。
- 未配置任何通道时行为与 v1 完全一致（仅日志），不报错。

## 前端

- Follow-ups 自动日志表新增 **Delivery** 列：显示如 `Email ✓ · Teams skipped`（sent / skipped / failed 摘要），失败原因 title 悬浮可见。模板既有列不动。

## 依赖

新增运行时依赖：`aiosmtplib`（邮件）、`httpx`（webhook POST）。
