# JSA — Cost of Carry & Seasonal Spreads

Streamlit app that prices CBOT and MGEX grain futures spreads against the full financial
cost of carry (storage + interest), replicating the JSA *Cost of Carry Sheet* workbook with
live market data.

## What it does

For every near/deferred contract pair on the curve it computes:

```
spread          = near price - far price
full storage    = days between expirations x daily storage rate   (x100 on cents/bu markets)
full interest   = near price x annual rate x days / 360
full carry      = full storage + full interest
% of full carry = spread / -(full storage + full interest)
```

A spread paying 100% of full carry covers storage and interest exactly. Colour coding
follows the workbook: green >= 75%, yellow 50-74%, red < 50%.

## Tabs

| Tab | Purpose |
| --- | --- |
| **Summary** | All seven markets stacked in the workbook's layout, two-digit contract labels, one interest rate driving every market. |
| **Spread Builder** | Free-form seasonal chart: pick market, both legs, measure, and overlay prior crop years on a shared calendar axis with an average line. |
| **Per-market tabs** | Full spread matrix with 12-month spread high/low and dates, plus history and seasonal charts. |

Markets: corn (ZC), soybeans (ZS), soybean meal (ZM), soybean oil (ZL), Chicago/SRW wheat
(ZW), KC/HRW wheat (KE), MGEX spring wheat (HRS).

## Interest rate

Defaults to the live front-month **CME 30-Day Federal Funds future (ZQ)** implied rate
(`100 - price`) plus a 2.25% spread for a commercial cost of funds. Editable per market.

## Data source

