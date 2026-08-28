#!/usr/bin/env python3
"""
Debug do resume Harmonia - passo a passo.
"""
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from harmonia.graph.build import compilar_sem_checkpoint, criar_estado_inicial
from harmonia.graph.state import HarmoniaState, DialAutonomia, SolicitacaoAprovacao
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command


async def main():
    plano_path = Path(__file__).parent.parent / "plano_aprovacao.json"
    with open(plano_path, 'r', encoding='utf-8-sig') as f:
        plano = json.load(f)
    
    state = criar_estado_inicial(
        plano_id=plano["plano_id"],
        fundamentos=plano["fundamentos"],
        etapas=plano["etapas"],
        dial=DialAutonomia.SONINHO,
    )
    
    workflow = compilar_sem_checkpoint()
    checkpointer = InMemorySaver()
    graph = workflow.compile(checkpointer=checkpointer)
    
    thread_id = f"debug-{datetime.now().strftime('%H%M%S')}"
    config = {"configurable": {"thread_id": thread_id}}
    
    print("=== EXECUCAO 1 ===")
    result = await graph.ainvoke(state, config=config)
    
    if isinstance(result, dict):
        fila = result.get("fila_aprovacao", [])
        pend = result.get("acoes_pendentes", [])
        execs = result.get("acoes_executadas", [])
        
        print(f"execs={len(execs)}, pend={len(pend)}, fila={len(fila)}")
        
        if fila:
            sol = fila[-1]
            print(f"Solicitacao type: {type(sol)}")
            if isinstance(sol, SolicitacaoAprovacao):
                print(f"  id={sol.id}, status={sol.status}")
            elif isinstance(sol, dict):
                print(f"  id={sol.get('id')}, status={sol.get('status')}")
        
        # Check snapshot
        snap = await graph.aget_state(config)
        print(f"Snapshot next: {snap.next}")
        print(f"Snapshot values keys: {list(snap.values.keys()) if isinstance(snap.values, dict) else type(snap.values)}")
        
        # Check __interrupt__ in result
        if "__interrupt__" in result:
            interrupts = result["__interrupt__"]
            print(f"Interrupts in result: {len(interrupts)}")
            for intr in interrupts:
                print(f"  value={intr.value}")
        
        print("\n=== RESUME ===")
        resposta = {
            "resposta": "deploy da versao 1.2.3 em producao",
            "aprovado": True,
        }
        
        print(f"Enviando resume...")
        result2 = await graph.ainvoke(Command(resume=resposta), config=config)
        print(f"Resume retornou: type={type(result2).__name__}")
        
        if isinstance(result2, dict):
            execs2 = result2.get("acoes_executadas", [])
            pend2 = result2.get("acoes_pendentes", [])
            fila2 = result2.get("fila_aprovacao", [])
            log2 = result2.get("log_rastro", [])
            msg = result2.get("mensagem_final")
            
            print(f"execs={len(execs2)}, pend={len(pend2)}, fila={len(fila2)}, log={len(log2)}")
            if msg:
                print(f"msg_final: {msg}")
            
            if len(execs2) > len(execs):
                print("\nSUCESSO!")
                return True
            elif len(execs2) == len(execs):
                print("Mesmo numero de execs")
                # Maybe it worked but executed and removed from pending?
                if len(pend2) == 0 and len(fila2) == 0:
                    print("Pendentes e fila vazias - possivelmente executou")
                    return True
            else:
                print("Algo errado")
                print(json.dumps({k: str(v)[:300] for k,v in result2.items()}, indent=2, default=str))
                return False
    else:
        print(f"Result type: {type(result)}")
        return False
    
    return False

if __name__ == "__main__":
    ok = asyncio.run(main())
    print(f"\nFinal: {'OK' if ok else 'FALHOU'}")
    exit(0 if ok else 1)
