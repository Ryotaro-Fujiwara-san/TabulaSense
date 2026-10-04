@echo off
cd /d "%~dp0"
rem Update from GitHub, then hand off to scripts\launch.bat.
rem Everything below is one ( ) block: cmd reads the whole block before running it,
rem so "git pull" can safely replace this file while it is running.
(
    set "PULL_FAILED="
    set "OLD_HEAD="
    for /f %%i in ('git rev-parse HEAD 2^>nul') do set "OLD_HEAD=%%i"
    echo Checking for updates on GitHub...
    git pull --ff-only || set "PULL_FAILED=1"
    call "%~dp0scripts\launch.bat" %*
    exit /b
)
