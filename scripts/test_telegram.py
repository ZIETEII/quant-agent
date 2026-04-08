import asyncio, aiohttp

async def test():
    TOKEN = '8674652186:AAE89hG3kW4389XGm_J4sWpe2I1BtospJJo'
    CHAT  = '8603163934'
    url = f'https://api.telegram.org/bot{TOKEN}/sendMessage'
    payload = {
        'chat_id': CHAT,
        'text': (
            '🤖 <b>QuantAgent Pro</b> — Conexión verificada!\n\n'
            'Recibirás alertas cuando el bot:\n'
            '🟢 <b>COMPRE</b> una posición\n'
            '🎉 <b>TAKE PROFIT</b> sea alcanzado\n'
            '🚨 <b>STOP LOSS</b> sea activado\n\n'
            '✅ Todo configurado correctamente.'
        ),
        'parse_mode': 'HTML'
    }
    async with aiohttp.ClientSession() as s:
        r = await s.post(url, json=payload)
        result = await r.json()
        print('HTTP Status:', r.status)
        print('Enviado OK:', result.get('ok'))
        if not result.get('ok'):
            print('Error:', result.get('description'))

asyncio.run(test())
