# 部署说明（服务器端）

从 git 拉取代码到 Linux 服务器，一条命令起服务。整个过程不需要在服务器上装 Python——只要有 Docker。

## 前提

> 服务器上没有管理员权限、装不了 Docker？看 [windows-portable/README.md](windows-portable/README.md)：免安装 Python 运行时，`git clone` 后双击 `start.bat` 即可（这条路监听 **8031** 端口，Docker 那条路是 8062）。

- 一台内网 Linux 服务器，能访问外网（拉基础镜像）或已有 Docker 镜像缓存
- 服务器上已安装 **Docker Engine + Docker Compose**（`docker compose version` 能出版本号即可；没有则让 IT 装，或参考官方文档 docs.docker.com/engine/install）
- 8062 端口可用（被占用见下方「改端口」）

## 首次部署

```bash
# 1) 拉代码（换成你的仓库地址）
git clone git@github.com:Chenxin-hub1/sourcing-committee-cockpit.git sourcing-cockpit   # 私有仓库：服务器上的 SSH 密钥要先加到 GitHub（或改用 https 地址 + 个人令牌）
cd sourcing-cockpit

# 2) 设置对外访问地址与首个 Sourcing 管理员账号（提醒消息里的链接前缀 + 启动时建立的第一个管理员）
cp .env.example .env
nano .env   # 至少改 SC_PUBLIC_URL 与 SC_BOOTSTRAP_ADMIN_EMAIL / SC_BOOTSTRAP_ADMIN_PASSWORD；其余项见文件内注释
# 把 id -u / id -g 的输出填入 .env 的 SC_UID / SC_GID，匹配宿主机目录所有者
id -u
id -g

# 3) 建数据目录（用当前登录用户建，容器以同身份写入）
mkdir -p data

# 4) 构建并启动
docker compose up -d --build

# 5) 验证
curl http://127.0.0.1:8062/api/bootstrap   # 应返回 cases / submissions JSON
docker compose ps                          # STATUS 一栏应显示 (healthy)
```

浏览器访问 `http://<服务器IP>:8062/` 即可使用。首次初始化空数据库默认装载演示数据（22 个案例 + 1 条待审提交）；正式使用请在首次启动前设置 `SC_SEED_ON_EMPTY=false`。初始化记录落库后，重启或删除全部案例都不会再次灌入演示数据。

Compose 通过 `SC_UID` / `SC_GID` 指定容器身份，默认均为 1000；`data` 目录必须属于相同身份。当前写锁与限流为进程内实现，镜像明确使用 `--workers 1`，请保持单实例部署。

## 上线前清单（2026-09-29，领导要求尽快试用）

`.env` 里这几项上线前必须定好，其余（SMTP / Teams / SharePoint）等 IT 参数到位再填、重启即生效：

| 项 | 填什么 |
| --- | --- |
| `SC_PUBLIC_URL` | 同事访问的地址，如 `http://<服务器IP>:8062/`（免安装方式是 `:8031/`；提醒邮件里的链接前缀） |
| `SC_SEED_ON_EMPTY` | `false`（正式库从空开始，不灌 22 条演示案例） |
| `SC_TIMEZONE` | `Europe/Berlin`（登记截止周一 23:59 按这个时区；文件名日期也是） |
| `SC_BOOTSTRAP_ADMIN_EMAIL` / `_PASSWORD` | 领导本人的邮箱（xiangwei.chen@zf-lifetec.com）+ 初始密码；他首次登录后自己改密码 |
| `SC_UID` / `SC_GID` | 服务器上 `id -u` / `id -g` 的输出 |

启动后的人工步骤：领导登录 → 让 Carrie 与四位区域联系人各自用公司邮箱注册 → 领导在 Accounts 页把他们提升为 **Manager**；其他 buyer 自行注册即可提交（User）。如果先用演示库试用，正式启用前删掉演示案例或换空库重启。

## 日常升级

```bash
cd sourcing-cockpit
git pull
docker compose up -d --build
```

数据在宿主机 `./data/` 目录里，重建容器**不会**丢数据。

**v3 Phase-13（周号改 ISO 周 / KW）**：升级后第一次启动会自动把已有案例的周号换算一次（有会议日期的按日期算，没有日期的模板演示数据 +1；库里记下标记，之后不再重复），不用手动操作。升级前照例先做一次在线备份（见下表）。

## 运维备忘

