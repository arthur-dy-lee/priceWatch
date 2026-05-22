# Rule reference

A rule is a YAML block under `rules:` in `pricewatch/config.yaml`. It binds a
boolean expression to one or more notifier channels, with optional debounce
and cooldown gates.

```yaml
- name: 993 跌破 1000
  when: "nb_993_grey.price < 1000"
  notify: [telegram]
  cooldown: 6h
  debounce: 30m       # optional — see Caveats below
  message: "NB 993 dropped below 1000"   # optional custom body
```

## Expression syntax

Expressions are evaluated by [`simpleeval`](https://github.com/danthedeckie/simpleeval)
— a safe subset of Python that supports arithmetic, comparisons, and boolean
operators, but not function calls, attribute traversal into arbitrary
objects, or imports.

Supported:

| Form                | Example                                             |
|---------------------|-----------------------------------------------------|
| Comparison          | `nb_993_grey.price < 1000`                          |
| Arithmetic          | `aapl.price * 100 < aapl.market_cap`                |
| Boolean `and / or / not` | `nb.price < 900 or nb.pct_change_7d <= -10`    |
| Range chains        | `5 < apl.pe < 20`                                   |
| Numeric literals    | `int`, `float`, `-3.5`                              |

**Tip:** test before you commit to a config:

```
pricewatch test-rule "nb_993_grey.pct_change_7d <= -5"
```

## Notify channels

`notify: [telegram, macos]` — each name must match a key under the
top-level `notifiers:` block.

Currently shipped:

| Channel    | Required env / config                                   |
|------------|---------------------------------------------------------|
| `telegram` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` in `.env`       |
| `macos`    | None (uses local osascript Notification Center)         |

## Debounce vs Cooldown

These are **different** mechanisms — set both if you want both behaviors.

|              | Purpose                                              | Default |
|--------------|------------------------------------------------------|---------|
| `debounce: 30m` | Predicate must stay true for the whole 30m window before firing. Suppresses brief flickers (e.g. price jitter 999/1001). | off  |
| `cooldown: 6h`  | After a fire, suppress further fires of the same rule for 6h. Prevents notification spam. | off  |

**v0.1 status:** `cooldown` is fully enforced (persisted in `rule_fires`
table). `debounce` is parsed and logged but not strictly enforced yet — it
requires re-evaluating the predicate at past timestamps using historical
snapshots, planned for v0.2.

## Duration syntax

`s` seconds · `m` minutes · `h` hours · `d` days. Whole numbers only.
`30m`, `1h`, `7d`, `15s`. No combinations like `1h30m`.

## Examples

```yaml
# 1. Absolute price threshold
- name: NB 993 under 1000
  when: "nb_993_grey.price < 1000"
  notify: [telegram]
  cooldown: 6h

# 2. Percent-drop threshold
- name: AirPods 7-day drop >= 10%
  when: "jd_airpods_pro.pct_change_7d <= -10"
  notify: [telegram]
  cooldown: 12h

# 3. Historical-low trigger
- name: NB 993 at 30-day low
  when: "nb_993_grey.price <= nb_993_grey.min_30d"
  notify: [telegram, macos]
  cooldown: 24h

# 4. Combined: cheap AND still falling (avoid sideways markets)
- name: cheap and trending down
  when: "nb_993_grey.price < 1000 and nb_993_grey.pct_change_7d < -5"
  notify: [telegram]
  cooldown: 6h

# 5. Stock — volume-confirmed dump
- name: AAPL volume-confirmed dump
  when: "aapl.pct_change_1d <= -3 and aapl.volume >= aapl.avg_30d * 2"
  notify: [telegram]
  cooldown: 4h

# 6. Multi-condition fallback
- name: any-trigger
  when: "nb.price < 900 or nb.drop_from_max_30d <= -25"
  notify: [telegram]
```

## Caveats

- **Unknown names** in expressions cause the rule to be skipped, not crash.
  Check logs.
- **Insufficient history** makes derived fields return `None`. A rule like
  `pct_change_30d < -10` will not fire until you have at least 30 days of
  data — by design, but watch for it on day 1.
- Don't reference the same source by two different names; the engine
  keys on the configured `name`.
