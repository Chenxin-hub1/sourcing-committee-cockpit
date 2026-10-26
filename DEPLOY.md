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
nano .env   # 至少改 SC_BOOTSTRAP_ADMIN_EMAIL / SC_BOOTSTRAP_ADMIN_PASSWORD；其余项见文件内注释
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
| `SC_PUBLIC_URL` | 同事在自己电脑上访问的地址（提醒邮件里的链接前缀）。不写就是正式服务器 `http://10.13.100.10:8031/`；Docker 方式是 `http://<服务器IP>:8062/`。写成 `localhost` / `127.0.0.1` 不算数，仍用正式服务器地址——收信人点链接时它指的是收信人自己的电脑 |
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
| 术语归一（Cluster / Commodity） | 从 Excel 导入的 Commodity 原文自动映射到三个固定 Cluster + 规范 Commodity 名（词表在 `backend/app/commodities.py`，v3 Phase-18）；服务启动时按词表版本自动重算一次，`python -m app.migrations normalize-clusters` 可先看映射表（`--apply` 写回）。认不出的原文保持原样，列在预览的 notes 里，补进词表后把 `VERSION` 加一即可 |
| 导入历史 Excel | 最简单：Sourcing admin 登录首页，"Stored weekly files" 下拉框旁点 "Add all not yet imported" 再 Import（36 周历史文件随程序放在 `backend/app/history/`，`git pull` 就有）。命令行方式：把 "KW39, 23.09.2026" 这类周文件夹（含里面的 Agenda / MM .xlsx）拷到服务器，`python -m app.migrations import-excel <文件夹> --apply`（免安装方式用 `..\windows-portable\python\python.exe -m app.migrations …`，在 backend 目录下跑）；先不带 `--apply` 看预览。每周只放一份文件（优先 MM）。同一周再跑会替换上次导入的案例 |
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

- **个人账号**：每人用公司邮箱（`SC_ALLOWED_EMAIL_DOMAINS`，默认 `zf.com,zf-lifetec.com`）在右上角 "Log in → Register" 自注册，只填姓名和邮箱，**不设密码**，之后凭邮箱直接登录（v3 Phase-16，领导要求）。只有 **Sourcing admin** 用密码登录：提升某人为 admin 时系统生成临时密码（Accounts 页只显示一次），本人首次登录后必须改，至少 6 位。新账号默认 **User**（提交登记、查看）。注意：邮箱免密意味着内网里任何人都能以别人的邮箱身份提交或（Manager 时）审批，这是业务方接受的取舍。三种角色：User；**Manager**（采购经理与 NPI 经理共用，内部代号 `npi_manager`；另可确认 / 退回登记、编辑与删除案例、记录决议与待办、发提醒、管理案例文件）；**Sourcing admin**（另可改汇率、登记截止、提醒设置，并在 Accounts 页管理账号）。角色由 Sourcing admin 在 Accounts 页提升或收回、停用账号；所有权限由**服务端**按角色强制，前端隐藏按钮只是附加层。
- **首个管理员**：`.env` 填 `SC_BOOTSTRAP_ADMIN_EMAIL` / `SC_BOOTSTRAP_ADMIN_PASSWORD`，启动时若还没有任何可用的 Sourcing admin 就用它建一个（已有则忽略）。登录后在 Accounts 页把真人提升为 Sourcing admin，再停用这个引导账号。管理员全部丢失时，重新填上这两项并重启即可恢复。
- **管理员忘记密码**：还没有邮件通道，由另一位 Sourcing admin 在 Accounts 页 "Reset password" 生成一次性临时密码（只显示一次），私下告知本人；本人用临时密码登录后必须先改密码才能操作，其它会话同时失效。非管理员没有密码，不存在忘记。
- **会话与防爆破**：登录令牌存浏览器（同一浏览器关掉再开仍保持登录）、7 天过期，登出、改密码或被停用后失效；服务端只存令牌哈希。同一来源 15 分钟内输错 5 次锁 5 分钟；同一来源每小时最多注册 10 个账号。
- 浏览案例、看板、下载演示文件**不需要登录**（内网可达即用）；**提交登记必须登录**，提交人姓名 / 邮箱取自账号（请求里填的不作数）。首页的 "Import weekly committee Excel"（把每周的 Agenda / MM 导入成案例）仅 Sourcing admin 可用。
- 从 v2 升级：`SC_ADMIN_PASSWORD` 已无作用，可从 `.env` 删除；原共享口令的会话全部失效，每人重新注册即可。

## 提醒真实外发（邮件 + Teams）

服务器容器 7×24 运行，每天自动执行提醒检查（启动时 + 每小时）：任务**到期当天**、以及**逾期后每 N 天**（规则在 Follow-ups 页可调）自动发送，无需任何人打开页面。日志中 Delivery 列显示每通道投递结果；未配置的通道显示 `skipped`，不会报错。

除定时提醒外，**审批结果邮件**（管理员确认/退回登记时发给提交人——即提交页承诺的通知）也走同一条 SMTP 通道：未配置时同样记 `skipped`，Approvals 页 Recently Processed 列表可见每次通知的投递结果。

