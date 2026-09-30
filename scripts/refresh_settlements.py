"""Bank each day's futures settlements into Snowflake (see settlement_archive.py).

Run daily after the close; safe to re-run. Credentials come from the environment or the
repo's .env: MASSIVE_API_KEY plus the usual SNOWFLAKE_* (key-pair or password).

    python scripts/refresh_settlements.py              # last week, all markets
    python scripts/refresh_settlements.py --backfill   # everything Massive still serves
    python scripts/refresh_settlements.py --coverage   # report what's stored, load nothing
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env")
except ImportError:
    pass

import settlement_archive  # noqa: E402


def api_key() -> str:
    key = os.environ.get("MASSIVE_API_KEY", "")
    if key:
        return key
    secrets = REPO / ".streamlit" / "secrets.toml"
    if secrets.exists():
        import tomllib

        return tomllib.loads(secrets.read_text(encoding="utf-8")).get("MASSIVE_API_KEY", "")
    return ""


def main() -> int:
    if "--coverage" in sys.argv:
        print(settlement_archive.coverage().to_string(index=False))
        return 0

    key = api_key()
    if not key:
        print("No MASSIVE_API_KEY in the environment, .env or .streamlit/secrets.toml")
        return 1

    backfill = "--backfill" in sys.argv
    sent = settlement_archive.refresh(key, backfill=backfill)
    for product_code, rows in sent.items():
        print(f"{product_code}: merged {rows:,} rows")
    print()
    print(settlement_archive.coverage().to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
