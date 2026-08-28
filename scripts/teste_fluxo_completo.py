#!/usr/bin/env python3
"""
Teste do fluxo completo Harmonia em processo unico.
Fluxo: plano -> classificacao -> interrupt -> resume -> execucao

Uso: python -m scripts.teste_fluxo_completo
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from harmonia.graph.build import compilar_sem_checkpoint, criar_estado_inicial
from harmonia.graph.state import HarmoniaState, DialAutonomia, SolicitacaoAprovacao
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command


async def executar_fluxo_completo(plano_path: str = None):
    print("=" * 60)
    print("TESTE FLUXO COMPLETO HARMONIA (processo unico)")
    print("=" * 60)
    
    if plano_path is None:
        plano_path = Path(__file__).parent.parent / "plano_aprovacao.json"
    else:
        plano_path = Path(plano_path)
    with open(plano_path, 'r', encoding='utf-8-sig') as f:
        plano = json.load(f)
    
    plano_id = plano["plano_id"]
    print(f"\n1. Plano: {plano_id}")
    
    state = criar_estado_inicial(
        plano_id=plano_id,
        fundamentos=plano["fundamentos"],
        etapas=plano["etapas"],
        dial=DialAutonomia.SONINHO.value,
    )
    
    acoes = state.get("acoes_pendentes", [])
    print(f"2. Estado: {len(acoes)} acao(es)")
    if acoes:
        a = acoes[0]
        print(f"   -> {a.get('tipo')}: {a.get('descricao')}")
    
    workflow = compilar_sem_checkpoint()
    checkpointer = InMemorySaver()
    graph = workflow.compile(checkpointer=checkpointer)
    
    thread_id = f"teste-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    config = {"configurable": {"thread_id": thread_id}}
    
    print(f"\n3. Executando (thread: {thread_id})...")
    resultado = await graph.ainvoke(state, config=config)
    
    print(f"4. Resultado: tipo={type(resultado).__name__}")
    
    if not isinstance(resultado, dict):
        print(f"   ERRO: resultado nao e dict")
        return False
    
    execs = resultado.get("acoes_executadas", [])
    pend = resultado.get("acoes_pendentes", [])
    fila = resultado.get("fila_aprovacao", [])
    log = resultado.get("log_rastro", [])
    
    print(f"   executadas={len(execs)}, pendentes={len(pend)}, fila={len(fila)}, log={len(log)}")
    
    if fila:
        sol = fila[-1]
        print(f"   Solicitacao: id={sol.get('id')}, status={sol.get('status')}, qualificada={sol.get('confirmacao_qualificada')}")
        msg = sol.get("mensagem", "")
        print(f"   Mensagem: {msg[:120]}...")
    
    if not fila:
        print(f"\n   Sem fila de aprovacao")
        if execs:
            print(f"   OK: {len(execs)} acao(es) executada(s) diretamente")
            return True
        print(f"   FALHA: nada aconteceu")
        return False
    
    print(f"\n5. Testando RESUME com Command(resume=...)...")
    
    resposta = {
        "resposta": "Deploy da versão 1.2.3 em produção",
        "aprovado": True,
        "usuario": "teste",
        "timestamp": datetime.now().isoformat(),
    }
    
    try:
        resultado2 = await graph.ainvoke(
            Command(resume=resposta),
            config=config
        )
        
        print(f"6. Resultado do resume: tipo={type(resultado2).__name__}")
        
        if isinstance(resultado2, dict):
            execs2 = resultado2.get("acoes_executadas", [])
            pend2 = resultado2.get("acoes_pendentes", [])
            fila2 = resultado2.get("fila_aprovacao", [])
            log2 = resultado2.get("log_rastro", [])
            msg = resultado2.get("mensagem_final")
            
            print(f"   executadas={len(execs2)}, pendentes={len(pend2)}, fila={len(fila2)}, log={len(log2)}")
            
            if msg:
                print(f"   mensagem_final: {msg}")
            
            if len(execs2) > len(execs):
                print(f"\n   SUCESSO! Acoes executadas: {len(execs)} -> {len(execs2)}")
                for a in execs2:
                    print(f"   - {a.get('tipo')}: {a.get('status')}")
                return True
            
            if len(pend2) == 0 and len(fila2) == 0:
                print(f"   Pendentes e fila vazias - possivelmente executou tudo")
                return True
            
            print(f"   Fluxo continuou mas acoes nao aumentaram")
            return False
        else:
            print(f"   Resultado inesperado: {resultado2}")
            return False
    
    except Exception as e:
        print(f"   ERRO no resume: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    import sys
    plano_path = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        sucesso = await executar_fluxo_completo(plano_path)
        print("\n" + "=" * 60)
        if sucesso:
            print("TESTE PASSOU")
        else:
            print("TESTE FALHOU")
        print("=" * 60)
        return 0 if sucesso else 1
    except Exception as e:
        print(f"\nERRO GERAL: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
