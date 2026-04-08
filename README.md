# Quant Agent Solana — v1.2

> **Motor de Inteligencia Artificial para Trading Autónomo en Solana DEX**  
> Red: Solana Mainnet · Exchange: Jupiter / Raydium / Pump.fun

---

## ¿Qué es esto?

Un ecosistema híbrido de agentes autónomos que operan en la red de **Solana** a través de DEX agnósticos. El sistema combina tres estrategias especializadas (DNA Clones) gestionadas por un Cerebro central que analiza el mercado, gestiona el riesgo y ejecuta swaps reales on-chain.

---

## Arquitectura

```
bot_agente.py          ← Cerebro Principal (Orquestrador)
│
├── exchange/
│   └── axiom_client.py   ← Motor de Ejecución (Jupiter Swap API + Firma on-chain)
│
├── ai/
│   ├── sentiment.py       ← Macro-termómetro (Fear & Greed + Funding Rate BTC)
│   ├── ml_predictor.py    ← Predictor ML de señales
│   ├── kelly_criterion.py ← Calculador de tamaño de posición (Kelly)
│   └── clone_brain_feedback.py ← Aprendizaje evolutivo de los clones
│
├── clones/
│   ├── base_clone.py      ← Lógica compartida de todos los clones
│   ├── 🐢 turtle.py       ← Conservador (TP bajo, SL estrecho)
│   ├── 🗡️ ninja.py        ← Agresivo / Scalper (alto riesgo)
│   └── 🌊 trend.py        ← Seguidor de tendencia (SL amplio)
│
├── scanner/
│   └── token_scanner.py   ← Scanner de oportunidades en Solana DEX
│
└── db.py                  ← Capa de persistencia SQLite
```

---

## Instalación

```bash
# 1. Clonar el repositorio
git clone https://github.com/tu-usuario/quant-agent-solana.git
cd quant-agent-solana

# 2. Crear entorno virtual
python3 -m venv .venv
source .venv/bin/activate  # macOS/Linux

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# → Editar .env con tus llaves reales (ver sección abajo)
```

---

## Configuración (`.env`)

```env
# ── Notificaciones ──
TELEGRAM_TOKEN=tu_token_de_telegram
TELEGRAM_CHAT_ID=tu_chat_id

# ── Solana Mainnet ──
SOLANA_WALLET_ADDRESS=tu_direccion_de_wallet
SOLANA_PRIVATE_KEY=tu_llave_privada_base58
SOLANA_RPC_URL=https://mainnet.helius-rpc.com/?api-key=TU_API_KEY

# ── Modo de Trading ──
PAPER_TRADING_MODE=False          # True = simulación | False = dinero real
VIRTUAL_BALANCE_SOL=2.0           # Solo aplica en modo simulación

# ── APIs ──
JUPITER_API_KEY=tu_api_key_de_jupiter
```

> ⚠️ **Nunca subas tu `.env` a GitHub.** Está protegido por `.gitignore`.

---

## Modo de Uso

```bash
# Arrancar el bot
./start.sh

# Reset completo (borra memoria y reinicia desde cero)
./reset.sh
```

El **Dashboard interactivo** se levanta automáticamente en:  
👉 `http://localhost:8000`

---

## Cómo Funciona el Live Trading

En modo `PAPER_TRADING_MODE=False`, el bot ejecuta swaps reales:

1. **Scanner** detecta tokens con alto momentum en Solana DEX
2. **Cerebro** evalúa señales de IA + análisis de sentimiento macro
3. **Jupiter Swap API** construye la ruta de swap óptima
4. **`axiom_client.py`** firma la transacción con tu llave privada usando `solders`
5. La transacción se emite a la **red Solana Mainnet** via RPC
6. La venta lee el balance exacto on-chain (`get_token_accounts_by_owner`) antes de cotizar

---

## DNA Shadow Clones

Cada clon gestiona su propio capital de forma independiente con perfiles de riesgo distintos:

| Clon | Perfil | Take Profit | Stop Loss | Horizonte |
|------|--------|-------------|-----------|-----------|
| 🐢 Turtle | Conservador | 8% | 5% | 30 días |
| 🗡️ Ninja | Agresivo/Scalper | 25% | 12% | 15 días |
| 🌊 Trend | Tendencia | 40%+ | 20% | 90 días |

---

## Requisitos de Sistema

- Python 3.10+
- `uv` o `pip` para gestión de paquetes
- Dependencias clave: `solana`, `solders`, `base58`, `aiohttp`, `fastapi`, `uvicorn`

---

## Seguridad

- Tu llave privada **nunca sale del servidor local**. Se firma localmente y solo la transacción firmada viaja a la red.
- Usa un **RPC privado** (Helius / Quicknode) para velocidad y sin rate limits en Mainnet.
- En producción, considera usar una **wallet dedicada** solo para el bot con capital limitado.

---

*Quant Agent Solana — Construido con Python · Jupiter · Solana*
