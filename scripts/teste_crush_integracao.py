from __future__ import annotations

import asyncio
import os
import sys

# Adicionar path do projeto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harmonia.integrations.crush_client import CrushClient, CrushConfig


async def teste_conexao_basica():
    """Testa conexão básica com Crush server."""
    print("=" * 60)
    print("TESTE 1: Conexão básica + workspace")
    print("=" * 60)
    
    config = CrushConfig(
        server_url=os.getenv("CRUSH_SERVER_URL", "http://localhost:9876"),
        workspace_path=os.getenv("WORKSPACE_PATH", "/workspace"),
    )
    
    async with CrushClient(config) as client:
        print(f"✅ Conectado! Workspace ID: {client.workspace_id}")
        print(f"✅ SSE ativo: {client._connected}")
        
        # Testar health check
        resp = await client._client.get("/v1/health")
        print(f"✅ Health check: {resp.status_code}")
        
        # Listar workspaces
        resp = await client._client.get("/v1/workspaces")
        workspaces = resp.json()
        print(f"✅ Workspaces: {len(workspaces)}")
        for ws in workspaces:
            print(f"   - {ws['id']}: {ws['path']}")
    
    print("✅ Desconexão limpa")


async def teste_execucao_simples():
    """Testa execução de prompt simples."""
    print("\n" + "=" * 60)
    print("TESTE 2: Execução de prompt simples")
    print("=" * 60)
    
    config = CrushConfig(
        server_url=os.getenv("CRUSH_SERVER_URL", "http://localhost:9876"),
        workspace_path=os.getenv("WORKSPACE_PATH", "/workspace"),
    )
    
    async with CrushClient(config) as client:
        # Prompt simples
        resultado = await client.execute(
            prompt="Crie um arquivo hello.py que imprima 'Olá Harmonia!'",
            run_id="teste-001",
            session_title="teste-simples",
        )
        
        print(f"✅ Execução concluída")
        print(f"   Sucesso: {resultado.success}")
        print(f"   Run ID: {resultado.run_id}")
        print(f"   Session ID: {resultado.session_id}")
        print(f"   Output: {resultado.output[:200]}...")
        if resultado.error:
            print(f"   Erro: {resultado.error}")
        
        # Verificar arquivo criado
        if resultado.success:
            # Listar mensagens
            print(f"   Mensagens: {len(resultado.messages)}")
            for msg in resultado.messages[-3:]:
                role = msg.get("role", "?")
                parts = msg.get("parts", [])
                print(f"   - {role}: {len(parts)} parts")


async def teste_shell_direto():
    """Testa execução de shell direto."""
    print("\n" + "=" * 60)
    print("TESTE 3: Shell direto")
    print("=" * 60)
    
    config = CrushConfig(
        server_url=os.getenv("CRUSH_SERVER_URL", "http://localhost:9876"),
        workspace_path=os.getenv("WORKSPACE_PATH", "/workspace"),
    )
    
    async with CrushClient(config) as client:
        # Garantir sessão
        await client._ensure_session("teste-shell")
        
        # Executar comando
        resp = await client.run_shell("ls -la /workspace")
        print(f"✅ Shell executado")
        print(f"   Exit code: {resp.get('exit_code')}")
        print(f"   Output:\n{resp.get('output', '')[:500]}")


async def teste_eventos_sse():
    """Testa consumo de eventos SSE."""
    print("\n" + "=" * 60)
    print("TESTE 4: Eventos SSE (permite ver permissões/questions)")
    print("=" * 60)
    
    config = CrushConfig(
        server_url=os.getenv("CRUSH_SERVER_URL", "http://localhost:9876"),
        workspace_path=os.getenv("WORKSPACE_PATH", "/workspace"),
    )
    
    async with CrushClient(config) as client:
        # Executar algo que pode gerar permissão
        print("Enviando prompt que pode pedir permissão...")
        resultado = await client.execute(
            prompt="Liste os arquivos no workspace e mostre o conteúdo de hello.py se existir",
            run_id="teste-sse-001",
        )
        
        print(f"✅ Resultado: success={resultado.success}")
        
        # Coletar eventos por alguns segundos
        print("Coletando eventos SSE por 3s...")
        await asyncio.sleep(3)
        
        events = await client.get_events(max_events=20)
        print(f"Eventos recebidos: {len(events)}")
        for ev in events:
            print(f"  - {ev['type']}: {ev['payload'].get('id', '')[:30] if ev['payload'] else 'N/A'}")


async def teste_ciclo_completo():
    """Testa ciclo completo: múltiplas ações em sequência."""
    print("\n" + "=" * 60)
    print("TESTE 5: Ciclo completo - múltiplas ações")
    print("=" * 60)
    
    config = CrushConfig(
        server_url=os.getenv("CRUSH_SERVER_URL", "http://localhost:9876"),
        workspace_path=os.getenv("WORKSPACE_PATH", "/workspace"),
    )
    
    async with CrushClient(config) as client:
        acoes = [
            "Crie um arquivo calculadora.py com funções soma, subtrai, multiplica, divide",
            "Crie testes unitários para a calculadora em test_calculadora.py",
            "Execute os testes e mostre o resultado",
        ]
        
        for i, prompt in enumerate(acoes):
            print(f"\n--- Ação {i+1}/{len(acoes)} ---")
            resultado = await client.execute(
                prompt=prompt,
                run_id=f"ciclo-{i}",
                session_title=f"ciclo-completo-{i}",
            )
            
            print(f"   Sucesso: {resultado.success}")
            if resultado.error:
                print(f"   Erro: {resultado.error}")
            else:
                print(f"   Output: {resultado.output[:150]}...")
            
            # Pausa entre ações
            await asyncio.sleep(1)


async def main():
    print("🧪 TESTES DE INTEGRAÇÃO HARMONIA ↔ CRUSH")
    print("=" * 60)
    print(f"Server URL: {os.getenv('CRUSH_SERVER_URL', 'http://localhost:9876')}")
    print(f"Workspace: {os.getenv('WORKSPACE_PATH', '/workspace')}")
    print()
    
    testes = [
        ("Conexão básica", teste_conexao_basica),
        ("Execução simples", teste_execucao_simples),
        ("Shell direto", teste_shell_direto),
        ("Eventos SSE", teste_eventos_sse),
        ("Ciclo completo", teste_ciclo_completo),
    ]
    
    for nome, teste_fn in testes:
        try:
            await teste_fn()
        except Exception as e:
            print(f"❌ {nome} FALHOU: {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("TESTES CONCLUÍDOS")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())