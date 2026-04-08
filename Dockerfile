FROM python:3.12-slim

# Evitar escritura de bytecode y force stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependencias del sistema necesarias para compilar librerías (cryptography / solders / base58)
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    libssl-dev \
    cargo \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Solo copio los requirimientos mínimos necesarios para correr el agente
COPY requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt
RUN pip install --no-cache-dir "fastapi[all]" uvicorn aiohttp requests "solana" "solders" "base58" jinja2 slowapi python-dotenv numpy pandas scikit-learn psycopg2-binary

# Copio el resto del código
COPY . .

# Exponer el puerto
EXPOSE 8000

ENV PYTHONPATH="/app/src"

# Archivo de start por defecto
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
