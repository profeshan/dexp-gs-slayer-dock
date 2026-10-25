@echo off
cd /d "%~dp0"
start "" pyw -3 -m dexp_dock tray %*
