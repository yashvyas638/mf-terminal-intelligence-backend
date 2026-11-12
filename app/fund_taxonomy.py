"""Canonical Indian mutual-fund taxonomy based on SEBI's 26-Feb-2026 circular.

Unknown labels deliberately remain unclassified. Never infer a sub-category from
a scheme marketing name or accept arbitrary text from a database row.
"""
from __future__ import annotations

import re

SCHEME_GROUP_ASSET_CLASS = {
    "Equity Scheme": "Equity",
    "Debt Scheme": "Debt",
    "Hybrid Scheme": "Hybrid",
    "Life Cycle Funds": None,
    "Other Schemes": "Other",
}
VALID_SCHEME_GROUPS = frozenset(SCHEME_GROUP_ASSET_CLASS)
VALID_ASSET_CLASSES = frozenset(value for value in SCHEME_GROUP_ASSET_CLASS.values() if value is not None)

SUBCATEGORIES_BY_GROUP = {
    "Equity Scheme": frozenset({
        "Multi Cap Fund", "Large Cap Fund", "Large & Mid Cap Fund",
        "Mid Cap Fund", "Small Cap Fund", "Flexi Cap Fund",
        "Dividend Yield Fund", "Value Fund", "Contra Fund", "Focused Fund (No. of Stocks)",
        "Sectoral Fund", "Thematic Fund", "ELSS Tax Saver Fund",
    }),
    "Debt Scheme": frozenset({
        "Overnight Fund", "Liquid Fund", "Ultra Short Term Fund",
        "Ultra Short to Short Term Fund", "Money Market Fund",
        "Short Term Fund", "Medium Term Fund", "Medium to Long Term Fund",
        "Long Term Fund", "Dynamic Term Fund", "Corporate Bond Fund",
        "Credit Risk Fund", "Banking and PSU Debt Fund", "Gilt Fund",
        "10-year Constant Maturity Gilt Fund", "Floating Interest Rates Fund",
        "Sectoral Fund",
    }),
    "Hybrid Scheme": frozenset({
        "Conservative Hybrid Fund", "Balanced Hybrid Fund",
        "Aggressive Hybrid Fund", "Dynamic Asset Allocation Fund",
        "Multi Asset Allocation",
        "Arbitrage Fund", "Equity Savings",
    }),
    "Life Cycle Funds": frozenset(),
    "Other Schemes": frozenset({
        "Index Funds / ETFs", "FoFs (Overseas/Domestic)",
    }),
}

def _key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").casefold()).strip()

_GROUP_ALIASES = {
    "equity scheme": "Equity Scheme",
    "equity schemes": "Equity Scheme",
    "growth": "Equity Scheme",
    "growth scheme": "Equity Scheme",
    "elss": "Equity Scheme",
    "debt scheme": "Debt Scheme",
    "debt schemes": "Debt Scheme",
    "income debt oriented schemes": "Debt Scheme",
    "income": "Debt Scheme",
    "income scheme": "Debt Scheme",
    "liquid": "Debt Scheme",
    "gilt": "Debt Scheme",
    "floating rate": "Debt Scheme",
    "money market": "Debt Scheme",
    "hybrid scheme": "Hybrid Scheme",
    "hybrid schemes": "Hybrid Scheme",
    "balanced": "Hybrid Scheme",
    "balanced scheme": "Hybrid Scheme",
    "life cycle": "Life Cycle Funds",
    "life cycle fund": "Life Cycle Funds",
    "life cycle funds": "Life Cycle Funds",
    "other scheme": "Other Schemes",
    "other schemes": "Other Schemes",
    "other etfs": "Other Schemes",
    "gold etfs": "Other Schemes",
    "fund of funds": "Other Schemes",
    "fund of funds scheme domestic": "Other Schemes",
    "fund of fund scheme": "Other Schemes",
    "fund of fund schemes": "Other Schemes",
    "fund of funds scheme": "Other Schemes",
    "overseas fund of funds": "Other Schemes",
    "index funds": "Other Schemes",
    "index funds etfs": "Other Schemes",
    "exchange traded funds etfs": "Other Schemes",
}

_SUBCATEGORY_ALIASES = {
    _key("ELSS-Tax Saver Fund"): "ELSS Tax Saver Fund",
    _key("ELSS - Tax Saver Fund"): "ELSS Tax Saver Fund",
    _key("Banking and PSU Fund"): "Banking and PSU Debt Fund",
    _key("Banking & PSU Debt Fund"): "Banking and PSU Debt Fund",
    _key("10 Year Constant Maturity Gilt Fund"): "10-year Constant Maturity Gilt Fund",
    _key("Floating Rate Fund"): "Floating Interest Rates Fund",
    _key("Index Funds/ ETFs"): "Index Funds / ETFs",
    _key("FoFs (Domestic)"): "FoFs (Overseas/Domestic)",
    _key("FoFs (Overseas)"): "FoFs (Overseas/Domestic)",
    _key("Fund of Funds (Domestic)"): "FoFs (Overseas/Domestic)",
    _key("Fund of Funds (Overseas)"): "FoFs (Overseas/Domestic)",
}

def classify_amfi_category(raw_category: str) -> tuple[str | None, str | None, str | None]:
    """Return canonical broad group, allow-listed sub-category and asset class."""
    raw = " ".join((raw_category or "").strip().split())
    group_raw, separator, subcategory_raw = raw.partition(" - ")
    group = _GROUP_ALIASES.get(_key(group_raw))
    if group is None:
        return None, None, None
    subcategory = None
    if separator and subcategory_raw.strip():
        key = _key(subcategory_raw)
        candidate = _SUBCATEGORY_ALIASES.get(key)
        if candidate is None:
            candidate = next(
                (item for item in SUBCATEGORIES_BY_GROUP[group] if _key(item) == key),
                None,
            )
        if candidate in SUBCATEGORIES_BY_GROUP[group]:
            subcategory = candidate
    return group, subcategory, SCHEME_GROUP_ASSET_CLASS[group]

def canonical_subcategory(group: str | None, category: str | None) -> str | None:
    """Sanitize persisted category text before it reaches APIs or facets."""
    group = canonical_group(group)
    if group not in SUBCATEGORIES_BY_GROUP or not category:
        return None
    key = _key(category)
    candidate = _SUBCATEGORY_ALIASES.get(key)
    if candidate is None:
        candidate = next(
            (item for item in SUBCATEGORIES_BY_GROUP[group] if _key(item) == key),
            None,
        )
    return candidate if candidate in SUBCATEGORIES_BY_GROUP[group] else None

def canonical_group(group: str | None) -> str | None:
    if not group:
        return None
    return group if group in VALID_SCHEME_GROUPS else _GROUP_ALIASES.get(_key(group))

def canonical_asset_class(group: str | None, asset_class: str | None) -> str | None:
    expected = SCHEME_GROUP_ASSET_CLASS.get(canonical_group(group) or "")
    return expected if expected is not None and asset_class == expected else None
