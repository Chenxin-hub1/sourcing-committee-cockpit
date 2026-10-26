# 通知流：邮件与 Teams 经 Power Automate 发出

> 2026-10-13 建立。适用情况：IT 只给系统批了 SharePoint 权限，系统自己不能发邮件、不能发 Teams 消息。

## 为什么这样绕一圈

- 系统的 Graph 应用只有 **Sites.Selected + 站点 write** 权限，没有 Mail.Send。
- 公司数据策略禁用了 Power Automate 的 "When a Teams webhook request is received" 触发器，所以系统不能直接调用流。默认环境和 PP-Dev-PU-GR-Amber 实测都报 `restricts use of these apis: TeamsWebhookRequestReceived`。
- 变通办法是**用 SharePoint 列表当留言板**：系统要发通知时，在列表里写一行；流每隔一会儿检查一次，发现新行，就用流所有者自己的 Outlook 和 Teams 连接发出去（邮件以公共邮箱 `Sourcing_reminder@zf-lifetec.com` 的名义发）。

## 现在已经建好的东西

| 东西 | 位置 |
| --- | --- |
| 列表 **Cockpit Notifications** | 站点 `https://passivesafety.sharepoint.com/sites/SCC_PROC_SOURCINGCOMMITTEE` |
| 流 **Sourcing Cockpit - Notifications** | Power Automate，环境 **passivesafety (default)** |
| 系统配置 | `.env` 里 `SC_NOTIFY_LIST_NAME=Cockpit Notifications`（站点沿用 `SC_SP_SITE_URL`） |

### 列表的列

列名就是流里 `triggerBody()?['…']` 读取的名字。**改列名会让流读不到值**，改了要同步改流。

| 列 | 类型 | 内容 |
| --- | --- | --- |
| Title | 单行文本 | 标题（与 subject 相同，方便在列表里浏览） |
| channel | 单行文本 | `email` 或 `teams` |
| to | 多行纯文本 | 收件人，多个用分号隔开 |
| cc | 多行纯文本 | 抄送（只用于邮件），可以为空 |
| subject | 单行文本 | 标题 |
| html | 多行纯文本 | 正文：特殊字符已转义，换行已变成 `<br>` |

### 流的结构

1. **触发器**：SharePoint "When an item is created"，站点选 SCC_PROC_SOURCINGCOMMITTEE，列表选 Cockpit Notifications。
   - **Settings → Trigger conditions**（安全关卡，不能删）：
     `@equals(triggerOutputs()?['body/Author/Claims'], 'i:0i.t|00000003-0000-0ff1-ce00-000000000000|app@sharepoint')`
2. **Condition**：`triggerBody()?['channel']` 等于 `email`。
   - **True 分支**：Office 365 Outlook "Send an email (V2)"
     - To = `triggerBody()?['to']`（To 框要先在右侧齿轮里打开 "Use dynamic content"）
     - Subject = `triggerBody()?['subject']`
     - Body = `triggerBody()?['html']`
     - CC = `if(empty(triggerBody()?['cc']), null, triggerBody()?['cc'])`（抄送为空时传 null，CC 框同样要先打开 "Use dynamic content"）
     - From (Send as) = `Sourcing_reminder@zf-lifetec.com`（高级参数里勾选后手打，不用动态内容；见下文“发件人：公共邮箱”）
   - **False 分支**：Microsoft Teams "Post message in a chat or channel"
     - Post as = Flow bot
     - Post in = Chat with Flow bot
     - Recipient = `triggerBody()?['to']`（同样先打开 "Use dynamic content"）
     - Message = `triggerBody()?['html']`

## 安全：只发系统写入的行

列表默认继承站点权限，站点里任何有编辑权限的人都能往里加行。如果流对每一行都照发，任何人都能借流所有者的邮箱或 Teams，把任意内容发给任意人（越权代理，confused deputy）。

所以触发器加了一个触发条件：**只有创建者是系统应用的新行才会启动流**。系统通过 Graph 应用身份写入的行，“创建者”由 SharePoint 自动填成 `SharePoint App`（`i:0i.t|00000003-0000-0ff1-ce00-000000000000|app@sharepoint`）。用户在网页或接口里写的行，创建者是他本人，没法伪造。

