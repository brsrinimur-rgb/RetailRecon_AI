@echo off
cd /d "%~dp0"
python -m compileall -q .
if errorlevel 1 (
  echo Python compile check FAILED.
  pause
  exit /b 1
)
echo Python compile check PASSED.
python run_regression_suite.py
set RC=%ERRORLEVEL%
echo.
if %RC%==0 (echo Regression suite completed without code failures.) else (echo Regression suite has failures.)
pause
exit /b %RC%
