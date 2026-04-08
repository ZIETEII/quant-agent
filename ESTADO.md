# 🧠 ESTADO DEL PROYECTO — Quant Agent AI v1.2 (Online Edition)

> **Última auditoría:** 2026-04-07  
> **Refactorización Core:** Transición a Entorno de Producción  
> **Stack:** Python 3.12 · FastAPI · PostgreSQL (Supabase) · Docker Swarm · Jupiter v6 API  
> **Estado:** Bot activo en `https://quant.logvox.com` — Paper Trading Mode / Live Trading con despliegue CI/CD

---

## 📊 RESUMEN EJECUTIVO

| Módulo | Archivo(s) | Estado | % | Detalles |
|--------|-----------|--------|---|----------|
| 🧠 Motor Principal | `bot_agente.py` | ✅ Producción | 95% | Manejo de loops y endpoints estabilizado |
| 💾 Base de Datos | `db.py` | ✅ Producción | 100% | **Migración Full a PostgreSQL** (Supabase) + Mock de fallback local |
| 🚀 Deploy / CI-CD | `.github/workflows` | ✅ Producción | 100% | Imagen auto-construida en GHCR y montada en Portainer Swarm |
| 📊 Dashboard PWA | `templates/index.html` | ✅ Responsive | 100% | UX mejorado para pantallas móviles, Neu-Glass estabilizado |
| 💱 Exchange Client | `jupiter_client.py` | ✅ Dual Mode | 95% | Slippage configurado, soporte Live/Paper |
| 🔍 Token Scanner | `token_scanner.py` | ✅ Triple-Flujo | 95% | Bluechip, Trending y Sniper operativos |
| 🧬 Clones (3) | `clones/*.py` | ✅ Independientes | 95% | Ninja, Turtle, Trend funcionales |
| 📡 Bus de Señales RT| `clone_signals.py` | ✅ Activo | 100% | Con buffer rotativo web e interconectado |
| 🤖 ML Predictor | `ai/ml_predictor.py` | ⚠️ Entrenando | 70% | Falla la intersección de predicciones predict->engine |

**Total estimado del sistema: ~92% completado.** Alcanzamos madurez de Producción.

---

## ✅ LO QUE TENEMOS (Producción v1.2) 

### 1. 🚀 INFRAESTRUCTURA DE PRODUCCIÓN (¡NUEVO!)
Hemos abandonado las pruebas 100% locales en mac para habilitar concurrencia escalable.
- **Docker Swarm + Portainer**: El agente ahora está envuelto en una imagen de contenedor en GHCR (`ghcr.io/zieteii/quant-agent`).
- **Base de Datos Continua**: Hemos reemplazado SQLite con **PostgreSQL hospedado nativo en Supabase**. Esto permite que el contenedor se destruya sin perder historial de trading.
- **CI/CD Automático**: Con cada `git push` a `main`, GitHub empaqueta la imagen. 
- **Protocolo de Recuperación**: Archivo `PROTOCOLO_PRODUCCION.md` e inyección de URL del servidor a través de Traefik para correr bajo SSL nativo `https://quant.logvox.com`.
- **Failsafe DB Mock**: Archivo `db_mock.py` para levantar la plataforma web local incuso cuando no hay PostgreSQL instalado en MacOS.

### 2. 🧠 MOTOR PRINCIPAL — `bot_agente.py` (1,677 líneas)
El servidor FastAPI asíncrono tiene tres loops incesantes:
- **Engine Loop (5s)** — Escáner de mercado, señales de clones y validaciones.
- **Price Loop** — Actualización al segundo de las inversiones retenidas de Jupiter.
- **Report Loop** — Capturas analíticas cíclicas.
*Protegido por autenticación básica.*

### 3. 📱 UI/UX MOBILE RESPONSIVO (¡NUEVO!)
La arquitectura visual en celulares fue completamente refactorizada:
- Elementos laterales (KPIs) migrados a flujo de cuadrícula apilable verticalmente (1 fr).
- Contenedores de las tablas habilitados con gestos nativos horizontales (`overflow-x: auto`) sin chocar con elementos del sistema.

### 4. 🛡️ RISK MANAGEMENT — Nivel Institucional
- 🔴 Circuit Breaker: Ante 3 caídas consecutivas = contracción agresiva de Slitppage y SL.
- 📐 Kelly Dinámico: Ponderación de riesgo de cuenta inteligente.
- 😱 Sentiment Gate: Aborta compras al detectar 'Extreme Fear'.
- 📉 Trailing Stop y Moonbag para captar olas de explosión.

