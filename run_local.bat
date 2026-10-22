@echo off
REM ============================================================
REM run_local.bat
REM Double-click this to run the chatbot locally.
REM This just launches run_local.ps1 in PowerShell for you.
REM ============================================================

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_local.ps1"
pause
