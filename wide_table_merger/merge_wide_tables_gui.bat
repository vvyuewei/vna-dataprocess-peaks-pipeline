@echo off
setlocal
cd /d "%~dp0"
python "%~dp0merge_wide_tables_gui.py"
if errorlevel 1 pause
