# 🛡️ Sentinel Infrastructure Health Monitor

[![Continuous Integration](https://github.com/Reload-ARTS/sentinel-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/Reload-ARTS/sentinel-monitor/actions)
[![Python Version](https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Sentinel** es un sistema modular de monitoreo de salud de infraestructura y alertas en tiempo real construido en Python. Diseñado para auditar la disponibilidad HTTP/HTTPS, latencia de respuesta y caídas de servicio, integrándose con Webhooks (Discord, Slack, MS Teams) para la gestión de incidentes.

---

## 🛠️ Características Clave

* **Monitoreo de Endpoints HTTP/HTTPS:** Verificación de estados de respuesta y medición precisa de latencia en milisegundos.
* **Manejo Resiliente de Fallos:** Captura de *Timeouts*, errores de red y excepciones de resolución de nombres (DNS).
* **Alertas en Tiempo Real:** Envío de notificaciones enriquecidas (*Embeds*) a través de Webhooks cuando se detecta degradación o caída del servicio.
* **Arquitectura Basada en Variables de Entorno:** Gestión segura de credenciales y configuraciones sensibles con `python-dotenv`.
* **Testing & CI/CD Automatizado:** Cobertura de pruebas unitarias con `pytest` y pipeline de Integración Continua mediante GitHub Actions.

---

## 📂 Arquitectura del Proyecto

```text
sentinel-monitor/
├── .github/
│   └── workflows/
│       └── ci.yml            # Pipeline de CI/CD con GitHub Actions
├── config/
│   └── targets.json          # Lista de endpoints y parámetros de chequeo
├── src/
│   ├── __init__.py
│   ├── checker.py            # Motor principal de auditoría HTTP y latencia
│   └── notifier.py           # Módulo de alertas y notificaciones por Webhook
├── tests/
│   ├── __init__.py
│   └── test_checker.py       # Pruebas unitarias con Mocks (pytest)
├── .env.example              # Plantilla pública de variables de entorno
├── .gitignore                # Reglas de exclusión de Git
├── requirements.txt          # Dependencias del proyecto
└── README.md                 # Documentación del repositorio
```
---

## 🚀 Guía de Instalación y Uso
**1. Requisitos Previos**
- Python 3.9 o superior
- Git

**2. Clonar el Repositorio e Instalar Dependencias**

**Clonar el repositorio**
- git clone [https://github.com/Reload-ARTS/sentinel-monitor.git](https://github.com/Reload-ARTS/sentinel-monitor.git)
- cd sentinel-monitor

**Crear y activar entorno virtual**
- python -m venv venv

**En Windows (PowerShell):**
- .\venv\Scripts\Activate.ps1

**En Linux/macOS:**
- source venv/bin/activate

**Instalar dependencias**
- pip install -r requirements.txt

**3. Configuración de Variables de Entorno**

**Copia el archivo .env.example a .env y configura tu URL de Webhook:**
- cp .env.example .env

**Edita .env:**
- WEBHOOK_URL=[https://discord.com/api/webhooks/TU_WEBHOOK_AQUI](https://discord.com/api/webhooks/TU_WEBHOOK_AQUI)
- ENABLE_ALERTS=true

**4. Ejecución del Sistema**

**Para ejecutar una prueba de monitoreo sobre las URLs configuradas en config/targets.json:**
- python src/checker.py
**Para probar el módulo de alertas en tiempo real:**
- python src/notifier.py

---

## 🧪 Ejecución de Pruebas Unitarias

**El proyecto cuenta con suites de pruebas unitarias implementadas con pytest:**
- pytest -v

---

## 📝 Licencia
Este proyecto está bajo la Licencia MIT.
