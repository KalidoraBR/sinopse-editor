@echo off
setlocal
cd /d "%~dp0"
title Gerador da versao portatil - Sinopse Editor

echo Instalando ou atualizando os componentes necessarios...
python -m pip install -r requirements.txt
if errorlevel 1 goto erro

echo Gerando o programa portatil...
python -m PyInstaller --noconfirm --clean --windowed --onedir ^
  --name "Sinopse Editor" ^
  --icon icone.ico --add-data "icone.ico;." ^
  --collect-all customtkinter ^
  --collect-all playwright ^
  --collect-all webview ^
  --collect-all clr_loader ^
  --collect-all pythonnet ^
  --add-data "ui;ui" ^
  sentai_studio.py
if errorlevel 1 goto erro

echo.
echo Concluido.
echo A versao portatil esta em: dist\Sinopse Editor
echo Copie a pasta inteira para outro local ou pendrive.
pause
exit /b 0

:erro
echo.
echo Nao foi possivel gerar a versao portatil.
echo Confira as mensagens acima.
pause
exit /b 1
