# 部署与迁移

应用仓库：https://github.com/mihuhu/arxiv-paper-radar 。支持 macOS/Linux，Python 3.11+；Windows 需要 WSL（代码使用 Unix 文件锁）。

## 新电脑

1. 确认 `python3 --version` 至少 3.11。macOS 可使用 Homebrew `brew install python git`，或 python.org 官方安装包。
2. 在用户选择的位置 `git clone https://github.com/mihuhu/arxiv-paper-radar.git`，进入仓库，执行 `./start.sh --setup-only`。
3. 使用用户实际已有库路径：`.venv/bin/python -m radar.cli configure --vault "/真实的/Obsidian/库"`。此命令不修改库。未选库也能浏览/抓取；入库需要有效目录。首次默认 `~/Obsidian/paper-vault`，也可设置 `ARXIV_RADAR_VAULT`；保存设置优先于环境默认。
4. `./start.command`（macOS 双击）或 `./start.sh`，访问 `http://127.0.0.1:8765/`。保持启动终端开启；只监听本机。
5. 安装 skill：`python3 scripts/install_skill.py`。默认进入 `${CODEX_HOME:-~/.codex}/skills/arxiv-paper-radar`，已存在时拒绝覆盖。在 Codex 新一轮对话使用 `$arxiv-paper-radar`，告知项目与库目录。

自定义解释器：`PYTHON=/path/to/python3 ./start.sh --setup-only`。解释器变更时重建 `.venv`，不删除 `data/`。不要跨电脑复制虚拟环境。

## 旧数据迁移

源码仓库是空数据库，不含任何个人论文、摘要报告或笔记。用户需要迁移历史时，先停旧机服务和定时抓取，再私下复制项目 `data/`、`reports/`、`backups/`；Obsidian 库另行同步。重启前在新机运行 `configure --vault` 更新复制数据库内的旧路径。不要将这些目录提交到公开 GitHub，也不要直接覆盖新机已有数据；分别备份后决定是否合并。

## 定时任务

网页不会自行生成中文摘要或发通知。需要用户请求后，在新机 Codex 创建本线程定期任务，读取项目 README、目标库规则，执行 digest、筛选、单位核验、中文简报、sync-summaries、成功汇报后 ack。设置每天北京时间 09:00（或用户指定时间）。电脑、Codex 执行环境和网络需可用。不要把某个旧电脑的线程 ID、自动化 ID 或绝对路径带到新电脑。

## 验证与排障

- `.venv/bin/python -m radar.cli status` 确认库路径。
- `curl --noproxy '*' http://127.0.0.1:8765/api/state` 检查本机服务。
- 页面无法连接：先查看启动终端。已有雷达服务会复用；别的程序占用 8765 时报告占用，不杀未知进程。
- 中文待整理：完成版本匹配的中文报告，再 sync-summaries；新抓取不会自动调用付费翻译 API。
- arXiv 失败：检查 task、日志和 `data/raw/`，保留断点后重试。
