#!/usr/bin/env python3
"""Teste direto do braço (grafo → executor → OpenCode → filesystem) sem daemon HTTP."""
import asyncio
import sys
sys.path.insert(0, '.')

from harmonia.graph.build import criar_estado_inicial, compilar_com_checkpoint


async def test_braco():
    plano = {
        "plano_id": "teste-braco-direto",
        "fundamentos": [{"id": "f1", "descricao": "Verificar braco real", "prioridade": 10}],
        "etapas": [{
            "descricao": "Criar arquivo de teste",
            "fundamentos_ids": ["f1"],
            "acoes_propostas": [{
                "tipo": "editar_arquivo",
                "descricao": "Criar /tmp/teste_harmonia.txt com conteudo harmonia funcionou",
                "parametros": {"arquivo": "/tmp/teste_harmonia.txt", "conteudo": "harmonia funcionou"},
                "risco": "baixo",
                "raciocinio": "Teste de braco real",
                "reversivel": True
            }]
        }]
    }
    
    state = criar_estado_inicial(
        plano_id="teste-braco-direto",
        fundamentos=plano["fundamentos"],
        etapas=plano["etapas"],
        dial="soninho"
    )
    
    graph, conn = await compilar_com_checkpoint()
    config = {"configurable": {"thread_id": "teste-braco-direto"}}
    
    print("=== EXECUTANDO GRAFO DIRETO (sem daemon HTTP) ===")
    resultado = await graph.ainvoke(state, config=config)
    await conn.close()
    
    execs = resultado.get("acoes_executadas", [])
    pendentes = resultado.get("acoes_pendentes", [])
    fila = resultado.get("fila_aprovacao", [])
    logs = resultado.get("log_rastro", [])
    
    print(f"Acoes executadas: {len(execs)}")
    print(f"Acoes pendentes: {len(pendentes)}")
    print(f"Fila aprovacao: {len(fila)}")
    print(f"Logs: {len(logs)}")
    
    for e in execs:
        print(f"  - {e.get('tipo')}: {e.get('descricao')} -> {e.get('status')}")
        if e.get("erro"):
            print(f"    ERRO: {e['erro']}")
        if e.get("resultado"):
            print(f"    resultado: {e['resultado']}")
    
    for log in logs:
        print(f"  LOG: {log.get('causa')} -> antes: {log.get('estado_antes')} -> depois: {log.get('estado_depois')}")
    
    return resultado


if __name__ == "__main__":
    asyncio.run(test_braco())