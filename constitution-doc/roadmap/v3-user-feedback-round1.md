# v3 — 用户反馈第一轮

## Charter

落实 Sourcing 业务方对提交表单、待办与导出的反馈：9 条口头反馈（2026-09-24 收到）加反馈 PPT《Feedback Sourcing Committee Cockpit_10.09.2026》（文字版存 `~/backups/sourcing-cockpit/feedback-deck-2026-09-10.md`）：简化表单、欧元金额、多区域、议程/纪要 Excel、演示文件上传、待办录入权限、商务字段与门槛、登记截止时间、待办分类。2026-09-24 反馈人答复后，Phase-6 改走个人账号路径（公司邮箱自注册 + 角色），不再排除；不含 SSO（升级路径保留）；SupplyOn 集成（PPT 第 7、8、11 页，用户先去问 IT 有无接口再定）；统计报表与迟定点标记（PPT 第 9、10 页，反馈人自注"仍由 PFS / Sourcing 看板跟踪"）；待办关闭附件与 approve / reject 按钮（PPT 第 4、11 页）已排入 Phase-14。

## Acceptance

- 提交页 Project 可自由输入（如 MBEAL），并提示已用过的项目名；空项目名在前后端都被拒绝（422）。
- Family Case 选 Yes 且 Alignment 选 Yes 即可提交，不再出现证据链接字段；Alignment 选 No 仍被拒绝。
- 待办编辑与手动提醒只填收件邮箱、抄送、通道，不再有 "Reminder to (name)"；未填邮箱的未关闭待办不能保存；系统不再按姓名猜测邮箱。
- 提交时填写的 Case Comments 出现在案例详情、审批页、CSV 与议程导出中。
- 提交页填写 Pc Price CQA、Supplier Price (landed)、Tooling CQA、Supplier Tooling Cost 与 Tooling Payment 后才能提交；Lifetime Spend 折算超过 3 Mio EUR 而 BPG 不可用、或 Level 2 案例 FRA 不可用，前后端都拒绝（422）；可选字段留空可提交，填了就出现在审批页、案例详情与 CSV。
- 管理员在 Dashboard 设置登记截止（会前第几天、几点、时区）后，提交页的可选会议日期随之变化；截止后提交本周日期被服务端拒绝，勾选例外并填理由则接受并在审批页标出。
- 待办编辑只提供八个固定分类（CQA / Volume / Technical / Timing / Supplier strategy / BPG / Saving / Further VAVE），Follow-ups 页可按分类筛选；旧任务上的自由标签仍显示。
- 汇率卡片按财务 OP 记法录入（1 EUR = X 外币），提交按除法折算；旧美元案例一次性换算成欧元并保留原美元金额。
- 页面、导出文件名与标题、案例周号统一为 ISO 周（KW）；2026-09-30 显示 2026-KW40。
- 提交时可上传 PPT / PDF / Excel / Word（单个 ≤ 100 MB）到 SharePoint 文档库；案例详情列出文件，所有人可下载。
- 用公司邮箱自注册账号；新账号默认普通用户，Sourcing 管理员在页面上提升为 NPI 经理或管理员；NPI 经理能审批、编辑、删除案例和发提醒，不能改系统设置和账号；共享管理员口令下线。
- 问题 4（2026-09-24 答复）：Excel 导出与驾驶舱在线查看同时保留——议程 / 纪要按 MM 模板导出（Phase-4），大家也可直接打开驾驶舱链接看登记与议程。
- 问题 7（2026-09-24 答复）：登记截止用默认值——会前周一 23:59、服务器时区；管理员仍可在 Dashboard 调整（Phase-8）。

- 领导反馈（2026-10-12）：新案例按"年份 + 周"从 1 号编起，删除或改走案例后该周补成连续号；截止后只有 Sourcing admin 能补登记进本周（普通用户与 Manager 看不到例外选项、服务端拒绝且不提例外）；编辑页一键从 Committee Discussion 列出编号任务（负责人、日期能识别的先填好），勾选后加入待办，邮箱由人填；详情页纪要保留换行。

- 同事反馈（2026-10-20）：提交页与编辑页的零件号按表格一行一个零件号录入，列顺序与委员会周会 Excel 一致；从委员会 Excel 连同表头复制多行粘贴进表格，零件行字段自动对上，其他列被跳过；价格格子里的单位与第二种货币被去掉，`0,0865` 解析为 0.0865，`39,157` 这类有歧义的值和 `tbd` 标红不入库，零件号的前导零保留；Tab / Enter 可以在格子之间移动；Project / Sourcing Type / Recommended Supplier 能一键填到所有行；缺项与重复零件号在对应格子上标红。

- 领导反馈（2026-09-29）：提交页 Peak Year Spend / Lifetime Spend 只在案例级各填一个 bundle 金额（必填、须大于 0），零件行不再填；Project / Sourcing Type / Recommended Supplier 按零件行填写，案例级显示去重汇总；议程 / 纪要 Excel 的 Type / Project / Supplier 列按零件行、Peak Year Spend / LT Spend 列按案例合并；上传的演示文件在系统里改名为 `YYYY.MM.DD 项目 零件描述 零件号, 供应商.ext`，原文件名保留可见；角色 "NPI manager" 页面上显示为 "Manager"。

## Phase-1: 表单简化（反馈第一批）

Status: `closed`

Description: 反馈 #3 项目名自由输入、#4 去掉 Family Alignment 证据、#6 Case Comments 进入导出、#8 提醒收件人字段简化并停止猜测邮箱。2026-09-24 验证：143 项 pytest（新增：项目必填、Alignment 完成即可登记且不存证据、不按姓名猜邮箱）、21 项前端回归（新增 1 项）、16 项滚动回归、Ruff 通过；隔离实例（临时库）端到端走通提交 → 审批 → 编辑待办（缺邮箱被拦、补填后保存）→ Follow-ups 显示与手动提醒面板 → 议程 .xls 与 CSV 含 Case Comments 列。旧记录里已有的证据链接仍在审批页显示。

Spec: non-spec

## Phase-2: 欧元金额与汇率折算

Status: `closed`

Description: 反馈 #1。采购员按本币（CNY / USD / EUR）填写，按管理员维护的汇率折算为欧元，保存原币、欧元与所用汇率。已完成机制：Dashboard 汇率卡片（管理员维护口径与 USD/CNY 汇率，Decimal 精确保存）；提交时逐行折算、整欧元四舍五入，记录保存原币金额与汇率快照；改汇率只影响新提交；编辑按原币填写、沿用提交时汇率；旧数据（无币种信息）保持美元显示。2026-09-24 反馈人答复：用财务 OP 汇率表，随时可改，旧美元案例统一换算成欧元 —— 已在 Phase-12 落地（OP 记法汇率 + `python -m app.migrations usd-to-eur` 换算命令）。2026-09-24 验证：新增 11 项 pytest（折算取整、汇率设置门禁与校验、EUR 默认、缺汇率拦截、USD 折算与汇率快照、改汇率不影响旧记录、编辑沿用原汇率、旧数据不折算）与 1 项前端回归；隔离实例端到端：设汇率 → USD 两零件提交（预览 $278,000 ≈ €255,760，存 €255,760）→ 确认 → 改汇率 0.95 后编辑仍按 0.92 → CSV 含 Spend Currency 列 → 旧案例仍显示美元。

Spec: non-spec

## Phase-3: 多区域

Status: `closed`

Description: 反馈 #2。区域可多选（如 EU + NA），筛选按包含匹配，Dashboard 各区域分别计数。区域存为固定顺序文本 "AP + EU + NA"：旧单区域数据无需迁移，SharePoint 单行文本列原样写入；提交至少选一个区域。2026-09-24 验证：新增 pytest（规范化、非法值、提交到案例全流程）与 1 项前端回归（筛选与计数）；隔离实例端到端：EU + NA 提交 → 确认 → 按 NA 筛选可见 → Dashboard NA/EU 各计一次并显示说明。2026-09-24 反馈人确认：各区域各算一次，保持现状。

Spec: non-spec

## Phase-4: 议程与会议纪要 Excel

Status: `closed`

Description: 反馈 #7。分别导出 Agenda 与 Meeting Minutes 两个真 .xlsx（反馈 PPT 第 9 页确认 MM = Meeting Minutes，并提出另一种做法："只发链接，大家在线看登记与议程"）。已完成底座：后端 `exports.py` 用 openpyxl 生成（新依赖，见 tech-stack），`GET /api/exports/{agenda|minutes}?week=N`；Agenda 一案例一行、含商务字段、不含决议；Minutes 两个工作表——"Minutes" 加决议 / 讨论 / 行动状态 / 待办计数，"Actions" 一待办一行（任务、分类、负责人、到期、状态、提醒邮箱）；Dashboard 周视图两个按钮；以 "=" 开头的文本强制按文本存，Excel 不会当公式。2026-09-24 傍晚反馈人的 MM 模板到了（`KW39 23.09.2026_SBS Sourcing Alignment Committee_MM.xlsx`），版式已按它重做：一个零件一行、案例级单元格跨行合并，列序 # / KW / Meeting Date / Region / Type / Project / Commodity / Parent PF Code / SWAT ID / Part Description / PN / Supplier / Presenter / Decision Level（L2 写法）/ Peak & LT Spend / Currency / Comment /（纪要多 Sourcing Decision、Notes-Task-Resp-Due）/ CQA PC Price / Rec. Supplier Landed / Average & LT Volume / 三个节省额 Excel 公式（沿用模板算法：(推荐价 − CQA) × 产量，负数 = 低于 CQA）/ CQA & Rec. Supplier Tooling / Tooling Payment / BPG / FRA / Late Registration /（纪要多 Action Status），金额写数字带欧元格式；议程蓝表头、纪要绿表头与标签色区分。随之数据模型改动：件价、模具费与新增的年均 / 生命周期产量按零件行填写（提交页与编辑页每行输入，单零件同时放顶层，多零件顶层置 None、详情页按行一张表；CSV 按行用 " | " 拼接）。Database 页新增 "Export Agenda / Export Meeting Minutes" 两个按钮按当前筛选结果导出（`POST /api/exports/{kind}` 传行 id），Export CSV 保留；Dashboard 周视图两个按钮同一版式。周号已在 Phase-13 改为 ISO 周（KW），议程 / 纪要的 KW 列、标题与文件名随之显示 "2026-KW40"。验证：pytest 252（导出 10 项：模板列序与合并、公式文本、迟登记列、按 id 导出与上限、空周；商务 3 项：每行必填、多零件按行存与提升）、前端回归 29（新增 Database 两按钮 POST 当前筛选 id；多零件详情表与编辑预填）、滚动回归 16、ruff；隔离实例真实提交两零件 USD 案例 → 详情按行显示折算价与原币 → 记录决议与待办 → 三种导出读回核对合并区、公式、Notes 列。LibreOffice 在本机启动超时，公式值由 Excel 打开时计算（公式字符串已由测试固定）。2026-09-28 用户对照反馈人原版模板复核后修正：金额列按案例币种带货币符号（`#,##0 [$€-407]`，旧美元案例 `[$$-409]`）、会议日期与到期日写成真日期单元格（yyyy-mm-dd）、Sourcing Decision 按模板文案（Approved / Approved with conditions / Rejected / Pending）、说明行改为 ISO 周；pytest 323。

