#!/bin/bash
# ─────────────────────────────────────────────────
#  Quant Agent Solana v1.2 — Reset Completo
#  Borra toda la memoria y reinicia desde cero
# ─────────────────────────────────────────────────

echo ""
echo "🗑️  Reiniciando Quant Agent Solana desde CERO..."

# Detener bot activo
lsof -ti:8000 | xargs kill -9 2>/dev/null
pkill -f "python bot_agente.py" 2>/dev/null
sleep 1

# Borrar memoria y logs
rm -f quant_memory.db quant_ml_memory.db agent.log
echo "   ✓ Bases de datos eliminadas"

# Limpiar pycache
find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null
echo "   ✓ Cache de Python limpiada"

echo ""
echo "🟢  Arrancando sesión fresca..."
echo "──────────────────────────────────────────────────"

source .venv/bin/activate 2>/dev/null || true
python bot_agente.py
