"""Greedy, deterministic selection of distinct product alternatives."""

from __future__ import annotations

import re
from collections.abc import Sequence
from sqlite3 import Row

from otto_categories import UNKNOWN_CATEGORY, price_band

_TOKEN_STOPWORDS = {
    "der", "die", "das", "den", "dem", "des", "und", "oder", "mit", "für",
    "von", "im", "in", "auf", "set", "stück", "neu", "otto", "home",
}


def select_diverse_alternatives(
    candidates: Sequence[Row],
    main_product: Row,
    limit: int = 3,
) -> list[Row]:
    if limit <= 0:
        return []

    selected: list[Row] = []
    excluded_urls = {main_product["produkt_url"]}
    references = [main_product]
    covered_categories = _known_categories(references)
    covered_brands = _known_brands(references)
    covered_price_bands = _known_price_bands(references)

    while len(selected) < limit:
        best: Row | None = None
        best_score = -1
        for candidate in candidates:
            url = candidate["produkt_url"]
            if url in excluded_urls or _too_similar(candidate, references):
                continue

            category = _category(candidate)
            brand = _brand(candidate)
            band = price_band(candidate["preis"], candidate["currency"])
            category_new = bool(category and category not in covered_categories)
            brand_new = bool(brand and brand not in covered_brands)
            band_new = bool(band and band not in covered_price_bands)
            score = 4 * category_new + 2 * brand_new + band_new
            if score > best_score:
                best = candidate
                best_score = score

        if best is None:
            break
        selected.append(best)
        references.append(best)
        excluded_urls.add(best["produkt_url"])
        covered_categories.update(_known_categories([best]))
        covered_brands.update(_known_brands([best]))
        covered_price_bands.update(_known_price_bands([best]))
    return selected


def _category(product: Row) -> str | None:
    category = product["category"]
    return category if category and category != UNKNOWN_CATEGORY else None


def _brand(product: Row) -> str | None:
    brand = product["marke"]
    return brand.strip().casefold() if brand and brand.strip() else None


def _known_categories(products: Sequence[Row]) -> set[str]:
    return {category for product in products if (category := _category(product))}


def _known_brands(products: Sequence[Row]) -> set[str]:
    return {brand for product in products if (brand := _brand(product))}


def _known_price_bands(products: Sequence[Row]) -> set[str]:
    return {
        band
        for product in products
        if (band := price_band(product["preis"], product["currency"]))
    }


def _too_similar(candidate: Row, references: Sequence[Row]) -> bool:
    candidate_tokens = _title_tokens(candidate)
    if not candidate_tokens:
        return False
    for reference in references:
        reference_tokens = _title_tokens(reference)
        if not reference_tokens:
            continue
        union = candidate_tokens | reference_tokens
        if union and len(candidate_tokens & reference_tokens) / len(union) >= 0.85:
            return True
    return False


def _title_tokens(product: Row) -> set[str]:
    title = (product["titel"] or "").casefold()
    brand = (product["marke"] or "").casefold()
    brand_tokens = set(re.findall(r"\w+", brand))
    return {
        token
        for token in re.findall(r"\w+", title)
        if token not in _TOKEN_STOPWORDS and token not in brand_tokens and not token.isdigit()
    }
