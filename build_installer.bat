@echo off
REM Builds LocalShare.exe and packages it into a single
REM LocalShareSetup.exe installer using Inno Setup.
REM
REM Requires Inno Setup (free, one-time install):
REM   https://jrsoftware.org/isinfo.php
REM During Inno Setup's own installer, it doesn't matter whether you
REM add it to PATH — this script checks both the typical install
REM locations and PATH automatically.

echo Step 1: Building LocalShare...
call build.bat nopause

if not exist "dist\LocalShare\LocalShare.exe" (
    echo.
    echo LocalShare.exe was not found in dist\LocalShare\ -- the build must succeed before creating an installer.
    pause
    exit /b 1
)

echo.
echo Step 2: Compiling the installer with Inno Setup...

where iscc >nul 2>nul
if %errorlevel%==0 (
    iscc localshare_setup.iss
) else if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
    "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" localshare_setup.iss
) else if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" (
    "%ProgramFiles%\Inno Setup 6\ISCC.exe" localshare_setup.iss
) else (
    echo.
    echo Inno Setup wasn't found. Install it first ^(free^): https://jrsoftware.org/isinfo.php
    echo Then run this script again.
    pause
    exit /b 1
)

echo.
if exist "Output\LocalShareSetup.exe" (
    echo Installer created: Output\LocalShareSetup.exe
    echo This is the ONLY file you need to share with your friend.
) else (
    echo Installer build finished but Output\LocalShareSetup.exe was not found -- check the output above for errors.
)
pause
