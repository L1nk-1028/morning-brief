# 我的每日早报 · Morning Brief

一个每天北京时间早上 8:30 左右自动生成、可在手机查看、可推送到微信的个人早报。

它把三件事串起来：

1. **抓新闻**：从 30 多个 RSS 源抓取国内时政、国际时政、AI 科技、财经、科学、体育、游戏动漫等内容。
2. **做编辑**：按你的兴趣和“事件重要性”排序；在 GitHub Actions 里用免费的 GitHub Models 生成中文标题、摘要和“为什么值得看”。
3. **送到手**：生成一个手机友好的网页，并用 Server酱 推送到微信。

> 这是为你第一次系统学习准备的“可读、可改、可扩展”的项目。代码只用 Python 标准库，不需要安装第三方包。

---

## 1. 最终效果

- 每天 08:20（北京时间）云端自动运行，08:30 左右收到微信。
- 微信消息里是早报摘要和阅读链接。
- 点开链接是一个排版好的手机网页，也可以直接收藏网页地址。
- 网页每天更新，旧日期自动归档在 `docs/` 里。

---

## 2. 它是怎么工作的

```text
                 ┌─────────────────────────────┐
                 │  GitHub Actions（云端定时）  │
                 │  每天 00:20 UTC = 08:20 北京 │
                 └──────────────┬──────────────┘
                                │
              ┌─────────────────▼─────────────────┐
              │  run.py                            │
              │  1. fetch.py  抓 RSS               │
              │  2. rank.py   去重/打分/选栏目     │
              │  3. llm.py    AI 写中文标题和摘要  │
              │  4. render.py 生成 HTML / Markdown │
              │  5. push.py   推送到微信           │
              └─────────────┬───────────┬──────────┘
                            │           │
                  ┌─────────▼───┐   ┌───▼────────────┐
                  │ GitHub Pages│   │ Server酱        │
                  │ 手机网页     │   │ 微信服务号通知  │
                  └─────────────┘   └────────────────┘
```

关键概念（顺便学习）：

- **RSS**：网站提供的一种“标准新闻列表”，程序可以定时读取。
- **cron**：定时表达式。GitHub 用 UTC，所以北京时间 08:20 要写成 `20 0 * * *`。
- **GitHub Actions**：GitHub 提供的免费云端运行环境，电脑关机也能跑。
- **GitHub Pages**：把 `docs/` 里的网页免费发布到互联网。
- **Secret**：GitHub 里保存密码/密钥的地方，不会出现在代码里。
- **环境变量**：程序从系统里读取密钥的方式，例如 `SERVERCHAN_SENDKEY`。

---

## 3. 目录说明

```text
morning-brief/
├─ config.json              # 你的兴趣、栏目、新闻源、推送设置
├─ run.py                   # 入口：抓取 → 筛选 → AI → 渲染 → 推送
├─ briefing/
│  ├─ fetch.py              # 抓取与解析 RSS/Atom
│  ├─ rank.py               # 去重、打分、今日要闻选择
│  ├─ llm.py                # GitHub Models / DeepSeek 中文编辑
│  ├─ render.py             # Markdown + 手机 HTML
│  └─ push.py               # Server酱 / PushPlus 推送
├─ output/                  # 每天生成的 md / html / json
├─ docs/                    # GitHub Pages 发布的网页
├─ .github/workflows/daily.yml  # 每天 08:20 的云端定时任务
└─ README.md
```

---

## 4. 本地先跑起来（今天就能看到）

在项目目录打开 PowerShell：

```powershell
python run.py --no-llm
```

如果你和本项目在同一台 Windows 上，也可以用 DSH 自带的 Python：

```powershell
& "C:\Users\ASUS\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" run.py --no-llm
```

运行完成后打开：

```text
output/latest.html
```

也可以双击 `run.ps1`（或运行 `.\run.ps1 -NoLLM -Open`），它会自动用 DSH 自带的 Python 生成并打开网页。

想在手机上看同一份网页（手机和电脑连同一个 Wi-Fi）：

```powershell
.\preview.ps1
```

然后手机浏览器打开 `http://<电脑的局域网IP>:8765/`。Windows 可能会弹出防火墙提示，选择“允许访问”。

你会看到当天的早报。第一次运行会访问 30 多个新闻源，部分海外源在当前网络下可能超时，这是正常的；程序会跳过失败的源，并在页面底部列出。

### 只看某几个源（调试用）

```powershell
python run.py --no-llm --source chinanews_china,chinanews_world,france24
```

### 推送测试

```powershell
$env:SERVERCHAN_SENDKEY="你的SendKey"
python run.py --push
```

