#!/bin/bash
set -e

echo "=== Teste completo WSL2: OpenCode + Harmonia ==="
cd /mnt/c/Users/porra/Documents/Default\ Project

# Matar processos anteriores
pkill -f "opencode serve" 2>/dev/null || true
sleep 2

# Iniciar OpenCode server em background
echo "Iniciando OpenCode server..."
/mnt/c/Users/porra/AppData/Roaming/npm/opencode serve --hostname 0.0.0.0 --port 4096 &
OPENCODE_PID=$!
echo "OpenCode PID: $OPENCODE_PID"

# Aguardar server subir
sleep 5

# Testar health check
echo "Testando OpenCode health..."
curl -s http://127.0.0.1:4096/global/health || echo "Health check falhou"

# Testar Harmonia grafo direto
echo "=== Testando Harmonia grafo direto ==="
python3 scripts/teste_braco_direto.py

# Limpar
kill $OPENCODE_PID 2>/dev/null || true

echo "=== Teste completo ==="