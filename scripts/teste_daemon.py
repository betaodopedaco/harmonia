#!/usr/bin/env python3
"""Teste completo do daemon rodando servidor em background."""
import asyncio
import json
import sys
import httpx
sys.path.insert(0, '.')

async def test_daemon_completo():
    from harmonia.daemon import HarmoniaDaemon
    
    daemon = HarmoniaDaemon(port=8084)
    
    # Iniciar servidor em background
    server_task = asyncio.create_task(
        asyncio.to_thread(daemon.run)
    )
    
    try:
        # Aguardar servidor subir - usar health check
        for i in range(20):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.get('http://localhost:8084/health', timeout=1.0)
                    if resp.status_code == 200:
                        print('Servidor pronto!')
                        break
            except:
                pass
            await asyncio.sleep(0.5)
        else:
            print("Timeout aguardando servidor")
            return
        
        # Carregar plano
        with open('plano_aprovacao.json', 'r', encoding='utf-8-sig') as f:
            plano = json.load(f)
        
        thread_id = 'teste-daemon-123'
        
        # Submeter plano
        async with httpx.AsyncClient() as client:
            print('=== SUBMETENDO PLANO ===')
            resp = await client.post(
                'http://localhost:8084/plano',
                json={'plano': plano, 'dial': 'soninho', 'thread_id': thread_id},
                timeout=30.0
            )
            print(f'Status: {resp.status_code}')
            print(f'Response: {resp.json()}')
            
            # Se pausou, aprovar
            data = resp.json()
            if data.get('status') == 'pausado':
                print()
                print('=== APROVANDO ===')
                resp2 = await client.post(
                    'http://localhost:8084/aprovar',
                    json={
                        'thread_id': thread_id,
                        'resposta': {'resposta': 'Deploy da versão 1.2.3 em produção', 'aprovado': True}
                    },
                    timeout=30.0
                )
                print(f'Status: {resp2.status_code}')
                print(f'Response: {resp2.json()}')
            
            # Ver status final
            print()
            print('=== STATUS FINAL ===')
            resp3 = await client.get(f'http://localhost:8084/status/{thread_id}')
            print(f'Status: {resp3.status_code}')
            print(f'Response: {resp3.json()}')
    
    finally:
        # Parar servidor
        import os
        import signal
        os.kill(os.getpid(), signal.SIGTERM)
        await asyncio.sleep(0.5)

asyncio.run(test_daemon_completo())