@echo off
REM ============================================================
REM  Backtest ICT/SMC -- generador del ejecutable (.exe)
REM
REM  Este script se ejecuta en Windows, dentro de la carpeta
REM  "packaging" del proyecto (no lo muevas de ahi). Genera:
REM
REM     ..\dist\BacktestICT.exe
REM
REM  Ese .exe ya se puede copiar a cualquier PC Windows sin que
REM  tenga Python instalado. Si ademas quieres un instalador tipo
REM  asistente (Setup.exe) para repartirlo, ve luego a
REM  packaging\installer.iss (ver README, seccion "Instalador").
REM
REM  Nota: se incluye "--collect-all numpy" ademas de MetaTrader5
REM  porque PyInstaller no siempre detecta automaticamente todos los
REM  modulos internos de numpy (C extensions) que MetaTrader5 necesita
REM  para importar -- sin esto, la app compila bien pero al conectar
REM  a MT5 falla con un error de "numpy._core.multiarray failed to
REM  import" enmascarado como si MetaTrader5 no estuviera disponible.
REM ============================================================

setlocal
cd /d "%~dp0.."

echo ============================================
echo  Backtest ICT/SMC - generador de .exe
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] No se encontro Python en el PATH.
    echo Instala Python desde https://www.python.org/downloads/
    echo y marca la casilla "Add Python to PATH" durante la instalacion.
    pause
    exit /b 1
)

echo Creando entorno virtual de compilacion (build_env)...
python -m venv build_env
call build_env\Scripts\activate.bat

echo.
echo Instalando dependencias del proyecto + PyInstaller...
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

echo.
echo Generando el ejecutable (puede tardar varios minutos)...
echo.
pyinstaller --noconfirm --onefile --windowed --name BacktestICT ^
    --hidden-import=MetaTrader5 ^
    --collect-all MetaTrader5 ^
    --collect-all numpy ^
    --hidden-import=reportlab ^
    --collect-all reportlab ^
    main.py

echo.
if exist dist\BacktestICT.exe (
    echo ============================================
    echo  Listo: dist\BacktestICT.exe
    echo ============================================
    echo Ese archivo ya funciona solo en cualquier PC Windows.
    echo Si quieres un instalador tipo asistente, sigue con
    echo packaging\installer.iss ^(ver README^).
) else (
    echo Algo fallo generando el ejecutable. Revisa los mensajes de arriba.
)

call build_env\Scripts\deactivate.bat
pause