### 5. 🔍 TOKEN SCANNER Y MULTI-AGENTE
**Flujos Activos:** Bluechip (grandes tokens), Trending (DexScreener), Sniper (memecoins minadas hace < 60 min).
**Comite Multitudinario:** `Ninja (Scalper)`, `Turtle (Holding)`, `Trend (Momentum)`.
Los agentes envían ráfagas via `CloneSignalBus` con feeds inyectados directamente al UI con Emojis visuales para validación humana rápida.

---

## ❌ EL CAMINO AL 100% (Roadmap Pendiente en Vivo)

Al tener nuestro software alojado remotamente en Portainer, nuestras prioridades giran hacia la auto-ejecución pura.

### 🔴 PRIORIDAD ALTA

#### 1. 🤖 ENGANCHE FINAL DEL CEREBRO MACHINE LEARNING
**Estado:** Modelo entrena en un sandbox pero no filtra de manera estricta los trades diarios.
**Problema:** `ml_predictor.py` tiene la infraestructura lista pero no estamos invocando la directriz `predict_trade_probability()` en el pipeline caliente de `bot_agente.py > should_enter`.
**Solución:** Mapear en caliente los datos e inyectar un threshold duro (ej. Si AI dice que probabilidad de pérdida > 50%, veto instantáneo de la memoria base).

#### 2. 🔄 GRACEFUL RECOVERY ON-CHAIN
**Estado:** No implementado robustamente en la V2 del modelo vivo.
**Problema:** Si le das a "Update Service" en Portainer con un volumen de riesgo retenido, el agente podría perder rastro de la posición abierta sobre la cadena al reiniciarse la memoria del balance base o los threads del Jupiter Client.
**Solución:** Hacer que al nacer en el contenedor, el engine corra un scan en la wallet real (`HSAeFg7SW2KwVv...`), reclame monedas varadas y reanude los Stop Loss.

#### 3. 🎯 AUTO-EJECUCIÓN BURSÁTIL POR SEÑALES CLONADAS
**Estado:** Únicamente Log visual (Console log).
**Problema:** Si `Trend` y `Ninja` detectan sincronización y radian `CONVICTION` o `HOT_TRADE` (+5% bajo 3 mins), el Agente los aplaude visualmente en el UI, pero NO ataca el mercado con pólvora extra. 
**Solución:** Incorporar función autómata `_auto_buy_from_signal_injection()` para premiar económicamente detecciones fuertes.

### 🟡 PRIORIDAD MEDIA

#### 4. 📡 NOTIFICACIONES EXTERNAS EN ESTADO CRÍTICO
- Migración robusta a un BOT de Telegram que mande notificaciones directas ("Agente inyectando 5 SOL a Token_X").
- Alertadores sobre cambios subyacentes de liquidez extrema o Circuit Breakers activados para accionar remotamente por móvil.

#### 5. 💹 BACKTESTER CUALITATIVO EN VIVO
- Consolidación del Pipeline DB -> ML en el VPS para que corra el backtesting durante madrugadas o domingos y exporte una nueva versión del RandomForest semanalmente en base a las operaciones documentadas en Supabase Postgres.

---

## 📅 CHANGELOG v1.2 (2026-04-07) - The Online Mainframe Update

```diff
+ [PRODUCCIÓN] Despliegue en Portainer ejecutando "ghcr.io/zieteii/quant-agent:latest".
+ [PRODUCCIÓN] Integración HTTPS con dominio "quant.logvox.com" activo permanentemente.
+ [DB] Aniquilación de SQLite por PostgreSQL de Supabase.
+ [DB] Se implementó db_mock.py para no dañar entornos de prueba sin Postgres instalado.
+ [FIX] Responsive de Dashboard para móviles perfeccionado (Total Equity + Tablas Touchpad).
+ [FIX] Reset.py purga ahora de forma atómica y remota la base PostgreSQL en el reinicio en caliente.
```

> ⚠️ **Aviso de Responsabilidad para Modificaciones V1.2:** A partir de ahora los cambios entran directo en el código remoto empujados por el pipeline local. Es obligatorio cuidar sintaxis de Postgres en todo momento y no confiar en inMem local tests para interacciones de `db.py`.