Spec: non-spec

## Phase-5: Sourcing 演示文件上传

Status: `closed`

Description: 反馈 #5。提交时可选拖拽上传演示文件。2026-09-24 反馈人答复：存 SharePoint 文档库（与建单共用 Graph 凭据；按微软 Selected 权限文档，站点级 write 授权覆盖该站点的文档库，不用另外申请）；格式 PPT / PPTX、PDF、XLS / XLSX、DOC / DOCX；单个 ≤ 100 MB；所有能打开驾驶舱的人可下载。待办关闭附件（PPT 第 4 页）沿用同一存放，本 Phase 不做。实现：`app/files.py`（文件名清洗与类型白名单、流式接收边收边数超 100 MB 即 413、存放、下载、删除）+ `graph.py` 文档库函数（按站点取默认库或 `SC_SP_LIBRARY_NAME`，`SC_SP_FOLDER/<案例号>` 文件夹，createUploadSession 10 MiB 分块、块上不带 Authorization，同名自动改名；下载取 `@microsoft.graph.downloadUrl` 302 跳转，看的人不需要 SharePoint 权限）；SharePoint 未配置时存服务器本地 `data/uploads/`，每个文件记录自己的存放位置。接口：`POST /api/submissions/{subId}/files`（提交响应里的一次性 `uploadKey`，只存哈希、只在待确认期间有效，或管理员）、`POST /api/cases/{rowId}/files` 与 `DELETE /api/cases/{rowId}/files/{fileId}`（管理员；删除时原提交单上的同一条一起去掉）、`GET /api/files/{fileId}`（所有人）；确认登记时文件随提交单进案例；每条记录最多 10 个。前端：提交页 "Sourcing Presentation Files" 拖拽 / 选择区（浏览器先查类型与大小），提交成功后逐个上传并在横幅显示进度与结果（上传失败不影响已提交的登记）；审批页列出文件；案例页 "Sourcing Presentation Files" 卡片（所有人下载，管理员 Add files / Remove）。顺带修掉两处部署老问题（v2 Phase-10 起）：docker-compose 没把 `SC_GRAPH_*` / `SC_SP_*` / Teams ID 传进容器（容器读不到 .env 文件，填了不生效）；代码认的 Teams 配置名与文档的 `SC_TEAMS_TEAM_ID` / `SC_TEAMS_CHANNEL_ID` 不一致——新增测试保证 .env.example 的每一项都传进容器、都被程序读到。另：模具费与摊销总额改为显示 2 位小数（页面与导出，存储仍 4 位）。验证：pytest 299（文件 18 项：文件名清洗与拒绝、本地上传下载、uploadKey 必需且只存哈希、类型 / 空文件 / 超限 / 数量上限且不留临时文件、确认后进案例、确认后 key 失效、案例页加删、删除连提交单一起、编辑不清文件、SharePoint 三块分块的 Content-Range 与无授权头、文件夹已存在走 409、下载 302、上传会话 403 → 502 且不落记录；配置一致性 3 项）、前端回归 31（新增：排队时拒 .exe、提交后带 key 上传、横幅 "1 file attached"、案例页下载链接、管理员删除、非管理员只能下载）、滚动回归 16、ruff、`docker compose config` 通过；隔离实例（演示库副本、本地存放）真实浏览器：提交带 3 MB pptx + pdf → 横幅 "2 files attached" → 审批页列出 → 确认 → 案例页下载字节数一致、文件名正确 → 管理员加 docx、删掉；curl 101 MB 两种方式（声明长度 / 分块流式）都 413 且不留临时文件。SharePoint 真实联调等 IT 凭据。2026-09-28 用户决定：**先按本地存放上线**（方案 1，零 IT 依赖），SharePoint 建单与文档库作为后续可选项，凭据到位后填 .env 即切换。

Spec: non-spec

## Phase-6: 待办录入权限（个人账号）

Status: `closed`

Description: 反馈 #9。2026-09-24 反馈人答复：每人一个账号，用公司邮箱自注册（邮箱 + 自设密码，只允许公司域名）；新账号默认普通用户，由 Sourcing 管理员在页面上提升角色。角色：普通用户（提交、查看）；NPI 经理（另可审批登记、编辑与删除案例、记录决议与待办、发送提醒、管理案例文件；主要职责追踪进度）；Sourcing 管理员（另可改汇率、登记截止、提醒设置，管理账号）。共享管理员口令取消。用户 2026-09-24 决定：zf.com 与 zf-lifetec.com 都允许；首个管理员先用 demo 邮箱（`.env` 的 `SC_BOOTSTRAP_ADMIN_EMAIL` / `SC_BOOTSTRAP_ADMIN_PASSWORD`，启动时没有可用管理员才建）；SMTP 没到位前忘记密码由管理员在 Accounts 页重置为一次性临时密码，本人登录后必须先改。实现：`app/accounts.py`（scrypt 密码哈希、邮箱域名与密码规则 ≥ 10 位、角色 user < npi_manager < admin）；`users` 表；会话只存令牌 SHA-256、7 天过期，请求头 `X-Session-Token`；`/api/auth/register|login|logout|password`、`/api/users`（列表 / 改角色与停用、至少留一个可用管理员 / 重置密码）；登录失败锁定沿用，注册每来源每小时 10 个；提交必须登录且提交人取自账号；审批 / 编辑 / 删除 / 提醒 / 案例文件 = NPI 经理及以上，汇率 / 截止 / 提醒设置 / 账号 / legacy-upload = 管理员，全部服务端强制。前端：右上角账号面板（登录 / 注册 / 改密码 / 菜单，临时密码登录后强制改密码且不能关掉）；提交页未登录显示登录门槛、已登录时姓名 / 邮箱只读取自账号；Accounts 页（仅管理员：角色下拉、停用 / 启用、Reset password 一次性显示临时密码，自己的账号让别的管理员改）；提醒按钮对普通用户显示 "Send reminder: NPI manager"。DEPLOY.md 安全说明、README、.env.example、docker-compose 同步；`SC_ADMIN_PASSWORD` 废弃。验证（2026-09-28）：pytest 312（账号 13 项：哈希与盐、注册规则五种、两个域名与大小写与重复 409、注册限流、角色矩阵、至少留一个管理员、停用踢会话、重置密码强制改、bootstrap 管理员；会话持久化）、前端回归 34（新增：提交页登录门槛与注册后只读提交人、Accounts 页改角色 / 停用 / 重置密码只显示一次、临时密码强制改密码、登录失败 / 取消登录 / 令牌过期改到新接口、存储被禁时令牌留内存且改密码不擦草稿）、滚动回归 16、ruff；隔离实例（演示库副本）真实浏览器：gmail 注册被拒 → zf-lifetec 注册即登录 → 只读提交人提交 SUB → 普通用户审批页无按钮 → 管理员 Accounts 提升 NPI 经理并重置密码（自降级被拒）→ 旧密码失效、临时密码登录被要求改密码且服务端 403 → 改完成为 NPI 经理确认登记、看不到 Accounts 与汇率保存。8062 演示服务已重启到本代码（bootstrap 管理员 admin@zf.com）。

Spec: non-spec

## Phase-14: 待办反馈与关闭审批

Status: `closed`

Description: 反馈 PPT 第 4、11 页。待办关闭现在靠邮件跟进：负责人汇报进展、附上邮件凭证，由 Sourcing admin 或采购经理确认。用户 2026-09-28 批准范围：任何登录用户可对开放待办提交反馈（文字 + 可选附件，附件沿用 Phase-5 存放与 100 MB 限制，类型另加 Outlook 邮件 .msg / .eml）；NPI 经理及以上 approve（待办置 Closed，记录谁、何时、凭哪条反馈；若是最后一条开放待办，须同时给出最终文件链接，与编辑页规则一致）或 reject（必须填进一步要求，待办保持开放）；反馈提交时邮件通知全部 NPI 经理与管理员，approve / reject 结果邮件给待办提醒收件人并抄送反馈人（复用 SMTP / Graph 通道，未配置记 skipped）；案例详情与 Follow-ups 页显示反馈与审批历史。SupplyOn 集成仍等 IT 答复。实现：`app/feedback.py`（反馈记录、approve / reject 规则、两封通知信、收件人）；数据挂在待办上 `feedback[]`（{id, when, by, byEmail, text, files, status pending|approved|rejected, notify, decision{when, by, remark, notify}}），approve 后待办带 `closure{when, by, feedbackId}`；接口 `POST /api/tasks/{id}/feedback`（登录）、`POST …/feedback/{fbId}/files`（反馈人本人或 NPI 经理、待审期间）、`POST …/feedback/{fbId}/decision`（NPI 经理及以上，body decision / remark / finalDocLink）；编辑页保存不会擦掉服务端维护的 feedback / closure；附件白名单 `files.FEEDBACK_EXTENSIONS`，`/api/files/{id}` 同样能下载；通知与审批邮件一样先落库、锁外外发、短事务回填结果。前端：待办下的 "Feedback & closure approval" 区块（案例详情常显；Follow-ups 页每行 "Feedback (n to approve)" 按钮展开），汇报表单（文字 + 文件选择，前端先查类型与大小）、经理的 Approve / Reject 面板（最后一条开放待办时多出最终文件链接栏），Follow-ups 计数行显示 "n feedback to approve"，登出清掉打开的面板。验证（2026-09-28）：pytest 322（新增 10 项：登录 / 空文本 / 未知待办、已关闭待办拒收与通知全部审批人、无审批人记 skipped、附件类型 / 权限 / 待审后禁加 / 下载 / 不留临时文件、approve 关闭待办并邮件负责人抄送反馈人、reject 须备注且待办保持开放、最后一条开放待办要最终链接且被拒的审批不落库、已有最终链接直接关闭、编辑页保存保留反馈与关闭记录、信件文案与收件人）、前端回归 36（新增 2 项：用户汇报 + .exe 拒收 + .msg 上传带令牌 + 待审条目与计数 + 未登录只读；经理拒绝须备注、批准最后一条待办带最终链接、关闭后无汇报入口）、滚动回归 16、ruff；隔离实例（演示库副本）真实浏览器：注册用户在 Follow-ups 页汇报并附 4 KB .msg → 下载字节一致、审批人通知 skipped（无 SMTP）→ 管理员看到 "1 feedback to approve"，不填备注被拦、填后 reject → 再汇报一条 → 批准最后一条开放待办被服务端要求最终链接 → 填链接批准 → 待办 Closed、tracker 消失、案例页显示完整历史与关闭记录，刷新后仍在。截图 `~/backups/sourcing-cockpit/e2e-screenshots-2026-09-28-phase14/`。

