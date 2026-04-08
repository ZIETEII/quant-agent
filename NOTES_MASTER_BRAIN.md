# Notas de Optimización del Ecosistema de Agentes

## Problema Resuelto: Los clones parecían inicializar con saldos "irreales" o operar "solos".
El ecosistema estaba programado por defecto de manera inteligente: cuando el contenedor Portainer se "reiniciaba" (Re-deploy o Restart), el bot se conectaba a Supabase para cargar la persistencia y salvar tu trabajo, en lugar de resetear tu balance. 
Por eso:
1. Al reiniciar sin purgar la base de datos, siempre revivía el historial de trades pasados ($184.79 para Turtle) porque el bot no es amnésico.
2. Al ejecutar el "Cold Start" (Inyectar Capital), el Bot *SÍ* borra todo, **PERO** antes inmediatamente convertía el motor a `ON`, lo que hacía que los clones compraran su cuota apenas veían los tokens escaneados (bajando tu balance en menos de 5 segundos) y aparentaban haber operado solos mientras tú cerrabas o recargabas la pestaña principal.

## Modificaciones Implementadas 
### 1. Motor Inactivo en Cold Start
- Archivo: `src/main.py` -> `api_inject_capital()`
- Se desactivó el auto-arranque. Al "Inyectar Capital", el bot inyecta el balance en memoria y en Postgres, pero **permanece apagado**. Esto protege el capital cero-estado hasta que el humano dé el "Start".

### 2. Sincronización Front-end (UI)
- Archivo: `index.html` (o render de clone dashboard)
- El mensaje fijo del header *"Motor algorítmico escaneando 3 fuentes..."* se va a mantener en el Hero banner informativo (que explica qué hace el motor), pero abajo el tag de estado de los clones dirá explícitamente "AGENTE APAGADO" cuando la llave principal esté OFF.
- El saldo del Inversión es **0.00** siempre que `active_trades` esté limpio (en RAM y SQLite).

## Guía de Edición y Referencia Principal
- ¿Dónde vive el `lifespan` y el arranque? `src/main.py` -> `@asynccontextmanager async def lifespan()`
- ¿Dónde se limpia SQLite Supabase y `app_state` y RAM de Clones? `src/main.py` -> `api_inject_capital()` 
- ¿Dónde gestionan el balance los Clones localmente? `src/clones/base_clone.py` -> `load_from_db()` (carga la copia estricta post DB)
- ¿Dónde se refleja visualmente esto en UI? `web/templates/index.html` -> Función `fetchState()` y `renderSidebar()`.

¡Este sistema ahora está 100% blindado para un Cold Start real y no operará nada a tus espaldas!