---

## 5. 改成你真正感兴趣的内容

你的具体偏好记录在 [PREFERENCES.md](PREFERENCES.md)。下面是如何改 `config.json`：

### 5.1 兴趣关键词

```json
"interests": {
  "AI 与前沿科技": ["ai", "大模型", "芯片", "机器人", "..."],
  "体育": ["nba", "足球", "F1", "..."]
}
```

这些词会影响排序：标题或摘要里命中越多，越容易排在栏目前面。

### 5.2 栏目和条数

```json
{ "id": "tech", "title": "AI 与科技", "emoji": "🤖", "limit": 4 }
```

- `limit`：这个栏目最多显示几条。
- 栏目 `id` 要跟新闻源的 `section` 对应。

### 5.3 新闻源

```json
{
  "id": "bbc_world",
  "name": "BBC World",
  "url": "https://feeds.bbci.co.uk/news/world/rss.xml",
  "section": "world",
  "lang": "en",
  "weight": 1.3,
  "enabled": true
}
```

- `weight`：来源权重，越高越容易入选。
- `lang`：`zh` 或 `en`，AI 会据此决定是否翻译。
- `enabled`：`false` 可以临时关掉一个源。

> 小技巧：想加新源，先找它的 RSS 地址（很多网站页脚有 RSS 图标），把 URL 填进来，运行 `python run.py --source 新源id` 测试。

---

## 6. 部署到 GitHub（免费云端定时）

### 6.1 准备

- 一个 GitHub 账号（没有就注册，免费）。
- 建议把仓库设为 **Public**：GitHub Pages 对私有仓库需要付费计划；这个项目只包含公开新闻，不包含你的隐私。
- 不要把任何 SendKey、API Key 写进文件。

### 6.2 创建仓库并上传

1. GitHub 右上角 `+` → `New repository`。
2. 名称填 `morning-brief`，选择 `Public`，不要勾选初始化 README。
3. 在本项目目录执行（把 `<你的用户名>` 换成你的 GitHub 用户名）：

```powershell
git init
git add .
git commit -m "first commit"
git branch -M main
git remote add origin https://github.com/<你的用户名>/morning-brief.git
git push -u origin main
```

如果没装 Git，也可以用 GitHub 网页的 `uploading an existing file` 把整个文件夹上传。

### 6.3 打开 GitHub Pages

1. 进入仓库 → `Settings` → `Pages`。
2. `Build and deployment` → `Source` 选择 **GitHub Actions**。
3. 进入 `Actions` 标签，左侧选 `Daily Morning Brief`，点 `Run workflow` 手动跑一次。
4. 跑完后，网页地址是：

```text
https://<你的用户名>.github.io/morning-brief/
```

这个地址就是手机阅读页，可以收藏到手机浏览器。

### 6.4 第一次运行可能遇到的问题

- **Actions 没有权限提交**：`Settings` → `Actions` → `General` → `Workflow permissions` 选 `Read and write permissions`。
- **Pages 404**：确认 `Settings` → `Pages` 的 Source 是 `GitHub Actions`，并且 deploy job 成功。
- **AI 没有生效**：如果网页底部显示 `AI 返回格式异常：OK`，说明 GitHub Models 在当前环境没有返回模型结果。把 `config.json` 的 `llm.enabled` 设为 `false`（默认），或按第 8 节接入 DeepSeek。

---

## 7. 推送到微信（Server酱）

### 为什么推荐 Server酱，而不是公司企业微信

- 公司企业微信的机器人属于公司资产，管理员能看到/限制，离职后可能失效。
- 早报是个人内容，放在个人微信通道更合适。
- Server酱 的原理：你关注一个叫「方糖」的微信服务号，第三方程序把消息发给 Server酱，Server酱再通过服务号推给你。**不需要登录你的个人微信，也不需要装外挂。**

### 配置步骤

1. 打开 <https://sct.ftqq.com>，用 GitHub 登录。
2. 按页面提示关注「方糖」服务号。
3. 复制你的 `SendKey`（一串 `SCT...` 的字符）。
4. 回到 GitHub 仓库 → `Settings` → `Secrets and variables` → `Actions` → `New repository secret`：
   - Name：`SERVERCHAN_SENDKEY`
   - Secret：粘贴 SendKey
5. 下次定时任务会自动带上 `--push`，微信就能收到。

免费额度每天几条，对“每天一条早报”足够；以后想扩展多通道，可以再加 PushPlus 或邮件。

### 推送失败怎么查

- 在 Actions 日志里搜索“微信推送”。
- 常见原因：SendKey 复制错、没有关注方糖服务号、免费额度用完。
- 可以本地先测：

