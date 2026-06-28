@echo off
setlocal
cd /d "%~dp0"

echo Merge wide-format tables
echo.

python "%~dp0merge_wide_tables.py" %*
set EXITCODE=%ERRORLEVEL%

echo.
if not "%EXITCODE%"=="0" (
  echo Failed. Please check the messages above.
) else (
  echo Done. Results were written to the merged_output folder.
)
pause
exit /b %EXITCODE%
