@echo off
REM Builds LocalShare (as dist\LocalShare\, a folder — see
REM localshare.spec for why this isn't a single .exe) from source.
REM Run this from inside the localshare project folder (where main.py
REM lives).
REM
REM Pass "nopause" as an argument (used by build_installer.bat when
REM chaining this script) to skip the final "press any key" prompt.

echo Installing/updating dependencies...
pip install -r requirements.txt
pip install pyinstaller

echo.
echo Building LocalShare (this can take a few minutes)...
REM --clean forces PyInstaller to wipe its own intermediate build
REM cache first. Without it, changes to resource files like the app
REM icon have been observed to not always refresh in a rebuild — the
REM icon embedding step can reuse cached data from a previous run.
python -m PyInstaller --noconfirm --clean localshare.spec

echo.
if exist "dist\LocalShare\LocalShare.exe" (
    echo Build succeeded: dist\LocalShare\LocalShare.exe
    echo ^(This is now a folder, not a single file — see localshare.spec for why:
    echo  a plain folder avoids a whole class of "failed to start" errors that
    echo  onefile's self-extraction was prone to. Copy/share the WHOLE
    echo  dist\LocalShare folder, not just the .exe on its own.^)
) else (
    echo Build finished but dist\LocalShare\LocalShare.exe was not found — check the output above for errors.
)
if /I not "%~1"=="nopause" pause
