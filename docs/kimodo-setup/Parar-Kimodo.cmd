@echo off
title Kimodo - parando
echo.
echo   Parando os servicos do Kimodo...
wsl -d Ubuntu -u dap_p -- bash -lc "cd ~/kimodo && docker compose stop"
echo.
echo   Servicos parados. A imagem e os modelos continuam no disco,
echo   entao abrir de novo sera rapido.
echo.
echo Pressione qualquer tecla para fechar esta janela.
pause >nul
