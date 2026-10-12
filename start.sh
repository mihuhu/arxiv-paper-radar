#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if [ ! -x .venv/bin/python ]; then
  task_python="${PYTHON:-}"
  if [ -z "$task_python" ]; then
    for task_candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
      if command -v "$task_candidate" >/dev/null 2>&1 && "$task_candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        task_python="$task_candidate"
        break
      fi
    done
    if [ -z "$task_python" ]; then
      echo '需要 Python 3.11+。macOS 可运行 brew install python 后重新启动。' >&2
      exit 1
    fi
  fi
  if ! command -v "$task_python" >/dev/null 2>&1; then
    echo '需要 Python 3.11 或更新版本。macOS 可运行 brew install python，随后重新启动。' >&2
    exit 1
  fi
  if ! "$task_python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo 'Python 版本过旧：需要 3.11+。可使用 PYTHON=/path/to/python3 ./start.sh。' >&2
    exit 1
  fi
  "$task_python" -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, uvicorn, httpx, yaml, bs4' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi
if [ "${1:-}" = '--setup-only' ]; then
  echo '依赖准备完成。运行 ./start.command 或 ./start.sh 启动论文雷达。'
  exit 0
fi
exec .venv/bin/python -m radar.launcher "$@"
