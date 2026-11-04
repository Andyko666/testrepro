# Primary Case: Demand20%Above Historical Average

Assumption: each retained flight has demand1.20times its directional route historical carried-passenger average per performed departure. This is a user-selected assumption, not observed bookings or a calibrated lost-demand estimate. Raw passenger data remain unchanged.

| Metric | Value |
|---|---:|
| Objective | USD3,361,858.29 |
| Operating expense | USD3,201,237.68 |
| Spill penalty | USD160,620.61 |
| Estimated spilled passenger-equivalents | 820.36 |
| Flights with spill | 54/204 |
| Assignment changes versusphi1 | 0 |
| Gurobi MIP gap |0%|

All original common-event flow and fleet checks passed.39tests passed. Aircraft types, fleet assumptions and turnaround estimates remain unchanged. In this solve the assignment itself does not change; the20%uplift produces additional capacity shortfalls and spill penalties.

For HA1LAX-HNL: historical average252.584158, estimated demand303.100990, capacity278, estimated spill25.100990. Fractional values follow monthly-average demand and the PDF continuous spill variable.

The penalty is still a cost-recovery proxy, not actual DB1Bfare or measured lost revenue. These results should be reported conditional on all listed assumptions.
