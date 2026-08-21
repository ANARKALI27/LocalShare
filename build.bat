@echo off
REM Builds LocalShare.exe from source. Run this from inside the
REM localshare project folder (where main.py lives).

echo Installing/updating dependencies...
pip install -r requirements.txt
pip install pyinstaller

echo.
echo Building LocalShare.exe (this can take a few minutes)...
pyinstaller --noconfirm localshare.spec

echo.
if exist "dist\LocalShare.exe" (
    echo Build succeeded: dist\LocalShare.exe
) else (
    echo Build finished but dist\LocalShare.exe was not found — check the output above for errors.
)
pause
