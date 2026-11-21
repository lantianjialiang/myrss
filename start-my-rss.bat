@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-my-rss.ps1"
if errorlevel 1 pause