Spec: non-spec

## Phase-7: 商务字段与登记门槛

Status: `closed`

Description: 反馈 PPT 第 2、3 页。提交表单新增必填商务字段（Pc Price CQA、Supplier Price landed、Tooling CQA、Supplier Tooling Cost、Tooling Payment Lumpsum / MPC）与两条门槛（Lifetime Spend > 3 Mio EUR 须有 BPG；Level 2 须有 FRA），以及 8 项可选字段（低于 CQA 否则填理由、战略/认可供应商、LTA、FOT / PPAP 交期、摊销总额与件数、USMCA、年产能 / 生命周期产能）。金额沿用 Phase-2 机制：按提交币种填写、按当时汇率折算欧元并保存原币。2026-09-24 用户确认：不单独加 Bundle ID，导出的 "SWAT ID / Bundle ID" 列只写 SWAT ID；导出的 Commodity 列填 Cluster；节省额正负号照模板（正 = 高于 CQA）。仍待定：新字段是否也要写入 SharePoint 列（目前不写）。2026-09-24 验证：新增 15 项 pytest（十进制解析与空值、4 位小数折算、四个必填价格与 Tooling Payment、BPG 按折算后欧元判定且 3 Mio 整不触发、FRA 仅 Level 2、低于 CQA 答 No 须填理由、原币与汇率快照、确认带入案例、编辑按案例汇率重算且不带字段时原值不动）与 1 项前端回归（必填拦截、BPG 提示变红与 No 拦截、FRA、理由栏显隐、载荷字段、详情显示与编辑预填、旧案例说明）；隔离实例端到端：USD 提交 → 审批页显示 €9.66 ($10.50 entered) 与摊销 €0.23/pc → 确认 → 详情 → 编辑件价 20 USD 存 €18.40。

Spec: non-spec

## Phase-8: 登记截止时间与例外登记

Status: `closed`

Description: 反馈 PPT 第 2 页。截止规则改为管理员可配置（会前第几天、几点、时区，默认沿用模板的周一 23:59 服务器时区），服务端强制：截止后提交本周会议日期被拒；提交人可勾选"申请例外"并填理由，登记进入审批队列时带"Late registration"标记，由 Sourcing 管理员确认登记即视为批准例外。截止的星期与时间：2026-09-24 反馈人答复用默认值（周一 23:59、服务器时区）。2026-09-24 验证：新增 12 项 pytest（默认周一 23:59 服务器时区、自定义时区、截止那一分钟仍开放、跨时区比较、截止后 422 且文案带规则、下周仍开放、例外无理由拦截、例外带理由接受并存 deadline、开放期间例外标记忽略、确认带入案例、管理员设置生效并下发、非法值 422）与 1 项前端回归（默认无例外入口、规则文案、勾选后出现已截止的周三、无理由拦截、载荷、审批页标记、Dashboard 卡片保存）；测试时钟冻结在 2026-09-24（conftest），用例不随日历失效。隔离实例端到端：设"会前 6 天 00:01 Asia/Shanghai" → 提交页最早只给 10/07 → 勾例外选 09/30 填理由 → 审批页黄色标记 → 确认后案例详情记录例外。

Spec: non-spec

## Phase-9: 待办固定分类

Status: `closed`

Description: 反馈 PPT 第 4 页。待办的标签改为八个固定分类（CQA / Volume / Technical / Timing / Supplier strategy / BPG / Saving / Further VAVE），编辑页用多选框，Follow-ups 页按分类筛选；旧任务上的自由标签保留显示。服务端不改（tags 仍是文本列表，旧数据无需迁移），`logic.ACTION_CATEGORIES` 只作常量记录。2026-09-24 验证：1 项前端回归（八个多选框 + 旧标签 "Cost (legacy)" 预勾、保存载荷、Follow-ups 筛选列出全部分类并按分类过滤）；隔离实例端到端：记录决议 → 加待办勾 Supplier strategy + Saving → 保存 → Follow-ups 按 Saving 筛出。

Spec: non-spec

## Phase-10: 输入加固与提醒权限

Status: `closed`

Description: 2026-09-23 全方位扫描发现、用户 2026-09-24 说"继续"后落实的两处隐患：手动提醒接口 `POST /api/reminders/manual` 改为管理员专用（真实外发不能匿名调用；Follow-ups 页非管理员只看到 "Send reminder: Admin mode"），请求字段加长度上限（短字段 500、长文本 5000、零件行 50、待办 100、分类 20）。顺带删除前端无人调用的 `kpi()`。2026-09-24 验证：新增 10 项 pytest（各上限的临界值、超限 422 文案可读、匿名提醒 401）与 1 项前端回归；滚动回归里的提醒面板用例改为管理员态。

Spec: non-spec

## Phase-11: 复测修复与 Database 汇报人列

Status: `closed`

Description: 2026-09-24 傍晚全量复测（237 pytest、28 前端回归、16 滚动回归、隔离实例 45 个 API 探针、49 项浏览器端到端）发现的 6 处服务端漏洞，用户批准后修复：提交必须带会议日期且为周三（空日期可绕过登记截止）；未关闭待办无收件邮箱服务端拒绝；案例编辑区域不能为空；案例编辑对明确答 No 的 BPG / FRA / Below CQA 门槛拒绝（留空放行，旧案例仍可编辑）；cc / alwaysCc 加 500 上限；Follow-ups 提醒面板 "simulated" 过期文案改正。顺带：Database 表增加 Presenter 列（用户 2026-09-24 提出；CSV 已有该列）。验证：新增 9 项 pytest（三处抄送上限、会议日期留空与非周三 422、编辑空区域与无邮箱待办 422 且已关闭待办不需邮箱、编辑 BPG / FRA / Below CQA 明确答 No 被拒且留空放行、被拒的编辑不落库、旧案例仍可编辑），pytest 246、ruff、前端回归 28、滚动回归 16 全过。

Spec: non-spec

## Phase-12: OP 记法汇率与旧美元案例换算

Status: `closed`

Description: 反馈人答复问题 1 的落地。汇率卡片改按财务 OP 表的记法录入（1 EUR = X 外币，OP 2025 plan rates 2026：USD 1.17、CNY 8.30），系统内部按除法折算，避免倒数取 6 位小数的误差；一次性迁移脚本把没有 `spendCurrency` 的旧案例（含零件行与提交单）按 USD 汇率换算成欧元，保留原美元金额为 `*Entered` 并记录汇率快照；DEPLOY.md 的 SharePoint 金额列契约同步。实现：汇率表存 `perEur`（接口 `PUT /api/fx-settings` 的请求体同名；没刷新的旧页面仍发 `rates` 时 422 提示刷新，不会把汇率清空；库里早期存的倒数读出时换成 OP 记法取 4 位小数）；折算规则 `logic.Fx`（新记录快照 `fx.perEur` 做除法，v3 早期记录的 `fx.rate` 仍按乘法读）；换算命令 `python -m app.migrations usd-to-eur`（默认只预览，`--apply` 写库，汇率与口径默认取 Dashboard，可用 `--per-eur` / `--basis` 覆盖；放在 `app/` 里以便容器内运行），换算过的记录带 `fx.convertedAt`，编辑页说明汇率来自换算；DEPLOY.md 新增换算步骤。验证：pytest 264（新增：除法折算与取整、两种快照记法、早期汇率表读出换算、旧记法请求被拒且不清表、单零件 / 多零件 / 件价与摊销 / 无 partNumbers 的提交单换算、已是欧元不动、预览不写库、缺汇率退出码 2、按 Dashboard 汇率换算后重跑为零且编辑仍按美元折算）、前端回归 30（新增汇率卡片 OP 记法录入保存与提交页除法预览；换算案例的汇率说明；早期快照照旧显示）、滚动回归 16、ruff；隔离实例（演示库副本）：旧记法 PUT 422 → 录入 1.17 / 8.30 → 预览 59 条案例行 + 3 条提交单 → 换算 → 重跑 0 条 → 详情 "€3,589,744 ($4,200,000 entered)"、编辑页按美元预填 → 提交页 $1,170,000 ≈ €1,000,000 → 议程导出 Currency 列为 EUR。演示服务 8062 的库尚未换算，等用户决定。

Spec: non-spec

## Phase-13: 周号改 ISO 周（KW）

Status: `closed`

Description: 反馈人答复问题 3 的落地。前端 `dateToWeekNum` / `weekDate` / `wk` 改 ISO 周算法，标签改 "2026-KW40"；schemas 里的 `meetingWeekNum` 同步；导出文件名与标题随之；一次性迁移把已存案例与提交单的 `weekNum` 按其会议日期重算（没有日期的旧演示数据按 2026 年整体 +1）；跨年周按 ISO 规则归属。实现：前端新增 `isoWeekYear`（会议日期选项按 ISO 周年份标注，如 2025-12-31 → 2026-KW01），`weekDate` 返回该 ISO 周的周三；服务端 `logic.iso_week_of_record`（优先 meetingDateISO，其次 meetingDateLabel，都没有则 +1、上限 53）；迁移在服务启动时自动做一次（`service._migrate_iso_weeks`，kv 标记 `week_numbering`，索引列 week_num 一起改；新库装载演示数据后同样换算），不需要手动命令。已知边界不变：周号不带年份，标签年份跟随当前年（跨年周标签歧义，v2 已评估不做）；"legacy upload" 模拟注入仍落在第 34 周。验证：pytest 278（新增 14 项：五个日期的 ISO 周含 53 周与跨年、KW 标签、记录换算规则、新库演示数据 +1 且重启不再加、旧库启动换算含索引列与提交单、确认登记落在 KW40 且导出文件名 2026-KW40）、前端回归 30（三个时区下会议日期 KW 标签、2026-KW53 / 2027-KW01、`weekDate(40)` = Sep 30）、滚动回归 16、ruff；隔离实例（演示库副本）重启：59 条案例行全部 +1（有日期的 SWAT-9900 按 10/07 算为 KW41），再重启不变；提交单按日期重算；首页 / Database / 周筛选 / Dashboard 周选择 / 提交页 / 详情与时间线均显示 KW；纪要导出文件名 2026-KW41。

Spec: non-spec

## Phase-15: bundle 金额、零件行字段与文件重命名

Status: `closed`

