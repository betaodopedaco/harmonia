#!/usr/bin/env python3
"""
Teste MINIMO de interrupt/resume com LangGraph.
Isola o problema: o interrupt() + Command(resume=...) funciona com InMemorySaver?
"""
import asyncio
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command
from typing import TypedDict, Annotated
from operator import add


class SimpleState(TypedDict):
    values: Annotated[list[int], add]
    message: str


def node_a(state: SimpleState) -> SimpleState:
    print("[node_a] Executando...")
    return {"values": [1], "message": "depois de A"}

def node_b(state: SimpleState) -> SimpleState:
    print("[node_b] Pausando para aprovacao...")
    resposta = interrupt("Aguarde aprovacao")
    print(f"[node_b] Resposta recebida: {resposta}")
    return {"values": [2], "message": f"aprovado por: {resposta}"}

def node_c(state: SimpleState) -> SimpleState:
    print("[node_c] Finalizando...")
    return {"values": [3], "message": "feito"}


def build_graph():
    g = StateGraph(SimpleState)
    g.add_node("a", node_a)
    g.add_node("b", node_b)
    g.add_node("c", node_c)
    g.set_entry_point("a")
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    g.add_edge("c", END)
    return g


async def main():
    print("=" * 50)
    print("TESTE MINIMO INTERRUPT/RESUME")
    print("=" * 50)
    
    checkpointer = InMemorySaver()
    graph = build_graph().compile(checkpointer=checkpointer)
    
    config = {"configurable": {"thread_id": "test-001"}}
    initial = {"values": [], "message": ""}
    
    print("\n--- Primeira execucao (deve pausar em B) ---")
    result1 = await graph.ainvoke(initial, config=config)
    print(f"Resultado 1: {result1}")
    
    print("\n--- Verificando estado salvo ---")
    state_snapshot = await graph.aget_state(config)
    print(f"Estado salvo: {state_snapshot.values}")
    print(f"Tasks pendentes: {state_snapshot.next}")
    
    print("\n--- Resume com Command(resume=...) ---")
    result2 = await graph.ainvoke(
        Command(resume="aprovado pelo usuario"),
        config=config
    )
    print(f"Resultado 2: {result2}")
    
    if result2.get("values") and len(result2["values"]) == 3:
        print("\nSUCESSO! interrupt/resume funciona!")
        return True
    else:
        print("\nFALHA")
        return False


if __name__ == "__main__":
    ok = asyncio.run(main())
    exit(0 if ok else 1)
