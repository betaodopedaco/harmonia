#!/bin/bash
# ============================================
# Setup WSL2 + Docker + OpenCode para Harmonia
# Rode DENTRO do terminal Ubuntu (WSL2)
# ============================================

set -e

echo "=== [1/5] Atualizando sistema ==="
sudo apt update && sudo apt upgrade -y

echo "=== [2/5] Instalando Docker ==="
sudo apt install -y docker.io docker-compose-plugin
sudo usermod -aG docker $USER

echo "=== [3/5] Configurando workspace ==="
mkdir -p ~/harmonia/workspace
cd ~/harmonia

echo "=== [4/5] Criando .env (EDITE DEPOIS!) ==="
cat > .env << 'EOF'
# OpenCode Server
OPENCODE_SERVER_URL=http://localhost:4096
OPENCODE_SERVER_PASSWORD=harmonia123

# LLM Providers (PREENCHA PELO MENOS UM)
ANTHROPIC_API_KEY=sk-ant-SEU_KEY_AQUI
OPENAI_API_KEY=sk-SEU_KEY_AQUI
GITHUB_TOKEN=ghp_SEU_TOKEN_AQUI

# PostgreSQL
POSTGRES_DSN=postgresql://postgres:harmonia@localhost:5432/harmonia

# Telegram (opcional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEBHOOK_URL=
TELEGRAM_SECRET_TOKEN=
TELEGRAM_ALLOWED_USERS=
EOF

echo "=== [5/5] Subindo OpenCode Server ==="
docker run -d \
  --name opencode \
  --restart unless-stopped \
  -p 4096:4096 \
  -v ~/harmonia/workspace:/workspace \
  -v opencode-data:/home/opencode/.local/share/opencode \
  -v opencode-config:/home/opencode/.config/opencode \
  --env-file .env \
  ghcr.io/anomalyco/opencode:latest serve --host 0.0.0.0 --port 4096

echo ""
echo "✅ OpenCode subindo... Aguardando health check..."
sleep 10

# Health check
for i in {1..30}; do
  if curl -s http://localhost:4096/global/health | grep -q "healthy"; then
    echo "✅ OpenCode saudável!"
    break
  fi
  echo "   Tentativa $i/30..."
  sleep 2
done

echo ""
echo "=== PRÓXIMOS PASSOS ==="
echo "1. Edite ~/harmonia/.env com SUAS chaves de API"
echo "2. Reinicie: docker restart opencode"
echo "3. Teste: python3 /mnt/c/Users/porra/Documents/Default\ Project/scripts/teste_opencode_integracao.py"
echo ""
echo "Para subir stack completa (Harmonia + Postgres) depois:"
echo "  cd /mnt/c/Users/porra/Documents/Default\ Project"
echo "  docker-compose up -d"