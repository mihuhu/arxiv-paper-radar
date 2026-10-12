#!/usr/bin/env python3
"""Install the bundled skill without replacing an existing skill."""
import argparse
import os
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description='安装 arxiv-paper-radar Codex skill')
    parser.add_argument('--dest', type=Path, help='skills 目录，默认为 CODEX_HOME/skills 或 ~/.codex/skills')
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1] / 'skills' / 'arxiv-paper-radar'
    base = args.dest or Path(os.environ.get('CODEX_HOME') or Path.home() / '.codex') / 'skills'
    target = base.expanduser() / source.name
    if target.exists() or target.is_symlink():
        parser.error(f'目标已存在，未覆盖：{target}。更新时请先保留自己的修改。')
    base.expanduser().mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns('__pycache__', '.DS_Store'))
    print(f'已安装：{target}\n在 Codex 新一轮对话中使用 $arxiv-paper-radar。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