| 事项 | 做法 |
| --- | --- |
| 看日志 | `docker compose logs -f` |
| 重启 | `docker compose restart` |
| 停止 | `docker compose down` |
| 健康检查 | compose 已内置（`/api/health`，30s 一次）；`docker compose ps` 看 `(healthy)` |
| 备份数据 | 演示文件存本地时连 `data/uploads/` 一起备份（见 Graph 接入 → 演示文件）。数据库：WAL 模式下直接 `cp` 数据库文件有风险，用在线备份（不用停服务）：`docker compose exec cockpit python -c "import sqlite3; s=sqlite3.connect('/app/data/cockpit.db'); d=sqlite3.connect('/app/data/cockpit-backup.db'); s.backup(d); d.close()"`，再把 `data/cockpit-backup.db` 拷走 |
| 恢复/迁移服务器 | 停止目标服务，将上面的在线备份放到新的 `data/cockpit.db`，确认目录所有者与 `SC_UID` / `SC_GID` 一致，再启动；勿与旧库的 WAL/SHM 文件混放 |
| 改端口 | `docker-compose.yml` 里 `"8062:8000"` 左边（对外端口）改成想要的端口，如 `"80:8000"`；右边 8000 是容器内监听，保持不动 |
| 改提醒时区 | `.env` 里 `SC_TIMEZONE=Asia/Shanghai`（IANA 名）后 `docker compose up -d` |
| 清空演示数据、从零开始 | 先完成备份，再 `docker compose down`；将原 `data` 目录改名留存，创建新的空目录；设置 `SC_SEED_ON_EMPTY=false` 后启动 |
| 换 PostgreSQL | 当前交付仅验证 SQLite；切换需补充异步数据库驱动、连接配置、迁移及并发验证，不能只改连接串 |

### 旧美元案例换算成欧元（v3 Phase-12，一次性）

EUR 改造之前登记的案例（含模板演示数据）没有币种信息、按美元显示。按财务 OP 汇率一次性换算成欧元，原美元金额保留为 "entered" 金额，案例记下所用汇率与换算时间；之后编辑仍按美元填写、按同一汇率折算。

1. 管理员在 Dashboard 汇率卡片按 OP 表录入：Rate basis 填口径（如 `OP 2025 plan rates 2026`），`1 EUR = ? USD` 填 `1.17`，保存。
2. 按上表"备份数据"做一次在线备份。
3. 先预览（只统计，不写库）：`docker compose exec cockpit python -m app.migrations usd-to-eur`
4. 在没人操作时执行：`docker compose exec cockpit python -m app.migrations usd-to-eur --apply`

不想用 Dashboard 上的汇率，可加 `--per-eur 1.17 --basis "OP 2025 plan rates 2026"`。重复执行是安全的：已是欧元的记录不会再换算。

## 安全说明（v3 起：个人账号）

- **个人账号**：每人用公司邮箱（`SC_ALLOWED_EMAIL_DOMAINS`，默认 `zf.com,zf-lifetec.com`）在右上角 "Log in → Register" 自注册，密码至少 10 位，注册即登录。新账号默认 **User**（提交登记、查看）。三种角色：User；**Manager**（采购经理与 NPI 经理共用，内部代号 `npi_manager`；另可确认 / 退回登记、编辑与删除案例、记录决议与待办、发提醒、管理案例文件）；**Sourcing admin**（另可改汇率、登记截止、提醒设置，并在 Accounts 页管理账号）。角色由 Sourcing admin 在 Accounts 页提升或收回、停用账号；所有权限由**服务端**按角色强制，前端隐藏按钮只是附加层。
- **首个管理员**：`.env` 填 `SC_BOOTSTRAP_ADMIN_EMAIL` / `SC_BOOTSTRAP_ADMIN_PASSWORD`，启动时若还没有任何可用的 Sourcing admin 就用它建一个（已有则忽略）。登录后在 Accounts 页把真人提升为 Sourcing admin，再停用这个引导账号。管理员全部丢失时，重新填上这两项并重启即可恢复。
- **忘记密码**：还没有邮件通道，由 Sourcing admin 在 Accounts 页 "Reset password" 生成一次性临时密码（只显示一次），私下告知本人；本人用临时密码登录后必须先改密码才能操作，其它会话同时失效。
- **会话与防爆破**：登录令牌存浏览器（同一浏览器关掉再开仍保持登录）、7 天过期，登出、改密码或被停用后失效；服务端只存令牌哈希。同一来源 15 分钟内输错 5 次锁 5 分钟；同一来源每小时最多注册 10 个账号。
- 浏览案例、看板、下载演示文件**不需要登录**（内网可达即用）；**提交登记必须登录**，提交人姓名 / 邮箱取自账号（请求里填的不作数）。首页的 Legacy Excel 上传（演示功能，一次注入 18 条随机案例）仅 Sourcing admin 可用。
- 从 v2 升级：`SC_ADMIN_PASSWORD` 已无作用，可从 `.env` 删除；原共享口令的会话全部失效，每人重新注册即可。

