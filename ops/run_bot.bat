@echo off
REM WARDOGS TOOLS — цикл автоперезапуска. Упал -> ждём 5 сек -> стартуем снова.
cd /d "%~dp0.."
:loop
echo [%date% %time%] starting bot...
python -u bot.py
echo [%date% %time%] bot exited with code %errorlevel%, restart in 5s...
timeout /t 5 /nobreak >nul
goto loop
