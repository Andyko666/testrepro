# Download the Load-Factor Code Update

Download [HA_LoadFactor90_CodeUpdate.zip](downloads/HA_LoadFactor90_CodeUpdate.zip)
using GitHub's Download raw file button. This is code/configuration only; it
contains no uploaded Excel source data or new solver result files.

Extract it and copy its files into your existing HA_Gurobi_No787 project folder.
Keep your data, .venv312, prepare_data.py and compact_model.py. No additional
dependencies are needed.

```powershell
.\.venv312\Scripts\python.exe run_model.py
```

The new default is historical directional-route LF>0.90:phi=1.20, otherwisephi=1.
For a threshold comparison, run run_load_factor_comparison.py with the same
Python interpreter. All new results are generated on your own computer.

See [the update guide](HA_Gurobi_No787/LOAD_FACTOR_UPDATE.md) for the exact
formula, parameter precedence and output fields. Earlier data/results already
present in the repository are not changed by this code-only update.
