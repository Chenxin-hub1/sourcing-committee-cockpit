# Spec v2 — 管理员口令门禁（Phase-1）

## 后端

- 配置：`SC_ADMIN_PASSWORD`（空 = 管理功能整体停用，登录端点返回 503 提示未配置）。
- `POST /api/admin/login` `{password}` → 校验通过生成随机令牌（`secrets.token_urlsafe`），存 kv `admin_tokens`（持久，重启不失；登出即删）→ `{ok, token}`；错误口令 401。
- `POST /api/admin/logout`（携带 `X-Admin-Token`）→ 删除该令牌。
- 管理端点（confirm / reject / PUT case / DELETE case / PUT reminder-settings）统一要求 `X-Admin-Token` 在有效令牌表中，否则 401 `Admin login required.`
- 开放端点不变：bootstrap、提交登记、手动提醒、遗留上传（模板中这些本就对所有人开放）。

## 前端

- `API.request` 自动附带 `sessionStorage['sc_admin_token']`；收到 401 且本地认为 isAdmin → 清令牌、降级用户视图并重渲染。
- 右上角按钮：用户视图时点击 → 弹口令面板（模板样式：密码框 + Log in / Cancel，Enter 提交）；登录成功显示 Admin mode: ON（与模板一致的既有文案与样式）。ON 时点击 → 登出回用户视图。
- 初始化时 `state.isAdmin = !!sessionStorage` 令牌，刷新不丢会话。
- 模板里"prototype stand-in"注释更新为真实口令门禁说明。

## 边界（记录于 tech-stack）

共享口令（非个人账号）；无防爆破限速（内网信任，后续可加）；SSO 仍为升级路径。

## 当前实现补充（2026-09-22 核验）

以上为最初规格。当前实现已增加登录滑动窗口限流、7 天令牌有效期、口令变更使会话失效，以及管理员专用的遗留上传门禁。共享口令支持 Unicode。登录、登出和令牌清理与业务写入共用进程内互斥，部署必须保持单 worker。确认/退回后的通知只合并投递结果，不覆盖网络等待期间发生的其他数据变更。
