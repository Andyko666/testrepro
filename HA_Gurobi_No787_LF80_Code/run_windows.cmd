@echo off
setlocal
cd /d "%~dp0"

echo Hawaiian Airlines - Gurobi fleet assignment
echo Project folder: %CD%
echo.

if not exist ".venv312\Scripts\python.exe" (
    echo Creating the Python 3.12 virtual environment...
    py -3.12 -m venv .venv312
    if errorlevel 1 goto setup_error
)

echo Checking required packages...
".venv312\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto setup_error

echo.
".venv312\Scripts\python.exe" run_model.py %*
set "HA_RUN_EXIT_CODE=%ERRORLEVEL%"
echo.
echo Finished with exit code %HA_RUN_EXIT_CODE%.
echo Open the Output folder printed above to view this run's results.
pause
exit /b %HA_RUN_EXIT_CODE%

:setup_error
echo.
echo Setup failed. Install Python 3.12 with the Windows Python launcher,
echo then run this file again. The error above identifies the failed step.
pause
exit /b 1
