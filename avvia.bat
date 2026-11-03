@echo off
chcp 65001 >nul
title Monitor Vinted
cd /d "%~dp0"

rem --- Trova Python: prima il launcher "py", altrimenti "python" -----------
py -3 -c "" >nul 2>nul
if not errorlevel 1 set "PYEXE=py -3" & goto verifica
python -c "" >nul 2>nul
if not errorlevel 1 set "PYEXE=python" & goto verifica

echo.
echo  Python non risulta installato su questo PC.
echo  Scaricalo da:  https://www.python.org/downloads/
echo  Durante l'installazione spunta la casella "Add python.exe to PATH".
echo.
pause
exit /b 1

rem --- Verifica che l'ambiente esista e funzioni, altrimenti lo ricrea ------
:verifica
if not exist ".venv\Scripts\python.exe" goto prepara
".venv\Scripts\python.exe" -c "import vinted_scraper" >nul 2>nul
if not errorlevel 1 goto avvia

:prepara
echo.
echo  Preparo l'ambiente: circa un minuto, attendi...
echo.
if exist ".venv" rmdir /s /q ".venv"
%PYEXE% -m venv .venv
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet -r requirements.txt
if not exist ".venv\Scripts\python.exe" goto errore_installazione
".venv\Scripts\python.exe" -c "import vinted_scraper" >nul 2>nul
if errorlevel 1 goto errore_installazione
echo  Ambiente pronto.
echo.

:avvia
".venv\Scripts\python.exe" monitor.py
echo.
pause
exit /b 0

:errore_installazione
echo.
echo  Preparazione dell'ambiente fallita: controlla i messaggi qui sopra.
echo  Riprova quando la connessione a internet e' attiva.
echo.
pause
exit /b 1
