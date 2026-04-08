# 🧠 ESTADO DEL PROYECTO — Quant Agent AI v1.2

> **Última auditoría:** 2026-04-07  
> **Código Python:** ~5,400 líneas | **Frontend:** ~3,500 líneas (190KB HTML/CSS/JS)  
> **Stack:** Python 3.12 · FastAPI · SQLite WAL · Jupiter v6 API · Solana Mainnet  
> **Estado:** Bot activo en `localhost:8000` — Paper Trading Mode con señales en tiempo real

---

## 📊 RESUMEN EJECUTIVO

| Módulo | Archivo(s) | Líneas | Estado | % |
|--------|-----------|--------|--------|---|
| 🧠 Motor Principal | `bot_agente.py` | 1,677 | ✅ Producción | 95% |
| 💾 Base de Datos | `db.py` | 583 | ✅ Producción | 100% |
| 💱 Exchange Client | `exchange/jupiter_client.py` | 534 | ✅ Dual Mode | 95% |
| 🔍 Token Scanner | `scanner/token_scanner.py` | 760 | ✅ Triple-Flujo | 95% |
| 🧬 Clones (3 agentes) | `clones/*.py` | 706 | ✅ Independientes | 95% |
| 📡 Bus de Señales RT | `ai/clone_signals.py` | 237 | ✅ **NUEVO v1.2** | 90% |
| 🧠 Feedback Mutante | `ai/clone_brain_feedback.py` | 195 | ✅ Funcional | 90% |
| 📐 Kelly Criterion | `ai/kelly_criterion.py` | 130 | ✅ Dinámico | 100% |
| 🌡️ Sentiment Analysis | `ai/sentiment.py` | 184 | ✅ Multi-fuente | 95% |
| 🤖 ML Predictor | `ai/ml_predictor.py` | 104 | ⚠️ Desconectado | 70% |
| 📊 Dashboard PWA | `templates/index.html` | 3,537 | ✅ Neu-Glass | 100% |
| 📑 Report Generator | `report_generator.py` | 275 | ✅ Funcional | 90% |
| 🧪 Test Suite | `tests/*.py` | ~200 | ⚠️ Tier 1 básico | 30% |
| 🚀 Deploy / DevOps | — | — | ❌ Falta | 10% |

**Total estimado del sistema: ~87% completado.**

---

## ✅ LO QUE TENEMOS (Producción)

### 1. 🧠 MOTOR PRINCIPAL — `bot_agente.py` (1,677 líneas)

El corazón del sistema. Un servidor FastAPI asíncrono con tres loops paralelos:

- **Engine Loop** — Ciclo cada 5s que escanea tokens, evalúa entrada/salida, gestiona trades y procesa señales de clones.
- **Price Loop** — Actualiza precios en vivo de posiciones activas via Jupiter/DexScreener.
- **Report Loop** — Genera snapshots periódicos del estado del portafolio.

**14 Endpoints API activos:**
| Endpoint | Función |
|----------|---------|
| `/api/state` | Estado completo del bot (KPIs, configuración, posiciones) |
| `/api/equity` | Serie temporal de equity para gráficas |
| `/api/chart/{symbol}` | Mini-charts OHLCV por token |
| `/api/multi-chart` | Datos multi-gráfica (4 tokens simultáneos) |
| `/api/clones` | Estado de los 3 clones + sparklines de rendimiento |
| `/api/signals` | **NUEVO v1.2** — Feed de señales en tiempo real |
| `/api/brain-events` | Log de eventos del cerebro (decisiones, aprendizaje) |
| `/api/scanner-feed` | Tokens detectados por el scanner en el último ciclo |
| `/api/top-tokens` | Top Solana tokens por market cap (live) |
| `/api/config/override` | Modificar parámetros en caliente |
| `/api/reset` | Destruir memoria y reiniciar |
| `/` | Dashboard PWA principal |

**Seguridad:** HTTPBasicAuth con credenciales desde `.env`.

---

### 2. 🛡️ RISK MANAGEMENT — Nivel Institucional

