@echo off
REM ============================================================
REM run_runpod.bat
REM Double-click this to run the chatbot using a Runpod backend.
REM This just launches run_runpod.ps1 in PowerShell for you.
REM ============================================================

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_runpod.ps1"
pause
