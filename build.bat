@echo off
REM Builds LocalShare.exe from source. Run this from inside the
REM localshare project folder (where main.py lives).
REM
REM Pass "nopause" as an argument (used by build_installer.bat when
REM chaining this script) to skip the final "press any key" prompt.

echo Installing/updating dependencies...
pip install -r requirements.txt
pip install pyinstaller

echo.
echo Building LocalShare.exe (this can take a few minutes)...
REM --clean forces PyInstaller to wipe its own intermediate build
REM cache first. Without it, changes to resource files like the app
REM icon have been observed to not always refresh in a rebuild — the
REM icon embedding step can reuse cached data from a previous run.
python -m PyInstaller --noconfirm --clean localshare.spec

echo.
if exist "dist\LocalShare.exe" (
    echo Build succeeded: dist\LocalShare.exe
) else (
    echo Build finished but dist\LocalShare.exe was not found — check the output above for errors.
)
if /I not "%~1"=="nopause" pause
