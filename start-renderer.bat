@echo off
cd /d "%~dp0"
py -3 render_server.py
if errorlevel 1 pause
