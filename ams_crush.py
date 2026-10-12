"""USDA AMS inputs for a regional soybean cash crush, banked into Snowflake.

Feeds the Oilseeds Crush Margins dashboard's regional model:
  MARS 3511  National Grain and Oilseed Processor Feedstuff Report (weekly)
             -> JSA.COST_OF_CARRY.AMS_FEEDSTUFF   soybean meal, soybean oil, canola meal by region
  MARS 3192 / 2850 / 3463 / 2851 / 3049 / 3225  Illinois / Iowa / Indiana / Ohio / Southern Minnesota / Nebraska bids (daily)
             -> JSA.COST_OF_CARRY.AMS_BEAN_BIDS   soybean bids by location and delivery point

marsapi.ams.usda.gov rejects Streamlit Cloud's IPs, so this runs from the droplet (or a PC) and the app reads
Snowflake. Rows are MERGEd on their natural keys, so re-runs and overlapping windows are safe.
Key: MARS_API_KEY from the environment, else a sibling repo's .env (see _key()).
"""
from __future__ import annotations

import os
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

BASE = "https://marsapi.ams.usda.gov/services/v1.2/reports"
FEED_SLUG = 3511
FEED_COMMODITIES = ("Soybean Meal", "Soybean Oil", "Canola Meal")
FEED_FLOOR = date(2022, 2, 1)           # MARS' history for this report starts 2022-02-07
BID_REPORTS = {"IL": 3192, "IA": 2850, "IN": 3463, "OH": 2851, "MN": 3049, "NE": 3225}
BID_FLOOR = date(2020, 7, 1)

FEED_TABLE, BID_TABLE = "AMS_FEEDSTUFF", "AMS_BEAN_BIDS"
DDL_FEED = """
CREATE TABLE IF NOT EXISTS {schema}.AMS_FEEDSTUFF (
    REPORT_DATE DATE NOT NULL,        -- Monday of the report week
    COMMODITY   VARCHAR(32) NOT NULL, -- Soybean Meal | Soybean Oil | Canola Meal
    TRADE_LOC   VARCHAR(48),          -- region, e.g. Illinois
    PROTEIN     VARCHAR(16),
    TRANS_MODE  VARCHAR(16),          -- Rail | Truck | Truck/Rail
    QUOTE_TYPE  VARCHAR(16),
    PRICE_UNIT  VARCHAR(24),          -- $ Per Ton | Cents Per Lb
    PRICE_MIN   FLOAT,
    PRICE_MAX   FLOAT,
    AVG_PRICE   FLOAT,
    LOADED_AT   TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
"""
DDL_BID = """
CREATE TABLE IF NOT EXISTS {schema}.AMS_BEAN_BIDS (
    REPORT_DATE    DATE NOT NULL,
    STATE          VARCHAR(2) NOT NULL,
    TRADE_LOC      VARCHAR(48),
    DELIVERY_POINT VARCHAR(48),       -- Mills and Processors | Country Elevators | Barge Loading Elevators ...
    GRADE          VARCHAR(16),
    FUTURES_MONTH  VARCHAR(24),       -- the futures month the basis is quoted against
    BASIS_MIN      FLOAT,             -- cents/bu
    BASIS_MAX      FLOAT,
    PRICE_MIN      FLOAT,             -- $/bu
    PRICE_MAX      FLOAT,
    AVG_PRICE      FLOAT,
    CURRENT_FLAG   VARCHAR(3),        -- Yes = nearby delivery
    DELIVERY_START DATE,
    LOADED_AT      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
"""


