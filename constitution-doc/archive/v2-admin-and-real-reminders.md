# v2 — 管理员门禁与提醒真实外发

## Charter

解决 v1 的两个已知边界：① Admin 开关人人可点改为服务端强制的管理员口令；② Follow-ups 自动/手动提醒从"仅记日志"升级为邮件 + Teams 真实发送（未配置通道时优雅退回仅日志）。不含：个人账号体系、SSO（升级路径保留）。

## Acceptance

- 未登录管理员口令时：确认/驳回登记、编辑案例、删除案例、保存提醒设置在**服务端**被拒绝（401），前端按钮隐藏只是附加层。
- 口令登录后右上角仍显示 Admin mode: ON，全部管理功能可用；刷新页面会话保持；登出即失效。
- 配置 SMTP 后：到期/逾期提醒真实发出邮件（收件人/抄送/正文与模板一致），日志条目显示投递结果。
- 配置 Teams Webhook 后：提醒消息推送到 webhook；未配置通道显示 skipped 而非报错。
- 既有 9 条 pytest 全部通过（管理端点带令牌），新增认证与投递用例通过。

## Phase-1: 管理员口令门禁

Status: `closed`

Description: SC_ADMIN_PASSWORD + 持久令牌（kv）+ 五个管理端点强制校验；前端口令登录面板与会话保持。

Spec: specs/v2-admin-gate.md

## Phase-2: 提醒真实外发

Status: `closed`

Description: delivery 模块（SMTP 邮件 + Teams webhook），挂接到每日检查与手动提醒，日志记录投递状态，前端日志表加 Delivery 列。

Spec: specs/v2-delivery.md

## Phase-3: 验证与文档

Status: `closed`

Description: pytest 更新与新增；compose/DEPLOY.md/tech-stack 更新（向 IT 索取的参数清单与 Teams 流契约）。2026-09-22 项目级复核完成：请求校验、提醒与审批并发、会话、持久化和日期/页面交互修复；123 项 Python 测试、20 项浏览器回归、Ruff、镜像构建与隔离容器核心流程通过。详情见 [核验记录](../../docs/project-audit-2026-09-22.md)，保留既有功能边界，待用户验收。

Spec: non-spec

## Phase-4: 代码审查加固

Status: `closed`

Description: 外部代码审查 14 项修复。安全：admin token 改带发行时间的记录、7 天过期并在校验时清理（旧裸字符串令牌废弃，需重新登录一次）；登录加进程内限流（连续 5 次失败锁 5 分钟）；前端所有用户数据插值统一 esc()/escapeAttr() 转义。持久化与并发：写操作从全表重写改为按行 upsert / 定点删除（并发粒度 = 单案例行）；每日检查改为先落库、事务外外发、再回填投递结果（消除长事务与失败重发）；init_db 直接用 Engine.begin()，SQLite 连接加 busy timeout 30s。外发：收件人/抄送清洗（兼容分号分隔、丢弃空项与含换行的项）。时区与年份：参考时区经 SC_TIMEZONE 可配（默认 America/New_York），周标签年份随当前年份而非硬编码 2026。前端：四处静默 catch 加全局 toast；401 时提示会话过期；加离线状态横幅；CSV 导出补 UTF-8 BOM。运维：/api/health 轻量端点 + compose healthcheck；.env.example 模板；后台循环异常改用 logging。

Spec: non-spec

## Phase-5: 加固收尾

Status: `closed`

Description: 复查后的 5 项收尾。① 时区一致性：bootstrap 快照携带服务器时区（snapshot.serverTimezone），前端 getNATime 跟随而非硬编码 America/New_York —— SC_TIMEZONE 改非默认值时前后端"今天"判断不再错位。② /api/legacy-upload 加 admin 门禁（此前任何人可注入 18 条随机演示案例）；前端非管理员点击上传区给出提示。③ 写端点进程内互斥（asyncio.Lock）：并发读-改-写不再撞 SUB 编号/整行覆盖；每日检查锁内计算落库、锁外网络外发。④ 提交按钮防双击（等待响应期间禁用，避免第二次 422 误报）。⑤ CSV 导出公式注入防护（= + - @ 或制表/回车开头的非数值单元格加 ' 前缀，纯数值不处理）。

Spec: non-spec

## Phase-6: 二轮审查打磨

Status: `closed`

Description: 第二轮代码审查 5 项。① 登录限流改 15 分钟滑动窗口（存失败时间戳列表而非裸计数器——跨周的口误不再累计触发锁定，办公室 NAT 共享 IP 场景尤甚），并在读取时限时清理窗口外无活动的条目，字典不无界增长。② 管理操作防双击：确认登记 / 驳回 / 删除 / 手动提醒 / 案例保存的按钮在异步请求期间禁用（确认/驳回/删除的第二击此前会撞 422/404 弹红色误报；手动提醒会真发出两封信）。③ 会议议程 .xls 公式注入双保险：单元格样式加 mso-number-format:'\@'，值级与 CSV 同一套 formulaGuard（= + - @ 开头的非数值加 ' 前缀）——Excel 各版本解析顺序不一致，样式单独不保证生效。④ lifespan 退出 cancel 后 await 后台任务，消除 "Task was destroyed but it is still pending!"。⑤ 测试卫生：autouse fixture 在每条用例后清空 _login_failures，限流用例不再要求"必须排在最后"。

Spec: non-spec

## Phase-7: 滚动与缩放适配

Status: `closed`