[Massive](https://massive.com) futures REST API (`api.massive.com/futures/v1`):

- `/contracts` — outright tickers and settlement dates (combos filtered client-side)
- `/snapshot` — live prices
- `/aggs/{ticker}?resolution=1session` — daily settlement history

Daily bars begin **2021-09-02**, which caps seasonal overlays at roughly five crop years —
except for corn and soybeans, bridged by a local archive (below) back to 2008.
Massive carries no options on futures — only OPRA-listed equity/index options, which are
a separate entitlement.

### Pre-2021 archive (corn & soybeans only)

Daily settlements for every corn and soybean contract month from 2008 through 2021,
ETL'd once from the JSA "Futures History.xlsx" workbook via
`scripts/build_history_archive.py` (re-run only if that source workbook is updated).
Seasonal overlays for corn/soybeans use it to reach up to 18 crop years back instead of
Massive's ~5, switching sources at contract year 2022 with no gap. Wheat, meal, and oil
have no archive and stay capped at Massive's native window.

**Storage:** the archive lives in Snowflake at `JSA.COST_OF_CARRY.FUTURES_HISTORY_ARCHIVE`
(49,672 rows / 168 contracts). `history_archive.py` reads it when `USE_SNOWFLAKE=1` and
otherwise falls back to the committed `data/futures_history_archive.csv`, which holds
identical data — so a Snowflake outage degrades rather than breaks the app. The Spread
Builder's seasonal caption names whichever source actually served the rows.
`snowflake/01_migrate_archive.py` creates the schema and (re-)loads it from the CSV.

### Historical storage and interest rates

Applying today's rates to every past spread misstates history. With **Historical rates** on
(the default, on every market), each spread is priced at the rates that actually applied.

**Storage is priced per spread, not per date** (`storage_rates.py`). A spread carries under
the CME maximum storage rate in force across its **carry window** — from the 19th of its
near delivery month to the 19th of its far one. That rate belongs to the spread pair, so
it's one constant for the whole line whatever date the spread is viewed on:

- **VSR wheat (SRW, HRW).** Each *nearby* spread (H/K, K/N, N/U, U/Z, Z/H) is observed from
  the 19th of the previous delivery month through nearby option expiration. Its average %
  of financial full carry (≥ 80% up, ≤ 50% down, 10/100¢/day steps, 16.5 floor) sets the
  rate that takes effect on the 19th of the nearby delivery month, after delivery, and
  governs certificates carried into the next delivery month. So a Mar/May spread carries
  under the rate its own Mar–May observation set. Adjacent spreads sit in one VSR period;
  a wider spread such as Dec/May spans several and can straddle a change.
- **Corn and soybeans.** Fixed maximums that stepped from 16.5 to 26.5 after the Dec 2019
  (corn) and Nov 2019 (soybeans) contracts expired. The increase was announced in 2018, so
  a spread whose carry window falls after the step carries at 26.5 across its whole life.

| Market | Storage rate history (/100 of a cent per bushel per day) |
| --- | --- |
| Corn | 16.5 → **26.5** from 12/19/2019 (SER-8198RRR) |
| Soybeans | 16.5 → **26.5** from 11/19/2019 (SER-8198RRR) |
| Chicago SRW | VSR: 16.5 → 26.5 (9/19/2023) → 16.5 (3/19/2024) → 26.5 (5/19/2024) → 16.5 (3/19/2026) → 26.5 (12/19/2026, new minimum) |
| KC HRW | VSR: 16.5 → 26.5 (5/19/2025) → 16.5 (7/19/2026) → 26.5 (12/19/2026, new minimum) |

Both wheats' minimum rises to 26.5 after the December 2026 contracts expire, regardless of
that period's VSR result (SER-9809). Every wheat step comes from a CME VSR results notice,
and each notice's starting rate matches the previous notice's outcome. Rates are published
through Mar 18, 2027; carry windows reaching past that are flagged *pending*
(`KNOWN_UNTIL` — advance it as notices are added). Rate inputs default to today's CME rate.

Example: SRW Mar '26/May '26 carries under the 16.5 rate set by its own Mar–May 2026
observation (CME cut 26.5 → 16.5 on Mar 19, 2026), so its full storage is 10.23¢, not the
16.43¢ a flat 26.5 would give — e.g. 68.2% of full carry on Jul 17, 2025, against 49.3%.

**Interest is priced per date** (`interest_rates.py`) — financing is paid at the rate of the
day, as in CME's own VSR calculation: each session's effective fed funds plus the same 2.25%
spread the live rate uses. Source: Board of Governors of the Federal Reserve System (US),
Federal Funds Effective Rate [DFF], retrieved from FRED, Federal Reserve Bank of St. Louis —
public domain, citation requested. Downloaded live (cached 12h) with a committed fallback in
`data/fed_funds_dff.csv`; refresh with `python interest_rates.py`. History uses the
*effective* rate on the day, whereas today's rate in the app is *ZQ futures-implied*, so the
two can differ by a few basis points at a chart's right-hand edge.

Reference lines use the pair's carry-window storage and today's interest.

**Difference from CME's published VSR percentages.** CME's own observation-window
calculation uses the storage rate current on each observation day, because the outcome it
is deciding isn't known yet. These charts use the rate the spread was actually carried
under, known in hindsight, so a spread's % of full carry during its own observation window
can differ from the figure in CME's notice whenever that window produced a change.

Known limit: wheat storage between Mar 2021 and Apr 2022 is bracketed at the 16.5 floor at
both ends rather than individually verified.

**VSR colouring (wheat).** On SRW and HRW seasonal charts — per-market tabs and the Spread
Builder — each crop year's line is coloured by the VSR level governing its carry window:
green **VSR 1** (16.5, ~5¢/month), orange **VSR 2** (26.5, ~8¢), red **VSR 3** (36.5, ~11¢),
with the level in the legend. A spread straddling a change is labelled e.g. *VSR 2→1* and
coloured by the level covering more of its window; one reaching past the last published
determination is marked *pending*. Years sharing a level get successively lighter shades.
Levels are numbered by absolute rate, so they keep their meaning after the December 2026
minimum increase.

### Snowflake configuration

Set these as Streamlit Cloud secrets (or in a local, gitignored `.env`):

```toml
USE_SNOWFLAKE       = "1"
SNOWFLAKE_ACCOUNT   = "GNC89034.us-east-1"
SNOWFLAKE_USER      = "KOLTENPOSTIN"
SNOWFLAKE_PASSWORD  = "..."
SNOWFLAKE_ROLE      = "ACCOUNTADMIN"
SNOWFLAKE_WAREHOUSE = "COMPUTE_WH"
SNOWFLAKE_DATABASE  = "JSA"
SNOWFLAKE_SCHEMA    = "COST_OF_CARRY"
```

Leave `USE_SNOWFLAKE` unset to run entirely off the CSV.

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py --server.port 8512
```

Create `.streamlit/secrets.toml` from the example and add your key:

```toml
MASSIVE_API_KEY = "your-key-here"
```

## Deploying to Streamlit Cloud

Point the app at `app.py`, then add `MASSIVE_API_KEY` under **Settings -> Secrets**.
`.streamlit/secrets.toml` is gitignored and never leaves the machine.

`plotly` and `kaleido` are pinned deliberately: newer combinations have silently broken
PNG export on Streamlit Cloud. Charts also expose Plotly's built-in camera button, which
is client-side and works regardless.

## Notes

- First Notice Day is computed from the CME grain rule (last business day before the
  delivery month) — the API exposes no FND field. Weekend-aware, not holiday-aware.
- Spreads are calculated arithmetically and may deviate from quoted board spreads.
- Prior-year seasonal analogs are built by rolling the contract year back and aligning
  each year on its near leg's expiration.
