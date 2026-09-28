@echo off
setlocal
cd /d "%~dp0"
title Public Store Apps
goto :check_dependencies

:menu
cls
echo ================================
echo       Public Store Apps
echo ================================
echo 1. Run the mobile app on this computer
echo 2. Exit
echo.
set /p "choice=Choose 1 or 2: "
if "%choice%"=="1" goto :mobile
if "%choice%"=="2" goto :end
echo Please enter 1 or 2.
pause
goto :menu

:check_dependencies
py --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python was not found. Install Python from python.org and enable the Python Launcher.
    pause
    goto :end
)
py -c "import streamlit; assert tuple(map(int, streamlit.__version__.split('.')[:2])) >= (1, 51); import gspread, oauth2client, google.auth" >nul 2>&1
if not errorlevel 1 goto :menu
echo Installing required Python packages from requirements.txt...
py -m pip install -r requirements.txt
if errorlevel 1 (
    echo Package installation failed. Check your internet connection.
    pause
    goto :end
)
goto :menu

:mobile
if not exist "mobile_app.py" (
    echo ERROR: mobile_app.py was not found in this folder.
    pause
    goto :menu
)
echo Starting the mobile app locally. Keep this window open while using it.
echo Press Ctrl+C here to stop the app.
echo.
py -m streamlit run mobile_app.py
pause
goto :menu

:end
endlocal