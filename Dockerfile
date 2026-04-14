FROM python:3.10-slim

# Evitar escritura de bytecode y force stdout
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependencias del sistema necesarias para compilar librerías
# cargo/rustc necesarios para solders/driftpy si no hay wheel pre-built
RUN apt-get update && apt-get install -y \
    build-essential \
    pkg-config \
    libssl-dev \
    curl \
    && curl https://sh.rustup.rs -sSf | sh -s -- -y \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.cargo/bin:${PATH}"

# Solo copio los requirimientos mínimos necesarios para correr el agente
COPY requirements-test.txt .
RUN pip install --no-cache-dir -r requirements-test.txt

# Instalar dependencias core primero (tienen wheels pre-built)
RUN pip install --no-cache-dir \
    "fastapi[all]" uvicorn aiohttp requests jinja2 slowapi python-dotenv \
    numpy pandas scikit-learn psycopg2-binary

# Instalar Solana/Drift en paso separado (puede necesitar compilación Rust)
RUN pip install --no-cache-dir "solana" "solders" "base58" "anchorpy"
RUN pip install --no-cache-dir driftpy

# Copio el resto del código
COPY . .

# Exponer el puerto
EXPOSE 8000

ENV PYTHONPATH="/app/src"

# Archivo de start por defecto
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