Description: 窄窗口下的布局与滚动可用性修复，保留原始模板风格。① 宽表格统一局部横滚，支持水平滚轮、Shift＋滚轮、触摸与键盘方向键，普通纵向滚轮继续滚动页面。② 顶栏在 1100px 及以下换行，导航支持滚轮、鼠标拖动及 Tab 显露；保留 Ctrl/Meta＋滚轮缩放输入，清理取消和失焦后的拖动状态。③ 修复 320px 首页溢出、窄屏多零件/任务编辑过窄及提醒配置拥挤，日志表保留可读列宽。④ 按实际页头高度定位登录框和提示，短屏登录框内部可滚动。⑤ 同页排序与提醒展开/收起保留表格横向位置，切换主页面回顶部。2026-09-22 验证：16 项滚动回归、20 项原有前端回归通过；Chromium 64 个页面/宽度组合及 Firefox 两种宽度检查通过。实体设备惯性、帧率及 Safari 尚未验证。详见 [前端滚动核验记录](../../docs/frontend-scroll-audit-2026-09-22.md)，待用户验收。

Spec: non-spec

## Phase-8: 杂项收尾

Status: `closed`

Description: 用户点名的二、三档收尾。① favicon：内联 SVG data-URI（品牌橙 SC 方标），消除每次加载的 /favicon.ico 404。② DEPLOY.md 备份命令改为 WAL 安全做法（容器内 python sqlite3 backup API，在线可执行），替换"直接 cp ./data"的说法。③ compose 加 json-file 日志上限（10m × 3）。④ /api/submissions 按客户端 IP 限流：1 小时滑动窗口最多 10 条成功提交，超出 429（内网防误灌/脚本误循环；校验失败的 422 不计数）。⑤ 母版脱节注记写入 specs/v1-frontend-wiring.md：index.html 为实现与规范实体（含 v2 各轮加固），_template.html 仅作布局参考、不再同步修复。

Spec: non-spec

## Phase-9: 审批结果邮件通知

Status: `closed`

Description: 兑现提交页 "You'll be notified by email once it's approved or returned" 的承诺——管理员确认/退回登记后，向提交人（submitterEmail）发送结果邮件。邮件复用提醒的 SMTP 通道（未配置时记 skipped，不报错），事务纪律与每日提醒一致：先落库、写锁外发送、短事务回填。投递结果持久化在提交单 notify 字段（when/approved/result），审批页 Recently Processed 列表显示通知去向与投递结果；确认邮件带案例深链（`SC_PUBLIC_URL/#case/<SWAT>`），退回邮件正文含退回原因。DEPLOY.md 补充同通道说明。实现：delivery.send_email 抽出通用 SMTP 发送（deliver_email 变薄封装）；logic.decision_email 生成两种信件；确认/驳回端点事务外调用 _notify_submitter 并回填。

Spec: non-spec

## Phase-10: SharePoint Graph 自动建单

Status: `closed`

Description: 用户提交登记时自动向 SharePoint 团队站点的目标 List 建单（Graph app-only：client credentials + Sites.Selected，站点级 write 角色）——建单不等审批确认；审批/决议/编辑不回写。新增 graph 模块：token 获取与进程内缓存（过期前 5 分钟刷新，缓存键随配置走、改配置即生效）、站点按 URL 寻址与 List 按显示名解析 id（均缓存）、字段映射固定并写入 DEPLOY.md 列契约。事务纪律与审批邮件一致：主事务提交后、写锁外网络调用、短事务回填 sub["sharepoint"]（when/result/itemId）；未配置凭据记 skipped，失败记 failed 不阻断提交（配置类错误带提示、外部异常只报类型）。前端 Submit 页 Recent Submissions 与 Approvals 页（待审失败提示 + Recently Processed）显示建单结果。凭据经 SC_GRAPH_TENANT_ID / SC_GRAPH_CLIENT_ID / SC_GRAPH_CLIENT_SECRET / SC_SP_SITE_URL / SC_SP_LIST_NAME 配置，任一空 = 功能停用。2026-09-23 验证：131 项 pytest（新增 8 项：未配置 skipped、字段契约与单次建单、403/400/500 与 token 失败不阻断、确认不重复建单、404 提示）+ Ruff 通过；真实租户联调待凭据填入后进行。待用户验收。

Spec: non-spec

## Phase-11: 邮件与 Teams 消息接入 Graph

Status: `closed`

Description: 与建单共用同一套 Entra 凭据打通外发。邮件：delivery.send_email 通道选择改为 SMTP 优先（sc_smtp_host 配置即用），未配置时若 SC_GRAPH_SENDER + Graph 凭据齐备则走 Graph `POST /users/{sender}/sendMail`（Mail.Send 应用权限，saveToSentItems=false，收件人/抄送复用 clean_addresses 清洗），两者皆空记 skipped；403 给"应用访问策略/发件邮箱"类提示。Teams：**Graph 直发频道消息为优先路径**（用户决策，SC_TEAMS_TEAM_ID + SC_TEAMS_CHANNEL_ID 配齐即启用，纯文本转义后按 html 投递）；微软官方将应用权限直发定位为迁移场景（可能计费）——用户知情取舍，DEPLOY.md 注记限制与回落方式（清空两个 ID 即切回 Workflows/Power Automate webhook，Graph 凭据齐备时 webhook 附带 Bearer）。IT 申请清单含 ChannelMessage.Send。2026-09-23 验证：143 项 pytest（新增 12 项：SMTP 优先级、Graph 兜底、sendMail 载荷与收件人清洗、403/无收件人、Teams 直发优先级、频道消息转义与 403/404 提示、webhook Bearer、全未配置 skipped）+ Ruff 通过；真实外发联调按用户要求暂缓，待 IT 批复、凭据填入后进行。待用户验收。

Spec: non-spec