2026-10-13 实测：用个人账号写的一行被跳过，等了两个检查周期都没有运行；系统写的一行正常发出。

剩余风险：其他同样对这个站点有写权限的 Graph 应用，写出的行创建者也是 `SharePoint App`。目前只有本系统的应用被授权到这个站点，以后 IT 再给别的应用授权时要记得这一点。

## 发件人：公共邮箱

2026-10-26 起，邮件以公共邮箱 `Sourcing_reminder@zf-lifetec.com` 的名义发出（"Send an email (V2)" 的 From (Send as)）。

- 前提：Outlook 连接的账号（目前是 xin.chen.external）对这个公共邮箱有 **Send As** 权限，IT 2026-10-23 批的。只有 Send As，没有 Full Access：能用它的名义发信，但打不开这个邮箱，收件人的回信和退信没人看得到（用户 2026-10-23 确认可以接受）。
- 收件人看到的发件人名字是这个邮箱在公司邮件系统里的显示名，流里改不了，要改找 IT。
- 2026-10-26 实测：经通知列表发一封测试信，流运行 Succeeded，"Send an email (V2)" 输入里 From = 公共邮箱，返回 200。
- 换连接的人也要有 Send As：谁的 Outlook 连接在发信，谁就得对公共邮箱有 Send As，否则发信失败。

## 把流交接给 xiangwei.chen@zf-lifetec.com

流里的每个连接都属于登录它的那个人。"Send an email (V2)" 实际用哪个账号登录发信，取决于这一步的 Outlook 连接；收件人看到的发件人仍是公共邮箱（见上一节），但接手的人要先向 IT 申请这个公共邮箱的 Send As。

1. **（你）加共同所有者**：打开 [Power Automate](https://make.powerautomate.com)，确认右上角环境是 passivesafety (default) → My flows → 在 "Sourcing Cockpit - Notifications" 一行点 ⋮ → **Share** → 输入 `xiangwei.chen@zf-lifetec.com`。
2. **（xiangwei.chen）换成自己的连接**：他登录后在 **Team flows**（团队流）页签里找到这个流 → **Edit** → 点 "Send an email (V2)" → 面板底部 "Connected to …" 旁边点 **Change connection** → 选他自己的账号，或 Add new connection 后登录 → **Save**。
3. 建议他把 "Post message in a chat or channel"（Teams）和触发器 "When an item is created"（SharePoint）也换成自己的连接。这样你的账号不再参与，以后你调岗也不影响这个流。
   - 注意：触发器用的连接必须能读 SCC_PROC_SOURCINGCOMMITTEE 站点，xiangwei.chen 要有这个站点的访问权限。

微软文档说明：共同所有者可以修改流，也可以把某一步的连接换成自己的，但不能修改别人建的连接的凭据（[Share a cloud flow](https://learn.microsoft.com/en-us/power-automate/create-team-flows)）。

## 怎么确认发出去了

- 系统里显示的投递结果 `sent`，表示“已写进列表”，不代表已经送达。
- 真正发没发出，要看流的 **28-day run history**（流详情页）：每一行通知对应一次运行，失败的运行点进去能看到是哪一步出错。
- 触发器定义的是每分钟检查一次，实际间隔以许可证允许的最短间隔为准，所以通知会晚一会儿才到。

## 已知限制

- Teams 以 Flow bot 身份发消息：每个连接每 5 分钟最多 25 条（微软连接器文档）。哪天过期提醒特别多，Teams 那部分可能被限流，邮件不受影响。
- Outlook 连接：每个连接每 60 秒最多 300 次调用。
- 流的所有者离职、改密码，或连接过期，都要重新登录或换连接。
- 列表里的行不会自动删除，时间长了可以手动清理。
- 以后 IT 批了 Mail.Send，或者给了 SMTP 中继，在 `.env` 里填上对应配置后，邮件会优先走那条路（顺序见 DEPLOY.md），这个流只剩 Teams 部分在用。
