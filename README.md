# 我的 RSS

在 Windows 上运行的个人 RSS 阅读器。RSSHub 把社交平台内容转换成订阅源，阅读器把它们和博客 RSS 汇总到一个页面。

| 入口 | 用途 |
| --- | --- |
| [我的 RSS](http://127.0.0.1:1210/) | 添加订阅、浏览文章和筛选未读 |
| [阅读统计](http://127.0.0.1:1210/stats) | 按来源查看近 30 天阅读篇数、累计篇数和打开次数 |
| [聚合 RSS](http://127.0.0.1:1210/feed.xml) | 把最近 100 条订阅内容交给同一台电脑上的其他阅读器 |
| [RSSHub 健康检查](http://127.0.0.1:1200/healthz) | 检查 RSSHub 是否启动 |

## 首次安装

1. 安装 Git 和 Python 3.12。下载 Windows 版 Node.js 24.15 或同一主版本的更新版本，将 ZIP 解压到项目的 `node24` 目录，使 `node24\node.exe` 和 `node24\corepack.cmd` 可用。
2. 在项目根目录用 PowerShell 初始化 RSSHub 子模块，安装依赖并构建。

   ```powershell
   git submodule update --init --recursive
   $rssNodeDir = (Resolve-Path .\node24).Path
   $env:Path = "$rssNodeDir;$env:Path"
   Push-Location .\RSSHub
   try {
       corepack.cmd pnpm install --frozen-lockfile
       corepack.cmd pnpm build
   } finally {
       Pop-Location
   }
   ```

3. 首次部署时，将 [rsshub.env.example](rsshub.env.example) 复制为 `RSSHub\.env`。已有 `.env` 时，在原文件内修改所需设置。
4. 双击 [start-my-rss.bat](start-my-rss.bat)。脚本会安装阅读器所需的 Python 依赖，启动两个服务并打开首页。

## 每天使用

- 双击 [start-my-rss.bat](start-my-rss.bat) 启动，双击 [stop-my-rss.bat](stop-my-rss.bat) 停止。
- 打开「添加订阅」，选择对应平台并填写地址。首次抓取完成后，刷新页面即可看见条目。运行期间成功抓取的源每 30 分钟刷新一次，也可以手动刷新。
- 在阅读器里点击文章标题会标记为已读。近 30 天篇数按文章去重，重复打开会增加累计打开次数。

| 类型 | 可以填写 |
| --- | --- |
| 博客 / RSS | RSS 或 Atom 地址，也可以填在页面中声明了订阅地址的博客首页 |
| X | `@账号` 或个人主页链接 |
| 微信公众号 | RSS 地址、Wechat2RSS 订阅 ID 或带 `/mp/homepage` 的公众号栏目链接 |
| YouTube | `@账号`、频道主页或频道 ID，例如 `https://www.youtube.com/@zhengquejun` |
| 哔哩哔哩 | UP 主空间链接或数字 UID，订阅投稿视频 |
| 微博 | 带数字 UID 的博主主页链接或数字 UID |

## 凭据和本地数据

- **X** 在 `RSSHub\.env` 中设置 `TWITTER_AUTH_TOKEN`，值为网页登录 Cookie 中 `auth_token` 的值。
- **微博** 公开账号可尝试访客模式。将 `CHROMIUM_EXECUTABLE_PATH` 指向本机 Chrome。需要登录才能查看的账号可配置 `WEIBO_COOKIES`。
- 修改 `RSSHub\.env` 后，先停止服务再重新启动，使 RSSHub 读取新配置。两个服务默认只监听本机。
- 订阅和阅读记录位于 `runtime\reader.sqlite3`。备份前先停止服务。抓取问题可查看页面的订阅状态、`runtime\rsshub.log` 或 `runtime\reader.err.log`。