**待办反馈（v3 起）** 也走同一通道：有人对待办汇报进展时，邮件通知全部 Manager 与 Sourcing admin 账号（收件人就是账号邮箱）；approve / reject 后结果邮件发给待办的提醒收件人并抄送汇报人。投递结果记在反馈条目上，案例页可见。汇报时附的凭证（PowerPoint / PDF / Excel / Word / Outlook 邮件 .msg / .eml）与演示文件同一存放（SharePoint 文档库或本地 `data/uploads/`）。

`sent` 表示 SMTP 中继或 webhook 已接受请求，不代表收件人已读。SMTP 部分收件人被拒收、Webhook 返回重定向或错误状态时会记录失败；部分邮件可能已投递，重试前可先确认收件情况。

SMTP 中继可在 `.env` 中配置后通过 `docker compose up -d` 生效。Teams 新接入使用 Power Automate / Workflows，并先与 IT 确认请求契约及认证方式。

### 通知列表（2026-10-13 起：不等 IT 的发信 / 发 Teams 路径）

IT 只给应用批了 SharePoint 权限（Sites.Selected + 站点 write），没有 Mail.Send；公司数据策略又禁用了 Power Automate 的 Teams webhook 触发器（默认环境与 Dev 环境实测都报 `restricts use of these apis: TeamsWebhookRequestReceived`）。所以改用 **SharePoint 列表中转**：系统把每条通知写成站点里 `Cockpit Notifications` 列表的一行，Power Automate 流 **Sourcing Cockpit - Notifications**（passivesafety 默认环境）用 SharePoint "When an item is created" 触发，按 `channel` 分支用流所有者自己的 Outlook / Teams 连接发出（邮件的发件人是公共邮箱 `Sourcing_reminder@zf-lifetec.com`，靠 Outlook 连接账号的 Send As 权限）。`.env` 填 `SC_NOTIFY_LIST_NAME=Cockpit Notifications`（站点沿用 `SC_SP_SITE_URL`）。建列表、加共同所有者、换连接的步骤见 [`docs/notify-flow-setup.md`](docs/notify-flow-setup.md)。

| 通道 | 选择顺序 |
| --- | --- |
| 邮件（5 种通知都算） | SMTP（`SC_SMTP_HOST`）→ Graph 发信（凭据 + `SC_GRAPH_SENDER`）→ 通知列表 → `skipped` |
| Teams（提醒） | Graph 直发频道 → 通知列表 → 旧 webhook（`SC_TEAMS_WEBHOOK_URL`）→ `skipped` |

列（内部名与流里的 `triggerBody()?['…']` 一一对应，改名要同步改流）：`Title`（= 标题）、`channel`（`email` / `teams`）、`to` / `cc`（多行纯文本，分号分隔，Outlook 连接器的写法）、`subject`、`html`（多行纯文本：正文转义后换行变 `<br>`，给 Outlook 的 HTML 正文与 Teams 消息用）。应用的 write 角色**不能建列表**（实测 403），列表由有站点 ManageLists 权限的人建；`python -m app.migrations notify-list-setup` 只读核对列是否齐全（缺列时它会尝试补列，同样可能 403）。

**安全关卡**：流的触发器设了 Trigger condition，只处理创建者为 `SharePoint App`（系统的 Graph 应用身份）的新行。否则站点里任何有编辑权限的人都能往列表加一行，借流所有者的邮箱或 Teams 发任意内容。这个条件不能删，细节见 docs。

投递结果里的 `sent` 表示"已写进列表"；流按触发器的轮询间隔（定义里是每分钟，实际以许可证允许的最短间隔为准）读到后才真正发出，结果看流的运行记录。已知限制（微软连接器文档）：Outlook 每个连接每 60 秒 300 次；Teams 以 Flow bot 发消息每个连接每 5 分钟 25 条，单日过期提醒很多时 Teams 部分可能被限流；流所有者离职 / 改密码后要换连接；列表行不会自动清理。

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

**连通检查（2026-10-12 起，替代 explore 脚本）**：`.env` 填好后，在 backend 目录运行（免安装部署用 `..\windows-portable\python\python.exe -m app.migrations graph-check --write-test`）：

```
python -m app.migrations graph-check                # 令牌 → 站点 → 列表与文档库 → 建单列表的列（只读）
python -m app.migrations graph-check --write-test   # 另在文档库 Sourcing Cockpit/_connection-test 传一个小文件再连同文件夹删掉
```

输出不含密钥。常见失败：`[1/5] Token … AADSTS90002 Tenant not found` = Tenant ID 与 Client ID 填反了（2026-10-12 本机实际遇到；zf-lifetec / passivesafety 的租户 ID 是 `87f9dc52-…`）；`AADSTS7000215` = 密钥填成了 Secret ID 或已过期；`[2/5] Site … 403` = IT 还没对该站点授权；`[5/5] … FAILED` = 站点授的是 read 不是 write；超时 = 服务器出不了外网，需要代理（httpx 认 `HTTPS_PROXY` 环境变量）。IT 授权的站点是 `https://passivesafety.sharepoint.com/sites/SCC_PROC_SOURCINGCOMMITTEE`（默认文档库 Documents，暂无自定义列表，建单 `SC_SP_LIST_NAME` 先留空）。

