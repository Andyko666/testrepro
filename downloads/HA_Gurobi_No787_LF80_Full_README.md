# Complete LF80 Project: Download, Solve, and View in VS Code

Download [HA_Gurobi_No787_LF80_Full.zip](HA_Gurobi_No787_LF80_Full.zip). This complete archive contains the supplied source workbooks, reference PDF, all Python code/configuration/tests, the Windows launcher, VS Code workspace/tasks, and verified solver results. Python environments and license files are not included.

1. Extract All. The archive has project files directly at its root.
2. Open `HA_Gurobi_No787_LF80.code-workspace` in VS Code.
3. Press **Ctrl+Shift+B** to set up the local Python 3.12 environment and run Gurobi. A working Gurobi license is required.
4. Open `LATEST_RESULTS.md` and press **Ctrl+Shift+V** for the formatted result report.
5. Open `LATEST_assignments.csv` for the flight-by-flight assignment, or the linked Excel workbook for all result sheets.

Terminal alternative from the extracted project folder: `.\run_windows.cmd`.

Default: historical directional-route LF strictly greater than 0.80 applies phi=1.20; otherwise phi=1.00. `primary_assumptions.json` is the only default-rule source. Reports show actual effective settings after overrides. Uniform demand tests and other LF cutoffs are separately labeled comparisons.

Verification: 59 tests passed; the main solve is optimal within configured tolerance with zero MIP gap. Recorded LF80 objective is USD 3,361,858.29, with 820.359731 estimated spill across 54 flights. The missing DB1B fare input is still replaced by the explicitly documented cost-recovery proxy, not an observed fare or actual lost revenue.