def _key() -> str:
    k = os.environ.get("MARS_API_KEY", "").strip().strip('"')
    if k:
        return k
    here = Path(__file__).resolve().parent
    for env in (Path("/opt/beef-trimmings-dashboard/.env"), Path("/opt/cme-feeder-cattle-index/.env"),
                Path("/opt/livestock-portal/.env"), here.parent / "cme-feeder-cattle-index" / ".env",
                here.parent / "beef-trimmings-dashboard" / ".env"):
        if env.is_file():
            for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("MARS_API_KEY"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("MARS_API_KEY not found (environment or a sibling repo's .env)")


def _rows(slug: int, a: date, b: date, retries: int = 3) -> list[dict]:
    q = f"report_begin_date={a:%m/%d/%Y}:{b:%m/%d/%Y}"
    for i in range(retries):
        try:
            r = requests.get(f"{BASE}/{slug}/Report Detail", auth=(_key(), ""), params={"q": q}, timeout=300)
            r.raise_for_status()
            return r.json().get("results", [])
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(4)
    return []


def _windows(start: date, end: date, days: int = 183):
    lo = start
    while lo <= end:
        hi = min(lo + timedelta(days=days), end)
        yield lo, hi
        lo = hi + timedelta(days=1)


def _num(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v)


def _date(v):
    if not v or (isinstance(v, float) and pd.isna(v)):
        return None
    return pd.to_datetime(v).date()


def fetch_feedstuff(since: date, until: date | None = None) -> pd.DataFrame:
    until = until or date.today()
    out = []
    for a, b in _windows(max(since, FEED_FLOOR), until):
        for r in _rows(FEED_SLUG, a, b):
            if r.get("commodity") in FEED_COMMODITIES:
                out.append({"report_date": _date(r["report_date"]), "commodity": r["commodity"],
                            "trade_loc": r.get("trade Loc"), "protein": r.get("protein"),
                            "trans_mode": r.get("trans_mode"), "quote_type": r.get("quote_type"),
                            "price_unit": r.get("price_unit"), "price_min": _num(r.get("price_min")),
                            "price_max": _num(r.get("price_max")), "avg_price": _num(r.get("avg_price"))})
    df = pd.DataFrame(out)
    return df.drop_duplicates(["report_date", "commodity", "trade_loc", "protein", "trans_mode", "quote_type"],
                              keep="last") if len(df) else df


def fetch_bean_bids(since: date, until: date | None = None, states: list[str] | None = None) -> pd.DataFrame:
    until = until or date.today()
    out = []
    for state, slug in BID_REPORTS.items():
        if states and state not in states:
            continue
        for a, b in _windows(max(since, BID_FLOOR), until):
            for r in _rows(slug, a, b):
                if r.get("commodity") != "Soybeans":
                    continue
                out.append({"report_date": _date(r["report_date"]), "state": state, "trade_loc": r.get("trade_loc"),
                            "delivery_point": r.get("delivery_point"), "grade": r.get("grade"),
                            "futures_month": r.get("basis Min Futures Month"), "basis_min": _num(r.get("basis Min")),
                            "basis_max": _num(r.get("basis Max")), "price_min": _num(r.get("price Min")),
                            "price_max": _num(r.get("price Max")), "avg_price": _num(r.get("avg_price")),
                            "current_flag": r.get("current"), "delivery_start": _date(r.get("delivery_start"))})
    df = pd.DataFrame(out)
    key = ["report_date", "state", "trade_loc", "delivery_point", "futures_month", "current_flag", "delivery_start"]
    return df.drop_duplicates(key, keep="last") if len(df) else df


def _clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return v.isoformat() if isinstance(v, date) else v


def _merge(frame: pd.DataFrame, table: str, ddl: str, cols: list[str], key: list[str]) -> int:
    import snowflake_db

    if frame is None or not len(frame):
        return 0
    rows = [tuple(_clean(v) for v in r) for r in frame[cols].itertuples(index=False, name=None)]
    conn = snowflake_db.connect()
    try:
        cur = conn.cursor()
        schema = snowflake_db.SCHEMA
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        cur.execute(ddl.format(schema=schema))
        full = f"{schema}.{table}"
        cur.execute(f"CREATE TEMPORARY TABLE STAGE_T LIKE {full}")
        cur.executemany(f"INSERT INTO STAGE_T ({', '.join(c.upper() for c in cols)}) "
                        f"VALUES ({', '.join(['%s'] * len(cols))})", rows)
        on = " AND ".join(f"COALESCE(TO_VARCHAR(t.{k.upper()}), '') = COALESCE(TO_VARCHAR(s.{k.upper()}), '')" for k in key)
        sets = ", ".join(f"{c.upper()} = s.{c.upper()}" for c in cols if c not in key)
        cur.execute(f"""
            MERGE INTO {full} t USING STAGE_T s ON {on}
            WHEN MATCHED THEN UPDATE SET {sets}, LOADED_AT = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT ({', '.join(c.upper() for c in cols)})
                 VALUES ({', '.join('s.' + c.upper() for c in cols)})""")
        conn.commit()
        return len(rows)
    finally:
        conn.close()


FEED_COLS = ["report_date", "commodity", "trade_loc", "protein", "trans_mode", "quote_type", "price_unit",
             "price_min", "price_max", "avg_price"]
FEED_KEY = ["report_date", "commodity", "trade_loc", "protein", "trans_mode", "quote_type"]
BID_COLS = ["report_date", "state", "trade_loc", "delivery_point", "grade", "futures_month", "basis_min", "basis_max",
            "price_min", "price_max", "avg_price", "current_flag", "delivery_start"]
BID_KEY = ["report_date", "state", "trade_loc", "delivery_point", "futures_month", "current_flag", "delivery_start"]


def refresh(days: int = 21, backfill: bool = False) -> dict[str, int]:
    since = date(2000, 1, 1) if backfill else date.today() - timedelta(days=days)
    sent = {}
    sent[FEED_TABLE] = _merge(fetch_feedstuff(since), FEED_TABLE, DDL_FEED, FEED_COLS, FEED_KEY)
    sent[BID_TABLE] = _merge(fetch_bean_bids(since), BID_TABLE, DDL_BID, BID_COLS, BID_KEY)
    return sent
