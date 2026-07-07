# Live demo — real LLM + a real Analyst beat

_generated 2026-07-07T18:47:05+00:00_

## Decomposition — Decision → Goals (LLM)

**Decision:** Analyze the sales warehouse `warehouse.db` in your workspace (tables sales(region, quarter, revenue, units) and costs(region, quarter, cost)) and decide which region to invest in next quarter, with exact numbers and a written recommendation in findings.md.  
**Goals produced:** 4

| # | score | goal | metric | target |
|---|------|------|--------|--------|
| 1 | 1.00 | Query and validate warehouse.db schema and row coverage | Validation checklist completed | Confirm tables sales(region, quarter, revenue, units) and costs(region, quarter, cost) exist; list distinct regions and quarters; verify no NULLs in key columns; report row counts per table and per region-quarter |
| 2 | 0.90 | Compute region performance metrics for latest quarter and trailing trend | Analysis table produced | For each region: compute latest-quarter revenue, units, cost, gross profit (revenue-cost), gross margin %, and profit per unit; also compute quarter-over-quarter change in revenue and gross profit vs prior quarter; persist results as a CSV or markdown table snippet |
| 3 | 0.80 | Select investable region and quantify expected rationale with exact figures | Decision summary created | Choose 1 region; include exact latest-quarter values (revenue, cost, profit, margin, units) and QoQ deltas; add at least 2 supporting comparisons vs next-best region (e.g., higher profit by $X, higher margin by Y pp, better growth by Z%) |
| 4 | 0.70 | Write findings.md with recommendation and reproducible methodology | findings.md committed/created | findings.md contains: brief executive recommendation, metric table(s), key assumptions, SQL queries used (or a clear description) and a concise conclusion on which region to invest in next quarter with exact numbers |

## Intake — Goals → chorus tasks (Submitter + Prioritiser)

| goal | task | priority | assignee |
|------|------|----------|----------|
| Query and validate warehouse.db schema and row coverage | `task_0af3fcfd101e` | **high** | vera |

## Feedback — landed outcomes → health → re-priority (OutcomeListener)

**Verdicts folded:** 1

| goal | verdict | health | score | priority |
|------|---------|--------|-------|----------|
| Query and validate warehouse.db schema and row coverage | PASS | unknown → on_track | 1.00 → 0.50 | high → medium |

## Current direction (read model)

### Analyze the sales warehouse `warehouse.db` in your workspace (tables sales(region, quarter, revenue, units) and costs(region, quarter, cost)) and decide which region to invest in next quarter, with exact numbers and a written recommendation in findings.md.  
`dec_live` · status=active

| score | priority | health | goal | task |
|-------|----------|--------|------|------|
| 0.90 | high | unknown | Compute region performance metrics for latest quarter and trailing trend | — |
| 0.80 | high | unknown | Select investable region and quantify expected rationale with exact figures | — |
| 0.70 | medium | unknown | Write findings.md with recommendation and reproducible methodology | — |
| 0.50 | medium | on_track | Query and validate warehouse.db schema and row coverage | `task_0af3fcfd101e` |

## Live execution

- task `task_0af3fcfd101e` final status: **done**
- dod verdict: **{'cost_cents': 0, 'sprint_outcomes': ['pass'], 'steps_blocked': 0, 'steps_done': 1, 'steps_total': 1}**
- verdicts folded by the listener: **1**