### 演示文件（v3 Phase-5）

提交人在提交页拖拽或选择 PPT / PDF / Excel / Word（单个 ≤ 100 MB，每条登记最多 10 个），提交成功后逐个上传；管理员在案例页可再加、可删。所有能打开驾驶舱的人都能下载。
- **文件名**（v3 Phase-15，领导要求）：系统里统一改名为 `YYYY.MM.DD 项目 零件描述 零件号, 供应商.ext`（如 `2026.09.30 MBEAL Spool PN123, XLX.pptx`；日期 = 上传日、服务器时区）。多零件 bundle：项目 / 供应商去重用 `+` 连接，零件取第一个并标 `+N`（`PN123+2`）。原文件名留在记录里，案例页显示 "uploaded as …"。待办反馈的凭证附件不改名。

- **存放位置**：Graph 凭据 + `SC_SP_SITE_URL` 配齐 → SharePoint 文档库 `SC_SP_LIBRARY_NAME`（留空 = 站点默认库 Documents）下的 `SC_SP_FOLDER/<案例号>/` 文件夹，同名自动改名；没配齐 → 服务器本地 `data/uploads/`。每个文件记住自己存在哪，配好 SharePoint 之后新文件去 SharePoint，之前的本地文件照样能下载。
- **权限**：与建单是**同一个**站点级授权（Sites.Selected + 对站点授 write 角色），站点级授权覆盖该站点所有列表与文档库，**不用另外申请**。只有 IT 只授了某个列表的权限，或文件要放到另一个站点时，才需要再找 IT。
- **下载**：驾驶舱服务器向 SharePoint 取一个几分钟有效的临时下载地址，浏览器跳过去下载——看文件的人不需要 SharePoint 权限。
- **上线决定（2026-09-28）**：先按**本地存放**上线（不填 `SC_GRAPH_*` / `SC_SP_*`），文件落在 `data/uploads/`，随 `./data` 卷持久化；服务器磁盘按每条登记最多 10 × 100 MB 估算预留。SharePoint 凭据到位后填进 `.env` 重启即切换，之前存在本地的文件照样能下载，不用迁移。
- **备份**：文件存在本地时，备份数据库之外还要带上 `data/uploads/`（如 `tar czf uploads-backup.tgz data/uploads`）。
- **边界**：退回的登记、删除的案例，其文件不会自动从存放处删除；上传中途断网不续传，重新上传即可。
- **首页上传区分两类（v3 Phase-20）**：Sourcing admin 首页的 "Upload weekly committee data" 卡片分 **1 · Meeting minutes**（周会 Agenda / MM Excel，导入成案例）与 **2 · Presentations**（每个案例的 PDF / PPT）。Presentations 下拉框列出文件库里的文件和自动匹配到的案例（依次按 SWAT / bundle 号、零件号、周文件夹 + 文件名开头的案例序号，与 SharePoint 周文件夹里 `1. 110000034978 SPR8 Tube_….pdf` 的命名一致），可单个或 "Attach all matched" 批量挂到各自案例；"Upload presentations…" 从本机传进文件库，自动放进匹配案例所在周的文件夹（如 `KW15, 08.04.2026/`），对不上的放 `Unsorted/`，再到案例页手工挂。
- **服务器演示文件库（v3 Phase-18，领导要求"从服务器上选"）**：历史案例的演示文件逐案上传太慢，管理员把 PPT / PDF / Excel / Word 直接放进服务器目录 `SC_PRESENTATION_LIBRARY_DIR`（默认 `data/presentations/`，可按周建子文件夹如 `KW39, 23.09.2026/`；免安装部署就是 `D:\apps\sourcing-committee-cockpit\backend\data\presentations\`），Manager 及以上在案例页 "Sourcing Presentation Files" 卡片的下拉框里选一个点 **Attach from server**，文件按案例改名复制进 `data/uploads/`（配了 SharePoint 就进文档库），库里的原件不动、同一份可挂到多个案例。只列允许的类型，`~$` 临时文件与子目录外的路径一律忽略。

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
| Comments | **多行文本**（纯文本） | 提交人备注（可能超过 255 字；单行文本上限 255，超长会让建单失败） |
| CaseLink | 单行文本 | 案例深链（确认登记后可打开） |

**边界**：v3 Phase-7/8 新增的商务字段（件价、模具费、Tooling Payment、BPG / FRA、可选项）与例外登记标记**不写入** SharePoint，只存在驾驶舱里——要同步需先在 List 加列并扩展 `graph.py` 的字段映射；每次提交只建一条，确认登记不会重复建；审批结果、案例编辑**不回写**（Status 列停留在提交时的值）；建单失败不影响提交，也无自动重试——同一案例再次提交会生成新 item。令牌与站点/List id 有进程内缓存但按配置键区分，改 `.env` 后 `docker compose up -d` 即生效。联调可先跑只读探索脚本 `backend/scripts/explore_sharepoint_graph.py` 核对站点、List 与内部列名。
