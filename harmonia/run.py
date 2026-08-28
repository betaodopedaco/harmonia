#!/usr/bin/env python3
"""
CLI entry point para Harmonia.
Uso: python -m harmonia.run plano.json
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from harmonia.graph.build import criar_estado_inicial, compilar_com_checkpoint


async def executar_plano(plano_path: str, dial: str = "soninho", thread_id: str = None):
    with open(plano_path, 'r', encoding='utf-8-sig') as f:
        plano = json.load(f)
    
    plano_id = plano.get("plano_id", Path(plano_path).stem)
    thread_id = thread_id or plano_id
    
    print(f"[PLANO] {plano_id}")
    print(f"[DIAL] {dial}")
    print(f"[THREAD] {thread_id}")
    
    state = criar_estado_inicial(
        plano_id=plano_id,
        fundamentos=plano["fundamentos"],
        etapas=plano["etapas"],
        dial=dial,
    )
    
    graph, conn = await compilar_com_checkpoint()
    
    print(f"[INICIANDO] Execucao...")
    print(f"   Acoes pendentes: {len(state.get('acoes_pendentes', []))}")
    
    config = {"configurable": {"thread_id": thread_id}}
    try:
        resultado = await graph.ainvoke(state, config=config)
    finally:
        await conn.close()
    
    acoes_executadas = resultado.get("acoes_executadas", [])
    acoes_pendentes = resultado.get("acoes_pendentes", [])
    log_rastro = resultado.get("log_rastro", [])
    sinais_autoavaliacao = resultado.get("sinais_autoavaliacao", [])
    mensagem_final = resultado.get("mensagem_final")
    criterio_parada_seguranca = resultado.get("criterio_parada_seguranca", False)
    
    print(f"\n{'='*50}")
    print(f"[OK] EXECUCAO CONCLUIDA")
    print(f"{'='*50}")
    print(f"   Acoes executadas: {len(acoes_executadas)}")
    print(f"   Acoes pendentes: {len(acoes_pendentes)}")
    print(f"   Log de rastro: {len(log_rastro)} entradas")
    print(f"   Autoavaliacoes: {len(sinais_autoavaliacao)}")
    
    if mensagem_final:
        print(f"   Mensagem: {mensagem_final}")
    
    if criterio_parada_seguranca:
        print(f"   [AVISO] PARADA DE SEGURANCA acionada")
    
    for sinal in sinais_autoavaliacao:
        divergencia = sinal.get("divergencia_detectada", False)
        descricao = sinal.get("descricao", "")
        confianca = sinal.get("confianca", 0)
        status = "[AVISO] DIVERGENCIA" if divergencia else "[OK] OK"
        print(f"   {status}: {descricao} (confianca: {confianca:.0%})")
    
    return resultado


def main():
    if len(sys.argv) < 2:
        print("Uso: python -m harmonia.run <plano.json> [--dial soninho|ligadao] [--thread-id ID]")
        sys.exit(1)
    
    plano_path = sys.argv[1]
    dial = "soninho"
    thread_id = None
    
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--dial" and i + 1 < len(sys.argv):
            dial = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == "--thread-id" and i + 1 < len(sys.argv):
            thread_id = sys.argv[i + 1]
            i += 2
        else:
            i += 1
    
    if not os.path.exists(plano_path):
        print(f"[ERRO] Arquivo nao encontrado: {plano_path}")
        sys.exit(1)
    
    asyncio.run(executar_plano(plano_path, dial, thread_id))


if __name__ == "__main__":
    main()