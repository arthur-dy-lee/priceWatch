"""NewBalance product-page scraper.

Strategy:
  1. Most NB regional sites (US/EU/CN) ship a JSON-LD <script type="application/ld+json">
     Product block including offers.price. Try that first — it's stable.
  2. Fallback to common DOM selectors for the price element.

If the scraper returns wrong prices, run:
  pricewatch fetch --source <name> --debug
to dump the raw HTML to data/debug/.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from loguru import logger
from parsel import Selector

from ..settings import settings
from ..signals import Signal, SignalKind
from .base import Source
from .registry import register_source


_PRICE_FALLBACK_SELECTORS = [
    'meta[property="product:price:amount"]::attr(content)',
    'meta[itemprop="price"]::attr(content)',
    '[data-test="product-price"] *::text',
    '.product-price ::text',
    '.price ::text',
]

_PRICE_NUM_RE = re.compile(r"[-+]?\d{1,3}(?:[,\s]?\d{3})*(?:\.\d+)?")


@register_source("newbalance")
class NewBalanceSource(Source):
    kind = SignalKind.PRICE

    async def fetch(self) -> Signal:
        url = self.cfg.get("url")
        if not url:
            raise ValueError(f"source '{self.name}': missing 'url'")

        timeout = float(self.cfg.get("timeout", 15))
        async with httpx.AsyncClient(
            headers={"User-Agent": settings.pricewatch_user_agent, "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8"},
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            r = await client.get(url)
            r.raise_for_status()
            html = r.text

        if self.cfg.get("debug"):
            self._dump_debug(html)

        price, currency, meta = self._extract(html)
        sku = self.cfg.get("sku") or self._sku_from_url(url)
        meta["url"] = url
        return Signal(
            kind=self.kind,
            source=self.name,
            id=sku,
            value=price,
            currency=currency,
            ts=datetime.now(timezone.utc),
            meta=meta,
        )

    # ---- extraction ----

    def _extract(self, html: str) -> tuple[float, str | None, dict[str, Any]]:
        sel = Selector(text=html)

        # 1) JSON-LD Product block
        for block in sel.css('script[type="application/ld+json"]::text').getall():
            try:
                data = json.loads(block)
            except json.JSONDecodeError:
                continue
            price, currency, title = self._pluck_jsonld(data)
            if price is not None:
                return price, currency, {"title": title, "extractor": "jsonld"}

        # 2) DOM fallbacks
        for css in _PRICE_FALLBACK_SELECTORS:
            for raw in sel.css(css).getall():
                p = self._parse_price(raw)
                if p is not None:
                    title = sel.css("title::text").get(default="").strip()
                    return p, None, {"title": title, "extractor": f"css:{css}"}

        raise RuntimeError(f"source '{self.name}': could not locate price on page")

    def _pluck_jsonld(self, data: Any) -> tuple[float | None, str | None, str]:
        """Walk JSON-LD looking for Product.offers.price."""
        candidates = data if isinstance(data, list) else [data]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            t = item.get("@type")
            if t == "Product" or (isinstance(t, list) and "Product" in t):
                offers = item.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                if isinstance(offers, dict):
                    price = offers.get("price") or offers.get("lowPrice")
                    cur = offers.get("priceCurrency")
                    if price is not None:
                        try:
                            return float(price), cur, str(item.get("name", "")).strip()
                        except (TypeError, ValueError):
                            pass
            # nested @graph
            if "@graph" in item:
                p, c, t_ = self._pluck_jsonld(item["@graph"])
                if p is not None:
                    return p, c, t_
        return None, None, ""

    @staticmethod
    def _parse_price(raw: str) -> float | None:
        m = _PRICE_NUM_RE.search(raw)
        if not m:
            return None
        try:
            return float(m.group(0).replace(",", "").replace(" ", ""))
        except ValueError:
            return None

    @staticmethod
    def _sku_from_url(url: str) -> str:
        # Heuristic: last path segment before the query.
        from urllib.parse import urlparse
        path = urlparse(url).path.rstrip("/")
        return path.rsplit("/", 1)[-1] or url

    def _dump_debug(self, html: str) -> None:
        out = Path("data/debug") / f"{self.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8")
        logger.info(f"[{self.name}] dumped html to {out}")