Description: 领导（RB sourcing admin）2026-09-29 看演示后的四条要求，用户同日逐条确认。(1) Peak Year Spend 与 Lifetime Spend 从零件行上移到案例级，各填一个 bundle 金额并改为必填（buyer 不用按单个零件号拆分）；(2) Project、Sourcing Type、Recommended Supplier 下到零件行（一个 bundle 可混不同项目、GCS / New、不同供应商），案例级自动去重汇总，同一零件号按区域定给不同供应商时在供应商栏自由文本写明；(3) 上传的演示文件按领导例子改名 `2026.09.30 MBEAL Spool PNxxx, XLX`（日期 项目 零件描述 零件号, 供应商），bundle 案例项目 / 供应商去重用 "+" 连接、零件取第一个并标 "+N"，原文件名保留可查；(4) 角色 "NPI manager" 显示名改为 "Manager"（内部代号不变，账号无需迁移），采购经理 carrie.wang 用该角色、领导本人用 Sourcing admin，四位区域联系人只是建账号名单，不做按区域指派，CLS 不加区域；FRA 旁批注 "case" 指按案例填，现状已是。旧案例不迁移：案例级金额本来就是各行之和，零件行上的旧金额不再显示；旧多零件案例的 Excel 行级三列回退到案例级值。实现：`SubmissionIn` / `CaseEditIn` 带案例级 `peakYearSpend` / `lifetimeSpend`（编辑不带时原值不动），`PartNumberIn` 带 `project` / `sourcingType` / `recommendedSupplier`（行上留空沿用请求的案例级值，`logic.bundle_rows`），案例级三字段由 `logic.bundle_summary` 去重汇总；`logic.convert_spend` 改为折算 bundle 金额、零件行只折算件价（旧记录换算走 `_convert_legacy_rows`）；`exports.columns` 的 Type / Project / Supplier 改行级（行上没有回退案例级）、Peak Year / LT Spend 改案例级合并；`files.bundle_file_name` 生成文件名（日期取服务器时区 `SC_TIMEZONE` 的当天，上线前把它设成 Europe/Berlin 或 Asia/Shanghai），记录新增 `originalName`，案例页显示 "uploaded as …"，待办反馈附件不改名；`accounts.ROLE_LABELS` 的 npi_manager 显示 "Manager"。前端：提交页零件行带 Project（datalist）/ Sourcing Type / Recommended Supplier，案例级三个字段移除，Aggregate 行改成两个 bundle 金额输入（欧元预览与 BPG 提示跟随），审批页 / 详情页零件表改列，编辑页同样按行 + bundle 金额，CSV 的零件明细列改写项目 / 类型 / 供应商。验证（2026-09-29）：pytest 326（新增 4 项：金额非法值在提交与编辑两处都拒、旧客户端行级金额被忽略不 422、bundle 金额必填且行不带金额、三字段按行 + 汇总 + 留空回退 + 两边都空 422 + 编辑改行汇总跟着变 + 单零件顶层；Excel 三列按行不合并、两金额列合并；文件改名与 originalName、SharePoint 路径用新名；BPG 门槛改读 bundle 金额）、前端回归 37（新增 1 项：两行零件不同项目 / 类型 / 供应商 + 缺 bundle 金额拦截 + 预览与 BPG 提示 + 载荷；详情表与 "uploaded as"；编辑页按行改供应商 / 类型与 bundle 金额的 PUT 载荷）、滚动回归 16、ruff；隔离实例（演示库副本，8063）真实流程：缺金额 422 → 行缺供应商 422 → 美元提交两行 bundle（578,000 / 3,373,000 USD → €494,017 / €2,882,906，行无金额，汇总 "MBEAL, ACR8" / "New, GCS"）→ 上传 `Präsentation1 (final)(2).pptx` 存为 `2026.09.28 MBEAL+ACR8 ECU Housing, WMS R003B136A+1, Ningbo Deke+Kimball (EU) _ Deke (AP).pptx` → 确认 → 案例页再传 PDF 同规则 → 只改决议金额不动、改行供应商汇总变 "Ningbo Deke"、改 bundle 金额按 1.17 重算 → 议程导出行级 Type / Project / Supplier、金额合并只在首行。截图 `~/backups/sourcing-cockpit/e2e-screenshots-2026-09-29-phase15/`，代码包 `after-phase15-20260929.tar.gz`。8062 已重启到 Phase-15 代码。补充（2026-09-29 部署后领导反馈导出币种列是 USD）：演示种子 `seed.json` 一次性换算成欧元（OP 1.17，带 fx 快照），Legacy Excel Upload 生成的演示批次直接标 EUR，新装的库导出不再出现 USD；整库换算的测试改为自己放旧记录。同日部署收尾：仓库新增 `windows-portable/`（免安装 Python 3.12.10 + 同版本 wheel）与 `start.bat`，`SC_PORT` 同时决定 start.bat 端口与 docker-compose 宿主机端口。

Spec: non-spec

## Phase-16: 邮箱免密登录

Status: `closed`

Description: 领导 2026-09-29 试用后不想要密码；用户同日定：只有 Sourcing admin 用密码登录，其他人用公司邮箱注册（只填姓名 + 邮箱）、凭邮箱直接登录，权限仍由管理员在 Accounts 页按人设置。风险已向用户说明（内网里任何人可冒用他人邮箱，Manager 也免密），用户拍板按此做。实现：注册不收密码、账号不存哈希；登录只看邮箱，账号角色为 admin 时要求密码（未带时 401 "Password required."，前端据此展开密码框）；改密码与重置密码只对 admin 账号；提升为 admin 时服务端生成临时密码随响应返回一次并置 mustChangePassword，降级时清除该标记；`public_user` 增加 `hasPassword`。前端：登录面板只有邮箱，密码框按需展开；注册面板去掉密码；账号菜单只有 admin 有 "Change password"；Accounts 页 Reset password 只在 admin 行，提升为 admin 时显示临时密码提示。验证（2026-09-29）：pytest 328（账号用例重写：注册规则、邮箱登录 / 未注册 401、管理员密码规则与登录、提升发临时密码且立即要密码、重置只对 admin、降级回邮箱登录）、前端回归 37（登录面板按需展开密码框、邮箱直登、注册无密码、提升 admin 显示临时密码）、滚动回归 16、ruff。

Spec: non-spec

## Phase-17: 周会 Excel 导入（历史数据）

Status: `closed`

Description: 领导 2026-09-30 试用后反馈首页 "Legacy Excel Upload" 不好用（它只灌随机演示数据），要求做成能导入以往每周会议 Excel、把示例数据全部换成真实历史。用户同日登录 SharePoint 文档库（SBS BU Sourcing Alignment）让我拉取了 2025-09 至 2026-09 的 64 份周文件（本机备份 `~/backups/sourcing-cockpit/sharepoint-weekly-2026-09-30/`），模板一年多来列结构一致。实现：`app/excel_import.py`（表头按去空格标点后的前缀匹配；合并单元格展开并区分"自己的值 / 合并填充"，'#' 有自己值的行是案例起点；零件按行，行上有自己的项目 / 类型 / 供应商就用行的；金额文本 "439K Euro"、"2,5Mio Euro⏎2.7 Mio USD"、"60,000 Euro" 解析成欧元，只有 USD / RMB 时按 Dashboard 汇率折算并记警告；决议文案按关键词归类到四种决议、原文存 `decisionText`；Type / Level / Region 归一；SWAT 格子里 bundle 号做案例号、SWAT 数字号存零件行 `sourcingId`；会议日期与 KW 从文件名取，KW 与日期不一致时取那周的周三；案例带 `source{kind:excel,file,row,importedAt,importedBy}`）；接口 `POST /api/import/excel?name=&commit=&meetingDate=&sourceUrl=`（管理员；请求体为文件字节；commit=false 只预览，commit=true 先删同一年同一周之前导入的再插入）；命令行 `python -m app.migrations import-excel <文件或文件夹>… [--apply] [--source-url]`（文件名猜不出日期时用所在文件夹名）；`/api/legacy-upload` 与 `logic.generate_batch` 随机演示生成器删除；从 Excel 导入的案例编辑时不强求演示文稿链接（`validate_case_edit(imported=True)`）。前端：首页卡片改为导入队列（只有 Sourcing admin 可见）：多选或拖入 .xlsx → 每份先预览（周、案例数、零件行数、警告、会替换几条）→ 缺日期的文件出现日期框 → 勾选后 "Import N selected files" 顺序导入 → 结果条；可选填该周的 SharePoint 文件夹链接作为已决议案例的演示文稿链接；用户 2026-09-30 补充要求"历史文件直接存在系统里、下拉框选"：36 份周文件随程序放在 `app/history/<年>/<KWnn, dd.mm.yyyy>/`，`GET /api/import/library` 列出（含该周是否已导入），`POST /api/import/library {path, commit, sourceUrl}` 按相对路径导入（日期取文件夹名，防目录穿越），首页卡片多了 "Stored weekly files" 下拉框 + Add / "Add all not yet imported"；案例详情显示 "Excel: 决议原文" 与 "Imported from 文件 (row n)"。验证（2026-09-30）：pytest 384（新增 tests/test_excel_import.py 12 组：文件名日期、18 种金额写法、外币折算与读不懂的警告、件价逗号、决议归类、类型 / 级别 / 区域 / ID / 多零件号拆分、样本工作簿 4 个案例 7 行的完整映射、表头变体、接口权限 / 预览不写库 / 提交 / 同周替换 / 手填日期、错误输入 422、导入案例免链接可编辑、命令行按文件夹名取日期与重跑替换）、前端回归 36（去掉 2 条假上传用例，新增 1 条导入队列用例）、滚动回归 16、ruff；真实文件：51 份文件名带日期的全部解析通过，13 份无日期的靠文件夹名。本机 8062 已换成从这批文件导入的真实历史库（每周取一份，优先 MM）。已知边界：Notes 列整段存进 committeeDiscussion，不拆成待办；Commodity 原文存 cluster（领导的代码体系，未映射到三个 Cluster）；"4 < 750k" 这类不是金额的文本记 0 并在预览警告里列出。

Spec: non-spec

## Phase-18: 领导第三轮反馈（年份、术语、文件库、排序、待办分类与职能、行动统计）

Status: `closed`

