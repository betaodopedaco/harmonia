# Harmonia — Auditor Autônomo + Ponte OpenCode/Telegram

Sistema de automação com dois modos de operação:

## Modos

### 🌙 Soninho (Auditor Autônomo)
- Recebe plano JSON via `curl` → classifica risco → pausa ALTO risco
- Aprovação via Telegram com **confirmação qualificada** (digitar resumo da ação)
- Execução via OpenCode Server → status final `concluido`
- Persistência SQLite checkpoint (sobrevive a reinícios)

### ⚡ Ligado (Ponte Direta)
- `/ligado` no Telegram → texto livre → OpenCode executa
- Resposta em tempo real via HTTP direto (`POST /message`)
- Permissões via botões inline `✅ Permitir` / `❌ Negar`
- Contexto mantido na sessão OpenCode

### ☕ Acordar
- `/acordar` no Telegram → acorda Codespace hibernado via GitHub API
- Funciona do celular, do ônibus, de qualquer lugar

---

## Arquitetura

```
Telegram Bot (polling) → Harmonia Daemon (FastAPI:8081) → OpenCode Server (4096)
                              ↓
                        SQLite Checkpoint
```

---

## Componentes

| Componente | Arquivo | Descrição |
|------------|---------|-----------|
| Daemon | `harmonia/daemon.py` | FastAPI + lifespan + endpoints `/plano`, `/aprovar`, `/status` |
| Graph | `harmonia/graph/` | LangGraph com 6 nós + checkpoint SQLite |
| Bot | `harmonia/telegram_bot.py` | Polling Telegram → Soninho + Ligadão |
| Executor | `harmonia/nodes/executor.py` | OpenCode `execute()` síncrono + auto-commit git |
| Classificador | `harmonia/nodes/classificador_risco.py` | Regras de risco (deploy_producao=ALTO, editar_arquivo=BAIXO) |
| Roteador | `harmonia/nodes/roteador_autonomia.py` | Dial Soninho/Ligadão |
| OpenCode Client | `harmonia/integrations/opencode_client.py` | HTTP + SSE reconexão |

---

---

## Configuração (Codespace)

**.env** (raiz do projeto):
```env
TELEGRAM_BOT_TOKEN=8607637473:AAEov7X2aNrulmfK5-92NafdOZSiM-dL9Bk
DAEMON_URL=http://localhost:8081
OPENCODE_SERVER_URL=http://localhost:4096
OPENCODE_SERVER_PASSWORD=
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
CODESPACE_NAME=harmonia-dev
GITHUB_REPO=seu-usuario/seu-repo
```

**Inicialização fácil (um comando):**
```bash
# Linux/Mac/Codespace
./start_harmonia.sh

# Windows PowerShell
.\start_harmonia.ps1
```

Isso sobe os 3 serviços (OpenCode, Daemon, Bot) em terminais/abas separadas.

---
 
## Controle via Telegram
 
| Comando | Função |
|---------|--------|
| `/acordar` | Acorda Codespace hibernado via GitHub API |
| `/ligado` | Entra no modo ponte OpenCode ↔ Telegram |
| `/soninho` | Modo auditor (padrão) |
| `/status` | Saúde do daemon |
 
### 🌙 Soninho (Auditor Autônomo)
- Recebe plano JSON via `curl` → classifica risco → pausa ALTO risco
- Aprovação via Telegram com **confirmação qualificada** (digitar resumo da ação)
- Execução via OpenCode Server → status final `concluido`
- Persistência SQLite checkpoint (sobrevive a reinícios)
 
### ⚡ Ligado (Ponte Direta)
- `/ligado` no Telegram → texto livre → OpenCode executa
- Resposta em tempo real via HTTP direto (`POST /message`)
- Permissões via botões inline `✅ Permitir` / `❌ Negar`
- Contexto mantido na sessão OpenCode
 
### ☕ Acordar
- `/acordar` no Telegram → acorda Codespace hibernado via GitHub API
- Funciona do celular, do ônibus, de qualquer lugar
 
---
 
## Ida e Volta (auto-commit)
 
Após cada execução bem-sucedida, o Harmonia faz commit + push automático:
```
Harmonia: Criar arquivo deploy_teste.txt — ALTO risco, aprovado_via_Telegram
```
 
Configuração git necessária no container:
```bash
git config user.name "Harmonia Bot"
git config user.email "harmonia@bot.local"
git config --global push.autoSetupRemote true
```
 
---
 
## Keep-alive (anti-hibernação)
 
**1. Interno (daemon):** Task roda a cada **20 min** → escreve timestamp em `.harmonia_keepalive`
```bash
/workspaces/harmonia/.harmonia_keepalive
```
 
**2. Externo (GitHub Actions):** Workflow roda a cada **20 min** → ping `/health` + acorda Codespace se necessário
```yaml
# .github/workflows/keep-alive.yml
on:
  schedule:
    - cron: '*/20 * * * *'  # a cada 20 min
```
 
**Configurar no GitHub:**
- Settings → Secrets → `GITHUB_TOKEN` (PAT com permissão codespaces)
- Settings → Variables → `CODESPACE_NAME` (ex: `harmonia-dev`)
- Settings → Variables → `GITHUB_REPO` (ex: `usuario/repo`)
 
---
 
## Acordar Codespace (via Telegram)
 
`/acordar` no Telegram → chama GitHub API → inicia Codespace hibernado
 
Funciona do celular, do ônibus, de qualquer lugar.
 
Configurar no `.env`:
```env
GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
CODESPACE_NAME=harmonia-dev
GITHUB_REPO=seu-usuario/seu-repo
```
 
---
 
## Inicialização Fácil
 
```bash
# Linux/Mac/Codespace
./start_harmonia.sh

# Windows PowerShell
.\start_harmonia.ps1
```
 
Isso sobe: OpenCode Server (4096) + Daemon (8081) + Bot Telegram
 
---
 
## Sessão Remota / Desconexão
 
Para encerrar sessão remota (ex: lan house, celular descarregado):
1. Acesse **GitHub.com → Settings → Codespaces**
2. Clique em **"Stop"** ou **"Delete"** no Codespace ativo
3. Isso encerra todos os processos (daemon, bot, OpenCode)
 
*O GitHub nativo já resolve isso — não é necessário comando `/logout_remoto` no bot.*
 
Para acordar depois: mande `/acordar` no Telegram.
 
---
 
## Testes
 
```bash
python -m pytest tests/ -v
# 27 testes passando (classificador, roteador, fila_aprovacao)
 
# Teste Soninho BAIXO risco (criar arquivo)
curl -X POST http://127.0.0.1:8081/plano -H "Content-Type: application/json" -d @plano_deploy_teste.json
 
# Ver status
curl -s http://127.0.0.1:8081/status/{thread_id}
```
 
---
 
## Ida e Volta (auto-commit)
 
Após cada execução bem-sucedida, o Harmonia faz commit + push automático:
```
Harmonia: Criar arquivo deploy_teste.txt — ALTO risco, aprovado_via_Telegram
```
 
Configuração git necessária no container:
```bash
git config user.name "Harmonia Bot"
git config user.email "harmonia@bot.local"
git config --global push.autoSetupRemote true
```
 
---
 
## Próximos Passos
 
1. **Nó Auditor** — escaneia repo, acha TODOs/falhas, gera plano JSON sozinho
2. **Relatório final** — Telegram: "Executei X, Y falhou, próximos: Z"
3. **Loop contínuo** — Daemon roda auditor periodicamente (ex: 30min)