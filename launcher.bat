@echo off
chcp 65001 >nul
title Smart Desktop Assistant
cd /d E:\aiyidai
setlocal enabledelayedexpansion

echo.
echo ========================================
echo   Smart Desktop Assistant - Starting...
echo ========================================
echo.

set "WE_STARTED_OLLAMA=0"

:: Check if Ollama is already running
tasklist /nh /fi "imagename eq ollama.exe" 2>nul | find /i "ollama.exe" >nul
if errorlevel 1 (
    echo   [..] Ollama not running, starting...
    start /min "" "%LOCALAPPDATA%\Programs\Ollama\ollama.exe"

    :: Wait for Ollama API to be ready (max 30 seconds)
    echo   [..] Waiting for Ollama...
    set "WAIT_SECONDS=0"
    :wait_ollama
    timeout /t 2 /nobreak >nul 2>&1
    set /a WAIT_SECONDS+=2
    if !WAIT_SECONDS! geq 30 (
        echo   [!!] Ollama startup timeout, please run ollama serve manually
        pause
        exit /b 1
    )
    curl -s http://127.0.0.1:11434/api/tags >nul 2>&1
    if errorlevel 1 goto wait_ollama
    echo   [OK] Ollama started
    set "WE_STARTED_OLLAMA=1"
) else (
    echo   [OK] Ollama is already running
)

echo.
echo   [..] Launching AI Assistant...
echo.
python main.py
set "EXIT_CODE=%errorlevel%"

:: Always kill llama-server.exe to free GPU/CPU memory
echo.
echo   [..] Freeing model memory...
taskkill /f /im llama-server.exe >nul 2>&1
echo   [OK] Model memory freed

:: Only stop Ollama if we started it
if "%WE_STARTED_OLLAMA%"=="1" (
    echo.
    echo   [..] Stopping Ollama...
    taskkill /f /im ollama.exe >nul 2>&1
    echo   [OK] Ollama stopped
)

if "%EXIT_CODE%" neq "0" (
    echo.
    echo [ERROR] Program exited abnormally (code: %EXIT_CODE%)
    pause
)

endlocal
