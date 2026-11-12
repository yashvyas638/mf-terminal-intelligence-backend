# Portfolio risk and stress methodology

## Historical risk endpoint

`GET /v1/portfolios/{portfolio_id}/risk?days=1095`

- Portfolio access is scoped to the verified owner.
- Current market values determine portfolio weights; those weights are held constant over the selected lookback.
- Fund NAV series are aligned on exact common dates across every active holding.
- No missing NAV values are interpolated or forward-filled.
- Adjacent common-date pairs more than seven calendar days apart are excluded from daily return statistics.
- The response reports annualised volatility, downside deviation, Sharpe ratio (with an explicit 6% risk-free assumption), maximum drawdown, empirical 95% historical VaR/CVaR, worst 1-day/5-day/21-day return and data coverage/freshness.

VaR is the magnitude of the empirical 5th-percentile daily loss; CVaR is the magnitude of the average of observations at or below that threshold. These are backward-looking historical estimates, not forecasts or maximum-loss guarantees.

## Verified holdings look-through

Endpoint: `GET /v1/portfolios/{portfolio_id}/lookthrough?max_disclosure_age_days=180`

- Requires a verified personal Supabase user and an owned portfolio.
- Uses the latest VERIFIED disclosure per scheme on or before the current date.
- Multiplies current scheme market value by source-reported constituent weights.
- Aggregates the same constituent by ISIN when available; non-ISIN records use their source security identifier.
- Aggregates sector exposure and reports source URL, source hash, disclosure date and age.
- Missing disclosures are not treated as zero; stale disclosures are shown separately from fresh coverage.
- Portfolio-weight percentages are withheld when portfolio NAV valuation is incomplete.
- Unverified or pending disclosures are never included.

This is a holdings-disclosure look-through, not a live underlying security valuation. Constituents, sector labels and disclosed weights may be stale, rounded or subject to AMC reporting conventions. The coverage block is essential context and should accompany any exposure table.

## User-defined stress endpoint

`POST /v1/portfolios/{portfolio_id}/stress`

A scenario must specify one percentage shock for every active scheme holding. The engine applies each shock directly to the current market value and reports the per-scheme and total impact. It never assumes omitted holdings have zero shock.

The response labels the scenario `USER_DEFINED_SENSITIVITY_NOT_FORECAST`. It is deterministic arithmetic, not a probability-weighted stress model.

## Limitations

- Current-value weights are held constant through history; actual historical portfolio weights and cash flows are not reconstructed.
- Underlying stock, sector, duration, credit, currency and derivative exposures are not inferred from fund names.
- No correlation matrix, factor model, liquidity haircut, interest-rate shock model or Monte Carlo simulation is claimed.
- NAV freshness and common-date coverage can limit the validity of results.
- A missing NAV for any active holding withholds portfolio-level risk metrics rather than silently dropping that holding.
- A stale NAV is flagged even when a numerical estimate can be calculated.
