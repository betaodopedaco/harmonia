from __future__ import annotations

import asyncio
from harmonia.graph.build import compilar_sem_checkpoint, criar_estado_inicial
from harmonia.graph.state import DialAutonomia, Fundamento, EtapaPlano, AcaoProposta, NivelRisco


def criar_exemplo_plano() -> dict:
    return {
        "plano_id": "exemplo-001",
        "fundamentos": [
            {"id": "f1", "descricao": "Manter qualidade de código alta", "prioridade": 10},
            {"id": "f2", "descricao": "Entregar até sexta-feira", "prioridade": 8},
            {"id": "f3", "descricao": "Não gastar mais que $50 em APIs", "prioridade": 9},
        ],
        "etapas": [
            {
                "descricao": "Implementar feature X",
                "fundamentos_ids": ["f1", "f2"],
                "acoes_propostas": [
                    {
                        "tipo": "editar_arquivo",
                        "descricao": "Criar arquivo feature_x.py",
                        "parametros": {"arquivo": "feature_x.py", "fundamentos_ids": ["f1"]},
                        "raciocinio": "Implementação inicial da feature",
                        "impacto_estimado": "Criação de arquivo local",
                        "reversivel": True,
                    },
                    {
                        "tipo": "rodar_testes",
                        "descricao": "Rodar testes unitários",
                        "parametros": {"fundamentos_ids": ["f1"]},
                        "raciocinio": "Verificar qualidade",
                        "impacto_estimado": "Execução local de testes",
                        "reversivel": True,
                    },
                    {
                        "tipo": "build_local",
                        "descricao": "Build local para verificar compilação",
                        "parametros": {"fundamentos_ids": ["f1"]},
                        "raciocinio": "Verificar que compila",
                        "impacto_estimado": "Build local",
                        "reversivel": True,
                    },
                ],
            },
            {
                "descricao": "Deploy em staging",
                "fundamentos_ids": ["f2", "f3"],
                "acoes_propostas": [
                    {
                        "tipo": "deploy",
                        "descricao": "Deploy em ambiente staging",
                        "parametros": {"ambiente": "staging", "fundamentos_ids": ["f2", "f3"]},
                        "raciocinio": "Validar em ambiente próximo à produção",
                        "impacto_estimado": "Deploy em ambiente compartilhado",
                        "reversivel": True,
                        "rollback": "Rollback deploy anterior no staging",
                    },
                ],
            },
            {
                "descricao": "Deploy em produção",
                "fundamentos_ids": ["f2", "f3"],
                "acoes_propostas": [
                    {
                        "tipo": "deploy_producao",
                        "descricao": "Deploy em produção",
                        "parametros": {"fundamentos_ids": ["f2", "f3"]},
                        "raciocinio": "Entrega final para usuários",
                        "impacto_estimado": "Deploy irreversível em produção",
                        "reversivel": False,
                        "rollback": "Reverter para versão anterior via blue-green",
                    },
                ],
            },
        ],
    }


async def rodar_demo():
    print("=" * 60)
    print("HARMONIA - Demo de Execução do Grafo")
    print("=" * 60)
    
    plano = criar_exemplo_plano()
    
    print(f"\n📋 Plano: {plano['plano_id']}")
    print(f"📌 Fundamentos: {len(plano['fundamentos'])}")
    for f in plano['fundamentos']:
        print(f"   - {f['descricao']} (prioridade: {f['prioridade']})")
    print(f"📦 Etapas: {len(plano['etapas'])}")
    
    total_acoes = sum(len(e.get('acoes_propostas', [])) for e in plano['etapas'])
    print(f"⚡ Ações totais: {total_acoes}")
    
    for modo_nome, dial in [("Soninho", DialAutonomia.SONINHO), ("Ligadão", DialAutonomia.LIGADAO)]:
        print(f"\n{'='*60}")
        print(f"🔄 MODO: {modo_nome} ({dial.value})")
        print(f"{'='*60}")
        
        state = criar_estado_inicial(
            plano_id=plano["plano_id"],
            fundamentos=plano["fundamentos"],
            etapas=plano["etapas"],
            dial=dial,
        )
        
        graph = compilar_sem_checkpoint()
        
        print(f"\n🚀 Iniciando execução...")
        print(f"   Ações pendentes: {len(state.acoes_pendentes)}")
        
        step = 0
        while state.acoes_pendentes and step < 20:
            step += 1
            acao = state.acoes_pendentes[0]
            print(f"\n   Passo {step}: {acao.tipo} - {acao.descricao[:50]}")
            print(f"   Risco: {acao.risco.value}")
            
            state = await graph.ainvoke(state)
            
            if state.criterio_parada_seguranca:
                print(f"   ⛔ PARADA DE SEGURANÇA: {state.mensagem_final}")
                break
            
            if state.mensagem_final:
                print(f"   📝 {state.mensagem_final}")
        
        print(f"\n   ✅ Concluído: {len(state.acoes_executadas)} ações executadas")
        print(f"   📊 Log de rastro: {len(state.log_rastro)} entradas")
        print(f"   🔍 Sinais autoavaliação: {len(state.sinais_autoavaliacao)}")
        
        for sinal in state.sinais_autoavaliacao:
            status = "⚠️ DIVERGÊNCIA" if sinal.divergencia_detectada else "✅ OK"
            print(f"      {status}: {sinal.descricao} (confiança: {sinal.confianca:.0%})")


if __name__ == "__main__":
    asyncio.run(rodar_demo())