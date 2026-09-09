@echo off
echo Adding updated files...
git add .

echo Committing changes...
git commit -m "Updated mobile_app.py with bin filling mode"

echo Pushing to GitHub main branch...
git push origin main

echo ========================================
echo Deployment process finished!
echo ========================================
pause