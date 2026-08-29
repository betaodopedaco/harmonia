@echo off
REM Harmonia One-Click Launcher - Atalho para clicar duas vezes
REM Coloque este arquivo na Area de Trabalho ou onde preferir

@echo off
chcp 65001 >nul
title Harmonia One-Click Launcher

powershell -ExecutionPolicy Bypass -File "%~dp0harmonia_one_click.ps1"

pause