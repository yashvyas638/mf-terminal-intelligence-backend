# Capital gains lots and financial goal planning

## FIFO capital gains ledger

Endpoint: `GET /v1/portfolios/{portfolio_id}/tax-lots`.

The engine matches each redemption to acquisition lots using FIFO within each scheme:
- Buy lot cost includes gross amount plus recorded acquisition charges.
- Redemption proceeds are allocated proportionally to matched units after recorded redemption charges.
- Each realized match reports buy/sell dates, units, cost basis, net proceeds, realized gain/loss and holding-period days.
- Remaining open lots report units, remaining cost basis, latest NAV, market value and unrealized gain/loss.
- Sell quantities exceeding available lots are rejected.
- Voided transactions are excluded.

This is a pre-tax lot ledger, not a tax calculator. The API deliberately returns `TAX_RULES_NOT_APPLIED`. It does not infer equity/debt tax treatment from a scheme name, apply a guessed holding-period threshold, or estimate tax rates, surcharge, cess, exemptions, indexation or exit loads.

## Tax rule release gate

Before tax estimates are enabled, the product needs:
1. Verified scheme tax classification and relevant asset-allocation eligibility with source/effective dates.
2. Effective-dated rules aligned to the Income-tax Act, Finance Acts, CBDT notifications/circulars and the applicable transaction date.
3. Treatment for equity-oriented funds, specified/debt mutual funds, hybrid funds, international funds, switches, STT, grandfathering and special cases.
4. Boundary tests around every rule change and independent review by a qualified Indian tax professional.
5. User-visible source links, assumptions and estimates-vs-advice disclaimer.

Until those conditions are met, show FIFO gains and holding periods only. Do not calculate or label a tax liability.

Official legal reference starting point:
- Income Tax Department: https://www.incometax.gov.in/
- CBDT circulars/notifications: https://incometaxindia.gov.in/Pages/communications/circulars.aspx
- SEBI/AMFI scheme classification and disclosures must be reconciled separately.

## Financial goals

Goal APIs are owner-scoped to the verified Supabase user:
- `GET /v1/goals`
- `POST /v1/goals`
- `PUT /v1/goals/{goal_id}`
- `DELETE /v1/goals/{goal_id}`
- `GET /v1/goals/{goal_id}/projection`

A goal stores:
- Target amount in today's rupees and target date.
- Current invested amount and monthly contribution.
- User-entered inflation assumption.
- User-entered low/base/high annual return assumptions.

The projection compounds monthly, assumes contributions at month-end, inflates the target amount, and reports projected future value, shortfall/surplus and required monthly contribution for each scenario. It does not assign probabilities to scenarios.

## Limitations

- Return assumptions are supplied by the user and are not recommendations or forecasts.
- Goal projections exclude taxes, fees, exit loads, contribution interruptions and sequence-of-return uncertainty.
- The goal planner is not yet connected to verified tax rules or automatically reconciled to portfolio holdings.
- No guaranteed return or goal-achievement probability is displayed.
