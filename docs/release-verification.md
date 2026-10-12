# 首次发布验证 · 2026-10-12

- 从代码白名单创建干净副本，不复制作者个人的缓存、报告、日志、Obsidian 笔记、备份、旧本机诊断文档或虚拟环境。
- macOS / Python 3.13 新建虚拟环境，使用 start.sh --setup-only 安装依赖成功。
- 干净副本 pytest：40 项通过；原环境 Python 3.14 也为 40 项通过。第三方 Starlette TestClient 弃用提示不影响结果。
- Shell 与 JavaScript 语法检查通过；Codex skill 格式校验通过。
- 在独立本机端口启动干净副本，验证首页、静态脚本、空候选缓存、状态 API 和 no-store 响应。
- CLI 配置临时 Obsidian 库后服务能读取新路径，临时库未被修改。
- Skill 可安装到临时 skills 目录，已有同名 skill 时拒绝覆盖并保留人工修改。
- 独立代理先执行无 skill 基线，再使用 skill 检查中文报告绑定、单位归属、送达后确认、排除项与上限、跨电脑部署。只确认完整送达的相关论文，不自动入库。

公开版本从空缓存启动；中文摘要由 Codex 按原文整理报告并同步，网页不自动调用翻译服务。Linux/Python 3.11 与 macOS/Python 3.13 的远端验证由 GitHub Actions 执行。