## 提醒真实外发（邮件 + Teams）

服务器容器 7×24 运行，每天自动执行提醒检查（启动时 + 每小时）：任务**到期当天**、以及**逾期后每 N 天**（规则在 Follow-ups 页可调）自动发送，无需任何人打开页面。日志中 Delivery 列显示每通道投递结果；未配置的通道显示 `skipped`，不会报错。

除定时提醒外，**审批结果邮件**（管理员确认/退回登记时发给提交人——即提交页承诺的通知）也走同一条 SMTP 通道：未配置时同样记 `skipped`，Approvals 页 Recently Processed 列表可见每次通知的投递结果。

**待办反馈（v3 起）** 也走同一通道：有人对待办汇报进展时，邮件通知全部 Manager 与 Sourcing admin 账号（收件人就是账号邮箱）；approve / reject 后结果邮件发给待办的提醒收件人并抄送汇报人。投递结果记在反馈条目上，案例页可见。汇报时附的凭证（PowerPoint / PDF / Excel / Word / Outlook 邮件 .msg / .eml）与演示文件同一存放（SharePoint 文档库或本地 `data/uploads/`）。

`sent` 表示 SMTP 中继或 webhook 已接受请求，不代表收件人已读。SMTP 部分收件人被拒收、Webhook 返回重定向或错误状态时会记录失败；部分邮件可能已投递，重试前可先确认收件情况。

SMTP 中继可在 `.env` 中配置后通过 `docker compose up -d` 生效。Teams 新接入使用 Power Automate / Workflows，并先与 IT 确认请求契约及认证方式。

