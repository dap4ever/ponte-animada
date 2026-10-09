@echo off
rem Encerra o servidor local do PonteAnimada. O Kimodo/Docker continua como esta.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\parar.ps1"
timeout /t 4 >nul
