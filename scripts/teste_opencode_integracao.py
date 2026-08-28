from __future__ import annotations

import asyncio
import os
import sys

# Adicionar path do projeto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from harmonia.integrations.opencode_client import OpenCodeClient, OpenCodeConfig


async def teste_conexao_basica():
    """Testa conexao basica com OpenCode server."""
    print("=" * 60)
    print("TESTE 1: Conexao basica + health check")
    print("=" * 60)
    
    config = OpenCodeConfig(
        server_url=os.getenv("OPENCODE_SERVER_URL", "http://localhost:4096"),
        password=os.getenv("OPENCODE_SERVER_PASSWORD", ""),
    )
    
    async with OpenCodeClient(config) as client:
        print(f"Conectado! SSE ativo: {client._connected}")
        
        # Testar health check
        resp = await client._client.get("/global/health")
        data = resp.json()
        print(f"Health check: {data}")
        
        # Listar sessoes
        resp = await client._client.get("/session")
        sessions = resp.json()
        print(f"Sessoes existentes: {len(sessions)}")
    
    print("Desconexao limpa")


async def teste_execucao_simples():
    """Testa execucao de prompt simples."""
    print("\n" + "=" * 60)
    print("TESTE 2: Execucao de prompt simples")
    print("=" * 60)
    
    config = OpenCodeConfig(
        server_url=os.getenv("OPENCODE_SERVER_URL", "http://localhost:4096"),
        password=os.getenv("OPENCODE_SERVER_PASSWORD", ""),
    )
    
    async with OpenCodeClient(config) as client:
        # Prompt simples
        resultado = await client.execute(
            prompt="Crie um arquivo hello.py que imprima 'Ola Harmonia via OpenCode!'",
            session_title="teste-simples",
            model="nvidia/nemotron-3-ultra",
        )
        
        print(f"Execucao concluida")
        print(f"   Sucesso: {resultado.success}")
        print(f"   Session ID: {resultado.session_id}")
        print(f"   Output: {resultado.output[:200]}...")
        if resultado.error:
            print(f"   Erro: {resultado.error}")
        
        # Verificar mensagens
        if resultado.success:
            print(f"   Mensagens: {len(resultado.messages)}")


async def teste_shell_direto():
    """Testa execucao de shell direto."""
    print("\n" + "=" * 60)
    print("TESTE 3: Shell direto")
    print("=" * 60)
    
    config = OpenCodeConfig(
        server_url=os.getenv("OPENCODE_SERVER_URL", "http://localhost:4096"),
        password=os.getenv("OPENCODE_SERVER_PASSWORD", ""),
    )
    
    async with OpenCodeClient(config) as client:
        # Garantir sessao
        await client._ensure_session("teste-shell")
        
        # Executar comando
        resp = await client.run_shell("ls -la /workspace")
        print(f"Shell executado")
        info = resp.get("info", {})
        parts = resp.get("parts", [])
        print(f"   Output: {parts}")


async def teste_eventos_sse():
    """Testa consumo de eventos SSE."""
    print("\n" + "=" * 60)
    print("TESTE 4: Eventos SSE")
    print("=" * 60)
    
    config = OpenCodeConfig(
        server_url=os.getenv("OPENCODE_SERVER_URL", "http://localhost:4096"),
        password=os.getenv("OPENCODE_SERVER_PASSWORD", ""),
    )
    
    async with OpenCodeClient(config) as client:
        print("Enviando prompt...")
        resultado = await client.execute(
            prompt="Liste os arquivos no workspace",
            model="nvidia/nemotron-3-ultra",
        )
        
        print(f"Resultado: success={resultado.success}")
        
        # Coletar eventos por alguns segundos
        print("Coletando eventos SSE por 3s...")
        await asyncio.sleep(3)
        
        events = await client.get_events(max_events=20)
        print(f"Eventos recebidos: {len(events)}")
        for ev in events:
            print(f"  - {ev['type']}")


async def teste_ciclo_completo():
    """Testa ciclo completo: multiplas acoes em sequencia."""
    print("\n" + "=" * 60)
    print("TESTE 5: Ciclo completo - multiplas acoes")
    print("=" * 60)
    
    config = OpenCodeConfig(
        server_url=os.getenv("OPENCODE_SERVER_URL", "http://localhost:4096"),
        password=os.getenv("OPENCODE_SERVER_PASSWORD", ""),
    )
    
    async with OpenCodeClient(config) as client:
        acoes = [
            "Crie um arquivo calculadora.py com funcoes soma, subtrai, multiplica, divide",
            "Crie testes unitarios para a calculadora em test_calculadora.py",
            "Execute os testes e mostre o resultado",
        ]
        
        for i, prompt in enumerate(acoes):
            print(f"\n--- Acao {i+1}/{len(acoes)} ---")
            resultado = await client.execute(
                prompt=prompt,
                session_title=f"ciclo-completo-{i}",
                model="nvidia/nemotron-3-ultra",
            )
            
            print(f"   Sucesso: {resultado.success}")
            if resultado.error:
                print(f"   Erro: {resultado.error}")
            else:
                print(f"   Output: {resultado.output[:150]}...")
            
            await asyncio.sleep(1)


async def teste_permissao():
    """Testa fluxo de permissao (precisa acao que peça permissao)."""
    print("\n" + "=" * 60)
    print("TESTE 5: Permissao (executa comando que pode pedir permissao)")
    print("=" * 60)
    
    config = OpenCodeConfig(
        server_url=os.getenv("OPENCODE_SERVER_URL", "http://localhost:4096"),
        password=os.getenv("OPENCODE_SERVER_PASSWORD", ""),
    )
    
    async with OpenCodeClient(config) as client:
        # Prompt que pode gerar permissao (ex: bash, write file)
        resultado = await client.execute(
            prompt="Crie um arquivo teste_permissao.txt com conteudo 'teste'",
            model="nvidia/nemotron-3-ultra",
        )
        
        print(f"Resultado: success={resultado.success}")
        if resultado.error:
            print(f"   Erro: {resultado.error}")
        
        # Coletar eventos por alguns segundos
        print("Coletando eventos SSE por 3s (verificar permissoes)...")
        await asyncio.sleep(3)
        
        events = await client.get_events(max_events=20)
        print(f"Eventos recebidos: {len(events)}")
        for ev in events:
            print(f"  - {ev['type']}: {ev['payload'].get('tool', 'N/A')}")


async def main():
    print("TESTES DE INTEGRACAO HARMONIA <-> OPENCODE")
    print("=" * 60)
    print(f"Server URL: {os.getenv('OPENCODE_SERVER_URL', 'http://localhost:4096')}")
    print()
    
    testes = [
        ("Conexao basica", teste_conexao_basica),
        ("Execucao simples", teste_execucao_simples),
        ("Shell direto", teste_shell_direto),
        ("Eventos SSE", teste_eventos_sse),
        ("Ciclo completo", teste_ciclo_completo),
        ("Permissao", teste_permissao),
    ]
    
    for nome, teste_fn in testes:
        try:
            await teste_fn()
        except Exception as e:
            print(f"FALHOU: {nome} - {e}")
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print("TESTES CONCLUIDOS")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())