# Minimal LF80 Correction for the Existing Phi120 Project

Download [HA_Phi120_LF80_Only_Fix.zip](HA_Phi120_LF80_Only_Fix.zip). Extract it and copy the replacement files into the original project folder containing `run_model.py`. Replace the matching files, then rerun the original program using its existing Python/Gurobi environment.

The correction unifies the default to historical directional-route LF strictly greater than 0.80: phi=1.20; otherwise phi=1.00. The JSON is the sole default-rule source. It corrects the Python override, reports, example configuration, comparison defaults, obsolete test expectations, and documents. It retains the original project structure and source/environment files; no new launcher or execution workflow is added.

Old result workbooks are not recalculated by copying code. Use the new timestamped output after rerunning `python run_model.py`. Old uniform-phi1.20 documentation is labeled historical rather than current primary.

The newly uploaded large ZIP exceeded the reader's 32 MiB transfer limit and was not inspected. This correction is based on the individually uploaded source files and was verified against the earlier published Phi120 project: 56 tests passed, and the default native Gurobi solve passed all operational checks. The archive contains replacement code/configuration/documents only, without input workbooks or new operational result files.
