# arXiv Paper Radar · 本地论文雷达

在自己的电脑上检索 arXiv、筛选安全与水印论文，并将选中的论文写入 Obsidian。附带可安装的 **Codex skill**，用于部署、核验作者单位、生成中文简报和同步网页摘要。

开源仓库：[mihuhu/arxiv-paper-radar](https://github.com/mihuhu/arxiv-paper-radar) · [MIT License](LICENSE)

## 在另一台 Mac 启动

需要 **Python 3.11+**、Git 和可用网络。若使用 Homebrew，可先运行 `brew install python git`；也可使用 python.org 官方 Python 安装包。

```sh
git clone https://github.com/mihuhu/arxiv-paper-radar.git
cd arxiv-paper-radar
./start.sh --setup-only
./start.command
```

打开 **http://127.0.0.1:8765/**。以后可在 Finder 双击 `start.command`，也可运行 `./start.sh`。首次启动创建 `.venv` 并安装依赖；保持启动终端开启，按 Control-C 停止。只监听本机，不需要 API key。

Linux 使用 `./start.sh`；Windows 需 WSL。代码使用 Unix 文件锁，暂不支持原生 Windows。可通过 `PYTHON=/path/to/python3 ./start.sh --setup-only` 选择解释器。

## 选择自己的 Obsidian 库

网页左侧“文献库设置”选择已有库的绝对路径，或执行：

```sh
.venv/bin/python -m radar.cli configure --vault "$HOME/Obsidian/你的库"
```

默认候选路径为 `~/Obsidian/paper-vault`，**不会自动创建或修改这个库**。尚未选库也能浏览、抓取；导入需要真实存在的库。首次也可设置 `ARXIV_RADAR_VAULT` 环境变量，保存过的网页/CLI 设置优先。

论文写入 `03-literature/papers/`，作者进入 `04-authors/`，关键词进入 `05-keywords/`。使用 `literature-note`、`discussion_status`、`arxiv`、作者和关键词双链等字段，兼容原 mihuhu-paper 文献管理结构。新空库可以先在 Obsidian 创建，应用会在确认导入后建立相关目录和索引；如已有库有不同组织规则，先检查 `agents.md` / `AGENTS.md`，不要直接批量导入。

## 安装 Codex skill

在本仓库执行：

```sh
python3 scripts/install_skill.py
```

安装到 `${CODEX_HOME}/skills/arxiv-paper-radar`，未设置 CODEX_HOME 时为 `~/.codex/skills/arxiv-paper-radar`。已存在同名 skill 时拒绝覆盖，保留自己的修改后再更新。

在 Codex 新一轮对话使用：

> 使用 $arxiv-paper-radar 在这台 Mac 部署论文雷达。项目位于 ~/arxiv-paper-radar，Obsidian 库位于 ~/Obsidian/我的库。检查最近 7 天的新论文，整理中文摘要、完整作者和可核实的单位。

skill 位于 [skills/arxiv-paper-radar/SKILL.md](skills/arxiv-paper-radar/SKILL.md)。**skill 是操作指南，应用代码需单独克隆。** 网页本身不调用付费模型生成摘要；Codex 将原始摘要整理成中文报告后同步到网页。

## 使用网页

1. 选择方向、最近天数或历史日期、结果预算，抓取候选。五个方向：工具越权、智能体安全、蒸馏检测、模型与文本水印、智能体水印。
2. 点击标题、摘要或“查看详情”。详情展示中文摘要、完整作者、单位、原始英文和匹配理由。中文尚未整理或原文升级时明确提示。
3. 左侧列表、右侧详情独立滚动；最右侧滚动条控制整个页面。可按中文摘要搜索，调整方向并复用库内关键词。
4. 勾选后“预览入库”，检查目标路径与所有文件变更，再确认。默认“参考论文”，只有选择“待讨论”才加入队列。
5. 已有论文跳过，旧笔记不覆盖。高版本只提醒更新。修改作者/关键词索引前保存在 `backups/<batch>/manifest.json`；预览后文件被人工修改会拒绝导入并要求重新预览。

匹配分数反映规则命中，不能视为相关性概率。普通模型蒸馏或无关安全研究需要人工筛除。单位来源是 API affiliation 或实际读取的原文作者栏；无法确认写待核实，不根据姓名推断单位。

## CLI 与中文简报

```sh
# 检查缓存、配置和已生成简报
.venv/bin/python -m radar.cli status

# 少量抓取，不导入 Obsidian
.venv/bin/python -m radar.cli fetch --days 30 --budget 30

# 历史补抓；预算不足时对同一范围再次运行会续抓
.venv/bin/python -m radar.cli fetch --topics agent-watermark --start-date 2026-01-01 --end-date 2026-01-31 --budget 30

# 获取未汇报的候选，生成保留英文原文的简报草稿
.venv/bin/python -m radar.cli digest --days 7 --budget 30 --enrich --limit 15

# 仅从缓存生成草稿，适用于离线状态（不补核验单位）
.venv/bin/python -m radar.cli digest --no-fetch --limit 15

# 完成中文简报后同步到网页
.venv/bin/python -m radar.cli sync-summaries

# 已成功向用户汇报后确认实际送达的论文 ID；不是报告文件名
.venv/bin/python -m radar.cli ack 2401.12345
```

`digest` 草稿不会自动翻译、标记送达或导入。Codex 按 [简报格式](skills/arxiv-paper-radar/references/report-format.md) 整理 100–180 字中文摘要，完整保留原始标题、版本、英文摘要和来源，然后 `sync-summaries`。标题、ID、版本、原始摘要指纹必须匹配，过期摘要不展示。生成或保存草稿不等于送达，只有成功汇报的相关论文才能 ack。

检索默认按北京时间换算 UTC。arXiv 请求跨进程单连接，间隔至少 3.1 秒，支持重试、原始响应缓存与断点。最近天数扫描新提交和修订，历史范围只扫描提交日期。预算耗尽会报告未完整覆盖，网络失败保留缓存与日志，不当作没有新论文。“新”指系统首次发现且未入库、未汇报，不保证首次发表于当天。

## 在新电脑每天汇报

克隆仓库或安装 skill **不会自动创建定时任务**。可以在新机 Codex 中请求：

> 使用 $arxiv-paper-radar，每天北京时间 09:00 检查 ~/arxiv-paper-radar，给我新相关论文的标题、完整作者、已核实单位及中文摘要，保存简报并同步网页；成功汇报后才 ack，无新增且无异常保持安静，论文只由我在网页筛选入库。

电脑、Codex 的执行环境和网络需可用。不要在两台电脑的同一共享数据目录同时抓取或写入；任务应在各自环境按真实路径配置。

## 数据迁移、开发与许可

公开仓库只有代码、测试和 skill，不含个人论文缓存、报告、日志、Obsidian 笔记或备份。新安装从空缓存开始。需要迁移历史时先停旧机服务和任务，私下复制 `data/`、`reports/`、`backups/`，另行同步 Obsidian 库，再在新机执行 `configure --vault` 修正旧路径；不要复制 `.venv` 或把这些数据上传公开仓库。

- `data/radar.sqlite3`：缓存、设置、已汇报状态、中文摘要与断点。
- `data/raw/`：API/HTML 原始响应及请求来源。
- `reports/`：原始草稿及核实后的中文 Markdown 简报。
- `backups/`：导入前备份和变更清单。恢复前比对清单哈希，保留导入后的人工编辑。

```sh
./start.sh --setup-only
.venv/bin/python -m pytest -q
sh -n start.sh start.command
node --check web/app.js
```

`requirements.txt` 是兼容范围；`requirements.lock.txt` 记录初始已验证依赖快照。GitHub Actions 检查 Linux/Python 3.11 与 macOS/Python 3.13。[CONTRIBUTING.md](CONTRIBUTING.md) 说明开发约束。

MIT 许可覆盖本仓库代码与原创文档，不改变论文及第三方依赖自身许可。来源：[arXiv API 手册](https://info.arxiv.org/help/api/user-manual.html)、[API 使用规则](https://info.arxiv.org/help/api/tou.html)。
