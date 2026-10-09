@echo off
title Kimodo - iniciando
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kimodo-start.ps1"
echo.
echo Pressione qualquer tecla para fechar esta janela.
pause >nul
