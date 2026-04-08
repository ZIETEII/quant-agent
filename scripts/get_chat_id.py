import asyncio, aiohttp

async def get_chat_id():
    TOKEN = '8674652186:AAE89hG3kW4389XGm_J4sWpe2I1BtospJJo'
    url = f'https://api.telegram.org/bot{TOKEN}/getUpdates'
    async with aiohttp.ClientSession() as s:
        r = await s.get(url)
        result = await r.json()
        print('OK:', result.get('ok'))
        updates = result.get('result', [])
        if not updates:
            print('\nNO HAY MENSAJES.')
            print('Envia /start al bot en Telegram: t.me/ZieteToken_bot')
            print('Luego vuelve a correr este script.')
            return
        seen = set()
        for u in updates:
            msg = u.get('message', {})
            chat = msg.get('chat', {})
            cid = chat.get('id')
            if cid and cid not in seen:
                seen.add(cid)
                print(f'Chat ID: {cid}  |  Nombre: {chat.get("first_name")} {chat.get("last_name","")}  |  Mensaje: {msg.get("text")}')

asyncio.run(get_chat_id())
