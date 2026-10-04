@echo off
chcp 65001 >nul
title TabulaSense シミュレーション（このウィンドウを閉じると終了します）
cd /d "%~dp0"

rem 初回だけ: Python の仮想環境を作ってライブラリ（MuJoCo など）を入れる
if exist ".venv\Scripts\python.exe" goto :venv_ready
echo [初回準備] 仮想環境を作ってライブラリを入れています（数分かかります）...
py -m venv .venv || python -m venv .venv || goto :error
.venv\Scripts\python.exe -m pip install -e ".[dev]" || goto :error
:venv_ready

rem 初回だけ: XLeRobot のロボットモデルを取得する
if exist "third_party\XLeRobot\simulation\mujoco\xlerobot.xml" goto :model_ready
echo [初回準備] XLeRobot のモデルを取得しています...
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
