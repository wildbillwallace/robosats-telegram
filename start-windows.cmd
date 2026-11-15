@echo off
setlocal
cd /d "%~dp0"
set "PYTHONUTF8=1"

where npm.cmd >nul 2>&1
if errorlevel 1 (
    echo Install Node.js LTS with npm and open a new terminal. See SETUP-WINDOWS.md.
    exit /b 1
)
node -e "process.exit(Number(process.versions.node.split('.')[0]) < 22 ? 1 : 0)"
if errorlevel 1 (
    echo Install Node.js 22 or newer. See SETUP-WINDOWS.md.
    exit /b 1
)

if exist ".venv\Scripts\python.exe" goto python_ready
echo Creating a local Python environment...
where py.exe >nul 2>&1
if errorlevel 1 goto use_python
py -3 -m venv .venv
if errorlevel 1 goto failed
goto python_ready

:use_python
python -m venv .venv
if errorlevel 1 goto failed

:python_ready
".venv\Scripts\python.exe" -c "import sys; sys.exit(sys.version_info < (3, 10))"
if errorlevel 1 (
    echo Install Python 3.10 or newer. See SETUP-WINDOWS.md.
    exit /b 1
)
fc /b requirements.txt ".venv\installed-requirements.txt" >nul 2>&1
if not errorlevel 1 goto node_signature
echo Installing Python libraries...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
copy /y requirements.txt ".venv\installed-requirements.txt" >nul
if errorlevel 1 goto failed

:node_signature
fc /b package-lock.json "node_modules\.robosats-package-lock.json" >nul 2>&1
if errorlevel 1 goto install_node
fc /b package.json "node_modules\.robosats-package.json" >nul 2>&1
if not errorlevel 1 goto run

:install_node
echo Installing chat libraries...
call npm.cmd ci --ignore-scripts --no-audit --no-fund
if errorlevel 1 goto failed
copy /y package-lock.json "node_modules\.robosats-package-lock.json" >nul
if errorlevel 1 goto failed
copy /y package.json "node_modules\.robosats-package.json" >nul
if errorlevel 1 goto failed

:run
".venv\Scripts\python.exe" robosats_monitor.py %*
exit /b %errorlevel%

:failed
echo Setup did not finish. Check the message above and see SETUP-WINDOWS.md.
exit /b 1
