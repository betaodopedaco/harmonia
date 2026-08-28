#!/usr/bin/env python3
"""Teste de persistência: processo morre e retoma do checkpoint."""
import asyncio
import json
import sys
from pathlib import Path
from langgraph.types import Command

sys.path.insert(0, str(Path(__file__).parent.parent))

from harmonia.graph.build import criar_estado_inicial, compilar_com_checkpoint


async def test_persistencia():
    with open('plano_aprovacao.json', 'r', encoding='utf-8-sig') as f:
        plano = json.load(f)
    
    plano_id = plano['plano_id']
    thread_id = f'teste-persistencia-{plano_id}'
    
    state = criar_estado_inicial(
        plano_id=plano_id,
        fundamentos=plano['fundamentos'],
        etapas=plano['etapas'],
        dial='soninho',
    )
    
    graph, conn = await compilar_com_checkpoint()
    config = {'configurable': {'thread_id': thread_id}}
    
    # Primeira execução - deve pausar no interrupt
    print('=== PRIMEIRA EXECUÇÃO (deve pausar) ===')
    resultado1 = await graph.ainvoke(state, config=config)
    
    execs1 = len(resultado1.get('acoes_executadas', []))
    pend1 = len(resultado1.get('acoes_pendentes', []))
    fila1 = len(resultado1.get('fila_aprovacao', []))
    print(f'Executadas: {execs1}')
    print(f'Pendentes: {pend1}')
    print(f'Fila: {fila1}')
    
    await conn.close()
    
    if fila1 == 0:
        print('❌ FALHA: não pausou no interrupt')
        return False
    
    # Simular processo novo - reconectar e resume
    print()
    print('=== SEGUNDA EXECUÇÃO (novo processo, resume) ===')
    graph2, conn2 = await compilar_com_checkpoint()
    
    resposta = {'resposta': 'Deploy da versão 1.2.3 em produção', 'aprovado': True}
    resultado2 = await graph2.ainvoke(Command(resume=resposta), config=config)
    
    execs2 = len(resultado2.get('acoes_executadas', []))
    pend2 = len(resultado2.get('acoes_pendentes', []))
    fila2 = len(resultado2.get('fila_aprovacao', []))
    log2 = len(resultado2.get('log_rastro', []))
    print(f'Executadas: {execs2}')
    print(f'Pendentes: {pend2}')
    print(f'Fila: {fila2}')
    print(f'Log: {log2}')
    
    await conn2.close()
    
    if execs2 > execs1:
        print()
        print('✅ PERSISTÊNCIA FUNCIONA! Estado sobreviveu à reinicialização do processo.')
        return True
    else:
        print()
        print('❌ PERSISTÊNCIA FALHOU! Estado não retomou.')
        return False


if __name__ == '__main__':
    ok = asyncio.run(test_persistencia())
    sys.exit(0 if ok else 1)