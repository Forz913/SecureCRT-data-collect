@echo off
cd /d %~dp0
call .venv\Scripts\activate.bat
pyinstaller --noconfirm --clean --onefile --windowed ^
  --name "SecureCRT批量取数工具" ^
  --add-data "engine\engine.vbs;engine" ^
  --add-data "samples;samples" ^
  app.py
echo.
echo 生成: dist\SecureCRT批量取数工具.exe
pause