| Protección | Mecanismo | Ubicación |
|-----------|-----------|-----------|
| 🔴 Circuit Breaker | 3 pérdidas consecutivas → SL de activas se contrae 50% | `bot_agente.py` |
| 📊 Exposición Global | Máx 50% del balance en posiciones abiertas | `bot_agente.py` |
| 💧 Liquidez Mínima | Aborta si trade > 2.5% de USD líquidos del token | `bot_agente.py` |
| 🔗 Anti-Correlación | Bloquea tokens del mismo sector/raíz semántica | `bot_agente.py` |
| 😱 Sentiment Gate | Fear & Greed en "Extreme Fear" → multiplicador = 0 (veta compras) | `ai/sentiment.py` |
| 📐 Kelly Dinámico | Sizing matemático desde la 3ª operación | `ai/kelly_criterion.py` |
| 📉 Trailing Stop | Protege ganancias flotantes con trailing % | `bot_agente.py` |
| ⏳ Dead Timer | Cierra posiciones sin movimiento tras N minutos | `bot_agente.py` |
| 🌙 Moonbag | Al tocar TP, vende parcial y deja % corriendo libre | `bot_agente.py` |

---

### 3. 💱 EXCHANGE CLIENT — `exchange/jupiter_client.py` (534 líneas)

Conexión directa a Solana Mainnet via Jupiter v6 API:

| Modo | Descripción |
|------|-------------|
| **Paper Trading** | Simula trades con precios reales, slippage ficticio y balance virtual |
| **Live Trading** | Firma transacciones vía `solders`, envía a RPC, confirma en cadena |

- Soporta compra/venta con slippage configurado por estrategia
- Obtiene quotes de Jupiter v6 con priorización de rutas
- Wallet balance query via SPL Token Program
- Gas estimation y transaction confirmation

---

### 4. 🔍 TOKEN SCANNER — `scanner/token_scanner.py` (760 líneas)

Triple flujo de detección:

| Flujo | Objetivo | Filtros |
|-------|---------|---------|
| 💎 **Bluechip** | Tokens establecidos (JUP, WIF, RAY, BONK...) | Min score 35, TP 8%, SL 5% |
| 📈 **Trending** | Volumen en picada (DexScreener trending) | Momentum score + safety |
| 🔫 **Sniper** | Tokens nuevos < 60 min de edad | Min momentum 55, safety 35, TP 25%, SL 12% |

- Score compuesto: `momentum` (velocidad de precio), `safety` (liquidez, holders, verificación)
- Datos en vivo de DexScreener API + Jupiter API
- Anti-duplicación: no re-scannea tokens ya en posición
- Slot reservation por estrategia (5 Bluechip + 5 Sniper)

---

### 5. 🧬 SISTEMA MULTI-AGENTE — `clones/` (706 líneas)

Tres sub-agentes autónomos con capital paper independiente:

| Clon | Personalidad | Ciclo | Riesgo | Tokens |
|------|-------------|-------|--------|--------|
| 🥷 **Ninja** (Scalper) | Agresivo, TP alto, SL ajustado | 15 días | Alto | Diversificados |
| 🐢 **Turtle** (Conservador) | Cauteloso, SL amplio, trailing bajo | 30 días | Bajo | Bluechips |
| 🚀 **Trend** (Inercia) | Sigue momentum, trailing alto | 90 días | Medio | Trending |

**Comportamiento:**
- Cada clon hereda los trades del cerebro vía `sync_entries()` pero aplica sus propios filtros `should_enter()`
- Capital independiente (arrancan con fracción del balance del padre)
- Al final de un ciclo, reportan ROI vs cerebro y pueden mutar parámetros del padre si lo superan

---

### 6. 📡 BUS DE SEÑALES EN TIEMPO REAL — `ai/clone_signals.py` (237 líneas) — **NUEVO v1.2**

> **Antes (v1.1):** Los clones solo hablaban con el cerebro al final de cada ciclo (15-90 días).  
> **Ahora (v1.2):** Los clones emiten señales cada 5 segundos, sincronizados con el scanner del cerebro.

**Tipos de señal:**

| Señal | Emoji | Trigger | Impacto en Cerebro |
|-------|-------|---------|-------------------|
| `DISCOVERY` | 📡 | Clon tiene token que cerebro no | Alerta visual + candidato a compra |
| `HOT_TRADE` | 🔥 | Token sube +5% en < 3 minutos | Señal urgente de entrada |
| `CONVICTION` | 🎯 | 2+ clones en el mismo token | Señal fuerte — alta confianza |
| `ALPHA` | 🧬 | Clon supera PnL del cerebro | Adoptar sus parámetros |
| `EXIT_WARN` | ⚠️ | Clon cerró con pérdida > 5% | Posible riesgo sistémico |

**Flujo técnico:**
```
Scanner (5s) → Clones procesan → CloneSignalBus.emit() → Brain._process_signals()
                                       ↓
                              /api/signals → Dashboard feed en tiempo real
```

**Buffer rotativo:** Mantiene últimas 100 señales en memoria, con stats por tipo y TTL automático.

---