微软最新公告确认旧版 Teams Office 365 Connectors 于 2026-05-18 至 2026-05-22 停用，新申请应采用 Workflows，不能再申请旧 Incoming Webhook Connector。[微软退役公告](https://devblogs.microsoft.com/microsoft365dev/retirement-of-office-365-connectors-within-microsoft-teams/)

当前程序的 Flow 请求只发送 JSON，尚未附带 Entra Bearer Token。若 IT 使用限制租户或指定应用身份的 HTTP 触发器，需先补充 OAuth 调用能力，单填 URL 不够；正式方案优先采用受认证的调用方式。许可及连接器是否允许由 IT 核定。[HTTP 触发器认证](https://learn.microsoft.com/en-us/power-automate/oauth-authentication)

```bash
# 邮件（公司 SMTP 中继）
SC_SMTP_HOST=<IT 提供>
SC_SMTP_PORT=25            # 按 IT 提供修改
SC_SMTP_STARTTLS=false     # IT 要求加密时改 true
SC_SMTP_USER=              # 通常内网中继免认证；需要时填
SC_SMTP_PASSWORD=
SC_SMTP_FROM=sourcing-cockpit@zf.com   # 或 IT 分配的专用发件邮箱

# Teams
SC_TEAMS_WEBHOOK_URL=<Webhook URL>
SC_TEAMS_WEBHOOK_FORMAT=flow    # 工作流接收下方 to / subject / text 契约，再转发 Teams
```

### 向 IT 申请的内容（可直接转发）

> **中文说明**：内部工具 Sourcing Committee Cockpit（Docker 部署于内网 Linux 服务器）需要两件能力：
> 1. **发提醒邮件**：请提供内部 SMTP 中继的**主机名、端口**，是否要求 STARTTLS/账号密码，以及允许的**发件人地址**（建议专用邮箱如 sourcing-cockpit@zf.com）。
> 2. **发 Teams 消息**：使用 **Power Automate / Workflows** 建流，接收下方 JSON 后向指定频道或收件人发送消息；确认触发器认证、所需许可、工作流负责人及故障通知。请提供端点与允许调用的应用身份要求；采用 Entra 认证时，开发侧将补充令牌获取与传递。
>
> **English (for IT)**: Internal tool "Sourcing Committee Cockpit" (Docker, intranet Linux server) needs:
> 1. **Outbound reminder email**: an internal SMTP relay — hostname, port, whether STARTTLS/auth is required, and an approved sender address (e.g. sourcing-cockpit@zf.com).
> 2. **Teams messages**: provision a Power Automate / Workflows flow that accepts the JSON contract below and posts to the designated channel or recipient. Please confirm authentication, licensing, ownership, and failure notifications, and provide the endpoint and caller identity requirements. The application currently sends JSON without a bearer token; development will add Entra authentication where required.

### Power Automate 流的请求契约（`SC_TEAMS_WEBHOOK_FORMAT=flow`）

应用会向该 URL POST 如下 JSON；工作流需显式读取这些字段，并将 `text` 映射到 Teams 消息正文。按收件人私发时使用 `to`，发频道时由工作流固定目标频道。这里是本项目约定，并非任意 Workflows 模板都能直接接受的通用格式：

```json
{ "to": "l.novak@zf.com", "subject": "Follow-up Task for Sourcing Case SWAT-10555", "text": "<完整提醒正文>" }
```

保留的 `teams` 格式只 POST `{"text": "<完整提醒正文>"}`，用于明确接受此字段的自定义工作流兼容；不代表旧版 Teams Connector 仍可使用。当前审批结果邮件仍走 SMTP，不会自动经此 Flow 发出邮件。

## Graph 接入（SharePoint 建单 + 演示文件 + 邮件兜底 + Teams 认证，可选）

以下配置都写在项目根目录 `.env`，由 `docker-compose.yml` 逐项传进容器（容器里读不到 `.env` 文件本身；新增配置项时两边都要加，测试 `test_config.py` 会检查）。

一套 Entra 应用注册凭据（`SC_GRAPH_TENANT_ID` / `SC_GRAPH_CLIENT_ID` / `SC_GRAPH_CLIENT_SECRET`）可同时服务三件事，按 `.env` 各项是否填写独立启停：

| 能力 | 启用条件 | 未启用时 |
| --- | --- | --- |
| SharePoint 建单 | 凭据 + `SC_SP_SITE_URL` + `SC_SP_LIST_NAME` 齐备 | 提交照常，记 `skipped` |
| 演示文件存 SharePoint 文档库（v3 Phase-5） | 凭据 + `SC_SP_SITE_URL` 齐备 | 文件存服务器本地 `data/uploads/` |
| 邮件（Graph sendMail） | SMTP 未配置，且凭据 + `SC_GRAPH_SENDER` 齐备 | 记 `skipped` |
| Teams（Graph 直发频道） | 凭据 + `SC_TEAMS_TEAM_ID` + `SC_TEAMS_CHANNEL_ID` 齐备（优先于 webhook） | 回落 webhook，再无则记 `skipped` |

**邮件通道选择**：配置了 `SC_SMTP_HOST` 优先走 SMTP 中继；未配置而 Graph 凭据与发件邮箱齐备时走 Graph `POST /users/{sender}/sendMail`（`saveToSentItems=false`）；两者皆空记 `skipped`。

**Teams 通道选择**：Graph 直发频道消息优先（`POST /teams/{id}/channels/{id}/messages`，与邮件共用凭据）；团队/频道 ID 未配时回落 Workflows / Power Automate webhook（见上节契约，Graph 凭据齐备时附带 Bearer）；两者皆未配置记 `skipped`。团队/频道 ID 从 Teams 网页版频道链接获取：链接中 `groupId=` 后是团队 ID，`19:` 开头的一段是频道 ID。

**已知限制（用户知情取舍）**：微软官方将「应用权限直发频道消息」定位为**迁移场景**，未来可能按数据量计费（[权限参考](https://learn.microsoft.com/en-us/graph/api/channel-post-messages)）。当前按业务决策采用直发；若 IT 或微软政策不允许，清空 `SC_TEAMS_TEAM_ID` / `SC_TEAMS_CHANNEL_ID` 即回落 webhook，无需改代码。

**向 IT 申请（Graph 部分）**：Entra 应用注册 + client secret；应用权限 **Sites.Selected**、**Mail.Send** 与 **ChannelMessage.Send**（均需管理员同意）；对目标站点授予 **write** 角色（Graph `POST /sites/{site-id}/permissions`）；建议用**应用访问策略**把 Mail.Send 限定到专用发件邮箱（如 sourcing-cockpit@zf.com），不给全租户发信权。

### 演示文件（v3 Phase-5）

提交人在提交页拖拽或选择 PPT / PDF / Excel / Word（单个 ≤ 100 MB，每条登记最多 10 个），提交成功后逐个上传；管理员在案例页可再加、可删。所有能打开驾驶舱的人都能下载。
- **文件名**（v3 Phase-15，领导要求）：系统里统一改名为 `YYYY.MM.DD 项目 零件描述 零件号, 供应商.ext`（如 `2026.09.30 MBEAL Spool PN123, XLX.pptx`；日期 = 上传日、服务器时区）。多零件 bundle：项目 / 供应商去重用 `+` 连接，零件取第一个并标 `+N`（`PN123+2`）。原文件名留在记录里，案例页显示 "uploaded as …"。待办反馈的凭证附件不改名。

- **存放位置**：Graph 凭据 + `SC_SP_SITE_URL` 配齐 → SharePoint 文档库 `SC_SP_LIBRARY_NAME`（留空 = 站点默认库 Documents）下的 `SC_SP_FOLDER/<案例号>/` 文件夹，同名自动改名；没配齐 → 服务器本地 `data/uploads/`。每个文件记住自己存在哪，配好 SharePoint 之后新文件去 SharePoint，之前的本地文件照样能下载。
- **权限**：与建单是**同一个**站点级授权（Sites.Selected + 对站点授 write 角色），站点级授权覆盖该站点所有列表与文档库，**不用另外申请**。只有 IT 只授了某个列表的权限，或文件要放到另一个站点时，才需要再找 IT。
- **下载**：驾驶舱服务器向 SharePoint 取一个几分钟有效的临时下载地址，浏览器跳过去下载——看文件的人不需要 SharePoint 权限。
- **上线决定（2026-09-28）**：先按**本地存放**上线（不填 `SC_GRAPH_*` / `SC_SP_*`），文件落在 `data/uploads/`，随 `./data` 卷持久化；服务器磁盘按每条登记最多 10 × 100 MB 估算预留。SharePoint 凭据到位后填进 `.env` 重启即切换，之前存在本地的文件照样能下载，不用迁移。
- **备份**：文件存在本地时，备份数据库之外还要带上 `data/uploads/`（如 `tar czf uploads-backup.tgz data/uploads`）。
- **边界**：退回的登记、删除的案例，其文件不会自动从存放处删除；上传中途断网不续传，重新上传即可。

### SharePoint 建单

用户**提交登记时**自动在站点目标 List 建一条 item。`.env` 三项凭据 + `SC_SP_SITE_URL` + `SC_SP_LIST_NAME` 任一留空 = 功能停用，提交照常。结果持久化在提交单 `sharepoint` 字段（when / result / itemId），Submit 页 Recent Submissions 与 Approvals 页可见：`created` = 建单成功，`skipped` = 未配置，`failed: …` = 失败（细节看 `docker compose logs`，常见 403 = 站点未授 write 角色，400 = List 缺列或类型不匹配）。

**向 IT 申请**：Entra 应用注册 + client secret；应用权限 **Sites.Selected**（需管理员同意）；再对该站点给应用授予 **write** 角色（Graph `POST /sites/{site-id}/permissions`，参考微软 Create permission 文档）。同一个站点级授权也覆盖该站点的文档库，演示文件上传不用另外申请。

**列契约**：先在站点建好目标 List 与下列列（**名称不带空格**，保证内部列名 = 显示名；类型按表）：

| 列名 | 类型 | 写入内容 |
| --- | --- | --- |
| Title（内置） | 单行文本 | `SWAT号 — 零件描述` |
| SubId | 单行文本 | SUB-0001 |
| SWATId | 单行文本 | 案例号（SWAT 或 Supplyon 原样） |
| PartNumber | 单行文本 | 首个零件号；多个时 `12345678 (+2)` |
| PartDescription | 单行文本 | 首个零件描述 |
| RecommendedSupplier | 单行文本 | 推荐供应商 |
| Region / Project / Cluster / SourcingType / DecisionLevel | 单行文本 | 对应提交字段；Region 可多选，写成 `EU + NA` |
| PeakYearSpend / LifetimeSpend | 数字 | 合计金额（EUR，按提交时的 OP 汇率折算，1 EUR = X 外币、做除法；原币与汇率只存在驾驶舱里） |
| Status | 单行文本 | 提交时状态（后续不回写） |
| Submitter / SubmitterEmail / SubmittedAt / MeetingDate | 单行文本 | 提交人与会议信息 |
| Screening | 单行文本 | 家族案例 / ECM 筛选答案摘要 |
| Comments | 单行文本 | 提交人备注 |
| CaseLink | 单行文本 | 案例深链（确认登记后可打开） |

**边界**：v3 Phase-7/8 新增的商务字段（件价、模具费、Tooling Payment、BPG / FRA、可选项）与例外登记标记**不写入** SharePoint，只存在驾驶舱里——要同步需先在 List 加列并扩展 `graph.py` 的字段映射；每次提交只建一条，确认登记不会重复建；审批结果、案例编辑**不回写**（Status 列停留在提交时的值）；建单失败不影响提交，也无自动重试——同一案例再次提交会生成新 item。令牌与站点/List id 有进程内缓存但按配置键区分，改 `.env` 后 `docker compose up -d` 即生效。联调可先跑只读探索脚本 `backend/scripts/explore_sharepoint_graph.py` 核对站点、List 与内部列名。
