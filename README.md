# Sentinel Monitor

[![CI](https://github.com/Reload-ARTS/sentinel-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/Reload-ARTS/sentinel-monitor/actions/workflows/ci.yml)

**Sentinel Monitor comprueba si tus páginas web y APIs están disponibles y puede avisarte por Discord si alguna falla.** Es una herramienta gratuita desarrollada en Python como proyecto de aprendizaje y portafolio.

Por ejemplo, puedes configurar la web de tu negocio y una API. Cada vez que ejecutas el programa, revisa ambas direcciones y te muestra el resultado. Si alguna no responde correctamente, puede enviar una alerta a un canal de Discord.

## Qué puede hacer

- Revisar varias direcciones HTTP/HTTPS en una sola ejecución.
- Indicar si cada servicio funciona bien (**HEALTHY**), responde más lento de lo esperado (**DEGRADED**) o presenta un fallo (**DOWN**).
- Enviar una alerta a Discord por cada servicio **DOWN**, si las alertas están activadas.
- Generar un resultado en **JSON**, útil para consultar el estado o integrarlo con otras herramientas.

**Importante:** cada ejecución realiza una única revisión. Para comprobar servicios cada cierto tiempo, debes programar su ejecución en Windows o Linux. Actualmente no guarda un historial, no evita alertas repetidas ni envía avisos de recuperación.

## Instalación

Necesitas **Git**, **Python** y conexión a Internet para instalar las dependencias. La integración continua comprueba Python **3.11 y 3.14** en Ubuntu; el proyecto también se ha probado en Windows con Python 3.14.

**Windows (PowerShell):**

```powershell
git clone https://github.com/Reload-ARTS/sentinel-monitor.git
cd sentinel-monitor
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Si tienes Python 3.14 en lugar de 3.11, cambia `py -3.11` por `py -3.14`.

**Linux (terminal):**

```sh
git clone https://github.com/Reload-ARTS/sentinel-monitor.git
cd sentinel-monitor
python3 -m venv venv
./venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Comprueba que `python3` corresponde a una versión compatible. Los comandos utilizan el entorno virtual sin necesidad de activarlo.

## Configurar y probar

1. Abre **`config/targets.json`** y sustituye sus objetivos de demostración por las direcciones que quieras comprobar. Utiliza servicios propios o que tengas permiso para consultar.
2. Para una primera prueba, deja **`ENABLE_ALERTS=false`** en el archivo `.env`. Si esa variable ya está definida en tu terminal, cambia también su valor a `false`: la terminal tiene prioridad sobre el archivo.
3. Ejecuta Sentinel Monitor desde la carpeta principal del proyecto.

Ejemplo de `config/targets.json` para una web:

```json
{
  "settings": {
    "timeout_seconds": 5,
    "max_acceptable_latency_ms": 1000
  },
  "targets": [
    {
      "name": "Mi sitio web",
      "url": "https://example.com",
      "expected_status": 200
    }
  ]
}
```

`timeout_seconds` indica el tiempo de espera de la petición y `max_acceptable_latency_ms` el umbral para considerar que responde lento. Puedes añadir más elementos a `targets`. El ejemplo depende de la disponibilidad de una web externa.

**Ejecutar en Windows:**

```powershell
.\venv\Scripts\python.exe -B -m src.checker
```

**Ejecutar en Linux:**

```sh
./venv/bin/python -B -m src.checker
```

El programa muestra un informe JSON con el estado de cada servicio. Los diagnósticos se escriben por separado. Los estados significan:

| Estado | Significado |
|---|---|
| `HEALTHY` | Responde con el código HTTP esperado y dentro del tiempo aceptable. |
| `DEGRADED` | Responde correctamente, pero supera el tiempo aceptable. |
| `DOWN` | No responde, agota el tiempo de espera o devuelve un código HTTP distinto del esperado. |

Sentinel Monitor no sigue redirecciones HTTP. El código HTTP esperado es `200` si no indicas otro.

## Activar alertas de Discord

1. Crea un **webhook** en un canal de tu servidor Discord.
2. Edita tu archivo local **`.env`**:

```dotenv
ENABLE_ALERTS=true
WEBHOOK_URL=https://discord.com/api/webhooks/ID/TOKEN
```

3. Sustituye la URL de ejemplo por tu webhook real y vuelve a ejecutar el programa.

Las alertas se envían **solo para servicios DOWN**. Si un servicio sigue caído, puede volver a generar una alerta en la siguiente ejecución. Si Discord rechaza el envío o hay un problema de red, el monitoreo continúa.

**Seguridad:** nunca publiques `.env` ni compartas tu webhook. Si no quieres alertas, utiliza `ENABLE_ALERTS=false`; si la variable falta por completo, el programa interpreta que están activadas y exige un webhook válido.

## Ejecuciones periódicas

Puedes utilizar el **Programador de tareas de Windows** o **cron en Linux** para ejecutar el programa, por ejemplo, cada cinco minutos.

En Windows, configura la ruta al `python.exe` del entorno virtual como programa, `-B -m src.checker` como argumentos y la carpeta del repositorio en **«Iniciar en»**. Evita ejecutar varias instancias al mismo tiempo.

En Linux, puedes adaptar esta entrada de cron (sustituye la ruta por la tuya):

```cron
*/5 * * * * cd /ruta/sentinel-monitor && /ruta/sentinel-monitor/venv/bin/python -B -m src.checker
```

No se configura una ejecución programada automáticamente al instalar el proyecto.

## Pruebas y resultados

Para ejecutar las pruebas automatizadas, instala las dependencias de desarrollo:

```powershell
# Windows
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -B -m pytest -q
```

```sh
# Linux
./venv/bin/python -m pip install -r requirements-dev.txt
./venv/bin/python -B -m pytest -q
```

La [CI de GitHub Actions](https://github.com/Reload-ARTS/sentinel-monitor/actions/workflows/ci.yml) ejecuta comprobaciones automatizadas. Las pruebas no envían alertas reales.

El programa devuelve estos códigos de salida, útiles para automatizaciones:

| Código | Resultado |
|---|---|
| `0` | Revisión terminada sin servicios `DOWN`. |
| `1` | Revisión terminada con al menos un servicio `DOWN`. |
| `2` | Configuración inválida. |
| `3` | Error interno o revisión incompleta. |

## Límites y licencia

Sentinel Monitor comprueba **servicios HTTP/HTTPS**, no el consumo de CPU, memoria o disco de un servidor. Tampoco incorpora todavía email, Teams, historial ni deduplicación de alertas.

Distribuido bajo la [licencia MIT](LICENSE). Copyright (c) 2026 Reload-ARTS.
