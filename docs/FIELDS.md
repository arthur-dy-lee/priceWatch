# Fields reference

Every configured source exposes a set of fields you can use in rule expressions.
Fields are **derived on demand** from the SQLite history table — nothing is
precomputed or materialized, so adding new fields later won't require a
migration.

You can introspect what's available at any time:

```
pricewatch fields --source nb_993_grey
```

## Common fields (all kinds)

| Field                  | Type      | Meaning                                                       |
|------------------------|-----------|---------------------------------------------------------------|
| `price` / `value`      | float     | Latest observed value (aliases — `price` reads more naturally for goods, `value` for odds/abstract signals) |
| `price_prev` / `value_prev` | float | The observation immediately before the latest                |
| `ts`                   | iso str   | Timestamp of the latest observation (UTC)                     |
| `pct_change_1d`        | float (%) | Percent change vs. nearest snapshot 1 day ago (negative = drop) |
| `pct_change_7d`        | float (%) | Same, 7 days                                                  |
| `pct_change_30d`       | float (%) | Same, 30 days                                                 |
| `min_7d` / `max_7d`    | float     | Rolling min / max within last 7 days                          |
| `min_30d` / `max_30d`  | float     | Rolling min / max within last 30 days                         |
| `avg_7d` / `avg_30d`   | float     | Rolling mean                                                  |
| `min_all` / `max_all`  | float     | Lifetime min / max                                            |
| `drop_from_max_30d`    | float (%) | `(price - max_30d) / max_30d * 100` — convenience for "down N% from peak" |

> **Lookback semantics:** any "N days ago" field uses the most recent
> snapshot at or before `now - N days`. If you don't have data that far
> back yet, the field returns `None` and any rule using it will be
> treated as false.

## Stock kind — additional fields

Stock sources also expose passthrough fields from the snapshot's `meta`:

| Field         | Meaning                                |
|---------------|----------------------------------------|
| `open`        | Day's opening price                    |
| `close`       | Previous day's close                   |
| `high` / `low`| Intraday high / low                    |
| `volume`      | Number of shares traded today          |
| `pe`          | Trailing P/E ratio                     |
| `market_cap`  | Market capitalization                  |

Use cases:
- Volume confirmation: `AAPL.pct_change_1d < -3 and AAPL.volume > AAPL.avg_volume_30d * 2`
- Valuation gate: `AAPL.price < AAPL.min_30d and AAPL.pe < 20`

## Odds kind — additional fields

| Field          | Meaning                                                              |
|----------------|----------------------------------------------------------------------|
| `implied_prob` | Implied probability = 1 / odds                                       |
| `book`         | Bookmaker name                                                       |

Cross-book arbitrage will typically be expressed at the *rule* level, comparing
two odds sources for the same event.

## Adding new fields

1. Add a branch to `SourceView._compute` in `pricewatch/rules/derivers.py`.
2. Add the field name to `_COMMON_FIELDS` (or the kind-specific tuple).
3. Done — `pricewatch fields` and `test-rule` will see it immediately. No
   schema migration.
