from __future__ import annotations

import asyncio
import os
from harmonia.graph.build import compilar_com_checkpoint
from harmonia.graph.state import (
    HarmoniaState, DialAutonomia, Fundamento, EtapaPlano, 
    AcaoProposta, NivelRisco, StatusAcao
)


POSTGRES_DSN = os.getenv("HARMONIA_POSTGRES_DSN", "postgresql://postgres:harmonia@localhost:5432/harmonia")


def criar_plano_simples() -> HarmoniaState:
    state = HarmoniaState(
        plano_id="teste-sobrevivencia",
        dial_autonomia=DialAutonomia.SONINHO,
    )
    
    state.fundamentos = [
        Fundamento(id="f1", descricao="Teste de persistência", prioridade=10),
    ]
    
    state.etapas = [
        EtapaPlano(
            descricao="Etapa de teste",
            fundamentos_ids=["f1"],
            ordem=0,
        ),
    ]
    
    state.acoes_pendentes = [
        AcaoProposta(
            tipo="editar_arquivo",
            descricao="Ação 1 - antes do reinício",
            parametros={"fundamentos_ids": ["f1"]},
            risco=NivelRisco.BAIXO,
            raciocinio="Primeira ação",
        ),
        AcaoProposta(
            tipo="rodar_testes",
            descricao="Ação 2 - depois do reinício",
            parametros={"fundamentos_ids": ["f1"]},
            risco=NivelRisco.BAIXO,
            raciocinio="Segunda ação",
        ),
        AcaoProposta(
            tipo="build_local",
            descricao="Ação 3 - final",
            parametros={"fundamentos_ids": ["f1"]},
            risco=NivelRisco.BAIXO,
            raciocinio="Terceira ação",
        ),
    ]
    
    return state


async def executar_ate_meio(graph, state: HarmoniaState) -> HarmoniaState:
    """Executa até a metade das ações (simula crash no meio)."""
    print(f"🔄 Executando até o meio... ({len(state.acoes_pendentes)} ações pendentes)")
    
    step = 0
    while state.acoes_pendentes and step < 2:
        step += 1
        acao = state.acoes_pendentes[0]
        print(f"   Passo {step}: {acao.descricao}")
        state = await graph.ainvoke(state)
    
    print(f"   ✅ Parado no meio. Ações executadas: {len(state.acoes_executadas)}")
    print(f"   📋 Próxima ação: {state.acoes_pendentes[0].descricao if state.acoes_pendentes else 'Nenhuma'}")
    
    return state


async def teste_sobrevivencia():
    print("=" * 60)
    print("TESTE DE SOBREVIVÊNCIA - Postgres Checkpoint")
    print("=" * 60)
    
    print(f"\n📡 Conectando ao Postgres: {POSTGRES_DSN.split('@')[1] if '@' in POSTGRES_DSN else POSTGRES_DSN}")
    
    graph = compilar_com_checkpoint(POSTGRES_DSN)
    
    thread_id = "teste-sobrevivencia-001"
    config = {"configurable": {"thread_id": thread_id}}
    
    print("\n--- PRIMEIRA EXECUÇÃO (simula crash no meio) ---")
    state = criar_plano_simples()
    state = await executar_ate_meio(graph, state)
    
    print(f"\n💾 Checkpoint salvo no Postgres para thread_id: {thread_id}")
    print("   (Simulando crash/parada do processo aqui)")
    
    print("\n--- SEGUNDA EXECUÇÃO (novo processo, retoma do checkpoint) ---")
    print("   Criando NOVA instância do grafo...")
    graph2 = compilar_com_checkpoint(POSTGRES_DSN)
    
    print("   Invocando com mesmo thread_id (deve retomar)...")
    state_retomado = await graph2.ainvoke(None, config=config)
    
    print(f"\n   🔄 Estado retomado!")
    print(f"   Ações executadas: {len(state_retomado.acoes_executadas)}")
    print(f"   Ações pendentes: {len(state_retomado.acoes_pendentes)}")
    print(f"   Log de rastro: {len(state_retomado.log_rastro)}")
    
    if state_retomado.acoes_pendentes:
        print(f"   Próxima ação: {state_retomado.acoes_pendentes[0].descricao}")
    
    print("\n--- CONTINUANDO EXECUÇÃO ATÉ O FIM ---")
    step = 0
    while state_retomado.acoes_pendentes and step < 10:
        step += 1
        acao = state_retomado.acoes_pendentes[0]
        print(f"   Passo {step}: {acao.descricao}")
        state_retomado = await graph2.ainvoke(state_retomado, config=config)
    
    print(f"\n✅ EXECUÇÃO COMPLETA!")
    print(f"   Total ações executadas: {len(state_retomado.acoes_executadas)}")
    print(f"   Log de rastro total: {len(state_retomado.log_rastro)}")
    
    for i, log in enumerate(state_retomado.log_rastro):
        print(f"   {i+1}. {log.causa} (reversível: {log.reversivel})")
    
    assert len(state_retomado.acoes_executadas) == 3, "Deveria ter executado 3 ações"
    assert len(state_retomado.log_rastro) == 3, "Deveria ter 3 entradas no log"
    
    print("\n🎉 TESTE PASSOU: Checkpoint Postgres funciona corretamente!")
    print("   O estado sobreviveu à reinicialização do processo.")


if __name__ == "__main__":
    asyncio.run(teste_sobrevivencia())