Description: 领导 2026-10-01 前后在 Teams 里的 13 条反馈（截图 2026-10-08 交我整理），用户同日答复：演示文件也要一个服务器端下拉框、待办分类按领导意思回到自由文本标签、任务负责人加 Function 字段；Open 与 Overdue 的口径保持互斥（待办状态三选一，到期自动 Open → Overdue，三格相加等于总数），由用户转告领导。实现：(1) 周标签 / 周筛选 / 驾驶舱按案例自己的年份（`logic.case_year` / `week_label`，前端 `caseYear` / `caseWeekLabel` / `weekKey`；Database 加 Year 筛选，From / To week 选项带年份；导出与提醒的周标签同样带年）；(2) 术语归一：新模块 `app/commodities.py` 把 Excel 的 Commodity 原文映射到三个固定 Cluster + 规范 Commodity 名（代码族 CH / CH01 / FP / SC / FF / CA / EL / EA + 关键词；Textiles 按模板 CLUSTER_OF 归 Chemical），导入时写 `cluster` / `commodity` / `commodityRaw`，认不出的保留原文并进预览警告；服务启动按 `commodities.VERSION` 自动重算导入案例（kv `commodity_vocabulary`），`python -m app.migrations normalize-clusters [--apply]` 可先看映射表；编辑页 Cluster 放宽为文本（之前 Literal 让导入案例一编辑就 422，正是 2026-10-06 反馈 Excel 里的 "cluster: Input should be …"）；Database 加 Commodity 筛选、Cluster 单元格带 Commodity 副标题，详情页显示 "Commodity … (Excel: 原文)"，驾驶舱多一张 Cases by Commodity；本机 8062 的 142 条历史案例归一后 Chemical 44 / Metal 69 / Electronics 24，剩 MI01（3）、SO02（1）、"Yajun Zhao"（1，Commodity 列里写了人名）待领导定；(3) 服务器演示文件库：`SC_PRESENTATION_LIBRARY_DIR`（默认 `data/presentations/`，可分子文件夹），`GET /api/presentation-library`（Manager 及以上）、`POST /api/cases/{id}/files/from-library {path}`（复制进 uploads / SharePoint 并按案例改名，原件不动，防目录穿越、类型白名单、每案 10 个上限），案例页 "Attach from server" 下拉框按文件夹分组；(4) 首页搜索示例标签删除；(5) Database 13 列表头可点排序（`state.dbSort`，数字 / 文本 / 周键，再点反向，默认仍按周倒序）；(6) 文件列表改 grid 版式：文件名一行、元信息下一行、Remove 靠右（之前 meta 的 nowrap 把文件名挤成一字一行）；(7) 驾驶舱 YTD 改为年份下拉 + Whole year / By Week，周选项只列所选年份，Agenda / Minutes 导出带 `year`，Cluster / Region / Commodity 分布按所选年份；(8) 行动状态三格改数真实待办（已决议案例的 followUps 按各自状态计数，没有待办 = 0），点格子进 Follow-ups 页并带状态 + 年份筛选（Follow-ups 页新增 Status / Year / Function 筛选，默认 Open + Overdue）；(9)(10) 驾驶舱新增 Open / Overdue actions by function 与 by owner 四张图；(12) 待办分类改回自由文本 Tags，分类由 `logic.categorize_task` 按关键词（`CATEGORY_KEYWORDS`，短词整词、长词前缀）与标签同义词（`TAG_SYNONYMS`，含模板旧标签 Cost / Quality / Capacity）判定，保存时写 `categories`，规则随 bootstrap `taskRules` 下发、编辑页实时预览与服务端一致；(13) 待办 `ownerFunction`（编辑页 datalist 建议 `logic.FUNCTIONS`，可自由输入），Follow-ups 页 Owner / Function 列，纪要 Actions 表加 Tags / Function 列。验证（2026-10-08）：pytest 439（新增 tests/test_phase18.py 51 项：词表 19 种写法 + 3 种未知、归一只碰导入 / 非固定 Cluster 的案例且幂等、启动迁移按版本、CLI 预览 / 写回、编辑保留未知 Cluster、关键词分类 9 例、旧记录现算、保存写 categories 与 ownerFunction、周标签按年、Actions 表列、按年导出文件名、文件库列表权限 / 排序 / 缺目录、挂接改名 + 原件不动 + 可挂多案、`..` / 绝对路径 / 非白名单 / 空文件 / 上限、导入接口的归一与警告）、前端回归 39（重写分类用例，新增 3 条：年份标签与筛选与排序与 Commodity；驾驶舱按年 / 真实待办 / 四张图 / 周导出带年 / 点格子进 Follow-ups；案例页文件一行显示 + 文件库挂接 + 普通用户看不到）、滚动回归 16、ruff；本机 8062 真实历史库走查截图 `~/backups/sourcing-cockpit/e2e-screenshots-2026-10-08-phase18/`，演示库换代码前备份 `demo-db-before-phase18-20261008-1045.db`。已知边界：按年视图里同一案例跨年出现时各年各算一次（取该年最后一次登场）；词表改了只重算从 Excel 导入的案例，手工改过 Cluster 的导入案例会被按原文重算；未识别的 Commodity 保持原文显示在 Cluster 里。2026-10-06 反馈 Excel 与 2026-10-08 转来的同事反馈里尚未做的项（见 Charter 之外的待定清单）：提交 / 编辑页一次列出全部缺项、管理员把案例改到当前或过去的周、Tooling payment 加 "No tooling involved"、已上传演示文件即满足 "演示链接" 规则且编辑时也能加文件。

Spec: non-spec

## Phase-19: 同事试用反馈（缺项一次列全、管理员改周、无模具选项、演示文件即满足）

Status: `closed`

Description: 2026-10-06 反馈 Excel 与 2026-10-08 同事邮件，用户同日批准全部四条。(1) 缺项一次列全：服务端 `main._submission_problems`、`logic.commercial_problems`、`logic.case_edit_problems` 收集全部问题，422 的 detail 用换行分隔（只有一条时与原文案完全一致，旧断言不变）；前端提交页与编辑页同样先收集再显示，`problemListHtml` 多条时列成清单（"Please fix these N points…"），服务端返回的多条也拆成清单。(2) 管理员改周：`CaseEditIn.meetingDate`（任意一天，按所在 ISO 周的周三存），`logic.move_case_to_week` 同步 weekNum / meetingYear / 会议日期与标签，换周时案例号排到目标周最后，同周换日只对齐周三；只有 Sourcing admin 能换周（Manager 带同一周日期照常保存，换周 403）；编辑页标题下 "Committee week" 日期框，实时预览 "→ 2026-KW40 · Wed, Sep 30, 2026"，保存后时间线跟着这条记录走。(3) Tooling payment 加 "No tooling involved"（schema、提交页、编辑页、提示文案）。(4) 演示文件即满足：案例上已有上传 / 挂接的演示文件时，"非 Pending 决议须有演示文稿"规则视为满足（服务端 `has_files`，前端同规则，前端也补上了导入案例豁免——之前前端没豁免，正是反馈截图里导入案例存不了的原因）；编辑状态下文件卡片照常显示 Add files / Attach from server / Remove，上传前先把未保存的编辑收进 editBuffer，加文件与改待办、改周一次保存；查看页演示文稿格在只有文件时显示 "📎 n file(s) under Sourcing Presentation Files"。验证（2026-10-08）：pytest 448（新增 tests/test_phase19.py 9 项：提交 7 类缺项同时返回、单条原文案、编辑 4 类问题同时返回、商务问题收集与汇率缺失跳过 BPG、管理员改到 KW41 与 2025-KW51 及同周不动案例号、Manager 换周 403 / 同周 200 / 非法日期 422、改周辅助函数跨年不混、No tooling involved 可提交且非法值 422、上传文件后不填链接即可记录决议并带待办）、前端回归 42（新增 3 条：提交页缺项清单 + 单条原文 + 无模具选项载荷；服务端多条拆清单；编辑页两条问题同列、编辑中上传不丢待办与改周、有文件免链接、改周载荷与页面周标签、Manager 无改周框且载荷不带 meetingDate）、滚动回归 16、ruff；本机 8062 已重启到本代码，截图 `~/backups/sourcing-cockpit/e2e-screenshots-2026-10-08-phase19/`。已知边界：改周只改这条登场记录，同一案例其它周的登场不动；编辑中途上传 / 删除的文件立即生效，取消编辑不会撤回文件。

Spec: non-spec

## Phase-20: 上传区分 Meeting minutes 与 Presentation（演示文件自动对案例）

Status: `closed`

Description: 领导 2026-10-08 要求上传数据时用两个类别的下拉框区分会议文件与演示文件；用户同日给出 SharePoint 周文件夹截图说明：周文件夹（如 "KW15, 08.04.2026"）里 `…MM.xlsx` 是 meeting minutes，`1. 110000034978 SPR8 Tube_34235239A_ NA_CO_L2_Iron Force Huzhou_Tube_Haojie.pdf` 这类是 presentation（开头是该周案例序号、SWAT 号、零件号）。实现：新模块 `app/presentation_match.py`，按 SWAT 数字号 / bundle 号（文件名里 `B_2025_00234`、`B-2025-234` 都认，bundle 零件行上的 SWAT 号也算）/ 案例号原样出现 → 零件号 → 周文件夹 + 文件名开头的案例序号依次匹配，知道周时先在那一周里找，同号多次上会取最近一次；`GET /api/presentation-library` 每份文件带 `match {rowId, swatId, label, by, attached}`；`POST /api/presentation-library/files`（Sourcing admin，从本机上传进库：缺省放进匹配案例所在周文件夹 `KWnn, dd.mm.yyyy`，对不上放 `Unsorted`，同名加 (2)，文件夹名清洗不能跳出库目录）；`POST /api/presentation-library/attach {paths}`（Manager 及以上，批量按匹配挂接，已挂过 / 对不上 / 案例文件已满 / 路径不在库里的跳过并说明原因）。前端：首页卡片改名 "Upload weekly committee data"，分 "1 · Meeting minutes"（原周会 Excel 拖放与 Stored weekly files 下拉框）与 "2 · Presentations"（按周文件夹分组的下拉框，每项显示 "→ 匹配案例" / "✓ attached to …" / "no matching case"；Attach to matched case、Attach all matched not yet attached (n)、Upload presentations…、结果清单）。顺带修了 Phase-18 漏掉的一处年份问题：首页 Recent Committee Activity 只按周号排序，2025-KW51 排在 2026 前面，改为按年 + 周。验证（2026-10-08）：pytest 461（新增 tests/test_phase20.py 13 项：7 种命名的匹配依据、3 种对不上、标签与周文件夹、上传进库的权限 / 按周归档 / Unsorted / 同名不覆盖 / 批量挂接与跳过原因 / 已挂提示 / 文件夹名清洗 / 类型白名单 / 不留临时文件）、前端回归 43（新增 1 条：两类分区、下拉框分组与匹配文字、单个与批量挂接、上传拦 .exe 与提示）、滚动回归 16、ruff；本机 8062 真实历史库：截图里那份 PDF 放进 `data/presentations/KW15, 08.04.2026/` 后自动对到 2026-KW15 Case #1 并批量挂接成功，截图 `~/backups/sourcing-cockpit/e2e-screenshots-2026-10-08-phase20/`。用户 2026-10-08 决定：挂接后的系统文件名日期沿用 Phase-15 规则取上传当天（不改成会议日期）；历史演示 PDF 暂不批量补，之后手动上传；演示文件库只收 PDF / PowerPoint（`files.LIBRARY_EXTENSIONS`，上传进库与下拉框都按它，SharePoint 周文件夹整个复制进来时 MM Excel 与 .msg 不会混进 Presentations），pytest 462、前端回归 43。用户 2026-10-08 验收通过 Phase-15~20。已知边界：文件名里既没有号码也不在周文件夹里的只能在案例页手工挂。

Spec: non-spec

## Phase-21: 案例编号按年份、删除后补号

Status: `awaiting-acceptance`

