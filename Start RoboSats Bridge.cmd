@echo off
setlocal
call "%~dp0start-windows.cmd" %*
set "status=%errorlevel%"
if not "%status%"=="0" if "%~1"=="" pause
exit /b %status%
