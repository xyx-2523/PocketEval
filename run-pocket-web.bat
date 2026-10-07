@echo off
setlocal
cd /d "%~dp0"
set PORT=%PORT%
if "%PORT%"=="" set PORT=8766
if not defined PYTHON_BIN set PYTHON_BIN=python
"%PYTHON_BIN%" server.py --host 127.0.0.1 --port %PORT%
endlocal
