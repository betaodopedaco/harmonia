#!/usr/bin/env python3
"""Teste de validação da autoavaliação real - detecta divergência real."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from harmonia.graph.build import criar_estado_inicial, compilar_com_checkpoint


async def test_autoavaliacao_detecta_falha():
    """Teste: ação falha + fundamento qualidade -> deve detectar divergência."""
    
    plano = {
        "plano_id": "teste-autoavaliacao-divergencia",
        "fundamentos": [
            {"id": "f1", "descricao": "Qualidade do codigo deve ser mantida", "prioridade": 10},
        ],
        "etapas": [
            {
                "descricao": "Executar ação que falha",
                "fundamentos_ids": ["f1"],
                "acoes_propostas": [
                    {
                        "tipo": "editar_arquivo",
                        "descricao": "Tentar editar arquivo que vai falhar",
                        "parametros": {"fundamentos_ids": ["f1"]},
                        "risco": "baixo",
                        "raciocinio": "Teste de divergência",
                        "reversivel": True,
                    }
                ]
            }
        ]
    }
    
    plano_id = plano["plano_id"]
    thread_id = f"teste-autoavaliacao-{plano_id}"
    
    state = criar_estado_inicial(
        plano_id=plano_id,
        fundamentos=plano["fundamentos"],
        etapas=plano["etapas"],
        dial="soninho",
    )
    
    graph, conn = await compilar_com_checkpoint()
    config = {"configurable": {"thread_id": thread_id}}
    
    print("=== TESTE: Ação falha + fundamento qualidade ===")
    resultado = await graph.ainvoke(state, config=config)
    
    execs = resultado.get("acoes_executadas", [])
    sinais = resultado.get("sinais_autoavaliacao", [])
    
    print(f"Ações executadas: {len(execs)}")
    print(f"Sinais autoavaliação: {len(sinais)}")
    
    if sinais:
        sinal = sinais[-1]
        print(f"Divergência detectada: {sinal.get('divergencia_detectada')}")
        print(f"Descrição: {sinal.get('descricao')}")
        print(f"Confiança: {sinal.get('confianca')}")
        print(f"Requer pausa: {sinal.get('requer_pausa')}")
        
        if sinal.get("divergencia_detectada"):
            print("\n[OK] Autoavaliação detectou divergência corretamente (ação falhou).")
            await conn.close()
            return True
    
    print("\n[FALHA] Autoavaliação NÃO detectou divergência esperada.")
    await conn.close()
    return False


async def main():
    print("=" * 60)
    print("VALIDAÇÃO AUTOAVALIAÇÃO: Divergência real")
    print("=" * 60)
    ok = await test_autoavaliacao_detecta_falha()
    
    print()
    print("=" * 60)
    if ok:
        print("[OK] AUTOAVALIAÇÃO FUNCIONA - Detecta divergência real")
    else:
        print("[FALHA] AUTOAVALIAÇÃO NÃO FUNCIONA")
    print("=" * 60)
    
    return ok


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)