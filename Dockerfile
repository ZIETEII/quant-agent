FROM python:3.10-slim

# Evitar escritura de bytecode y force stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Solo copio los requirimientos mínimos necesarios para correr el agente
COPY requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt

# Instalar dependencias Python
# NOTA: driftpy se instala solo si se necesita live trading (lazy import en drift_client.py)
# En paper mode funciona sin driftpy usando precios de CoinGecko/Binance
RUN pip install --no-cache-dir \
    "fastapi[all]" uvicorn aiohttp requests jinja2 slowapi python-dotenv \
    numpy pandas scikit-learn psycopg2-binary \
    "solana" "solders" "base58"

# Copio el resto del código
COPY . .

# Exponer el puerto
EXPOSE 8000

ENV PYTHONPATH="/app/src"

# Archivo de start por defecto
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
