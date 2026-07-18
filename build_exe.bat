@echo off
setlocal
cd /d "%~dp0"
python -m PyInstaller --noconfirm --clean --noconsole --onefile --name HarmoCheck --paths src --collect-all matplotlib main.py
echo.
echo Build complete: dist\HarmoCheck.exe
endlocal
