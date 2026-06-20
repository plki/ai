@echo off
chcp 65001 >nul
title aiyidai - One-click Setup
cd /d E:\aiyidai
setlocal enabledelayedexpansion

echo.
echo ================================================
echo   AI Desktop Assistant - One-click Setup
echo ================================================
echo.

:: ========================
:: 1. Check Python
:: ========================
echo [1/4] Checking Python environment...
python --version >nul 2>&1
if errorlevel 1 (
    echo   [FAIL] Python not found!
    echo.
    echo   Please install Python 3.8+ from:
    echo   https://www.python.org/downloads/
    echo.
    echo   Remember to check "Add Python to PATH"
    echo.
    pause
    exit /b 1
)
for /f "delims=" %%v in ('python --version 2^>^&1') do set "PY_VER=%%v"
echo   [OK] %PY_VER%

:: ========================
:: 2. Install Python packages
:: ========================
echo [2/4] Installing Python packages...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo   [FAIL] Package installation failed
    pause
    exit /b 1
)
echo   [OK] Packages installed

:: ========================
:: 3. Check / Install Ollama
:: ========================
echo [3/4] Checking Ollama...
ollama --version >nul 2>&1
if errorlevel 1 (
    echo   [..] Ollama not found, downloading installer...
    echo   Please wait (approx 200MB)...
    
    curl -L -o "%TEMP%\OllamaSetup.exe" https://ollama.com/download/OllamaSetup.exe --progress-bar
    
    if errorlevel 1 (
        echo   [FAIL] Download failed, please install manually from https://ollama.com/download
        pause
        exit /b 1
    )
    
    echo   [..] Installing silently...
    "%TEMP%\OllamaSetup.exe" /S
    if errorlevel 1 (
        echo   [WARN] Installation may have been interrupted, please check manually
    )
    
    timeout /t 3 /nobreak >nul
    
    ollama --version >nul 2>&1
    if errorlevel 1 (
        echo   [FAIL] Installation failed, please install manually
        pause
        exit /b 1
    )
    echo   [OK] Ollama installed
) else (
    for /f "delims=" %%v in ('ollama --version') do set "OL_VER=%%v"
    echo   [OK] Ollama !OL_VER!
)

:: Ensure Ollama is running
echo   [..] Starting Ollama service...
tasklist /nh /fi "imagename eq ollama.exe" 2>nul | find /i "ollama.exe" >nul
if errorlevel 1 (
    start /min "" "%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
    set "WAIT=0"
    :wait_ollama_install
    timeout /t 2 /nobreak >nul
    set /a WAIT+=2
    if !WAIT! geq 20 (
        echo   [WARN] Ollama startup timeout
        goto :check_models
    )
    curl -s http://127.0.0.1:11434/api/tags >nul 2>&1
    if errorlevel 1 goto wait_ollama_install
)
echo   [OK] Ollama service ready

:: ========================
:: 4. Check and download model
:: ========================
:check_models
echo [4/4] Checking AI models...
curl -s http://127.0.0.1:11434/api/tags > "%TEMP%\ollama_models.json" 2>nul
if errorlevel 1 (
    echo   [WARN] Cannot connect to Ollama, please download models later
    goto :finish
)

findstr "models" "%TEMP%\ollama_models.json" >nul 2>&1
if errorlevel 1 (
    echo   [WARN] No models available!
    echo.
    echo   Please choose a model to download (qwen2.5 recommended for Chinese support):
    echo.
    echo     [1] qwen2.5:0.5b   (397MB) - Lightweight Chinese model
    echo     [2] qwen2.5:1.5b   (1.1GB) - Recommended, best Chinese quality
    echo     [3] tinyllama      (637MB) - General English model
    echo     [0] Skip, download later
    echo.
    set /p "MODEL_CHOICE=Enter number [0-3]: "
    
    if "!MODEL_CHOICE!"=="1" set "PULL_MODEL=qwen2.5:0.5b"
    if "!MODEL_CHOICE!"=="2" set "PULL_MODEL=qwen2.5:1.5b"
    if "!MODEL_CHOICE!"=="3" set "PULL_MODEL=tinyllama"
    if "!MODEL_CHOICE!"=="0" set "PULL_MODEL="
    
    if defined PULL_MODEL (
        echo.
        echo   [..] Downloading !PULL_MODEL! (may take a while on first run)...
        ollama pull !PULL_MODEL!
        echo   [OK] !PULL_MODEL! downloaded
    ) else (
        echo   [/] Skipping model download, run ollama pull ^<model_name^> later
    )
) else (
    echo   [OK] Models already available
)

del "%TEMP%\ollama_models.json" 2>nul

:: ========================
:: Complete
:: ========================
:finish
echo.
echo ================================================
echo   Setup Complete!
echo ================================================
echo.
echo   How to start:
echo     Double-click launcher.bat  or  run python main.py
echo.
echo   Common commands:
echo     help             Show help
echo     chat             Enter AI chat mode
echo     chat ask <text>  Quick question
echo     chat models      List available models
echo     model search     Search download models
echo     file list        List files
echo.
pause
endlocal
