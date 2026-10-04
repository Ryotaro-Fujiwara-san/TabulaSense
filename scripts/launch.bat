@echo off
chcp 65001 >nul
title TabulaSense シミュレーション（このウィンドウを閉じると終了します）
rem start-sim.bat から呼ばれる。最新版の取り込みは start-sim.bat が済ませている
cd /d "%~dp0.."

if not defined PULL_FAILED goto :pulled
echo.
echo [注意] 最新版を取り込めませんでした。手元の版で起動します。
echo        （ネットにつながっていない、またはこの PC でファイルを書き換えた可能性があります）
echo.
:pulled
set "NEW_HEAD="
for /f %%i in ('git rev-parse HEAD 2^>nul') do set "NEW_HEAD=%%i"

rem 初回だけ: Python の仮想環境を作ってライブラリ（MuJoCo など）を入れる
if exist ".venv\Scripts\python.exe" goto :venv_ready
echo [初回準備] 仮想環境を作ってライブラリを入れています（数分かかります）...
py -m venv .venv || python -m venv .venv || goto :error
.venv\Scripts\python.exe -m pip install -e ".[dev]" || goto :error
goto :deps_ready
:venv_ready

rem 必要なライブラリが変わっていたら入れ直す
if "%OLD_HEAD%"=="%NEW_HEAD%" goto :deps_ready
git diff --quiet %OLD_HEAD% %NEW_HEAD% -- pyproject.toml
if not errorlevel 1 goto :deps_ready
echo ライブラリの更新を入れています...
.venv\Scripts\python.exe -m pip install -e ".[dev]" || goto :error
:deps_ready

rem XLeRobot のロボットモデルを取得する（初回と、取得するバージョンが変わったとき）
if not exist "third_party\XLeRobot\simulation\mujoco\xlerobot.xml" goto :fetch_model
if "%OLD_HEAD%"=="%NEW_HEAD%" goto :model_ready
git diff --quiet %OLD_HEAD% %NEW_HEAD% -- scripts/fetch_xlerobot.py
if not errorlevel 1 goto :model_ready
:fetch_model
echo XLeRobot のモデルを取得しています...
.venv\Scripts\python.exe scripts\fetch_xlerobot.py || goto :error
:model_ready

echo シミュレーションを起動します。終わるときはシミュレーションの画面を閉じてください。
.venv\Scripts\python.exe scripts\view.py --demo %*
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo エラーが起きました。上の表示をコピーして Claude に貼ってください。
pause
exit /b 1
