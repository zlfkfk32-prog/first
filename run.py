"""Run with: python run.py [--demo] [--hours 24] [--output output]."""
from pathlib import Path
import os


if __name__ == "__main__":
    # Keep assets and output relative to the project, even when launched elsewhere.
    os.chdir(Path(__file__).resolve().parent)
    from cardletter.__main__ import main
    raise SystemExit(main())
