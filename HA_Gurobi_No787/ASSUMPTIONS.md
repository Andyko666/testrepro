# Primary Demand Assumption

For each directional route, compute historical LF=sum(PASSENGERS)/sum(SEATS)
from the supplied monthly observations, before optimization. If LF>0.90,
phi=1.20; if LF<=0.90,phi=1.00. Estimated demand is historical route passengers
per performed departure multiplied by phi. Equality does not trigger uplift.

This is a user-selected modeling rule allowed by the PDF demand-adjustment
framework; the PDF does not prescribe the threshold or multiplier. Original
passenger observations are unchanged. The rule does not identify true unmet
demand or time-of-day peaks. Use weighted route totals, not assigned aircraft
capacity or unweighted type-level ratios.

The existing no-787 scope, cost inputs, turnaround/fleet assumptions and
spill-penalty proxy remain in use. See LOAD_FACTOR_UPDATE.md for execution and
local audit outputs. This code update does not upload or bundle new data/results.
