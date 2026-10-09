@echo off
rem Abre o PonteAnimada (sobe o servidor local se preciso e abre a janela).
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0scripts\abrir.ps1"
