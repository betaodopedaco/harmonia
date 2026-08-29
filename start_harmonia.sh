#!/bin/bash
# start_harmonia.sh - Inicia o Harmonia (Bot + Daemon + OpenCode)
# Uso: ./start_harmonia.sh

set -e

# Cores
CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║                    🤖 HARMONIA - STARTUP                        ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"

# Verifica .env
if [[ ! -f .env ]]; then
    echo -e "${RED}❌ Arquivo .env não encontrado!${NC}"
    echo -e "${YELLOW}Copie .env.example para .env e configure as chaves.${NC}"
    exit 1
fi

# Carrega variáveis do .env
set -a
source .env
set +a

# Verifica variáveis críticas
REQUIRED_VARS=("TELEGRAM_BOT_TOKEN" "GITHUB_TOKEN" "CODESPACE_NAME" "GITHUB_REPO")
for var in "${REQUIRED_VARS[@]}"; do
    if [[ -z "${!var}" ]]; then
        echo -e "${YELLOW}⚠️ Variável $var não configurada no .env${NC}"
    fi
done

# Funções de verificação
test_opencode() {
    if curl -s -f "http://localhost:4096/global/health" > /dev/null 2>&1; then
        local resp=$(curl -s "http://localhost:4096/global/health")
        echo -e "${GREEN}✅ OpenCode Server: SAUDÁVEL ($(echo "$resp" | jq -r '.version // "unknown"'))${NC}"
        return 0
    fi
    return 1
}

test_daemon() {
    if curl -s -f "http://localhost:8081/health" > /dev/null 2>&1; then
        local resp=$(curl -s "http://localhost:8081/health")
        if echo "$resp" | grep -q '"status":"ok"'; then
            echo -e "${GREEN}✅ Daemon: RODANDO${NC}"
            return 0
        fi
    fi
    return 1
}

test_bot() {
    if curl -s -f "http://localhost:8081/health" > /dev/null 2>&1; then
        local resp=$(curl -s "http://localhost:8081/health")
        if echo "$resp" | grep -q '"daemon":"running"'; then
            echo -e "${GREEN}✅ Bot/Telegram: RODANDO${NC}"
            return 1
        fi
    fi
    return 1
}

# ===== VERIFICAÇÕES INICIAIS =====
echo -e "\n${CYAN}🔍 Verificando serviços existentes...${NC}\n"

OPENCODE_OK=0
DAEMON_OK=0
BOT_OK=0

test_opencode && OPENCODE_OK=1
test_daemon && DAEMON_OK=1
test_bot && BOT_OK=1

# ===== INICIA O QUE FALTA =====

if [[ $OPENCODE_OK -eq 0 ]]; then
    echo -e "\n${CYAN}🚀 Iniciando OpenCode Server...${NC}"
    nohup opencode serve --hostname 0.0.0.0 --port 4096 > opencode.log 2>&1 &
    echo "  ✅ OpenCode Server iniciado (PID: $!)"
    sleep 5
else
    echo -e "${GREEN}✅ OpenCode Server já está rodando${NC}"
fi

if [[ $DAEMON_OK -eq 0 ]]; then
    echo -e "\n${CYAN}🚀 Iniciando Daemon...${NC}"
    nohup python -m harmonia.daemon > daemon.log 2>&1 &
    echo "  ✅ Daemon iniciado (PID: $!)"
    sleep 3
else
    echo -e "${GREEN}✅ Daemon já está rodando${NC}"
fi

if [[ $BOT_OK -eq 0 ]]; then
    echo -e "\n${CYAN}🚀 Iniciando Bot Telegram...${NC}"
    nohup python harmonia/telegram_bot.py > bot.log 2>&1 &
    echo "  ✅ Bot Telegram iniciado (PID: $!)"
    sleep 3
else
    echo -e "${GREEN}✅ Bot Telegram já está rodando${NC}"
fi

# Aguarda estabilizar
sleep 3

# Verificação final
echo -e "\n${CYAN}🔍 Verificação final:${NC}\n"
test_opencode
test_daemon
test_bot

echo -e "\n${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║  ✅ HARMONIA PRONTO!                                           ║${NC}"
echo -e "${CYAN}║                                                                  ║${NC}"
echo -e "${CYAN}║  No Telegram:                                                    ║${NC}"
echo -e "${CYAN}║    /acordar      - Acorda Codespace se hibernou                ║${NC}"
echo -e "${CYAN}║    /ligado       - Modo ponte OpenCode <-> Telegram            ║${NC}"
echo -e "${CYAN}║    /soninho      - Modo auditor (padrão)                       ║${NC}"
echo -e "${CYAN}║    /status       - Saúde do daemon                             ║${NC}"
echo -e "${CYAN}║                                                                  ║${NC}"
echo -e "${CYAN}║  Keep-alive: GitHub Actions a cada 20 min (anti-hibernação)     ║${NC}"
echo -e "${CYAN}║  Ida e volta: automático via auto-commit                       ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"

echo -e "\n${GREEN}✅ HARMONIA PRONTO! Pressione Ctrl+C para parar.${NC}"

# Mantém script rodando se for chamado diretamente
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo -e "\n${YELLOW}Pressione Ctrl+C para parar todos os serviços...${NC}"
    wait
fi