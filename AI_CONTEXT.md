# Quant Agent - Contexto del Proyecto (AI Reference)

Este documento sirve como referencia rápida para que cualquier IA entienda la arquitectura, estado actual y reglas del proyecto Quant Agent.

## 📌 1. Visión General
**Quant Agent** es un bot de trading algorítmico automatizado en la blockchain de Solana, diseñado para operar tanto tokens establecidos (Bluechips) como nuevos listados (Sniper). Combina análisis de momento técnico con un modelo de Machine Learning (ML Scope Gate) para filtrar operaciones y utiliza **Jupiter v6 API** para cotizaciones ultra-realistas.

*   **Lenguaje/Framework:** Python (asyncio) + FastAPI
*   **Interfaz de Usuario (UI):** Vanilla HTML/CSS/JS servido directamente por FastAPI.
*   **Despliegue:** VPS privado, Docker Swarm (red `logvoxNet`), Portainer, GitHub Actions.
*   **Bases de Datos:**
    *   *Activa:* Supabase auto-hospedado en el VPS (`xxsupabase.logvox.com`) para Usuarios, Perfiles y Manejo de Fondos.
    *   *Temporal/Trades:* Historial y transacciones del bot gestionadas internamente.

---

## 🏗️ 2. Arquitectura de Software

El proyecto se estructura en varios módulos clave (dentro de `/Volumes/LOGVOX/Bot/src/`):

1.  **`main.py`:** El corazón del sistema. Ejecuta el lazo de eventos principal (`engine_loop`), define todas las rutas de la API (FastAPI) y sirve la interfaz web.
2.  **`exchange/jupiter_client.py`:** Encargado de hablar con la blockchain y Jupiter. Todo el **Paper Trading** ocurre aquí, capturando cotizaciones precisas y enrutamiento real para simular operaciones 100% fidedignas sin gastar SOL real.
3.  **`db/supabase_client.py`:** Módulo recientemente añadido para manejar Auth y Base de Datos con el Supabase del VPS. Funciones como `sign_in`, `add_funds`, y `get_profile`.
4.  **`web/templates/`:** Contiene `index.html` (dashboard analítico principal) y `login.html` (pantalla de autenticación estilo "terminal premium" dividida en 2 paneles).
5.  **`docker-compose.yml`:** Configuración de servicios Docker. Usa Traefik para reverse proxy y se conecta a la red `logvoxNet`.

---

## ⚙️ 3. Lógica de Trading (Reglas Críticas)

1.  **Modos de Trading:**
    *   **Bluechip (`BC_*`):** Configurado para top tokens. Toma ganancias (TP) y Stop Loss (SL) moderado.
    *   **Sniper (`SN_*`):** Configurado para memecoins. Umbrales de seguridad y momento modificados, *slippage* alto, y se guarda una porción (*moonbag*).
    *   **Paper Trading (`PAPER_TRADING_MODE=True`):** Usa cálculos exactos de *price impact* sobre mainnet, ajusta los balances virtuales correctamente. `SOLANA_RPC_URL` siempre apunta a mainnet-beta, pero en simulación no se transmiten firmas.

2.  **Warm-up Phase (Fase de Calentamiento):**
    *   Cuando el bot enciende, espera **5 minutos** obligatorios de sólo lectura (escaneando).
    *   **NO** se realizan compras en este periodo bajo ninguna circunstancia.
    *   Propósito: El agente necesita leer el mercado, recolectar datos y preparar las primeras entradas inteligentemente.

3.  **Mínimo de Operaciones (Floor Breach):**
    *   El sistema persigue un portafolio de **15 operaciones abiertas**.
    *   Hay un "piso" (*floor*) de **7 operaciones**.
    *   Si el número de trades abiertos es menor a 7, el bot entra en **Modo Agresivo**: relaja los umbrales de Score Técnico (20% más permisivos) y reduce la exigencia del filtro de ML (baja de 0.50 a 0.40) para recuperar volumen de mercado rápidamente.

---

## 🔐 4. Autenticación y Supabase

El sistema está migrado para usar **autenticación híbrida en base de datos**:

*   El *backend* de autenticación ahora depende de un servidor Supabase en el mismo VPS.
*   **Usuarios:** Existe un esquema en PostgreSQL (`public.profiles`, `public.fund_transactions`) con RLS y triggers automáticos al crearse desde `auth.users`.
*   **Login:** La página visual `/login` recopila email y contraseña, le pide al bot que verifique con Supabase y recibe de vuelta un `access_token`. El bot además asigna una cookie local (`qsession`) para el rooteo convencional dentro de las plantillas web.
*   **Fondos:** Los administradores pueden añadir fondos a un perfil mediante `add_funds` que inyecta capital virtual y guarda rastro del PnL separado.

---

## 🚀 5. Pipeline de CI/CD (Despliegue)

*   **GitHub Actions (`.github/workflows/docker.yml`):**
    1.  Al hacer *push* a `main`, el pipeline empaca todo y lo manda a GitHub Container Registry (`ghcr.io/zieteii/quant-agent`).
    2.  Hace `push` de dos *tags*: `:latest` y `:<sha_commit_id>`.
    3.  Llama al **Webhook de Portainer** (`PORTAINER_WEBHOOK`) vía cURL con flag `--insecure` usando modo tolerante a fallos (`continue-on-error: true`).
    4.  Espera 40 segundos e intenta consultar `/api/state` como Health Check.

*Importante:* Existen problemas esporádicos en los que el Webhook de Portainer de Docker Swarm no actualiza si sólo la etiqueta *latest* cambió, he ahí el uso de identificadores SHA.

---

## 💡 Instrucciones para el Agente que lea esto:

1.  **NO DESHAGAS LA LÓGICA VIGENTE:** Si modificas el `engine_loop` (el motor del bot), asegúrate de **mantener** los contadores de la fase de calentamiento (`warmup`) y la comprobación de los 7 trades mínimos (*floor logic*).
2.  **CONEXIONES AL VPS:** En archivos YAML o de configuración, ten el mente que el bot está en la red de Docker Subred (`logvoxNet`). Si va a enviar un llamado a Supabase, el hostname interno es usualmente `http://kong:8000` y la BD directo a `postgresql://postgres:pass@db:5432/postgres`.
3.  **UI/UX CSS:** Todo el front se maneja sin frameworks tipo Tailwind a no ser que sea específicamente requerido. Es puro CSS (glassmorphism flex, acentos verdes ciberpunk, glow redial) dentro del mismo componente `HTML`.