### 7. 🤖 INTELIGENCIA ARTIFICIAL — `ai/` (850 líneas total)

| Módulo | Función | Estado |
|--------|---------|--------|
| `kelly_criterion.py` | Sizing óptimo de posición usando win-rate y R:R | ✅ Activo |
| `sentiment.py` | Fear & Greed Index + Funding Rates + análisis multi-fuente | ✅ Activo |
| `clone_brain_feedback.py` | Mutación genética: si clon > cerebro → herencia de parámetros | ✅ Activo |
| `ml_predictor.py` | RandomForest para predecir probabilidad de éxito de un trade | ⚠️ Entrenándose, no conectado al engine |

---

### 8. 📊 DASHBOARD PWA — `templates/index.html` (3,537 líneas · 190KB)

Interfaz interactiva single-page con estética **Neu-Glass** premium:

| Tab | Contenido |
|-----|-----------|
| 📋 **Portfolio** | Posiciones activas con PnL flotante, historial de trades, mini-charts |
| 📈 **Gráficas** | 4 charts TradingView Lightweight simultáneos con datos OHLCV reales |
| 🧬 **Clones** | Cards de cada clon con sparklines, PnL, y modal de detalle al hacer click |
| 🧠 **Brain** | Feed de eventos del cerebro (entradas, salidas, aprendizaje, Fear/Greed) |
| 🔍 **Scanner** | Feed en vivo de tokens evaluados + Top 10 Solana tokens |
| ⚙️ **Config** | **Rediseñado v1.2** — Hero header, progress bars, señales RT, sliders dinámicos |

**Características técnicas:**
- PWA instalable (manifest.json + service worker)
- Polling inteligente: estado cada 1.5s, clones cada 3s, charts cada 5s, señales cada 5s
- Audio feedback: WebAudio API con bips en transacciones
- Sidebar fija con KPIs del sistema (equity, PnL, gas SOL, win rate)
- Responsive: funciona en desktop y mobile

---

### 9. 💾 BASE DE DATOS — `db.py` (583 líneas)

SQLite en modo WAL (Write-Ahead Logging) para rendimiento asíncrono:

| Tabla | Propósito |
|-------|-----------|
| `trades` | Historial completo de operaciones (entry, exit, PnL) |
| `equity_snapshots` | Serie temporal de equity para gráficas |
| `ohlcv_cache` | Cache de velas por token para charts inline |
| `agent_state` | Estado persistente del cerebro (ciclo, parámetros) |
| `clone_state` | Estado independiente de cada clon (balance, PnL, ciclo) |
| `clone_memory` | Tokens aprendidos por clones en ciclos anteriores |
| `brain_events` | Log de decisiones del cerebro con timestamps |
| `config_overrides` | Parámetros modificados en caliente desde el dashboard |
| `leaderboard` | Rankings históricos de performance (cerebro + clones) |

---

### 10. 🧪 TEST SUITE — `tests/` (Tier 1)

| Test | Qué valida |
|------|-----------|
| `test_kelly.py` | Criterio de Kelly + edge cases (WR negativo, 0 trades) |
| `test_sentiment.py` | Clasificación semántica (Extreme Fear → Neutral → Greed) |
| `test_scanner.py` | Score validators + filtros de calidad |
| `test_db.py` | Read/Write I/O con SQLite in-memory |

Ejecución: `./test_run.sh`

---

## 📐 ESTRUCTURA DE ARCHIVOS

