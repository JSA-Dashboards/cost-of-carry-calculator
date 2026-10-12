"""Bank USDA AMS feedstuff prices and soybean bids into Snowflake (see ams_crush.py).

    python scripts/refresh_ams_crush.py              # last 21 days
    python scripts/refresh_ams_crush.py --backfill   # everything MARS still serves (a few minutes)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
except ImportError:
    pass

import ams_crush  # noqa: E402

if __name__ == "__main__":
    for table, n in ams_crush.refresh(backfill="--backfill" in sys.argv).items():
        print(f"{table}: merged {n:,} rows")
