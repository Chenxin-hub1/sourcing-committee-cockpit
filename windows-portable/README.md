# Windows 免安装运行（没有管理员权限、装不了 Docker 时用）

`python/` 是 Python 3.12 官方免安装版 + 全部依赖库（与 `backend/uv.lock` 同版本），解压即用，不改注册表、不需要管理员。仓库根目录的 `start.bat` 用它启动服务，端口取 `.env` 的 `SC_PORT`（默认 8031；IT 配好域名后改成 80，地址就是 `http://sourcing-cockpit.zf-lifetec.com/`，不带端口号）。

## 首次启动

```powershell
cd D:\apps
git clone https://github.com/Chenxin-hub1/sourcing-committee-cockpit.git sourcing-cockpit
cd sourcing-cockpit
Copy-Item .env.example .env
notepad .env        # 按 DEPLOY.md「上线前清单」填：SC_PUBLIC_URL、SC_SEED_ON_EMPTY=false、SC_TIMEZONE、领导的引导管理员邮箱与初始密码
.\start.bat
```

窗口里出现 `Application startup complete` 就好了，浏览器打开 http://localhost:8031/ 。数据库和上传文件在 `backend\data\`，备份就是复制这个文件夹。

## 关掉窗口服务就停：让它常驻

任务计划程序（Task Scheduler）不需要管理员就能给自己的账号建任务：

1. 开始菜单搜 "任务计划程序" → 右侧 "创建任务"。
2. 常规：名称 `Sourcing Cockpit`；选 "不管用户是否登录都要运行"；"不存储密码" 这一项不要勾（需要存密码，否则你注销后服务会停）。
3. 触发器：新建 → "启动时"。
4. 操作：新建 → 程序填 `D:\apps\sourcing-cockpit\start.bat`，起始于填 `D:\apps\sourcing-cockpit`。
5. 设置：勾 "如果任务失败，按以下频率重新启动"，1 分钟，3 次。
6. 确定后右键任务 → 运行。以后重启服务器会自动起来。

## 更新到新版本

```powershell
cd D:\apps\sourcing-cockpit
git pull
```

然后在任务计划程序里 结束 → 运行 一次（或关掉 start.bat 窗口重开）。数据不受影响。

## 同事打不开

服务在本机能开、别的电脑打不开，是服务器防火墙没放行 8031 端口。没有管理员权限改不了，请 IT 放行 TCP 8031 入站。

## 重新打包运行时（维护者）

在 WSL 里下载 python.org 的 `python-3.12.x-embed-amd64.zip` 解压到 `python/`，用 `pip download --platform win_amd64 --python-version 3.12 --only-binary=:all:` 按 `uv.lock` 的版本下载 wheel，`pip install --no-deps --target python/Lib/site-packages` 装进去，`python312._pth` 末尾加一行 `Lib\site-packages`。
