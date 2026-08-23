#!/usr/bin/env python3
"""APA Server 冻结入口（PyInstaller）。

与 `python -m apa_core.cli` 同参：
    apa_server serve --port 8686 --journals 'data/*.jsonl' ...
"""
import sys

from apa_core.cli import main

if __name__ == "__main__":
    sys.exit(main())