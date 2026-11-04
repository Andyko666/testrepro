# Hawaiian Airlines: Local Gurobi Run

Outcome: **OPTIMAL_WITHIN_CONFIGURED_TOLERANCE**.

The PDF content is the complete Milestone4 model, although the attachment filename says Milestone3.
At the user's request, candidate type889is excluded. Flights with no remaining historically eligible type are explicitly listed outside this run's model scope; other flights are retained.
Input mode: **estimated**. Source and estimate audits are in `prepared/`.

## Primary demand assumption

The user-selected primary case assumes demand is 20% above the historical directional-route average carried passengers per departure: q_f = 1.20 * sum_route(PASSENGERS) / sum_route(DEPARTURES_PERFORMED). This is a documented modeling assumption, not an estimate calibrated from observed unmet demand. Raw passenger records remain unchanged. Explicit JSON or CLI overrides can replace this primary assumption; the effective phi range below is authoritative.

| Metric | Value |
|---|---:|
| Objective | USD 3,361,858.29 |
| Operating expense | USD 3,201,237.68 |
| Spill penalty | USD 160,620.61 |
| Estimated spill variable | 820.3597 |
| MIP gap | 0.000000% |
| Model variables / constraints | 1171 / 1036 |

These are results under the documented inputs. Estimated spill and cost-based penalties do not establish actual lost passengers or fare revenue.

## Demand interpretation

Effective phi range: 1.2 to 1.2.
Demand = monthly route carried passengers / performed departures * phi. This is a conditional model estimate. Spill describes demand exceeding assigned seats, not measured overbooking or denied boarding. Demand increases are sensitivity scenarios, not evidence of actual lost customers.

## Remaining limitations

- The three source Excel files contain no DB1B observations. Any optional local fare import is recorded separately and takes precedence. For uncovered routes, estimated mode uses monthly air-operating cost divided by carried passengers as a cost-recovery spill penalty. This is NOT inferred DB1B fare and explicitly differs from that requested PDF input source.
- Type889is excluded, so no787operating-cost proxy is calculated or used. Type837also remains outside the candidate set. Its source cost is preserved but unused.
- Turnaround proxies for608/696/721use the lower tail of positive scheduled ground dwells; dwell includes idle time and is not an approved operational minimum.
- Available-fleet estimates use observed tails and route/type compatibility. Ambiguous types, maintenance, spares, and international commitments remain uncertain. No FAA verification is invented.
- Demand and route airborne hours retain all historical aircraft observations, including787on retained routes. Removing an assignment option does not remove those passengers. Spill-penalty calibration uses only candidate aircraft with supplied costs, so no787cost is needed.
- Demand is the PDF passengers/departures estimate with phi=1 unless explicitly changed. Monthly carried passengers do not identify unmet demand.
- Ten monthly rows have scheduled departures0but performed departures>0. They are flagged and retained, not presumed wrong. All ratios use performed departures.
- HNL-LAX/type696has two nonidentical rows. They are summed, not deleted as duplicates.
- One planned ground overlap is flagged and excluded from positive-dwell estimates; original timestamps are preserved.
- UTC conversions retain dates, use IANA time zones including Phoenix's no-DST rule, and reconcile destination clocks.

## PDF-equivalent compact formulation

Default compact mode removes equal ground-inventory variables at non-events and enforces the fleet cap at one time cut per type, since total fleet is conserved by flow. Every returned solution is then checked at ALL common PDF events. Use `--formulation full` for the literal shared-event formulation.
A compact model keeps the same optimal flight assignments/objective while avoiding unnecessary model size; a size-limited Gurobi license may be sufficient for this dataset. Licensing behavior depends on the installed version and license.
