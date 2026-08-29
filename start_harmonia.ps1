<#>
.SYNOPSIS
    Inicia o Harmonia (Bot Telegram + Daemon + OpenCode Server)
.DESCRIPTION
    Inicia os 3 componentes necessários do Harmonia em terminais separados.
    Requer: GitHub Codespace ativo, OpenCode instalado, .env configurado.
#>

param(
    [switch]$PularOpenCode,
    [switch]$PularBot,
    [switch]$PularDaemon
)

Write-Host "╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║                    🤖 HARMONIA - STARTUP                        ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan

# Verifica .env
$envPath = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envPath)) {
    Write-Host "❌ Arquivo .env não encontrado!" -ForegroundColor Red
    Write-Host "Copie .env.example para .env e configure as chaves." -ForegroundColor Yellow
    exit 1
}

# Carrega variáveis do .env
$envContent = Get-Content $envPath -Raw
foreach ($line in $envContent -split "`n") {
    if ($line -match '^\s*([^#]\S+)\s*=\s*(.*)$') {
        $key = $matches[1].Trim()
        $value = $matches[2].Trim()
        [Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
}

# Verifica variáveis críticas
$required = @("TELEGRAM_BOT_TOKEN", "GITHUB_TOKEN", "CODESPACE_NAME", "GITHUB_REPO")
foreach ($var in $required) {
    if (-not $env:$var) {
        Write-Host "⚠️ Variável $var não configurada no .env" -ForegroundColor Yellow
    }
}

# Função para iniciar em novo terminal
function IniciarNoTerminal {
    param($titulo, $comando, $cor)
    $script = "cd '$PSScriptRoot'; $comando"
    Start-Process wt -ArgumentList "new-tab -p `"Windows PowerShell`" --title `"$titulo`" -- `$comando`"" -NoNewWindow
    Write-Host "  ✅ $titulo iniciado" -ForegroundColor Green
}

# Verifica se OpenCode Server está rodando
function TestarOpenCode {
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:4096/global/health" -TimeoutSec 5 -ErrorAction Stop
        if ($resp.healthy) {
            Write-Host "✅ OpenCode Server: SAUDÁVEL (v$($resp.version))" -ForegroundColor Green
            return $true
        }
    } catch {
        return $false
    }
    return $false
}

# Verifica se Daemon está rodando
function TestarDaemon {
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:8081/health" -TimeoutSec 5 -ErrorAction Stop
        if ($resp.status -eq "ok") {
            Write-Host "✅ Daemon: RODANDO" -ForegroundColor Green
            return $true
        }
    } catch {
        return $false
    }
    return $false
}

# Verifica se Bot está rodando (via health do daemon)
function TestarBot {
    try {
        $resp = Invoke-RestMethod -Uri "http://localhost:8081/health" -TimeoutSec 5 -ErrorAction Stop
        if ($resp.daemon -eq "running") {
            Write-Host "✅ Bot/Telegram: RODANDO" -ForegroundColor Green
            return $true
        }
    } catch {
        return $false
    }
    return $false
}

# ===== VERIFICAÇÕES INICIAIS =====
Write-Host "`n🔍 Verificando serviços existentes...`n"

$opencodeOk = TestarOpenCode
$daemonOk = TestarDaemon
$botOk = TestarBot

# ===== INICIA O QUE FALTA =====

if (-not $opencodeOk -and -not $PularOpenCode) {
    Write-Host "`n🚀 Iniciando OpenCode Server..." -ForegroundColor Cyan
    Start-Process wt -ArgumentList "new-tab -p `\"Windows PowerShell`\" --title `\"OpenCode Server`\" -- opencode serve --hostname 0.0.0.0 --port 4096" -NoNewWindow
    Write-Host "  ✅ OpenCode Server iniciado em nova aba" -ForegroundColor Green
    Start-Sleep 5
} elseif ($opencodeOk) {
    Write-Host "✅ OpenCode Server já está rodando" -ForegroundColor Green
}

if (-not $daemonOk -and -not $PularDaemon) {
    Write-Host "`n🚀 Iniciando Daemon..." -ForegroundColor Cyan
    Start-Process wt -ArgumentList "new-tab -p `\"Windows PowerShell`\" --title `\"Harmonia Daemon`\" -- python -m harmonia.daemon" -NoNewWindow
    Write-Host "  ✅ Daemon iniciado em nova aba" -ForegroundColor Green
    Start-Sleep 3
} elseif ($daemonOk) {
    Write-Host "✅ Daemon já está rodando" -ForegroundColor Green
}

if (-not $botOk -and -not $PularBot) {
    Write-Host "`n🚀 Iniciando Bot Telegram..." -ForegroundColor Cyan
    Start-Process wt -ArgumentList "new-tab -p `\"Windows PowerShell`\" --title `\"Harmonia Bot`\" -- python harmonia/telegram_bot.py" -NoNewWindow
    Write-Host "  ✅ Bot Telegram iniciado em nova aba" -ForegroundColor Green
    Start-Sleep 3
} elseif ($botOk) {
    Write-Host "✅ Bot Telegram já está rodando" -ForegroundColor Green
}

# Aguarda estabilizar
Start-Sleep 3

# Verificação final
Write-Host "`n🔍 Verificação final:`n"
TestarOpenCode
TestarDaemon
TestarBot

Write-Host "`n╔══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║  ✅ HARMONIA PRONTO!                                           ║" -ForegroundColor Cyan
Write-Host "║                                                                  ║"
Write-Host "║  No Telegram:                                                    ║"
Write-Host "║    /acordar      - Acorda Codespace se hibernou                 ║"
Write-Host "║    /ligado       - Modo ponte OpenCode <-> Telegram            ║"
Write-Host "║    /soninho      - Modo auditor (padrão)                       ║"
Write-Host "║    /status       - Saúde do daemon                             ║"
Write-Host "║                                                                  ║"
Write-Host "║  Keep-alive: GitHub Actions a cada 20 min (anti-hibernação)     ║"
Write-Host "║  Ida e volta: automático via auto-commit                       ║"
Write-Host "╚══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan

Write-Host "`nPressione Enter para fechar..." -ForegroundColor Gray
Read-Host | Out-Null