Description: 领导 2026-10-12 反馈：按 KW42 导出的议程 case 号是 4、5 而不是 1、2，别人会以为漏了案例。原因是确认登记时编号只看周号不看年份（2025-KW42 历史已有 1~3 号，`logic.confirm_submission`）。实现：确认登记按"年份 + 周"编号；`logic.renumber_weeks` 把指定周按原顺序重排成连续号（同号的几行仍同号），删除案例与 Sourcing admin 改周后对原周调用；服务启动一次性迁移 `service._migrate_case_numbers`（kv `case_numbering`），只整理含系统内登记案例的周——全部从 Excel 导入的周保持原件编号（2026-KW39 的周会 Excel 本身没有 6 号），改动逐条以 warning 写进 docker logs。同日修复带斜杠的 SWAT / Bundle ID（如 "B/2026/00198"）删除报 405 Method Not Allowed：前端编码的 %2F 被服务端解码回斜杠，路由匹配不上落到静态文件挂载；删除路由改用 `{swat_id:path}` 并注册在删除附件路由之后。验证（2026-10-13）：pytest 490（新增 tests/test_phase21.py 6 项：按年编号、补号与同号、删除补号并落库、改周补号、启动迁移只跑一次且不动纯导入周；test_excel_import 新增斜杠 ID 删除）、前端回归 44、滚动回归 16、ruff；本机真实库快照起临时实例 8063：admin 补登记 2026-KW42 得 1 号，删除 B/2025/00361 后 KW39 补成 1~5。

Spec: non-spec

## Phase-22: 截止后只有 Sourcing admin 能补登记

Status: `awaiting-acceptance`

Description: 领导 2026-10-12 要求：对外说周一晚上截止，但个别急项目可由 admin 周二补进本周会议；用户同日选定"只有 admin 能补登记"。截止后的 "Request an exception" 选项只对 Sourcing admin 显示（文案注明只有 admin 看得到），普通用户与 Manager 看不到、最早只能选下周三；服务端 `_late_registration` 按角色判断，非 admin 带了例外标记也 422，文案只说已截止、不提例外；admin 补登记仍进审批队列并带 Late registration 标记，presenter 先记成 admin、之后在编辑页改。验证（2026-10-13）：tests/test_registration_cutoff.py 改写 2 项（普通用户 / Manager 带例外被拒且文案不提例外、admin 不勾提示可勾 / 无理由拦截 / 有理由接受）、前端回归新增断言（截止后普通用户与 Manager 无例外入口）；临时实例 8063 实测。

Spec: non-spec

## Phase-23: 从会议纪要自动列出 Action Item

Status: `awaiting-acceptance`

Description: 领导 2026-10-12 要求：Committee Discussion（Excel Notes/Task/Resp./Due Date 列）里的编号任务自动列出来，负责人与日期能识别的先填好，她只补邮箱和具体日期。实现：新模块 `app/action_items.py`（主编号 "1." 按行或挤在一行里都认，只认按顺序出现的编号；子任务行首 a. b. 或行内 1) 2)，至少两条才算，编号记成 6a / 2.1；不带编号的行进上一条备注；负责人取最后一个 "--"，没有就取最后一个 " - "，末尾括号里的说明进备注；截止日期先在负责人段找、再在任务文字里找：dd.mm.yyyy / dd/mm/yy / ISO 照填，KW / CW 取那周周五、月份取月底并在备注提示核对，没写年份的 KW 按案例会议年份推算、跨年往后推）；接口 `POST /api/action-items/extract {text, meetingDateISO}`（Manager 及以上，只出草稿不写库）。前端：详情页纪要 `white-space: pre-wrap` 保留换行（之前挤成一段）；编辑页 Follow-up Tasks 区 "Extract action items from discussion" 用编辑框里的纪要识别 → 勾选面板（已在列表里的默认不勾）→ "Add N selected as follow-up tasks" 加进待办（任务文字带纪要编号，邮箱留空，保存时照常校验）。不按姓名猜邮箱、不猜负责人职能。验证（2026-10-13）：pytest 新增 tests/test_phase23.py 19 项（领导截图两段真实纪要逐条比对、历史纪要的 " - " 写法、无编号、句中数字不拆、8 种日期写法、接口权限与非法日期），前端回归新增 1 条（纪要换行、无编号提示、识别请求带编辑中的文字与会议日期、去重默认不勾、勾选计数、加入后未保存的输入不丢）；36 份历史周会 Excel 的 142 个案例中 71 个识别出 177 条任务，132 条带负责人、21 条带日期（其余是纪要原文没写）；临时实例 8063 截图 `.playwright-mcp/phase23-drafts*.png`。已知边界：一条编号里写了两个 "--负责人" 时只取最后一个，前面的留在任务文字里。

Spec: non-spec

## Phase-24: 邮件与 Teams 通知经 SharePoint 列表 + Power Automate 流发出

Status: `closed`

Description: 2026-10-13 用户要求测试 Teams 与邮件提醒。发现 IT 给的 Entra 应用只有 Sites.Selected（令牌 roles 实测只有这一项），没有 Mail.Send、也没有发 Teams 的权限，SMTP 中继仍等 IT；用户选择用 Power Automate 流代发。公司数据策略在 passivesafety (default) 与 PP-Dev-PU-GR-Amber 都禁用 "When a Teams webhook request is received"（`restricts use of these apis: TeamsWebhookRequestReceived`），改为 SharePoint 列表中转：系统把每条通知写成站点 SCC_PROC_SOURCINGCOMMITTEE 里 `Cockpit Notifications` 列表的一行（列 channel / to / cc / subject / html，内部名与流里的 `triggerBody()?['…']` 对应），流 **Sourcing Cockpit - Notifications**（passivesafety 默认环境，SharePoint "When an item is created" 触发）按 channel 用所有者的 Office 365 Outlook "Send an email (V2)" 或 Teams "Post message in a chat or channel"（Flow bot 私聊收件人）发出。实现：`SC_NOTIFY_LIST_NAME`（docker-compose 同步透传）；`delivery.send_email` 顺序 SMTP → Graph 发信 → 通知列表，`deliver_teams` 顺序 Graph 直发 → 通知列表 → 旧 webhook，5 种邮件通知都覆盖；`graph.queue_notification` / `ensure_notify_list`；命令 `python -m app.migrations notify-list-setup`（应用 write 角色建不了列表，实测 403，列表由有 ManageLists 权限的用户账号建，命令只读核对 / 补列）；说明 `docs/notify-flow-setup.md`。验证（2026-10-13）：pytest 500（新增 tests/test_notify_list.py 10 项：邮件 / Teams 行字段与分号收件人和 HTML 转义、列表 id 缓存、SMTP / Graph 优先级不变、未配置 skipped、400 / 403 / 列表不存在的可读失败、无收件人不发请求、建列表与补列与权限不足）；本机假 SMTP + 假 Teams 端点跑通 6 种通知与接收端宕机场景；真实链路：写入列表后流两次运行均 Succeeded（<1 分钟），用户收到测试邮件与 Teams 消息。安全复核（越权代理：站点里任何有编辑权限的人都能往列表加行，借所有者邮箱发信）后，给触发器加了 Trigger condition，只处理创建者为 SharePoint App（系统应用身份）的行；实测个人账号写的行被跳过、系统写的行正常发出。已知边界：发件人是流的连接所有者（目前 xin.chen.external），交接 xiangwei.chen 用户决定暂缓（加共同所有者会借出用户自己的 Outlook / SharePoint 连接，备选 Send a copy）；Teams 以 Flow bot 发每连接每 5 分钟 25 条；列表行不自动清理；本机 `.env` 故意不开（本机库有真实待办），服务器加 `SC_NOTIFY_LIST_NAME` 即开始以所有者邮箱真实发送。 验收（2026-10-14）：用户在隔离实例（空库、用户为唯一管理员、admin@zf.com 停用）实测示例案例 110000099990 的 4 种通知——登记确认、待办手动提醒（Email + Teams）、新反馈待审批、反馈审批结果——收到 4 封邮件 + 1 条 Teams，用户确认验收通过。仍只留本地、不上 GitHub。

Spec: non-spec

## Phase-25: 只看单周的周筛选与 Agenda 里 L4 排最后

Status: `awaiting-acceptance`

Description: 领导 2026-10-14 反馈：Database 页 From week 选了 2026-KW42、To week 留空时，KW43 的 5 个案例也出现，导出的 Agenda 也带上了它们（原因：To week 留空就是没有上限）；导出 Agenda 时 Level 4 案例只是 for info、不需要会上 review，要一直排在最后。用户同日确认：只改 Agenda（Meeting Minutes 不动）、多周导出时每周各自把 L4 放到该周最后、Database 列表也一样排。实现：Database 页选了 From week 而 To week 为空或更早时，To 自动设成同一周（下拉框里看得见，想看范围再选更晚的 To）；`exports._sorted` 改按"年份 + 周"排（原来只看周号，跨年导出会把 2025-KW42 与 2026-KW42 混在一起），Agenda 传 `l4_last`，每周内 Level 4 排到最后，A2 说明行注明这一点；Meeting Minutes 与 Actions 表顺序不变；Database 表按周排序（默认）时，每周内 L4 不论升降序都在该周最后，其他列排序不受影响。验证（2026-10-14）：pytest 501（test_exports 新增 1 项：多周 + 跨年 L4 排后、纪要顺序不变）、前端回归 45（周筛选只选 From 只看单周、L4 升降序都排后）、滚动回归 16、ruff check；本机库快照起临时实例 8063 实测：只选 From 2026-KW25 时 To 自动为 KW25、只列 KW25 两条；选 KW24~KW30 导出的 Agenda 按周升序、A2 带 L4 说明。本机库没有领导截图里的 2026-KW42 / KW43 数据（在服务器上），部署后请在服务器上按截图再看一遍。

Spec: non-spec

## Phase-26: 导航分组（Case Workflow / Data）与侧边栏

Status: `awaiting-acceptance`

