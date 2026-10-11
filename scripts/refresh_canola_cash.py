"""Bank Fastmarkets canola cash prices into Snowflake (see canola_cash.py).

    python scripts/refresh_canola_cash.py              # last 14 days
    python scripts/refresh_canola_cash.py --backfill   # everything since 2000
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

import canola_cash  # noqa: E402

if __name__ == "__main__":
    n = canola_cash.refresh(backfill="--backfill" in sys.argv)
    print(f"CANOLA_CASH: merged {n:,} rows")
