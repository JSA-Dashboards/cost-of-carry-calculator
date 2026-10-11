"""Canola cash prices from Fastmarkets into JSA.COST_OF_CARRY.CANOLA_CASH.

Feeds the Oilseeds Crush Margins dashboard's "Fastmarkets cash" canola legs:
  AG-RPS-0001  Canola oil, RBD, fob Los Angeles        US cents/lb
  AG-RPS-0003  Canola meal, fob Velva ND               $/short ton
  AG-RPS-0002 / AG-RPS-0004  the same two as basis to CME (oil ¢/lb, meal $/st)

Credentials: FOB_VESSEL_SERVICE_NAME / FOB_VESSEL_API_KEY (JSA's Fastmarkets licence), read
from the environment, else from the river-fob-portal .env on the droplet. Rows are MERGEd on
(symbol, date), so re-runs and overlapping windows are safe.
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

SYMBOLS = {
    "AG-RPS-0001": "canola_oil_la_cents_lb",
    "AG-RPS-0002": "canola_oil_basis_cents_lb",
    "AG-RPS-0003": "canola_meal_velva_usd_st",
    "AG-RPS-0004": "canola_meal_basis_usd_st",
}
TABLE = "CANOLA_CASH"
BASE = "https://api.fastmarkets.com/Physical/v2"
FIRST = date(2000, 9, 15)
DDL = """
CREATE TABLE IF NOT EXISTS {schema}.{table} (
    SYMBOL    VARCHAR(16) NOT NULL,   -- Fastmarkets symbol
    DATE      DATE        NOT NULL,
    LOW       FLOAT,
    MID       FLOAT,
    HIGH      FLOAT,
    LOADED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
"""


def _creds() -> tuple[str, str]:
    name = os.environ.get("FOB_VESSEL_SERVICE_NAME", "").strip().strip('"')
    key = os.environ.get("FOB_VESSEL_API_KEY", "").strip().strip('"')
    if not (name and key):
        for env in (Path("/opt/river-fob-portal/.env"),
                    Path(__file__).resolve().parent.parent / "river-fob-portal" / ".env"):
            if env.exists():
                vals = dict(l.strip().split("=", 1) for l in env.read_text().splitlines()
                            if "=" in l and not l.startswith("#"))
                name = vals.get("FOB_VESSEL_SERVICE_NAME", "").strip().strip('"')
                key = vals.get("FOB_VESSEL_API_KEY", "").strip().strip('"')
                break
    if not (name and key):
        raise RuntimeError("Fastmarkets creds not found (FOB_VESSEL_SERVICE_NAME / FOB_VESSEL_API_KEY)")
    return name, key


def _token() -> str:
    name, key = _creds()
    r = requests.post("https://auth.fastmarkets.com/connect/token", timeout=30, data={
        "grant_type": "servicekey", "client_id": "service_client",
        "scope": "fastmarkets.physicalprices.api", "serviceName": name, "serviceKey": key})
    r.raise_for_status()
    return r.json()["access_token"]


def fetch(since: date, until: date | None = None) -> pd.DataFrame:
    """symbol / date / low / mid / high, in <=2-year chunks (the API's history limit)."""
    until = until or date.today()
    headers = {"Authorization": "Bearer " + _token()}
    rows, lo = [], since
    while lo <= until:
        hi = min(lo + timedelta(days=700), until)
        r = requests.get(f"{BASE}/Prices/history", headers=headers, timeout=90, params={
            "symbols": ",".join(SYMBOLS), "fromDate": lo.isoformat(), "toDate": hi.isoformat(),
            "calendarType": "Weekdays"})
        r.raise_for_status()
        for ins in r.json().get("instruments", []):
            for p in ins.get("prices", []):
                rows.append({"symbol": ins.get("symbol"), "date": p["date"][:10],
                             "low": p.get("low"), "mid": p.get("mid"), "high": p.get("high")})
        lo = hi + timedelta(days=1)
    df = pd.DataFrame(rows, columns=["symbol", "date", "low", "mid", "high"])
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.dropna(subset=["mid"]).drop_duplicates(["symbol", "date"], keep="last")


def merge(frame: pd.DataFrame) -> int:
    import snowflake_db

    if frame is None or not len(frame):
        return 0
    rows = [(r.symbol, r.date.isoformat(), r.low, r.mid, r.high) for r in frame.itertuples(index=False)]
    conn = snowflake_db.connect()
    try:
        cur = conn.cursor()
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {snowflake_db.SCHEMA}")
        cur.execute(DDL.format(schema=snowflake_db.SCHEMA, table=TABLE))
        table = f"{snowflake_db.SCHEMA}.{TABLE}"
        cur.execute(f"CREATE TEMPORARY TABLE CASH_STAGE LIKE {table}")
        cur.executemany("INSERT INTO CASH_STAGE (SYMBOL, DATE, LOW, MID, HIGH) VALUES (%s,%s,%s,%s,%s)", rows)
        cur.execute(f"""
            MERGE INTO {table} t USING CASH_STAGE s ON t.SYMBOL = s.SYMBOL AND t.DATE = s.DATE
            WHEN MATCHED THEN UPDATE SET LOW = s.LOW, MID = s.MID, HIGH = s.HIGH, LOADED_AT = CURRENT_TIMESTAMP()
            WHEN NOT MATCHED THEN INSERT (SYMBOL, DATE, LOW, MID, HIGH) VALUES (s.SYMBOL, s.DATE, s.LOW, s.MID, s.HIGH)
        """)
        conn.commit()
        return len(rows)
    finally:
        conn.close()


def refresh(days: int = 14, backfill: bool = False) -> int:
    since = FIRST if backfill else date.today() - timedelta(days=days)
    return merge(fetch(since))
