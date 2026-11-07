#!/usr/bin/env python3
"""
PolicyLens CLI Entrypoint
"""

import sys
from pathlib import Path

# Ensure repo root is on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from CS2_PolicyLens.src.indexing_pipeline import main

if __name__ == "__main__":
    main()

