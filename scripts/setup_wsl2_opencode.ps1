<# 
.SYNOPSIS
    Configura WSL2 + Docker + OpenCode para o Projeto Harmonia
    Rode no PowerShell COMO ADMINISTRADOR
#>

Write-Host "=== HARMONIA: Setup WSL2 + OpenCode ===" -ForegroundColor Cyan

# 1. Verificar/instalar WSL2
Write-Host "`n[1/4] Verificando WSL2..." -ForegroundColor Yellow
$wslStatus = wsl --status 2>$null
if (-not $wslStatus) {
    Write-Host "   Instalando WSL2 + Ubuntu..." -ForegroundColor Green
    wsl --install -d Ubuntu
    Write-Host "   REINICIE O COMPUTADOR AGORA e rode este script novamente." -ForegroundColor Red
    exit 1
}
Write-Host "   WSL2 OK" -ForegroundColor Green

# 2. Verificar se Ubuntu existe
$distros = wsl --list --verbose
if ($distros -notmatch "Ubuntu") {
    Write-Host "   Instalando Ubuntu..." -ForegroundColor Green
    wsl --install -d Ubuntu
    Write-Host "   REINICIE O COMPUTADOR AGORA e rode este script novamente." -ForegroundColor Red
    exit 1
}

# 3. Copiar projeto para WSL2
Write-Host "`n[2/4] Copiando projeto para WSL2..." -ForegroundColor Yellow
$projectPath = "C:\Users\porra\Documents\Default Project"
$wslPath = "\\wsl$\Ubuntu\home\$env:USERNAME\harmonia"

if (-not (Test-Path $wslPath)) {
    New-Item -ItemType Directory -Force -Path $wslPath | Out-Null
}

# Copiar arquivos essenciais
$files = @(
    "harmonia",
    "scripts",
    "docker-compose.yml",
    "requirements.txt",
    ".env.example"
)

foreach ($f in $files) {
    $src = Join-Path $projectPath $f
    $dst = Join-Path $wslPath $f
    if (Test-Path $src) {
        Copy-Item $src $dst -Recurse -Force
        Write-Host "   Copiado: $f" -ForegroundColor Gray
    }
}

# 4. Executar setup DENTRO do WSL2
Write-Host "`n[3/4] Executando setup dentro do Ubuntu (WSL2)..." -ForegroundColor Yellow
Write-Host "   Isso vai instalar Docker, subir OpenCode, etc." -ForegroundColor Gray

$setupScript = @"
#!/bin/bash
set -e

echo '=== Atualizando sistema ==='
sudo apt update && sudo apt upgrade -y

echo '=== Instalando Docker ==='
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker \$USER

echo '=== Configurando workspace ==='
mkdir -p ~/harmonia/workspace
cd ~/harmonia

echo '=== Criando .env ==='
cat > .env << 'EOF'
OPENCODE_SERVER_URL=http://localhost:4096
OPENCODE_SERVER_PASSWORD=harmonia123
ANTHROPIC_API_KEY=sk-ant-SEU_KEY_AQUI
OPENAI_API_KEY=sk-SEU_KEY_AQUI
GITHUB_TOKEN=ghp_SEU_TOKEN_AQUI
POSTGRES_DSN=postgresql://postgres:harmonia@localhost:5432/harmonia
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_URL=
TELEGRAM_SECRET_TOKEN=
TELEGRAM_ALLOWED_USERS=
EOF

echo '=== Subindo OpenCode Server ==='
docker run -d \
  --name opencode \
  --restart unless-stopped \
  -p 4096:4096 \
  -v ~/harmonia/workspace:/workspace \
  -v opencode-data:/home/opencode/.local/share/opencode \
  -v opencode-config:/home/opencode/.config/opencode \
  --env-file .env \
  ghcr.io/anomalyco/opencode:latest serve --host 0.0.0.0 --port 4096

echo ''
echo 'Aguardando health check...'
sleep 10

for i in {1..30}; do
  if curl -s http://localhost:4096/global/health | grep -q healthy; then
    echo 'OpenCode saudavel!'
    break
  fi
  echo "Tentativa \$i/30..."
  sleep 2
done

echo ''
echo '=== PRONTO ==='
echo '1. Edite ~/harmonia/.env com SUAS chaves'
echo '2. docker restart opencode'
echo '3. Teste: python3 /mnt/c/Users/porra/Documents/Default\ Project/scripts/teste_opencode_integracao.py'
"@

wsl -d Ubuntu -u root bash -c $setupScript

# 5. Instruções finais
Write-Host "`n[4/4] FINALIZADO" -ForegroundColor Cyan
Write-Host "`nIMPORTANTE: O Docker precisa que você saia e entre novamente no WSL2 para o grupo 'docker' funcionar." -ForegroundColor Yellow
Write-Host "Rode no PowerShell:" -ForegroundColor Gray
Write-Host "  wsl -d Ubuntu" -ForegroundColor Gray
Write-Host "  # Dentro do Ubuntu:" -ForegroundColor Gray
Write-Host "  cd ~/harmonia" -ForegroundColor Gray
Write-Host "  nano .env    # Coloque SUAS chaves API" -ForegroundColor Gray
Write-Host "  docker restart opencode" -ForegroundColor Gray
Write-Host "  python3 /mnt/c/Users/porra/Documents/Default\ Project/scripts/teste_opencode_integracao.py" -ForegroundColor Gray

Write-Host "`nPara stack completa depois:" -ForegroundColor Cyan
Write-Host "  cd /mnt/c/Users/porra/Documents/Default\ Project" -ForegroundColor Gray
Write-Host "  docker-compose up -d" -ForegroundColor Gray