Description: 用户 2026-10-14 提出：Submit Case、Approval、Follow-ups 是同一条流程，归成一个大功能，点进去在侧边显示三个子功能。用户同日选定：左侧侧边栏（窄屏改成内容上方的横向标签）、流程组叫 **Case Workflow**、Database 与 Dashboard 也归成一组（**Insights**）。顶部导航变成 Home / Case Workflow / Insights / Accounts（仅系统管理员）；待审数量同时显示在 Case Workflow 与侧边栏的 Approval 上。与 mission "页面 UI 与模板一比一一致" 的目标有偏离，已向用户说明，mission 是否改写待用户决定。用户同日追加：板块说明要精简，或者收起来、鼠标移上去再显示。实现：`NAV_GROUPS` / `navGroupOf` / `groupLanding`，组按钮 `data-nav-group`、侧边栏条目沿用 `data-nav`；回到某组打开上次看的页，管理员有待审登记时点 Case Workflow 直接到 Approval；案例详情不显示侧边栏、顶部高亮 Insights；侧边栏宽 168px，≤900px 改横向标签，Database 页窗口不到 1440px 也改横向标签（管理员表格多一列 Delete，1280px 带侧边栏会多出 73px 横向滚动，领导要求正常屏幕不出横向滚动条）。说明收进 ⓘ（`infoTip`）：7 个页面标题下的说明（首页标语保留）、首页上传卡片两段说明、Dashboard 导出说明、自动提醒说明，悬停或 Tab 聚焦显示，aria-label 带全文，靠窗口边缘时自动左右平移（`placeInfoPop`）；侧边栏条目说明改为悬停提示（title）。验证（2026-10-14）：前端回归 46（新增导航分组、待审数量、组默认页与记忆、ⓘ 悬停、Database 1280/1500 布局、详情页无侧边栏；其余用例改走 goTo 先点组名）、滚动回归 16（导航拖动 / 滑动 / 取消 3 项改为压窄导航条制造溢出再测，键盘 Tab 改按新顶部按钮）、pytest 501、ruff；本机库快照起临时实例 8063 以管理员在 1440 / 1366 / 1280 / 390 宽截图核对，Database 表格在 1280 起无横向滚动。过程中修了两处布局问题：纵向排列时 `.page` 的 margin:auto 让页面被内容撑宽（加 width:100%）、隐藏的弹框仍占排版宽度（改 display:none）。 用户同日追加：按钮与侧边栏视觉要好看些。实现：按钮统一圆角 7px、细阴影、悬停 / 按下 / 禁用 / 键盘焦点样式，主次 / 危险按钮并排同高（36px）；导出按钮去掉内联样式与 emoji，改 `.btn-tool` + 线条图标（`ICONS`）；顶部导航当前项加短橙线、待审数量改橙色徽章（`.count-badge`，侧边栏共用）；侧边栏 Case Workflow 画成编号节点 + 竖线的流程轨道（提交 → 审批 → 跟进本来就有先后），Insights 节点放图标、不连线；手机横向标签收紧到 390px 放得下三步。复验：前端回归 46、滚动回归 16、pytest 501、ruff，8063 截图核对 1440 / 1500 / 390。 用户同日再追加：字段说明也一样精简、收进 ⓘ。实现：`fieldTip`（小号 ⓘ，放在 <label> 字段名后），提交页、案例编辑页、待办反馈、首页上传、Dashboard、自动提醒、汇率与截止卡片的固定说明共 40 余处收进 ⓘ；长字段名里的括号说明改到 ⓘ（如 "FRA available? (required for Level 2)"、"Parent PF (optional — definition to be clarified)"、证据文件类型）；BPG 提示平时不显示、超 3 Mio EUR 才出现红字；提交按钮上方的蓝框路由说明改成按钮旁一行小字。保留可见：会随状态变化或需要立刻注意的信息（漏填红字、加载中、导入警告、投递结果、当前汇率、案例号提示、权限提示、Last updated、换算案例的 "Enter amounts in …"）。自动提醒说明原文写 "SMTP relay / webhook" 已不符现状，改为不点名渠道。测试：截止规则、地区多计说明的 5 处断言改查 ⓘ 的 aria-label，一处改用缩短后的文字；前端回归 46、滚动回归 16、pytest 501、ruff。 用户同日再追加：不规范的 e.g. 示例会误导，不规范就不要举例。按随系统附带的 36 份周会 Excel（119 个案例）核对真实格式后：Part Number `12345678` → `R004A930`、SWAT Case # `SWAT-10482` → `110000035042` / bundle `B/2026/00132`、Parent PF `PF-1182` → `CH01016`、Part Description 改为 `Anchor Bracket`、快速搜索示例同步；Part Family Code 历史数据里一条都没有、定义待澄清，去掉示例；Recommended Supplier 去掉虚构供应商与自造的多区域写法，只留填写说明；提醒收件邮箱示例用允许的公司域名。保留：Project `MBEAL`（历史数据最常见）、Owner's function（取自固定职能清单）、数字示例与自由文本示例。案例号下方未输入时的长说明收进 ⓘ，输入后的"已在库 / 新案例"状态照常显示。模板演示数据（HAND_CASES）里的 SWAT-10482 等不在界面示例范围内，未改。复验同上。 用户同日再追加：侧边栏再优化。实现：每项下面一行实时状态（`navMeta`：Submit Case 显示最近可登记的会议周与截止时间、Approval 待审数、Follow-ups 进行中 / 逾期数（逾期红字、为 0 的部分不显示）、Database 案例总数、Dashboard 默认年份）；底部收起按钮，收起成 64px 窄条只留编号 / 图标，待审数缩成节点右上角小圆点，悬停提示带名称与状态，偏好存本机浏览器（`sc_nav_collapsed`，读不到默认展开）；横向标签模式不显示状态行与收起按钮；流程连线只连流程项。前端回归 46（导航用例新增状态行、收起 / 展开与记忆）、滚动回归 16、pytest 501、ruff。 用户同日要求把 Insights 改名：组名改为 **Data**（代码里组键 `insights` 一并改为 `data`），复验同上。 用户同日要求删掉顶部快速搜索框（首页与 Database 已有搜索）：去掉输入框、样式与回车跳 Database 的处理，账号按钮靠右；顶栏换两行的门槛从 1100px 降到 980px（管理员在 981px 一行放得下），复验同上。 部署前演练（2026-10-14，用户要求"都测试一遍再部署"）：部署候选 = origin/main + Phase-26（不含 Phase-24），pytest 491、ruff、前端回归 46、滚动回归 16；`graph-check --write-test` 全过；空库实例（SharePoint 文件存储开、无通知）浏览器走完：提交带附件 → 审批 → 单周筛选与 CSV / Agenda / Minutes 导出（L4、欧元、Actions 表）→ 编辑决议 + 待办 + 编辑页上传 / 删除文件 → 反馈带证据 → 审批反馈、案例关闭 → 导入周会 Excel 与重复导入替换 → 演示文件库上传按 SWAT 号匹配并挂到案例 → 注册 / 非公司邮箱拒绝 / 提升 Manager / 停用；三种角色 × 两种宽度逐页无报错、权限正确；重启后数据与 SharePoint 文件下载不变；每个文件都直接向 SharePoint 核对存在 / 删除与字节一致；服务日志无错误。发现（待用户决定，非阻塞）：删除案例不删附件文件（SharePoint 或本地都一样，登记记录仍引用它们）。测试文件夹已从 SharePoint 删除。

Spec: non-spec

## Phase-27: 删除案例时一并删除附件文件

Status: `awaiting-acceptance`

Description: 2026-10-14 部署前演练发现：删除案例只删数据库记录，附件文件（SharePoint 或本地）一直保留。用户同日认为这是问题，要求一起删除。范围：该 SWAT 全部登场行的附件、待办反馈证据、级联置 Deleted 的登记单上的同一批文件记录；仍被其他记录引用的文件不删（如同号新登记还在等审批）；SharePoint 上案例文件夹删空后一并删除。 实现：`logic.iter_attachments` / `case_attachments`（`_find_file` 改用同一个遍历），`delete_case_by_swat` 清空级联登记单的 files；删除接口在提交后、锁外调 `files.remove_case_files`（逐个 `files.remove`，SharePoint 删不掉只记日志；有 SharePoint 文件时再调 `graph.delete_folder_if_empty`），返回 `filesRemoved`；前端删除确认写明 "and its N attached files"（`caseAttachmentCount`，与服务端同口径），删完提示实际删了几个。SharePoint 删除进站点回收站可找回；本地文件直接删除。验证（2026-10-14）：pytest 508（新增 tests/test_phase27.py 7 项：本地三类附件全删与登记单清空、同号待审登记的文件保留、SharePoint 逐个删与空文件夹清理、无附件不碰 SharePoint、空 / 非空 / 不存在文件夹三种情况）、前端回归 46（删除用例加确认文案与提示）、滚动回归 16、ruff；隔离实例连真实 SharePoint：普通删除 3 个文件与文件夹都没了；同号新登记待审时只删旧案例 3 个、新登记的文件与文件夹保留；测试文件夹已删。上线前已删除的案例留下的旧附件不会被自动清理。

Spec: non-spec

## Phase-28: Presenter 可填可改、Agenda / MM 按级别与地区排序、导出按会议命名

Status: `awaiting-acceptance`

Description: 领导 2026-10-15 反馈三件事。一、5 条 L4 案例 Presenter 显示 "EXTERNAL_HU"，应为 Lingqing Hu（Tracy），目前靠手工改导出的 Excel：网上提交的 Presenter 取提交账号注册时填的名字，那个账号名字填成了 EXTERNAL_HU（推测，数据在服务器上未核实）。二、Agenda 和 MM 自动把 L2、L3 排前面（"L2-L3-L4"），不同地区按 AP / EU / NA 排。三、导出文件自动命名成 `KWXX DD.MM.YYYY_SBS Sourcing Alignment Committee_Agenda`（MM 同理），与委员会历史文件一致。用户同日决定：Presenter 三条都做（管理员在案例编辑页改已有案例、Accounts 页可改账号名、提交页加可改的 Presenter 字段，默认本人）；排序推翻 Phase-25 "MM 不动"——Agenda、MM（含 Actions 表）与 Database 按周排序时都按每周内 级别 L2 → L3 → L4 → 未填、地区 AP → EU → NA、案例号排，多区域案例按勾选里最靠前的地区归组；文件名用格式 KWXX DD.MM.YYYY，跨多周导出用 `KW42-KW43 2026_…`。 实现：提交页 Your Email 下加 Presenter（默认本人、可改，ⓘ 说明），`SubmissionIn.presenter`，留空回退到账号名字；审批页上会人不是提交人时显示 "Presenter: …"；Accounts 页名字改成输入框，失焦保存（后端 `UserUpdateIn.name` 原已支持），清空不发请求并恢复原名，改了自己的名字立即生效；`exports._sorted` 改为 年份 + 周 → 级别 → 地区 → 案例号（`LEVEL_ORDER` / `REGION_ORDER` / `_region_rank`），Agenda、MM 与 Actions 表共用，A2 说明行写明顺序；Database 表按周排序同口径（`levelRank` / `regionRank`）；`exports.filename(kind, cases, week=, today=)`：单周 `KW42 14.10.2026_SBS Sourcing Alignment Committee_Agenda.xlsx`（纪要 `_MM`，日期取周内一致的会议日期，否则那周周三）、多周 `KW42-KW45 2026_…`、跨年 `KW52 2025-KW01 2026_…`、按周导出空周按那周命名、Database 空选择用当天日期；`logic._meeting_date` 改为公开的 `meeting_date`。已有的 5 条 L4 案例需管理员在服务器上用案例编辑页的 Presenter 字段手工改正，并在 Accounts 页改正那个账号的名字。验证（2026-10-15）：pytest 518（新增 tests/test_phase28.py 11 项：两种文件的级别 + 地区排序、Actions 表顺序、单周 / 无日期 / 日期不一致 / 多周 / 跨年 / 空选择文件名、导入功能能从文件名认回 KW 与日期、两个导出接口的文件名、Presenter 默认与改名、管理员改账号名后新提交用新名字；Phase-25 的 L4 排序用例由此取代，3 处旧文件名断言改为新格式）、前端回归 46（Database 按周排序改测级别 + 地区、提交 payload 带 Presenter、注册后 Presenter 默认本人、审批页显示 Presenter、Accounts 改名与清空恢复）、滚动回归 16、ruff；空库临时实例 8063（SharePoint / 通知全关）实测：注册 EXTERNAL_HU → 管理员改名 Lingqing Hu → 提交 4 个 KW43 案例 → 确认，导出文件名为 `KW43 21.10.2026_SBS Sourcing Alignment Committee_Agenda.xlsx` / `_MM.xlsx`，两份顺序都是 L2 AP+EU、L2 NA、L3 AP、L4 EU，Presenter 全为 Lingqing Hu；提交页与 Accounts 页截图核对，Accounts 表在 1294px 宽无横向滚动（平板宽度约 820px 时表格卡片内横向滚动，与改前同样处理）。用户同日决定：导出文件的 "#" 列保持案例登记号（排序后同一周可能显示 3、2、1），不按显示顺序重编。上推前全盘实测（2026-10-15，种子库实例 8063，SharePoint 文件真实上传、通知关）：提交带 Presenter → 确认 → 导出顺序与文件名（单周、多周、空周）、Accounts 改名与清空恢复、案例页附件上传与删除、删整个案例连文件与案例文件夹一起从 SharePoint 清掉（Phase-27）、待办 / 手动提醒 / 反馈审批及其门槛，全部符合预期。

