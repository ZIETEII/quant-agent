#!/bin/bash
# 🧪 Test Runner for Quant Agent

echo "🚀 Iniciando Testing Suite del Agente Solana..."
export PYTHONPATH=$(pwd)
pytest tests/ -v
echo "✅ Test Suite Completada."
