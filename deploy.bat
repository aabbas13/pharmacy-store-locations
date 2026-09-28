@echo off
setlocal
cd /d "%~dp0"

echo Store Apps deployment
echo This will publish commits on the current main branch to GitHub.
echo Streamlit and GitHub Pages may deploy automatically after the push.
echo This publishes the apps publicly without sign-in.
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo ERROR: Git was not found. Install Git for Windows and try again.
    goto :failed
)

git rev-parse --show-toplevel >nul 2>&1
if errorlevel 1 (
    echo ERROR: This folder is not a Git repository.
    goto :failed
)

for /f "delims=" %%B in ('git branch --show-current') do set "BRANCH=%%B"
if /i not "%BRANCH%"=="main" (
    echo ERROR: Current branch is "%BRANCH%". Switch to main before deployment.
    goto :failed
)

echo.
set /p "CONFIRM=Do you want to publish these public apps now? Type YES to continue: "
if /i not "%CONFIRM%"=="YES" (
    echo Deployment cancelled. No files were staged or pushed.
    goto :done
)

rem Stage the public app files and the launcher. Spreadsheet and other untracked files are excluded.
git add -- mobile_app.py hmc_offline_picking_helper283420Accurate20Fit.html docs/index.html requirements.txt .gitignore deploy.bat run_store_apps.bat
if errorlevel 1 (
    echo ERROR: Could not stage the public app files.
    goto :failed
)
git add -u -- store_apps_user_management.py STORE_APPS_AUTH_SETUP.md
if errorlevel 1 (
    echo ERROR: Could not stage the selected deployment files.
    goto :failed
)

git diff --cached --check
if errorlevel 1 (
    echo ERROR: Staged changes have whitespace errors. Fix them before deploying.
    goto :failed
)

git diff --cached --quiet
if errorlevel 1 (
    git commit -m "Update Store Apps"
    if errorlevel 1 (
        echo ERROR: Commit failed.
        goto :failed
    )
)
git push origin main
if errorlevel 1 (
    echo ERROR: Push failed. Review the Git message above; nothing else was published by this script.
    goto :failed
)

echo.
echo Push completed. Check Streamlit Cloud and GitHub Pages for deployment status.
goto :done

:failed
echo.
echo Deployment did not complete successfully.

:done
echo.
pause
endlocal
