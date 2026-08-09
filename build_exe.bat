@echo off
chcp 65001 > nul
cls
echo =======================================================
echo     DONG GOI PHAN MEM TACH VA GHEP PDF SANG FILE .EXE
echo =======================================================
echo.

echo [1/2] Dang kiem tra va cai dat thu vien Python...
python -m pip install -r requirements.txt

echo.
echo [2/2] Dang dong goi ung dung bang PyInstaller...
pyinstaller --noconfirm --onedir --windowed --name "PDF_Splitter_Merger" --clean main.py

echo.
echo =======================================================
echo   DONG GOI HOAN TAT!
echo   File exe nam tai: dist\PDF_Splitter_Merger\PDF_Splitter_Merger.exe
echo =======================================================
echo.
pause