```powershell
$env:SERVERCHAN_SENDKEY="SCT..."
python run.py --push --no-llm
```

---

## 8. AI 编辑（可选）

为了让项目零成本先跑通，**默认关闭 AI**（`config.json` 里 `llm.enabled=false`）。

关闭 AI 时：

- 英文标题会用 MyMemory 免费翻译成中文；
- 部分英文摘要可能保留原文；
- 没有“为什么值得看”和 AI 摘要。

GitHub Models 本来是免费方案，但在部分网络/仓库环境下会返回一个 `OK` 字符串而不是模型结果，程序会跳过 AI 并显示原因。这不是你的配置错误。

### 想启用 AI：推荐 DeepSeek

1. 打开 <https://platform.deepseek.com>，注册并创建 API Key。
2. 充值少量金额（每天一份早报通常几分钱）。
3. 在 GitHub 仓库添加 Secret：`DEEPSEEK_API_KEY`。
4. 把 `config.json` 的 `llm` 改成：

```json
"llm": {
  "enabled": true,
  "provider": "deepseek",
  "api_key_env": "DEEPSEEK_API_KEY",
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-chat",
  "timeout": 120
}
```

5. 重新运行一次 Actions。

开启后它会：

- 把英文标题/摘要翻译成自然中文；
- 为每条新闻写 2-3 句摘要；
- 写一句“为什么值得看”；
- 从候选里挑 5 条今日要闻。

> 本地没有 `GITHUB_TOKEN` 或 `DEEPSEEK_API_KEY` 时，AI 会自动跳过，早报仍然能生成。这是故意的“优雅降级”。

---

## 9. 每天 8:30 是怎么保证的

GitHub Actions 的定时任务用 UTC：

```yaml
- cron: "20 0 * * *"
```

= 北京时间每天 08:20 开始。抓取 + AI + 推送通常需要 1-3 分钟，所以目标是在 08:30 左右送达。

注意：GitHub 的免费定时任务**可能延迟几分钟到十几分钟**（高峰期更明显），这是平台限制。如果你要求“必须 8:30 整”，需要更稳定的服务器或付费调度，这个项目先保证“8:30 左右”。

---

## 10. 常见问题

**Q：为什么很多海外源显示失败？**
A：你本地网络访问 BBC/Guardian 等可能超时；GitHub Actions 的服务器在海外，通常能访问。失败不会影响其他源，页面底部会列出。

**Q：为什么有的新闻是英文？**
A：本地没配置 AI 时会保留原文；GitHub Actions 里启用了 GitHub Models，会自动翻译。也可以 `--no-llm` 强制关闭 AI 对比效果。若云端 AI 失败，网页底部会显示原因，并自动启用 MyMemory 备用翻译。

**Q：网页底部显示“AI 编辑未生效”？**
A：先看它后面的原因。常见是 GitHub Models 未启用、模型名变化或 Token 权限不足。打开 `output/latest.json` 可以看到完整的 `llm_error`。也可以把 `config.json` 里的 `llm.provider` 改成 `deepseek`，再配置 `DEEPSEEK_API_KEY` 作为备用。

**Q：微信只收到一小段？**
A：Server酱 对消息长度有限制。早报全文在网页里，微信里保留标题、要闻和链接。后续可以把“今日要闻”单独做短消息。

**Q：GitHub 在国内访问不稳定怎么办？**
A：生成和推送都在 GitHub 云端，不依赖你本地访问 GitHub；只有你打开 Pages 网页时可能需要网络工具。若网页打不开，可以先看微信推送里的文字版，或后续换国内静态托管。

**Q：这个项目会泄露我的兴趣吗？**
A：`config.json` 里的兴趣关键词会进入公开仓库（如果仓库是 Public）。如果不希望公开，可以把仓库设为 Private（Pages 需要付费），或把兴趣放进 GitHub Secret/私有配置。当前版本先保持简单。

---

## 11. 下一步可以加什么

- [ ] 天气与穿衣建议（按城市）
- [ ] 市场速览：A 股、美股、黄金、人民币汇率
- [ ] “今天值得读的一篇长文”
- [ ] 根据你点开/忽略的新闻做反馈学习
- [ ] 每周日生成“本周回顾”
- [ ] 多通道：邮件、Telegram、飞书
- [ ] 把 AI 编辑提示词做成可配置的“编辑风格”

---

## 12. 一句话总结

**RSS 负责找料，规则负责初筛，AI 负责写成中文，GitHub Actions 负责每天准时跑，Server酱 负责送到微信。**

先跑通，再逐步替换成你喜欢的源和风格。
