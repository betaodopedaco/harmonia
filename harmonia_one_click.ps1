<#>
.SYNOPSIS
    Harmonia One-Click Launcher - Preparacao para sair de casa
.DESCRIPTION
    Um clique: commit + push local -> acorda Codespace -> inicia servicos no Codespace
    Uso: clique com botao direito -> "Executar com PowerShell"
#>

param(
    [string]$RepoPath = "C:\Users\porra\Documents\Default Project",
    [string]$CodespaceName = "harmonia-dev",
    [string]$GitHubRepo = "betaodopedaco/harmonia"
)

Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "           HARMONIA - ONE CLICK LAUNCHER" -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan

# Carrega variaveis do .env local
$envPath = Join-Path $RepoPath ".env"
if (Test-Path $envPath) {
    $envContent = Get-Content $envPath -Raw
    foreach ($line in $envContent -split "`n") {
        if ($line -match '^\s*([^#]\S+)\s*=\s*(.*)$') {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
        }
    }
}

$githubToken = $env:GITHUB_TOKEN
$codespaceName = $env:CODESPACE_NAME ?? "harmonia-dev"
$githubRepo = $env:GITHUB_REPO ?? "betaodopedaco/harmonia"

if (-not $env:GITHUB_TOKEN) {
    Write-Host "[ERRO] GITHUB_TOKEN nao encontrado no .env local" -ForegroundColor Red
    Read-Host "Pressione Enter para sair"
    exit 1
}

Write-Host "`n[1/4] Commit + Push local..." -ForegroundColor Cyan
Push-Location $RepoPath

# Verifica se ha mudancas
$status = git status --porcelain
if ($status) {
    Write-Host "  Mudancas detectadas, commitando..." -ForegroundColor Yellow
    git add -A
    $msg = "Harmonia: sync antes de sair - $(Get-Date -Format 'yyyy-MM-dd HH:mm')"
    git commit -m $msg
    Write-Host "  Commit criado" -ForegroundColor Green
} else {
    Write-Host "  Sem mudancas locais" -ForegroundColor Gray
}

# Push
Write-Host "  Push para GitHub..." -ForegroundColor Cyan
try {
    git push origin main
    Write-Host "  Push realizado" -ForegroundColor Green
} catch {
    Write-Host "  Push falhou (pode ser up-to-date): $_" -ForegroundColor Yellow
}

Pop-Location

Write-Host "`n[2/4] Acordando Codespace '$codespaceName'..." -ForegroundColor Cyan

# Acorda Codespace via GitHub API
$headers = @{
    "Authorization" = "Bearer $env:GITHUB_TOKEN"
    "Accept" = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
}

$url = "https://api.github.com/user/codespaces/$githubRepo/$codespaceName/start"

try {
    $resp = Invoke-RestMethod -Uri "https://api.github.com/user/codespaces/$githubRepo/$codespaceName/start" `
        -Method POST -Headers $headers -ErrorAction Stop
    Write-Host "  Codespace '$codespaceName' acordado!" -ForegroundColor Green
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 200 -or $_.Exception.Response.StatusCode.value__ -eq 202) {
        Write-Host "  Codespace acordado (ou ja ativo)" -ForegroundColor Green
    } else {
        Write-Host "  Erro ao acordar: $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

Write-Host "`n[3/4] Aguardando Codespace ficar pronto..." -ForegroundColor Cyan
Start-Sleep 10

Write-Host "`n[4/4] Pronto! No Telegram:" -ForegroundColor Green
Write-Host "  1. Mande /acordar (se hibernou de novo)" -ForegroundColor Cyan
Write-Host "  2. Mande /ligado  - para modo ponte OpenCode" -ForegroundColor Cyan
Write-Host "  3. Mande /soninho - modo auditor" -ForegroundColor Cyan
Write-Host "  4. Mande /status    - saude do daemon" -ForegroundColor Cyan

Write-Host "`nPRONTO! Pode fechar o PC e ir embora." -ForegroundColor Green
Read-Host "Pressione Enter para fechar"