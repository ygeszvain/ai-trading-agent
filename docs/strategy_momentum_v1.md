# Strategy: trend-momentum v1 (momentum-v1)

**Status:** M1 (Prompt 2). This document specifies the rule *before any
tuning*, per build plan section 11 ("Specify before tuning"). The M1
implementation must match this document exactly; parameter changes later are
experiments, not silent edits (plan section 23: do not silently alter
strategy objectives).

## Hypothesis

Persistent multi-session movement may contain useful information after costs.
This is a *testable hypothesis*, not an assumed market property. The strategy
is long-only, single-decision-per-session, and fully deterministic: given the
same data snapshot and configuration it always produces the same decisions.

## Inputs (point-in-time)

Every input is an observation with a timestamp at or before the decision
instant (plan section 8 cutoff rules):

- **Data snapshot:** the run's immutable fixture snapshot id (seed, start,
  session count, universe, missing scenarios).
- **Latest price P_last:** the most recent observation at the decision
  instant (the 10:00 tick close for the fixture).
- **Reference price P_ref:** the 16:00 session close of the session that is
  20 sessions before P_last's session (a 20-session return ending at the
  latest price).
- **Completed session closes:** the most recent 20 completed sessions
  (16:00 closes) at or before the current session.
- **Position:** current quantity and average cost for the instrument.
- **Book equity (NAV):** cash + sum(position value at latest price).

## Decisions

One decision per instrument per session at 10:00 exchange time (30 minutes
after the open, plan section 17). Actions:

| Condition | Action | Target weight |
| --- | --- | --- |
| Fewer than 21 price points available (warm-up) | HOLD | — |
| Latest observation is stale (per `data.stale_after_sessions`) | HOLD | — |
| No position AND momentum > `entry_momentum` (0.05) | ENTER | `target_weight` (0.05) |
| Position held AND momentum < `exit_momentum` (0.00) | EXIT | 0 |
| Otherwise | HOLD (explicit) | — |

Momentum = P_last / P_ref − 1. Feature computation may use floating point
(plan section 6); all money conversion happens in Decimal after the feature
computation.

HOLD is a first-class, persisted decision — the website shows why (insufficient
history, stale data, or no trigger crossed).

## Sizing (Decimal, all values exact)

For ENTER: `delta_value = max(0, target_weight × NAV − current position value)`.
For EXIT: `delta_value = current position value` (sell everything held).

Orders are slices of the delta:

1. `slice_value = order_slice_weight × NAV` (2% of NAV).
2. While `delta_remaining ≥ min_order_value` (value of one share):
   `order_qty = floor_to_precision(min(slice_value, delta_remaining) / P_last)`,
   rounded *down* to the instrument's quantity precision (never up).
3. Stop when `delta_remaining < min_order_value` or `order_qty = 0`.

This guarantees every single order ≤ 2% of NAV (the risk single-order limit)
and the sum of orders ≤ the target delta (never overshoots the position
limit). Buys price their limits at `P_last × (1 + spread_bps/10000)`; sells at
`P_last × (1 − spread_bps/10000)`, rounded to the price tick (docs:
fill_simulation.md).

## What this strategy is not

- Not a recommendation to trade real instruments. It trades fictional
  `TEST_*` instruments in simulation only.
- Not tuned: the grid is the documented values above. Any parameter sweep is
  a separate, labeled experiment (M3 evaluation protocol).
- No shorting, no margin, no options, no intraday churn (one decision point
  per session; working orders are managed by the execution layer, not the
  strategy).

## Benchmarks (same capital, same cost conventions)

- **Cash baseline:** the full initial capital earns `engine.cash_yield_annual`
  (4.5%/yr, daily compounding, Decimal).
- **Passive baseline:** equal-weight buy-and-hold of the fixture universe,
  purchased once at the first session open, same spread cost convention,
  residual cash earns the same daily yield.

The strategy's idle cash also earns the same documented daily yield so that
all books share identical capital and cost conventions (plan section 11).
