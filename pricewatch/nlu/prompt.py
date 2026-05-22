"""System prompt + few-shot examples for intent extraction.

Kept in its own file so we can iterate on the prompt without touching code.
"""
from __future__ import annotations

SYSTEM_PROMPT = """You convert one user instruction into ONE strict JSON object\
 describing a priceWatch monitor configuration. Output ONLY the JSON, no commentary,\
 no markdown fences, no leading/trailing text.

Schema:

{
  "action": "add_monitor",
  "source": {
    "name": "<short snake_case id chosen from the URL or product name>",
    "type": "<newbalance | jd | taobao | ...>",
    "url":  "<the product URL the user mentioned>",
    "interval": "<polling interval; default 1h; valid units s/m/h/d>"
  },
  "rules": [
    {
      "name": "<human label, can be Chinese or English>",
      "when": "<simpleeval expression using <source.name>.price / .pct_change_7d / .min_30d etc>",
      "notify": ["telegram"],   // or ["telegram","macos"], etc.
      "cooldown": "6h"
    }
  ]
}

For "stop / remove / cancel" instructions, output:

{ "action": "remove_monitor", "name": "<the configured source name to drop>" }

Available source types right now: REPLACE_TYPES.

Rule expression fields you may use on the right-hand side of `when:`
  .price            current value (number)
  .price_prev       previous fetch's value
  .pct_change_1d / .pct_change_7d / .pct_change_30d   percent change (negative = drop)
  .min_7d / .max_7d / .avg_7d
  .min_30d / .max_30d / .avg_30d
  .min_all / .max_all
  .drop_from_max_30d   percent below 30-day peak

Rules:
- If the user says "price below X" or "under X", use `<src>.price < X`
- If "drops N%", use `<src>.pct_change_7d <= -N`  (assume 7-day window unless specified)
- If "30-day low", use `<src>.price <= <src>.min_30d`
- Always include a cooldown (default 6h)
- Pick a stable `source.name` like `nb_rebel_v5`, `jd_airpods_pro`, etc.
- Set `type` from the domain: newbalance.com → newbalance, jd.com → jd, taobao.com → taobao.
"""


FEW_SHOT_EXAMPLES = [
    {
        "user": "盯一下这双鞋 https://www.newbalance.com/pd/fuelcell-rebel-v5/MFCXV5-50690.html 价格低于 100 美元告诉我",
        "assistant": '{"action":"add_monitor","source":{"name":"nb_rebel_v5","type":"newbalance","url":"https://www.newbalance.com/pd/fuelcell-rebel-v5/MFCXV5-50690.html","interval":"1h"},"rules":[{"name":"Rebel v5 跌破 $100","when":"nb_rebel_v5.price < 100","notify":["telegram"],"cooldown":"6h"}]}',
    },
    {
        "user": "monitor https://www.newbalance.com/pd/made-in-usa-993/M993-MUSA.html alert when it drops 15% in a week",
        "assistant": '{"action":"add_monitor","source":{"name":"nb_993","type":"newbalance","url":"https://www.newbalance.com/pd/made-in-usa-993/M993-MUSA.html","interval":"1h"},"rules":[{"name":"993 7d drop >= 15%","when":"nb_993.pct_change_7d <= -15","notify":["telegram"],"cooldown":"12h"}]}',
    },
    {
        "user": "stop watching nb_rebel_v5",
        "assistant": '{"action":"remove_monitor","name":"nb_rebel_v5"}',
    },
]


def build_messages(user_text: str, source_types: list[str]) -> list[dict]:
    """Return OpenAI-style messages list. Works for all three backends."""
    system = SYSTEM_PROMPT.replace("REPLACE_TYPES", ", ".join(source_types) or "(none)")
    msgs: list[dict] = [{"role": "system", "content": system}]
    for ex in FEW_SHOT_EXAMPLES:
        msgs.append({"role": "user", "content": ex["user"]})
        msgs.append({"role": "assistant", "content": ex["assistant"]})
    msgs.append({"role": "user", "content": user_text})
    return msgs
