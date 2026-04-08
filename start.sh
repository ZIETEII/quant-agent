#!/bin/bash
# ─────────────────────────────────────────────────
#  Quant Agent Solana v1.2 — Script de Arranque
# ─────────────────────────────────────────────────

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   🚀  QUANT AGENT SOLANA  v1.2               ║"
echo "║   DEX: Jupiter · Red: Solana Mainnet         ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# Matar instancias previas para liberar el puerto
lsof -ti:8000 | xargs kill -9 2>/dev/null
pkill -f "python bot_agente.py" 2>/dev/null
sleep 1

echo "🟢  Iniciando el Cerebro Principal..."
echo "📊  Dashboard disponible en: http://localhost:8000"
echo "──────────────────────────────────────────────────"

source .venv/bin/activate 2>/dev/null || true
python bot_agente.py
