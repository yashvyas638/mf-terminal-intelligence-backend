# UX and Design System — Intelligence Terminal

## Experience target

A premium, calm, high-density research terminal: powerful enough for analysis, clear enough for everyday use. The interface should feel fast, precise, confident and welcoming—not like a spreadsheet dumped into a browser.

## Visual principles

- Strong hierarchy, restrained colour and deliberate whitespace.
- Neutral canvas; use colour semantically: green positive, red negative, amber caution, blue informational.
- Never use colour alone to communicate status; include labels/icons.
- Consistent numeric alignment, tabular figures and units.
- Avoid oversized hero cards, excessive gradients, decorative charts and meaningless gauges.
- Use charts only when they reveal trend, distribution, comparison or relationship.
- Every chart has title, period, source/as-of date, legend, axis units and accessible text summary.
- Use progressive disclosure for advanced formulas, diagnostics and source citations.
- Keep primary workflows one-screen where possible; avoid long vertical forms.
- Desktop-first research workspace with responsive tablet/mobile layouts.

## Core shell

- Left navigation with clear active state and collapsible groups.
- Top command/search bar for scheme, portfolio, ticker/security, benchmark and actions.
- Global data freshness indicator and environment indicator (never expose secrets).
- Main content area with page title, short context, primary action and secondary tools.
- Right-side research/context drawer for methodology, source citations, assumptions and warnings.
- Toasts for success/failure plus durable inline status for important jobs.
- Keyboard shortcuts for search, navigation and table actions; publish shortcut guide.

## Dashboard layout

1. **Portfolio pulse:** total value, invested amount, gain/loss and valuation as-of date. Never show change if data is stale or incomplete.
2. **Allocation:** asset/category/fund/AMC breakdown with drill-down.
3. **Performance:** selected period, benchmark and contribution context.
4. **Risk radar:** concentration, overlap, drawdown, missing NAV and stale factsheet flags.
5. **Research watchlist:** meaningful fund changes with source and reason.
6. **Decision queue:** open cases, review date and pending user approval.
7. **Activity timeline:** imports, NAV refreshes, corrections and decisions.
8. **Data health:** source status, last successful sync, quality warnings and affected modules.

Dashboard should be configurable. Do not force every panel onto the first viewport.

## Fund profile

Header: scheme name, AMC, category, plan/option, benchmark, scheme code/ISIN, data freshness.
Tabs: Overview, Returns, Risk, Holdings, Costs, Manager, Documents, History.
Primary actions: Add to watchlist, Compare, Add to portfolio (only with explicit transaction/import flow).
Methodology drawer: formula, sample period, benchmark, risk-free rate, annualisation, coverage and source.

## Import wizard

Step 1 Choose file/source.
Step 2 Map columns and identify statement format.
Step 3 Preview normalised rows.
Step 4 Validation and duplicate warnings.
Step 5 Reconciliation totals.
Step 6 User confirmation.
Step 7 Import progress and result.
Step 8 Post-import portfolio impact.

Never make upload itself the commit action. Make rejected rows downloadable and explain exactly why each failed.

## Compare and quantitative research

- Align periods and data frequency before plotting.
- Show category/benchmark context and sample size.
- Allow users to inspect exact data points.
- Mark missing or stale windows.
- Include a table beneath charts for precise values.
- Do not use radar charts for precise metric comparison.
- Provide resettable filters and shareable URL state without private data leakage.

## Decision Centre

Each case shows:
- Proposed label: ADD / HOLD / REDUCE / SWITCH / EXIT (research classification, not an instruction).
- Thesis and evidence.
- Counter-evidence and risks.
- Portfolio impact and alternatives.
- Tax/exit-load/lock-in caveats.
- Confidence/coverage with explanation, never false precision.
- Data as-of date.
- User decision and review date.

User must confirm before a decision is recorded as accepted. No automated trading.

## Accessibility and interaction

- WCAG 2.2 AA target.
- Keyboard operation and visible focus.
- Semantic headings, labels, table headers and form errors.
- Screen-reader summaries for charts.
- Minimum contrast and scalable text.
- Respect reduced motion.
- No hover-only critical information.
- Clear undo/cancel where safe; confirmation for irreversible actions.
- Preserve filters and work-in-progress across navigation where appropriate.

## Performance targets (initial product goals)

- Main shell usable quickly on normal broadband; skeletons for slow queries.
- Common read endpoints target p95 under 500 ms after warm cache (measure, do not promise).
- Heavy analytics run asynchronously with progress and cancellation where safe.
- Pagination and server-side filtering for large tables.
- Avoid loading all NAV observations or all holdings into browser memory.
- Cache only with clear freshness and invalidation semantics.

## Delight without gimmicks

- Global command palette.
- Saved screens and reusable comparison sets.
- Watchlists and alert rules.
- Explain-this-metric and explain-this-change interactions.
- Side-by-side “what changed since last review”.
- One-click export of the current filtered research view.
- Personal notes attached to fund/portfolio/decision with privacy controls.
- Useful empty states with sample data clearly marked as demo.
