"""Load the latest USDA AMS ethanol prices into Snowflake.

Run by .github/workflows/refresh-ams.yml each weekday; also fine to run by hand.
Credentials come from the environment (GitHub secrets in the Action, the repo's .env
locally): USDA_MARS_API_KEY and SNOWFLAKE_ACCOUNT / _USER / _PASSWORD (+ optional
_ROLE, _WAREHOUSE, _DATABASE).

    python scripts/refresh_ams.py            # fetch since the last load, MERGE
    python scripts/refresh_ams.py --seed     # one-off: replace tables with data/*.csv
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
    pass  # the Action passes everything as real environment variables

import ethanol_grind  # noqa: E402
import snowflake_db  # noqa: E402


def seed() -> None:
    for kind, path in (("weekly", ethanol_grind.WEEKLY_PATH), ("daily", ethanol_grind.DAILY_PATH)):
        frame = ethanol_grind._read_snapshot(path)
        sent = snowflake_db.merge_ams(kind, frame, replace=True)
        print(f"seeded {kind}: {sent:,} rows from {path.name}")


def main() -> int:
    if "--seed" in sys.argv:
        seed()
    else:
        for kind, sent in ethanol_grind.refresh_snowflake().items():
            print(f"{kind}: merged {sent:,} rows")
    for kind in ("weekly", "daily"):
        print(f"{kind}: latest date in Snowflake {snowflake_db.max_ams_date(kind)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
