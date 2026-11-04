# Primary Modeling Assumptions

## Demand is 20% above historical average carried passengers

The user-selected primary case assumes each retained flight's demand is 20%
above the October 2024 historical average carried passengers per performed
departure on its directional route:

q_f = 1.20 * sum_route(PASSENGERS) / sum_route(DEPARTURES_PERFORMED).

Thus phi_f = 1.20 for every retained flight. The multiplier represents a modeling
allowance for potential demand beyond historically carried passengers. It is
not an observed booking count or a statistically identified estimate of true
unconstrained demand. The supplied PDF permits a documented phi_f >= 1 demand
rule but does not specify 1.20; the user selected this value.

All source PASSENGERS, SEATS and departures remain unchanged. Flights sharing
a directional route still use the same estimated average demand; the multiplier
does not identify peak-time flight demand. Expected passenger counts and spill
can be fractional because the PDF models demand estimates and continuous spill.

Example: HA1 LAX-HNL has historical mean 25,511/101 = 252.584158 passengers. The
primary estimate is 303.100990 passengers. With 278 A330 seats, the modeled
shortfall/spill is 25.100990 passenger-equivalents.

## Other assumptions retained

- Candidate types are 608/696/721; 787 is excluded at the user's request.
  HA35 PHX-HNL and HA36 HNL-PHX have no remaining historical eligible type and
  are listed outside scope. 204 flights remain; no other schedule changes occur.
- Type capacities 128/278/189 and route airborne hours follow supplied T100
  aggregates. Historical 787 passengers/time remain part of retained-route
  demand history even though 787 is not an assignment option.
- Supplied 608/696/721 airborne-hour costs are used. No 787 cost is estimated.
- Turnaround proxies are 30/100/75 minutes, based on positive scheduled-dwell
  P10 rounded up to 5 minutes. They are not approved operational minima.
- Available-fleet scenario is 16/16/17, inferred from observed tails and
  historical compatibility. Ambiguous types, reserves, maintenance and other
  commitments remain uncertain; no registration verification is invented.
- Missing DB1B prices are replaced by candidate-aircraft route monthly airborne
  operating cost / candidate-aircraft carried passengers. This is a labeled
  cost-recovery spill penalty, not actual ticket fare or lost revenue. It
  explicitly departs from the PDF-requested DB1B input source.
- Fixed times, cyclic integer inventories, type-specific readiness, no
  repositioning, and no passenger recapture follow the PDF model structure.

## Reproduction and parameter precedence

`primary_assumptions.json` is loaded automatically in estimated mode. An
explicit `--parameters` file can override it, and `--demand-multiplier` takes
final precedence. Strict mode does not auto-apply primary assumptions.

```bash
python run_model.py
python run_model.py --demand-multiplier 1.20
```

Both commands use the selected 20% assumption in the unmodified project. For
the historical-average comparison:

```bash
python run_model.py --demand-multiplier 1.00
python run_sensitivity.py
```

The prepared source/estimate stage retains its historical phi=1 audit. The
effective phi and demand after assumptions are recorded in the run's
`calculated_flight_parameters.csv`, `effective_parameters.json`, assignments,
and `run_summary.json`. The report prints the effective phi range.
