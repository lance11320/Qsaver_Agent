@echo off
cd /d "%~dp0"
py -3.12 -m venv fast_dev\venv
if errorlevel 1 goto failed
"fast_dev\venv\Scripts\python.exe" -m pip install -r fast_dev\requirements-lock.txt
if errorlevel 1 goto failed
echo Setup complete. Run fast_dev\start.bat to start Qsaver.
pause
exit /b 0
:failed
echo Setup failed. Check Python 3.12 and the output above.
pause
exit /b 1
