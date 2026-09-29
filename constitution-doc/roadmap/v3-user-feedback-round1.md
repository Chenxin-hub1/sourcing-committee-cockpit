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

Status: `awaiting-acceptance`

Description: 领导（RB sourcing admin）2026-09-29 看演示后的四条要求，用户同日逐条确认。(1) Peak Year Spend 与 Lifetime Spend 从零件行上移到案例级，各填一个 bundle 金额并改为必填（buyer 不用按单个零件号拆分）；(2) Project、Sourcing Type、Recommended Supplier 下到零件行（一个 bundle 可混不同项目、GCS / New、不同供应商），案例级自动去重汇总，同一零件号按区域定给不同供应商时在供应商栏自由文本写明；(3) 上传的演示文件按领导例子改名 `2026.09.30 MBEAL Spool PNxxx, XLX`（日期 项目 零件描述 零件号, 供应商），bundle 案例项目 / 供应商去重用 "+" 连接、零件取第一个并标 "+N"，原文件名保留可查；(4) 角色 "NPI manager" 显示名改为 "Manager"（内部代号不变，账号无需迁移），采购经理 carrie.wang 用该角色、领导本人用 Sourcing admin，四位区域联系人只是建账号名单，不做按区域指派，CLS 不加区域；FRA 旁批注 "case" 指按案例填，现状已是。旧案例不迁移：案例级金额本来就是各行之和，零件行上的旧金额不再显示；旧多零件案例的 Excel 行级三列回退到案例级值。实现：`SubmissionIn` / `CaseEditIn` 带案例级 `peakYearSpend` / `lifetimeSpend`（编辑不带时原值不动），`PartNumberIn` 带 `project` / `sourcingType` / `recommendedSupplier`（行上留空沿用请求的案例级值，`logic.bundle_rows`），案例级三字段由 `logic.bundle_summary` 去重汇总；`logic.convert_spend` 改为折算 bundle 金额、零件行只折算件价（旧记录换算走 `_convert_legacy_rows`）；`exports.columns` 的 Type / Project / Supplier 改行级（行上没有回退案例级）、Peak Year / LT Spend 改案例级合并；`files.bundle_file_name` 生成文件名（日期取服务器时区 `SC_TIMEZONE` 的当天，上线前把它设成 Europe/Berlin 或 Asia/Shanghai），记录新增 `originalName`，案例页显示 "uploaded as …"，待办反馈附件不改名；`accounts.ROLE_LABELS` 的 npi_manager 显示 "Manager"。前端：提交页零件行带 Project（datalist）/ Sourcing Type / Recommended Supplier，案例级三个字段移除，Aggregate 行改成两个 bundle 金额输入（欧元预览与 BPG 提示跟随），审批页 / 详情页零件表改列，编辑页同样按行 + bundle 金额，CSV 的零件明细列改写项目 / 类型 / 供应商。验证（2026-09-29）：pytest 326（新增 4 项：金额非法值在提交与编辑两处都拒、旧客户端行级金额被忽略不 422、bundle 金额必填且行不带金额、三字段按行 + 汇总 + 留空回退 + 两边都空 422 + 编辑改行汇总跟着变 + 单零件顶层；Excel 三列按行不合并、两金额列合并；文件改名与 originalName、SharePoint 路径用新名；BPG 门槛改读 bundle 金额）、前端回归 37（新增 1 项：两行零件不同项目 / 类型 / 供应商 + 缺 bundle 金额拦截 + 预览与 BPG 提示 + 载荷；详情表与 "uploaded as"；编辑页按行改供应商 / 类型与 bundle 金额的 PUT 载荷）、滚动回归 16、ruff；隔离实例（演示库副本，8063）真实流程：缺金额 422 → 行缺供应商 422 → 美元提交两行 bundle（578,000 / 3,373,000 USD → €494,017 / €2,882,906，行无金额，汇总 "MBEAL, ACR8" / "New, GCS"）→ 上传 `Präsentation1 (final)(2).pptx` 存为 `2026.09.28 MBEAL+ACR8 ECU Housing, WMS R003B136A+1, Ningbo Deke+Kimball (EU) _ Deke (AP).pptx` → 确认 → 案例页再传 PDF 同规则 → 只改决议金额不动、改行供应商汇总变 "Ningbo Deke"、改 bundle 金额按 1.17 重算 → 议程导出行级 Type / Project / Supplier、金额合并只在首行。截图 `~/backups/sourcing-cockpit/e2e-screenshots-2026-09-29-phase15/`，代码包 `after-phase15-20260929.tar.gz`。8062 已重启到 Phase-15 代码。补充（2026-09-29 部署后领导反馈导出币种列是 USD）：演示种子 `seed.json` 一次性换算成欧元（OP 1.17，带 fx 快照），Legacy Excel Upload 生成的演示批次直接标 EUR，新装的库导出不再出现 USD；整库换算的测试改为自己放旧记录。同日部署收尾：仓库新增 `windows-portable/`（免安装 Python 3.12.10 + 同版本 wheel）与 `start.bat`，`SC_PORT` 同时决定 start.bat 端口与 docker-compose 宿主机端口。

Spec: non-spec

## Phase-16: 邮箱免密登录

Status: `awaiting-acceptance`

Description: 领导 2026-09-29 试用后不想要密码；用户同日定：只有 Sourcing admin 用密码登录，其他人用公司邮箱注册（只填姓名 + 邮箱）、凭邮箱直接登录，权限仍由管理员在 Accounts 页按人设置。风险已向用户说明（内网里任何人可冒用他人邮箱，Manager 也免密），用户拍板按此做。实现：注册不收密码、账号不存哈希；登录只看邮箱，账号角色为 admin 时要求密码（未带时 401 "Password required."，前端据此展开密码框）；改密码与重置密码只对 admin 账号；提升为 admin 时服务端生成临时密码随响应返回一次并置 mustChangePassword，降级时清除该标记；`public_user` 增加 `hasPassword`。前端：登录面板只有邮箱，密码框按需展开；注册面板去掉密码；账号菜单只有 admin 有 "Change password"；Accounts 页 Reset password 只在 admin 行，提升为 admin 时显示临时密码提示。验证（2026-09-29）：pytest 328（账号用例重写：注册规则、邮箱登录 / 未注册 401、管理员密码规则与登录、提升发临时密码且立即要密码、重置只对 admin、降级回邮箱登录）、前端回归 37（登录面板按需展开密码框、邮箱直登、注册无密码、提升 admin 显示临时密码）、滚动回归 16、ruff。

Spec: non-spec
