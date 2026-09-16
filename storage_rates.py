"""CME maximum storage (premium) charges over time, for historical % of full carry.

Charts compute % of full carry for every past session. Using today's storage rate for all
of them misstates history wherever the exchange rate has since changed, so each session
is priced at the rate that was in effect on that date — the same point-in-time convention
CME's own VSR calculation uses ("current daily premium charge").

Rates are dollars per bushel per day, matching the app's `default_storage` convention
(x100 gives cents on the bushel-quoted markets): 0.00165 = 16.5/100 of a cent per bushel
per day, roughly 5 cents per bushel per month.

Sources
-------
Corn and soybeans — CME SER-8198RRR (Oct 23, 2018): 16.5/100 -> 26.5/100.
    Corn:     16.5 through 12/18/2019, 26.5 commencing 12/19/2019
              (after expiration of the December 2019 contract)
    Soybeans: 16.5 through 11/18/2019, 26.5 commencing 11/19/2019
              (after expiration of the November 2019 contract)

Chicago SRW (ZW) and KC HRW (KE) wheat — Variable Storage Rate. A nearby spread
averaging >= 80% of financial full carry raises the rate 10/100 of a cent following the
nearby delivery period; <= 50% lowers it; the floor is 16.5/100. Every step below is from
a CME VSR results Special Executive Report, and each report's starting rate matches the
previous report's outcome without a break:
    SER-8727  Mar  1 2021  ZW 16.5 floor, KE 16.5 floor   (earliest verified anchor)
    SER-8983  Apr 26 2022  ZW 16.5, KE 16.5 — no change through SER-9211 (Jun 2023)
    SER-9246  Aug 29 2023  ZW 16.5 -> 26.5 on Sep 19 2023  (90.29% FFC)
    SER-9341  Feb 26 2024  ZW 26.5 -> 16.5 on Mar 19 2024  (33.05%)
    SER-9368  Apr 29 2024  ZW 16.5 -> 26.5 on May 19 2024  (92.00%)
    SER-9560  Apr 29 2025  KE 16.5 -> 26.5 on May 19 2025  (83.40%)
    SER-9694  Feb 24 2026  ZW 26.5 -> 16.5 on Mar 19 2026  (45.50%)
    SER-9973  Jun 29 2026  KE 26.5 -> 16.5 on Jul 19 2026  (41.26%)
    SER-9809  Aug 24 2026  both unchanged at 16.5; minimum rises to 26.5 following
                           expiration of the December 2026 contracts

Known gaps — stated rather than papered over
--------------------------------------------
* Wheat, Mar 2021 -> Apr 2022: CME's notice index does not surface the five
  determinations in between. Both ends sit at the 16.5 floor, so the rate could only
  have differed through a rise and a fall inside that year; treated as 16.5.
* Dates before a product's first entry return None, and callers fall back to the rate
  entered in the app.

Corn and soybeans before 2019: the rate was unchanged at 16.5/100 for the whole archive
window (confirmed by JSA), so the 2019 steps are the only ones needed back to 2006.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date

# product_code -> [(effective_date, dollars_per_bushel_per_day), ...], ascending.
# A rate applies from its effective date until the next entry.
SCHEDULE: dict[str, list[tuple[date, float]]] = {
    "ZC": [
        (date(2006, 1, 1), 0.00165),    # unchanged before 2019, back to the archive start
        (date(2019, 12, 19), 0.00265),  # SER-8198RRR
    ],
    "ZS": [
        (date(2006, 1, 1), 0.00165),
        (date(2019, 11, 19), 0.00265),  # SER-8198RRR
    ],
    "ZW": [
        (date(2021, 3, 1), 0.00165),    # SER-8727, VSR floor
        (date(2023, 9, 19), 0.00265),   # SER-9246
        (date(2024, 3, 19), 0.00165),   # SER-9341
        (date(2024, 5, 19), 0.00265),   # SER-9368
        (date(2026, 3, 19), 0.00165),   # SER-9694
        (date(2026, 12, 19), 0.00265),  # SER-9809, minimum raised after Dec 2026 expiry
    ],
    "KE": [
        (date(2021, 3, 1), 0.00165),    # SER-8727, VSR floor
        (date(2025, 5, 19), 0.00265),   # SER-9560
        (date(2026, 7, 19), 0.00165),   # SER-9973
        (date(2026, 12, 19), 0.00265),  # SER-9809, minimum raised after Dec 2026 expiry
    ],
}

_DATES = {code: [d for d, _ in steps] for code, steps in SCHEDULE.items()}


def has_schedule(product_code: str) -> bool:
    return product_code in SCHEDULE


def rate_on(product_code: str, on: date) -> float | None:
    """The maximum storage rate in effect on `on`, or None if unknown for that date."""
    steps = SCHEDULE.get(product_code)
    if not steps:
        return None
    i = bisect_right(_DATES[product_code], on) - 1
    return steps[i][1] if i >= 0 else None


def rates_on(product_code: str, dates, fallback: float) -> list[float]:
    """Vectorised `rate_on` over a sequence of dates, substituting `fallback` wherever the
    schedule has no answer (unscheduled product, or a date before its first entry)."""
    if product_code not in SCHEDULE:
        return [fallback] * len(dates)
    out = []
    for d in dates:
        r = rate_on(product_code, d)
        out.append(fallback if r is None else r)
    return out


def changes_between(product_code: str, start: date, end: date) -> list[tuple[date, float]]:
    """Rate steps that take effect inside [start, end] — for marking them on charts."""
    return [(d, r) for d, r in SCHEDULE.get(product_code, ()) if start <= d <= end]