```
Bot/
├── bot_agente.py              # 🧠 Motor principal (1,677 líneas)
├── db.py                      # 💾 Memoria persistente SQLite WAL
├── report_generator.py        # 📑 Generador de reportes Markdown
├── start.sh                   # 🚀 Script de arranque con checks
├── reset.sh                   # 🔄 Reset atómico (destruye DB + estado)
├── test_run.sh                # 🧪 Runner de tests automatizado
│
├── exchange/
│   └── jupiter_client.py      # 💱 Jupiter v6 (Paper + Live modes)
│
├── scanner/
│   └── token_scanner.py       # 🔍 Triple-flujo: Bluechip + Trending + Sniper
│
├── clones/
│   ├── base_clone.py          # 🧬 Clase base con lógica compartida (490 líneas)
│   ├── ninja.py               # 🥷 Scalper agresivo (15 días)
│   ├── turtle.py              # 🐢 Conservador (30 días)
│   └── trend.py               # 🚀 Seguidor de inercia (90 días)
│
├── ai/
│   ├── clone_signals.py       # 📡 Bus de señales en tiempo real (NUEVO v1.2)
│   ├── clone_brain_feedback.py # 🧬 Mutación genética padre ← hijo
│   ├── kelly_criterion.py     # 📐 Sizing óptimo de posiciones
│   ├── sentiment.py           # 🌡️ Fear & Greed + Funding Rates
│   ├── ml_predictor.py        # 🤖 RandomForest predictor (desconectado)
│   └── clones.py              # 📋 Registro de configuraciones de clones
│
├── templates/
│   └── index.html             # 📊 Dashboard PWA Neu-Glass (3,537 líneas)
│
├── static/
│   ├── style.css              # 🎨 Design system + animaciones
│   ├── manifest.json          # 📱 PWA manifest
│   └── sw.js                  # ⚡ Service Worker
│
├── tests/
│   ├── conftest.py            # Fixtures compartidos (SQLite in-memory)
│   ├── test_kelly.py          # Kelly Criterion validation
│   ├── test_sentiment.py      # Sentiment classification
│   ├── test_scanner.py        # Score + filter validation
│   └── test_db.py             # Database I/O tests
│
├── docs/                      # 📚 Documentación adicional
├── scripts/                   # 🔧 Scripts auxiliares
├── .env                       # 🔐 Credenciales (Jupiter key, RPC, auth)
├── quant_memory.db            # 💾 Base de datos activa
└── requirements-test.txt      # 📦 Dependencias de testing
```

---

## ❌ EL CAMINO AL 100% (Roadmap)

### 🔴 PRIORIDAD ALTA

#### 1. 🔄 GRACEFUL RECOVERY ON-CHAIN
**Estado:** No implementado  
**Problema:** Si el bot se cae en Live Mode, pierde posiciones abiertas en Solana.  
**Solución:** Módulo de arranque que scannee la wallet SPL, detecte tokens residuales, y reconstruya `active_trades` automáticamente.

#### 2. 🧠 ML PREDICTOR → ENGINE
**Estado:** Modelo entrena pero no filtra  
**Problema:** `ml_predictor.py` genera `predict_trade_probability()` pero nunca se llama antes de comprar.  
**Solución:** Inyectar antes de `should_enter()` — si probabilidad < 50%, abortar la compra.

#### 3. 🎯 AUTO-EJECUCIÓN DE SEÑALES
**Estado:** Solo loguea  
**Problema:** Las señales CONVICTION y HOT_TRADE se loguean pero el cerebro no compra automáticamente.  
**Solución:** Implementar `_auto_buy_from_signal()` para que señales de alta confianza disparen compras reales.

### 🟡 PRIORIDAD MEDIA

#### 4. 🧪 TESTING TIER 2 (E2E + CI/CD)
- End-to-End tests que simulen un viaje completo sin gastar llamadas reales
- GitHub Actions ejecutando `./test_run.sh` en cada commit

#### 5. 📡 WEBSOCKETS
- Reemplazar HTTP polling (1.5s-5s) por WebSocket bidireccional
- Reducir latencia de red ~80%

#### 6. 💹 BACKTESTER LOCAL
- Descargar velas históricas de 3+ días
- Simular estrategias offline sin quemar tiempo real
- Calibrar Kelly + scores sin riesgo

### 🟢 NICE TO HAVE

#### 7. 📱 NOTIFICACIONES PUSH
- Telegram bot para alertas de trades y señales CONVICTION

#### 8. 🐳 DEPLOY DOCKER
- Dockerfile + docker-compose para despliegue reproducible
- Variables de entorno seguras

---

## 📅 CHANGELOG v1.2 (2026-04-07)

```
[NUEVO] ai/clone_signals.py — Bus de señales en tiempo real (5 tipos)
[NUEVO] /api/signals endpoint — Feed de señales para dashboard
[NUEVO] Sección "Señales Clone → Cerebro" en Config tab con 4 KPI cards + feed
[MEJOR] Config tab rediseñado con estética Neu-Glass premium
[MEJOR] Progress bars con gradientes por tipo (TP=verde, SL=rojo, Score=azul)
[MEJOR] Hero header con badge LIVE TRADING
[MEJOR] Sliders dinámicos por clon (Ninja, Turtle, Trend)
[MEJOR] Jupiter API + Solana RPC con checks visuales ✓
[MEJOR] Clones tab con sparklines y modal de detalle
[MEJOR] Brain events con categorización visual
[FIX]   Importación scipy/numpy estabilizada
[FIX]   Balance correcto tras reset ($984.92 → $1000)
```

> ⚠️ **Nota:** La DB corre en modo WAL transaccional de alta velocidad. El sistema completo está diseñado para ráfagas institucionales extremas en Solana DEX.