Spec: non-spec

## Phase-29: 待办负责人统一显示全名、职能跟着人走、Follow-ups 页直接编辑

Status: `awaiting-acceptance`

Description: 领导 2026-10-16 反馈四件事。一、"Can we add the function for owner?"——用户定：职能跟着人走，同一个负责人填过一次职能，他的其他待办自动带出，改一处全部跟着改。二、"We show email or we show full name. Don't mix"——Dashboard "Open actions by owner" 里人名与邮箱混排；用户定统一显示全名：负责人填的是邮箱时，先用注册账号的名字，没有账号就从邮箱推出名字（`andreas.huber1@…` → Andreas Huber），本来写的是人名照旧；提醒收件邮箱不变。三、Follow-ups 页状态筛选 "All statuses" 与同排 "Year: All" 等写法不一致，看起来像错字，改成 "Status: All"。四、"Can we add the edit functional for all the follow-ups"——Follow-ups 页每条待办可直接编辑，不必进案例编辑页。 实现：新模块 `app/owners.py`——`display_name`（邮箱 → 账号名字，没有账号按邮箱推名字，去掉 `.external` 和尾部数字；占位名 "Sourcing admin" 不用；几个邮箱逐个换；人名照旧）算出的全名存在待办的 `ownerName`，案例保存、单条编辑、注册、改账号名、每次启动时重算（幂等，只写改了的案例）；职能按全名（忽略大小写）归并：保存时职能新填或改过的推到这个人的全部待办（`spread_function`），只换了负责人、职能框没动的换成新负责人已知的职能，一个人只有一种职能时空着的待办自动补上，几条职能互相矛盾的旧数据不猜。页面（Follow-ups 列表与负责人筛选、案例页、Dashboard by owner 两图）、Database CSV、MM 的 Actions 表与纪要合并文字、提醒与反馈邮件里的 "Owner:" 都用全名；提醒收件邮箱不变。新接口 `PUT /api/tasks/{id}`（Manager 及以上，`TaskEditIn`）：门槛与案例编辑页的待办规则一致（开放待办要收件邮箱；关掉最后一条开放待办要案例已有最终文件链接，否则提示去案例页填），合并后按截止日重判 Open / Overdue、重算分类、保留提醒 / 反馈 / 关闭记录，重算案例 actionStatus（`logic._settle_task` 与案例保存共用）。Follow-ups 页每行加 Edit（行下展开与编辑页同样的字段，保存只改这一条，出错时提示在表单里、已填内容不丢；编辑中暂停自动刷新），"Reminders sent automatically" 每条旁也有 Edit（清掉筛选后打开那条；新日志带 `taskId`，旧日志按案例号 + 任务原文找）；编辑表单里改了负责人，职能框自动换成那个人的职能，职能旁 ⓘ 说明"一个人一种职能"；状态筛选 "All statuses" 改为 "Status: All"。`docs/manager-quick-start.md` 补了全名显示与行内编辑。验证（2026-10-16）：pytest 535（新增 tests/test_phase29.py 17 项：邮箱推名字 5 例、账号名优先与占位名、保存后带 ownerName 且收件邮箱不变、注册与改名后更新、导出与提醒文字用全名、补职能只在唯一时、改职能推到全部待办与冲突统一、换负责人取新职能、案例保存跨案例推职能、单条编辑字段 / 重判 Overdue / 保留提醒记录 / 推职能、权限 403 / 404 / 缺邮箱 422 / 无最终链接 422、带最终链接关掉最后一条则案例 Closed、日志带 taskId）、前端回归 47（新增：Status: All、全名显示与筛选、行内编辑发送的请求体、从日志打开被筛掉的待办、改负责人带出职能、缺邮箱前端拦截不丢输入、Dashboard 按全名）、滚动回归 16、ruff；种子库临时实例 8064（通知、SharePoint 全关）实测：接口改 3 条待办后全名与职能按预期推开、缺邮箱 422，页面截图核对 Follow-ups 行内编辑、日志 Edit、Dashboard "Overdue actions by owner" 为 Andreas Huber / Robert Nieczyporuk，1440px 宽无横向滚动。

Spec: non-spec

## Phase-30: 零件号改成表格行录入（像 Excel）

Status: `awaiting-acceptance`

Description: 两位同事反馈（截图 2026-10-20 交我整理）：提交页零件号多的时候不好用，例如 bundle B/2026/00135，原话是 "self registration 的 format 做成表格的模式" 和 "a row input theme (like Excel) can help (also timing wise), when you input that many numbers you can get lost in all the boxes"。现状：每个零件号一张卡片，11 个输入框分两列排，20 个零件号就是 220 个框。用户 2026-10-20 定：列顺序按委员会周会 Excel，编辑页这次一起改，下面 (1)～(6) 都做。列顺序（取自 KW20～KW39 Agenda / MM 表头，只留零件行字段、保持原相对顺序）：Type → Sourcing Type、Project/ Product → Project、Part Description、PN → Part Number、Recommended Supplier (s)、CQA PC PRICE → Pc Price CQA、Rec. Supplier Landed → Supplier Price (landed)、Average Volume、LT volume → Lifetime Volume、CQA Tooling → Tooling CQA、Rec. Supplier Tooling → Supplier Tooling Cost。范围：(1) 提交页零件号部分改成表格，一行一个零件号，列按上面的顺序；表头固定，行号列固定，每行有行尾删除按钮，显示零件号总数；(2) 从 Excel 复制多行多列后粘贴进表格，自动填满对应的行和列，行数不够时自动加行。复制内容带表头行时按表头名对列，委员会 Excel 中间夹着的其他列（Commodity、SWAT ID、Presenter、Spend、Comment、Saving 等）自动跳过；不带表头时按表格列顺序从光标所在格往右填。Type 原文按导入器同一规则归成 New / C/O / GCS（如 "New part"、"Carry over"）；(3) 键盘操作：Tab 往右，Enter 往下，在最后一行按 Enter 加新行；(4) Project / Sourcing Type / Recommended Supplier 列可以一键把一个值填到所有行；(5) 缺项在对应格子上标红并说明是哪一行，零件号重复录入时提示；(6) 案例编辑页的零件号部分同样改成表格，(2)～(5) 在编辑页也能用。注意事项（来自历史 Excel 的真实写法）：价格格子常带单位和第二种货币（`0,0865 Euro/pc` 换行 `0,0952 USD/pc`），粘贴时取与表单币种一致的那一行，认不出的保留原文并标红，不猜；小数点逗号和点号混用（`0,0865`、`0.6709`、`110.273 EUR`、`39,157 Euro`），像 `39,157` 这种既可能是 39.157 也可能是 39157 的值标红请人确认，不自动换算；`tbd` 之类非数字标红；零件号按文本保存（保留前导零）；一个格子里写了多个零件号（KW20 的 `R004H119A, R004H128A, …`）时标红，请人拆成多行（实现时定：拆行会让一行的价格被复制给几个零件号）；不引入表格库，手写表格加粘贴处理（Handsontable 商用收费）。实现（2026-10-20）：前端 `PN_GRID_COLUMNS` 定列与表头别名，`pnGridHtml` / `wirePnGrid` 提交页与编辑页共用，输入框 id 沿用旧卡片命名；`parseGridNumber` / `readNumberText` 读数字：取与表单币种一致的那个值，只有一种分隔符且后面正好三位（`39,157`）时给出两种读法让人点选，产量列只收整数所以 `378.979` 读成 378979，K / Mio、负数、超过 4 位小数（服务端上限）、别的币种都标红；小数位照原样保留（10.50 仍是 10.50）。实现时另定的三点：粘贴时 Type / Project / Supplier 为空的格子沿用上一行（委员会 Excel 里同一 bundle 这几列是合并格，复制出来下面几行是空的）；新加的行先带上一行的这三列；重复零件号只标黄提示、不拦（KW37 里同一零件号按地区分两行是正常写法）。编辑页的零件号卡片编辑时移到两栏上方占满整行；进入编辑时原有数字记为已确认写法，没改过的 1.125 不会被当成歧义拦下。浏览器草稿没有做（提交页本来就不会因后台刷新重绘而丢内容，见回归用例 "Keep this"）。测试：`backend/tests/frontend-regression.mjs` 新增一条（数字读法、委员会表带表头粘贴、点选读法、Enter / Shift+Enter、删行、Fill all、重复提示、缺项标红、编辑页），前端回归 48 条、滚动回归 16 条、pytest 541 条、ruff 全过。另用真实 KW39 文件在隔离的临时服务上走通了粘贴 → 提交 → 审批 → 编辑保存，存库值与表格一致。已知问题（2026-10-20 用户试用时发现，用户定"暂时先这样"）：Excel 里本来是数字、只是格式设了千分位的格子，复制出来是 `277,000`，也被当成两种读法标红要点选——KW39 六行里 8 个红格有 7 个是这种。改进方向：从剪贴板附带的 HTML 副本里取数字格子的原始值（待用用户电脑上的真实 Excel 剪贴板核实格式），只对人手写的文字格子（`39,157 Euro`）继续问；另加"同类歧义一键全部按千分位读"的按钮。

Spec: non-spec
