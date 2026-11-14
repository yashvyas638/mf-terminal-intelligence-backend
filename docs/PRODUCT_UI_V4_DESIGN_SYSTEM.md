# Product UI v4 — Design System and Interaction Contract

## Purpose

MF Terminal is a research and portfolio decision-support workspace. The interface should prioritize clear fund discovery, transparent evidence, low-friction navigation, and legible data tables over decorative density.

## Visual system

- Canvas: cool neutral grey-blue; surfaces: white; primary text: deep navy.
- Primary action: accessible medium blue; positive and negative values use green and red respectively.
- Use compact uppercase eyebrow labels only for context, not as primary headings.
- Cards use restrained borders, small shadows, and consistent rounded corners.
- Numeric values use tabular numerals and align consistently.
- Preserve visible focus states and reduced-motion preferences.

## Navigation and information hierarchy

- Overview is the personal command centre and gateway to portfolio, goals, fund discovery, comparison, and data health.
- Research is the dedicated research workspace.
- Research tabs remain: Screener, Fund Research Profile, Watchlist, and Holdings Overlap.
- The category leaderboard remains distinct from trailing-window screener ranks: it represents completed calendar-month NAV returns.
- Quick category filters are populated only from the authenticated facets endpoint. The UI must never invent or hardcode a category list.

## Data and interaction invariants

- Existing element IDs, API routes, request parameters, authentication behavior, and server-side ranking calculations are compatibility contracts.
- Category group and sub-category filters must use the exact canonical values returned by the API.
- Changing a quick filter resets pagination and reloads the server-side screener.
- NAV-derived returns are not represented as dividend-adjusted total returns.
- Missing metrics remain unavailable; do not substitute zero, estimates, synthetic ranks, or invented quality scores.
- Benchmark comparisons must continue to respect effective-dated verified mappings.
- Private watchlists, portfolios, and goals remain scoped to the authenticated Supabase identity.
- Never expose server operator credentials or add them to browser code.

## Responsive behavior

- Desktop: persistent overview rail, compact research header, multi-column leaderboards, and horizontally scrollable wide research tables.
- Tablet: collapsible/stacked workspace hierarchy, two-column filters, and three-column leaderboards.
- Mobile: horizontal navigation, single-column screener controls, two-column compact metrics, and scrollable data tables.
- Respect reduced-motion preferences and maintain keyboard-visible focus.

## Change policy

Before changing a workflow, inspect the existing DOM IDs, API contract, and controller. Prefer additive CSS and small controller changes. Any future API/data-model change requires its own migration, authorization review, tests, and data-quality validation. UI-only releases must not trigger NAV refreshes, taxonomy refreshes, or production data writes.


## Research comparison workflow (v5)

- Users can select 2–10 schemes from the screener and carry that selection into the Compare Funds workspace.
- Comparison is calculated by the existing authenticated `POST /v1/analytics/compare` endpoint using stored AMFI NAV observations.
- The UI shows NAV date and observation count for each scheme, plus total NAV return, CAGR, annualised volatility, maximum drawdown, Sharpe and Sortino when the backend reports sufficient history.
- Insufficient metrics remain unavailable; they are never converted to zero.
- Coverage dates may differ between schemes. The interface discloses that this is a NAV-only comparison and excludes benchmark TRI, distributions and category-peer adjustments.
- Selections are transient browser state and are cleared on sign-out. No comparison state is persisted to another user's account.
