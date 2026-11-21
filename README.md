# MyRSS · 我的 RSS

MyRSS 是运行在 Windows 本机的个人 RSS 阅读器。它直接订阅博客的 RSS / Atom，也通过本机 RSSHub 获取 X、微信公众号、YouTube、小宇宙等平台的更新。文章、订阅和阅读记录保存在本机的 SQLite 数据库中。

已经安装过的电脑可以直接双击 [start-my-rss.bat](start-my-rss.bat)，然后打开 [阅读器首页](http://127.0.0.1:1210/)。

| 入口 | 用途 |
| --- | --- |
| [我的 RSS](http://127.0.0.1:1210/) | 添加订阅、浏览文章和筛选未读 |
| [归档](http://127.0.0.1:1210/?view=archive) | 按订阅和首次同步日期查找历史内容 |
| [阅读统计](http://127.0.0.1:1210/stats) | 按来源查看近 30 天阅读篇数、累计篇数和打开次数 |
| [导入与导出](http://127.0.0.1:1210/library) | 导出文章，迁移 OPML 订阅列表 |
| [聚合 RSS](http://127.0.0.1:1210/feed.xml) | 把最近 100 条订阅内容交给同一台电脑上的其他阅读器 |

## 首次安装

1. 安装 Git 和 Python 3.12，确认 PowerShell 里可以运行 `git --version` 和 `python --version`。下载 Windows 版 Node.js 24.15.0 或更新的 24.x 版本，将 ZIP 内容解压到项目的 `node24` 目录，使 `node24\node.exe` 和 `node24\corepack.cmd` 可用。
2. 在项目根目录用 PowerShell 初始化 RSSHub 子模块，安装依赖并构建。

   ```powershell
   git submodule update --init --recursive
   if ($LASTEXITCODE -ne 0) { throw 'RSSHub submodule setup failed.' }
   $rssNodeDir = (Resolve-Path .\node24).Path
   $env:Path = "$rssNodeDir;$env:Path"
   Push-Location .\RSSHub
   try {
       corepack.cmd pnpm install --frozen-lockfile
       if ($LASTEXITCODE -ne 0) { throw 'RSSHub dependency installation failed.' }
       corepack.cmd pnpm build
       if ($LASTEXITCODE -ne 0) { throw 'RSSHub build failed.' }
   } finally {
       Pop-Location
   }
   ```

3. 首次部署时，将 [rsshub.env.example](rsshub.env.example) 复制为 `RSSHub\.env`。已有 `.env` 时，在原文件内修改所需设置。

   ```powershell
   if (!(Test-Path .\RSSHub\.env)) {
       Copy-Item .\rsshub.env.example .\RSSHub\.env
   }
   ```

4. 双击 [start-my-rss.bat](start-my-rss.bat)。脚本会安装阅读器所需的 Python 依赖，启动两个服务并打开首页。

两个服务都监听本机。阅读器使用 `1210` 端口，RSSHub 使用 `1200` 端口。可以分别打开 [阅读器健康检查](http://127.0.0.1:1210/healthz) 和 [RSSHub 健康检查](http://127.0.0.1:1200/healthz)，正常时返回 `ok`。

## 添加订阅

打开左侧「添加订阅」，选择平台并粘贴地址。首次抓取在后台进行，过几秒刷新页面即可查看同步结果。

| 类型 | 可以填写 |
| --- | --- |
| 博客 / RSS | RSS 或 Atom 地址、声明了订阅地址的博客首页，或本机 RSSHub 路由，如 `/zaobao/realtime/china` |
| X | `@账号` 或个人主页链接 |
| 微信公众号 | RSS 地址、Wechat2RSS 订阅 ID 或带 `/mp/homepage` 的公众号栏目链接 |
| YouTube | `@账号`、频道主页或频道 ID，例如 `https://www.youtube.com/@zhengquejun` |
| 哔哩哔哩 | UP 主空间链接或数字 UID，订阅投稿视频 |
| 微博 | 带数字 UID 的博主主页链接或数字 UID |
| 小宇宙 | 播客主页、单集分享链接或节目 ID。展开单集可播放源提供的音频 |
| 豆瓣 | 小组、豆列或带数字 ID 的用户广播主页；也可以填写 RSSHub 路由，如 `/douban/book/latest/fiction` |
| Readhub | `https://readhub.cn/daily` 或 `/readhub/daily`，通过本机 RSSHub 获取 |

**微信公众号示例**：在微信文章标题下找到公众号名称，到 [Wechat2RSS 公众号列表](https://wechat2rss.xlab.app/list/all) 查找，复制该账号的 RSS 链接，再粘贴到「微信公众号」订阅。普通的 `mp.weixin.qq.com/s/…` 分享地址只指向单篇文章。

**RSSHub 路由示例**：如果拿到的是 `https://rsshub.app/zaobao/realtime/china`，可以在「博客 / RSS」中填写 `/zaobao/realtime/china`。阅读器会从 [本机对应路由](http://127.0.0.1:1200/zaobao/realtime/china) 获取内容。

## 阅读、归档与迁移

- 双击 [start-my-rss.bat](start-my-rss.bat) 启动，双击 [stop-my-rss.bat](stop-my-rss.bat) 停止。服务运行期间，成功同步的源每 30 分钟自动刷新，也可以点击「刷新此源」或「刷新全部」。
- 点击文章标题可在列表内展开正文并标为已读。「全部标为已读」作用于当前订阅范围。阅读统计按实际打开的文章计数，批量标记已读不增加阅读次数。
- [归档](http://127.0.0.1:1210/?view=archive) 按订阅和首次同步日期筛选。源站移除旧文章或你取消订阅后，已抓取的文章仍可查看。同一条目更新时保存最新版本。
- [导入与导出](http://127.0.0.1:1210/library) 可把一个或全部订阅的历史文章导出为 PDF 或 Markdown，合并成一个文件，或每篇一份打包为 ZIP。PDF 包含正文文字和原文链接，Markdown 保留正文格式和图片链接。
- OPML 用于迁移当前订阅清单，导入时按地址合并。要迁移历史文章、已读状态和阅读统计，请先停止服务，再复制 `runtime\reader.sqlite3`。

## 平台设置与故障排查

- **X** 在 `RSSHub\.env` 中设置 `TWITTER_AUTH_TOKEN`，值为网页登录 Cookie 中 `auth_token` 的值。
- **微博** 公开账号可尝试访客模式。将 `CHROMIUM_EXECUTABLE_PATH` 指向本机 Chrome。需要登录才能查看的账号可配置 `WEIBO_COOKIES`。
- **豆瓣** 部分用户广播需要登录才能抓取，可在 `RSSHub\.env` 中设置 `DOUBAN_COOKIE`。
- **修改配置后**，先停止再启动服务，RSSHub 才会读取新的 `.env`。如需代理，可按 [配置示例](rsshub.env.example) 填入本机实际代理地址。
- **公共 RSSHub 返回 403**：把 `rsshub.app` 域名去掉，向阅读器添加剩余的路由，例如 `/readhub/daily`。如果同一路由在本机也失败，检查订阅状态或 `runtime\rsshub.log` 中的路由错误。500px 部落影集这类依赖源站接口的订阅，要等上游重新提供数据才能同步。
- **阅读器无法启动**：先查看 `runtime\reader.err.log`。如果缺少 `RSSHub\dist\index.mjs`，执行首次安装中的 RSSHub 构建步骤。

## 许可证

MyRSS 阅读器和本仓库脚本采用 [MIT 许可证](LICENSE)。RSSHub 子模块继续遵循其上游许可证，订阅内容的权利归原权利人。
