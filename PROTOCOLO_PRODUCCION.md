# 🚀 Manual Oficial de Producción: Quant Agent AI

Este documento explica de forma detallada la arquitectura, infraestructura y el flujo de trabajo (CI/CD) para operar el Bot de Trading en su entorno definitivo de producción.

---

## 🏗️ 1. Arquitectura del Sistema

El bot está desplegado en un **Servidor Privado Virtual (VPS)** utilizando **Docker Swarm** (administrado mediante **Portainer**). La arquitectura se divide en 3 capas fundamentales:

1. **El Cerebro (Contenedor Supabase):** 
   Gestiona la base de datos **PostgreSQL** para registrar logs en tiempo real, operaciones de compra/venta, métricas de rendimiento y tenencias vivas.
2. **El Agente (Contenedor Quant-Agent):** 
   Ejecuta las lógicas escritas en Python (Trading, IA Predictora, Conexión On-Chain en Solana).
3. **El Enrutador (Traefik):** 
   Se encarga de recibir el tráfico de internet, proporcionar el candado de seguridad SSL (Let's Encrypt) y enrutar las peticiones web de forma segura a `https://quant.logvox.com`.

*Ambos contenedores (Supabase y Quant-Agent) se comunican ultra-rápido en una red encriptada privada de Swarm llamada `logvoxNet`.*

---

## 🔄 2. Flujo de Trabajo y Actualizaciones (CI/CD)

Ya no necesitas acceder por consola al servidor VPS para inyectar nuevo código. Hemos instaurado un pipeline automático usando **GitHub Actions**.

### ¿Cómo actualizar el Bot con nuevo código?

1. **Desarrollo Local:** Realizas y guardas tus cambios en tu ordenador local (Mac).
2. **Git Push:** Sube tu código a GitHub ejecutando en la terminal:
   ```bash
   git add .
   git commit -m "Descripción de los cambios"
   git push origin main
   ```
3. **La Nube Ensambla:** 
   Inmediatamente tras hacer el *Push*, los servidores de GitHub Actions interceptan el código, compilan una nueva Imagen Docker, y la guardan en la bóveda de paquetes (**GHCR**) de forma **Pública** (ruta: `ghcr.io/zieteii/quant-agent:latest`). 
   *Este proceso tarda entre 2 a 3 minutos.*
4. **Despliegue en Portainer:**
   * Entra a [Tu Portainer].
   * Ve a **Services** y haz clic en `quant-agent_quant_agent`.
   * Ve hacia abajo y presiona el botón **Update the service**.
   * Portainer tirará la versión antigua y descargará la nueva en 10 segundos. **¡El bot ya estará actualizado en vivo!**

---

## 🔐 3. Variables de Entorno (Secretos)

Ninguna contraseña vive dentro del código que subes a GitHub. Si alguna vez necesitas cambiar una API (Telegram, Solana, OpenAI), lo haces de forma segura directamente dentro de Portainer.

**Para modificar una Variable:**
1. Ve a Detalles del Servicio en Portainer (`quant-agent_quant_agent`).
2. Desplázate hacia **Environment variables**.
3. Cambia a **Advanced Mode** (o hazlo uno por uno).
4. Guarda y haz clic en `Update the service`.

### Modo Real vs Modo Simulacro:
Las compras reales se controlan con la variable maestra:
* `PAPER_MODE=False` (El Bot gasta dinero real).
* `PAPER_MODE=True` (Simulacro, ideal para probar nuevas estrategias de la IA).

---

## ⚡️ 4. Siguientes Niveles de Automatización

Si deseas que Portainer actualice el Bot *completamente solo* sin que tengas que hundir el botón manualmente tras hacer un `git push`, existe la funcionalidad de los **Webhooks**.

1. Activa la opción **Service Webhook** dentro de la página del servicio en Portainer.
2. Copia la hiper-URL generada.
3. Agrégala como en los Webhooks de repositorio en las opciones de Github.
4. Github emitirá un "Grito de llamada" usando dicha URL y Portainer sabrá que es el momento de actualizar.

---

> **Elaborado para:** Administrador ZIETEII
> **Sistema Empaquetado por:** Antigravity AI
> **Estado:** PRODUCCIÓN (ON-LINE) 🟢
