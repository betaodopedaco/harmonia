#!/usr/bin/env python3
"""Teste interrupt/resume com @dataclass (como HarmoniaState)"""
import asyncio
from dataclasses import dataclass, field
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command


@dataclass
class MyState:
    values: list = field(default_factory=list)
    message: str = ""


def node_a(state: MyState) -> dict:
    print("[A] executando")
    return {"values": state.values + [1], "message": "depois de A"}

def node_b(state: MyState) -> dict:
    print("[B] pausando...")
    resposta = interrupt("Aguarde aprovacao")
    print(f"[B] resume com: {resposta}")
    return {"values": state.values + [2], "message": f"aprovado: {resposta}"}

def node_c(state: MyState) -> dict:
    print("[C] finalizando")
    return {"values": state.values + [3], "message": "feito"}


async def main():
    g = StateGraph(MyState)
    g.add_node("a", node_a)
    g.add_node("b", node_b)
    g.add_node("c", node_c)
    g.set_entry_point("a")
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    g.add_edge("c", END)
    
    checkpointer = InMemorySaver()
    graph = g.compile(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "dataclass-test"}}
    initial = MyState()
    
    print("--- Execucao 1 (pausa em B) ---")
    r1 = await graph.ainvoke(initial, config=config)
    print(f"Resultado: {r1}")
    
    snap = await graph.aget_state(config)
    print(f"Snapshot next: {snap.next}")
    
    print("\n--- Resume ---")
    r2 = await graph.ainvoke(Command(resume="OK pelo user"), config=config)
    print(f"Resultado: {r2}")
    
    if isinstance(r2, dict):
        vals = r2.get("values", [])
    else:
        vals = r2.values
    if vals and len(vals) == 3:
        print("\nSUCESSO com dataclass!")
        return True
    print("\nFALHA")
    return False

if __name__ == "__main__":
    ok = asyncio.run(main())
    exit(0 if ok else 1)
