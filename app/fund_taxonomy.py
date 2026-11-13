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
        "Multi Asset Allocation", "Arbitrage Fund", "Equity Savings",
    }),
    "Life Cycle Funds": frozenset({
        "Life Cycle Fund with Maturity of 5 Years",
        "Life Cycle Fund with Maturity of 10 Years",
        "Life Cycle Fund with Maturity of 15 Years",
        "Life Cycle Fund with Maturity of 20 Years",
        "Life Cycle Fund with Maturity of 25 Years",
        "Life Cycle Fund with Maturity of 30 Years",
    }),
    "Other Schemes": frozenset({
        "Index Funds / ETFs", "FoFs (Overseas/Domestic)",
        "Debt ETF", "Equity ETF", "ETFs investing overseas", "Gold ETF",
        "Hybrid ETF", "Other ETF", "Silver ETF",
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
    # AMFI Fund Performance service uses short labels for current SEBI categories.
    _key("Large Cap"): "Large Cap Fund",
    _key("Large & Mid Cap"): "Large & Mid Cap Fund",
    _key("Flexi Cap"): "Flexi Cap Fund",
    _key("Multi Cap"): "Multi Cap Fund",
    _key("Mid Cap"): "Mid Cap Fund",
    _key("Small Cap"): "Small Cap Fund",
    _key("Value"): "Value Fund",
    _key("ELSS"): "ELSS Tax Saver Fund",
    _key("Contra"): "Contra Fund",
    _key("Dividend Yield"): "Dividend Yield Fund",
    _key("Focused"): "Focused Fund (No. of Stocks)",
    _key("Sectoral"): "Sectoral Fund",
    _key("Thematic"): "Thematic Fund",
    # AMFI performance filters expose current debt categories without "Fund".
    _key("Long Term"): "Long Term Fund",
    _key("Medium to Long Term"): "Medium to Long Term Fund",
    _key("Short Term"): "Short Term Fund",
    _key("Medium Term"): "Medium Term Fund",
    _key("Ultra Short to Short Term"): "Ultra Short to Short Term Fund",
    _key("Ultra Short Term"): "Ultra Short Term Fund",
    _key("Liquid"): "Liquid Fund",
    _key("Overnight"): "Overnight Fund",
    _key("Dynamic Term"): "Dynamic Term Fund",
    _key("Corporate Bond"): "Corporate Bond Fund",
    _key("Credit Risk"): "Credit Risk Fund",
    _key("Banking and PSU Debt"): "Banking and PSU Debt Fund",
    _key("Floating Interest Rates"): "Floating Interest Rates Fund",
    _key("Gilt"): "Gilt Fund",
    _key("Sectoral Debt Fund"): "Sectoral Fund",
    # AMFI performance filters expose hybrid category names in short form.
    _key("Aggressive Hybrid"): "Aggressive Hybrid Fund",
    _key("Conservative Hybrid"): "Conservative Hybrid Fund",
    _key("Conservative Hyrbid"): "Conservative Hybrid Fund",
    _key("Balanced Hybrid"): "Balanced Hybrid Fund",
    _key("Arbitrage"): "Arbitrage Fund",
    # Current Other Schemes grouping uses the SEBI 2026 umbrella categories.
    _key("Index Funds ETFs"): "Index Funds / ETFs",
    _key("ELSS-Tax Saver Fund"): "ELSS Tax Saver Fund",
    _key("ELSS - Tax Saver Fund"): "ELSS Tax Saver Fund",
    _key("Banking and PSU Fund"): "Banking and PSU Debt Fund",
    _key("Banking & PSU Debt Fund"): "Banking and PSU Debt Fund",
    _key("10 Year Constant Maturity Gilt Fund"): "10-year Constant Maturity Gilt Fund",
    _key("Floating Rate Fund"): "Floating Interest Rates Fund",
    _key("Index Funds/ ETFs"): "Index Funds / ETFs",
    _key("Index Funds"): "Index Funds / ETFs",
    _key("Money Market"): "Money Market Fund",
    _key("Other ETFs"): "Other ETF",
    _key("Gold ETFs"): "Gold ETF",
    _key("FoFs (Domestic)"): "FoFs (Overseas/Domestic)",
    _key("FoFs (Overseas)"): "FoFs (Overseas/Domestic)",
    _key("FoF Domestic"): "FoFs (Overseas/Domestic)",
    _key("FoF Overseas"): "FoFs (Overseas/Domestic)",
    _key("Fund of Funds (Domestic)"): "FoFs (Overseas/Domestic)",
    _key("Fund of Funds (Overseas)"): "FoFs (Overseas/Domestic)",
    _key("Fund of Funds Scheme (Domestic)"): "FoFs (Overseas/Domestic)",
    _key("Fund of Funds Scheme (Overseas)"): "FoFs (Overseas/Domestic)",
    _key("Dynamic Asset Allocation or Balanced Advantage"): "Dynamic Asset Allocation Fund",
    _key("Balanced Advantage Fund / Dynamic Asset Allocation"): "Dynamic Asset Allocation Fund",
    _key("Multi Asset Allocation Fund"): "Multi Asset Allocation",
    _key("Equity Savings Fund"): "Equity Savings",
    _key("Focused Fund"): "Focused Fund (No. of Stocks)",
}

def classify_amfi_category(raw_category: str) -> tuple[str | None, str | None, str | None]:
    """Return canonical broad group, allow-listed sub-category and asset class."""
    raw = " ".join((raw_category or "").strip().split())
    group_raw, separator, subcategory_raw = raw.partition(" - ")
    group = _GROUP_ALIASES.get(_key(group_raw))
    if group is None:
        return None, None, None
    subcategory = None
    # Some official AMFI section headings contain only a category label
    # (for example "Money Market" or "Index Funds") rather than a
    # "group - subcategory" pair. Resolve only explicit, allow-listed labels.
    subcategory_label = subcategory_raw if separator else group_raw
    if subcategory_label.strip():
        key = _key(subcategory_label)
        candidate = _SUBCATEGORY_ALIASES.get(key)
        if candidate is None:
            # AMFI may append a sector/theme descriptor after the SEBI
            # category, e.g. "Sectoral Fund - Financial Services". Keep
            # the first, explicitly allow-listed category token; never use
            # the descriptor or a scheme marketing name as a category.
            primary_label = subcategory_label.split(" - ", 1)[0].strip()
            primary_key = _key(primary_label)
            candidate = _SUBCATEGORY_ALIASES.get(primary_key)
            if candidate is None:
                candidate = next(
                    (item for item in SUBCATEGORIES_BY_GROUP[group] if _key(item) == primary_key),
                    None,
                )
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


_GROUP_FILTER_ALIASES = {
    "Other Schemes": ("Other Scheme",),
}

_SUBCATEGORY_FILTER_ALIASES = {
    "ELSS Tax Saver Fund": ("ELSS-Tax Saver Fund", "ELSS - Tax Saver Fund"),
    "Banking and PSU Debt Fund": ("Banking and PSU Fund", "Banking & PSU Debt Fund"),
    "10-year Constant Maturity Gilt Fund": ("10 Year Constant Maturity Gilt Fund",),
    "Floating Interest Rates Fund": ("Floating Rate Fund",),
    "Focused Fund (No. of Stocks)": ("Focused Fund",),
    "FoFs (Overseas/Domestic)": (
        "FoFs (Domestic)", "FoFs (Overseas)", "FoF Domestic", "FoF Overseas",
        "Fund of Funds (Domestic)", "Fund of Funds (Overseas)",
        "Fund of Funds Scheme (Domestic)", "Fund of Funds Scheme (Overseas)",
    ),
    "Dynamic Asset Allocation Fund": (
        "Dynamic Asset Allocation or Balanced Advantage",
        "Balanced Advantage Fund / Dynamic Asset Allocation",
    ),
    "Multi Asset Allocation": ("Multi Asset Allocation Fund",),
    "Equity Savings": ("Equity Savings Fund",),
    "Index Funds / ETFs": ("Index Funds/ ETFs",),
}

def scheme_group_filter_values(group: str | None) -> tuple[str, ...]:
    """Include known legacy AMFI labels when filtering a canonical group."""
    canonical = canonical_group(group)
    if canonical is None:
        return (group,) if group else ()
    return (canonical, *_GROUP_FILTER_ALIASES.get(canonical, ()))

def subcategory_filter_values(group: str | None, category: str | None) -> tuple[str, ...]:
    """Match canonical categories plus explicitly mapped historic AMFI spellings."""
    if not category:
        return ()
    canonical = canonical_subcategory(group, category) if group else None
    if canonical is None and group is None:
        matches = {
            value
            for candidate_group in SUBCATEGORIES_BY_GROUP
            if (value := canonical_subcategory(candidate_group, category)) is not None
        }
        canonical = next(iter(matches)) if len(matches) == 1 else None
    if canonical is None:
        return (category,)
    return (canonical, *_SUBCATEGORY_FILTER_ALIASES.get(canonical, ()))
