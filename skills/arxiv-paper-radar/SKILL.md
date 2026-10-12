---
name: arxiv-paper-radar
description: Use when deploying or operating the local arXiv Paper Radar, checking papers on LLM tool authorization, agent security, distillation detection or watermarking, preparing its Chinese digests, or connecting its candidates to an Obsidian vault.
---

# arXiv 论文雷达

配套开源应用：https://github.com/mihuhu/arxiv-paper-radar 。此 skill 指导部署和中文简报；它本身不包含 Python 应用，也不自动创建定时任务。

## 找到应用

优先使用用户给出的目录、`ARXIV_RADAR_HOME` 或当前目录中同时含 `radar/cli.py` 与 `README.md` 的项目。否则检查 `~/arxiv-paper-radar`；仅当用户要求部署时克隆上述仓库。不要硬编码另一台电脑的用户名或文献库路径。

先读项目 README 和目标库的 `agents.md` / `AGENTS.md`（若存在）。部署时读 [部署与迁移](references/deployment.md)。使用项目 `.venv/bin/python`，从项目目录运行命令。

## 检查与中文简报

关注工具越权、智能体安全、模型/智能体蒸馏检测、模型/文本水印、智能体水印。普通模型压缩、无关统计指纹、一般经济机制和单纯研发基础设施不能仅凭关键词入选；按用户当前研究范围和原始摘要判断。

```sh
mkdir -p data
.venv/bin/python -m radar.cli digest --days 7 --budget 30 --enrich --limit 15 > data/digest-current.json
```

读取退出码与 JSON 的 `task.status`、`failures`、`truncated`，区分失败、预算未完整覆盖和无新增。保留失败日志和缓存；不要将失败说成没有新论文。应用已实现跨进程单连接、至少 3.1 秒请求间隔，不另起并发 arXiv 抓取绕过限速。`--no-fetch` 只使用缓存；此时 `--enrich` 不会补核验单位。

筛除项仍会出现在未汇报候选中。将 ID、版本、理由保存在本地 `data/exclusions.json`，原文升级或研究范围改变时重新判断。若结果达到 15 条上限，读取 `status` 的缓存总数，再用 `digest --no-fetch --limit <缓存总数>` 查看全部未汇报缓存，防止排除项挤占上限而漏报；每次最多整理 15 篇相关论文。不用 ack 冒充排除标记。

每篇入选论文提供完整原始标题、完整作者、单位、提交/更新日期、arXiv 链接、100–180 字中文摘要及方向关联。摘要只概括原始摘要，不补写未读取的实验结论。单位仅来自 API affiliation、实际读取的 HTML 作者栏或 PDF 作者栏；每位作者单独检查，缺失写“待核实”。整体核验状态不代表每位作者都有单位。论文级单位若未逐作者对应，明确写“未逐作者对应”，不推断个人归属。

按 [简报格式](references/report-format.md) 保存到 `reports/`。精确保留缓存标题、版本和原始摘要；格式错误或旧版本不会同步。

```sh
.venv/bin/python -m radar.cli sync-summaries
```

检查 `rejected`，修复后再同步，并读取对应 `/api/papers/<ID>` 的 `abstract_zh` / `abstract_zh_status` 或实际网页详情验证。不要仅凭 `saved` 数量认定对应关系正确。

## 送达与入库

保存报告、同步中文、成功向用户汇报是三个不同状态。只有成功汇报后才运行 `radar.cli ack <ID...>`：仅确认本次已经向用户提供完整简报的相关论文 ID，不能对原始 15 条结果全量 ack，也不能对筛除项或尚未送达的草稿 ack。不确定送达时保留报告与待确认 ID。

用户只通过网页勾选、预览并确认入库。生成简报不自动导入、覆盖笔记、改变阅读/讨论状态。新增默认“参考论文”，已有版本只提示。遵循目标库规则；不要将源库笔记复制给陌生库。

只有用户要求定期检查时设置自动化，使用当前电脑的真实项目目录；迁移源码不会迁移 Codex 任务。已存在相关任务时先查看再更新，避免重复。无新相关论文且无异常时保持安静，有新论文、失败或需要用户操作时通知。
