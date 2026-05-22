# priceWatch

A local sentinel daemon. Collects observations from configurable sources
(retail prices today, stock quotes and bookmaker odds later), derives
common indicators (rolling min/max, percent change, drop-from-peak), and
fires notifications when user-defined rules trigger.

Designed to run on one Mac, written for the operator-of-one — no server,
no cloud, single SQLite file.

## Architecture

```
Source (collect)  →  Signal (normalize)  →  Storage (sqlite)
                                                  │
                                                  ▼
                                       Rule engine (derived fields,
                                        debounce/cooldown)
                                                  │
                                                  ▼
                                          Notifier (Telegram, macOS)
```

The same pipeline serves prices, stocks, and odds; adding a new domain
means writing one `Source` subclass.

## Quick start

```bash
# 1. install (uv recommended)
cd ~/codes/priceWatch
uv venv && source .venv/bin/activate
uv pip install -e .

# 2. configure
cp .env.example .env
# edit .env: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
# edit pricewatch/config.yaml: sources + rules

# 3. try a one-shot
pricewatch fetch --source nb_993_grey
pricewatch fields --source nb_993_grey
pricewatch test-rule "nb_993_grey.price < 1200"

# 4. run the loop
pricewatch run
```

## Docs

- `docs/FIELDS.md` — what's available on the right-hand side of `when:`
- `docs/RULES.md` — full rule syntax, debounce vs cooldown

## Status

v0.1 — NewBalance source + Telegram/macOS notifiers + SQLite history +
rule engine with cooldown. JD/Taobao sources, stock kind, and odds kind
are scaffolded but not yet implemented.

## License

MIT — see LICENSE.
