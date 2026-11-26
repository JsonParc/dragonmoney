@echo off
rem JsonParc Stock Bot - Windows launcher. Usage: start.bat [--demo | --dry-run]
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.lock
  .venv\Scripts\python -m pip install -e .
)
if not exist web-ui\dist\index.html (
  pushd web-ui
  call npm install
  call npm run build
  popd
)
if not exist .env if not "%1"=="--demo" (
  echo .env 파일이 없습니다. .env.example 을 복사해서 .env 를 만들고 값을 채워주세요.
  exit /b 1
)
.venv\Scripts\python -m stockbot %*
