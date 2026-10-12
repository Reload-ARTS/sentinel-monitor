# Sentinel Monitor

[![CI](https://github.com/Reload-ARTS/sentinel-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/Reload-ARTS/sentinel-monitor/actions/workflows/ci.yml)

Monitor HTTP/HTTPS en Python que valida configuración, comprueba disponibilidad y latencia, clasifica objetivos y envía alertas opcionales a Discord. Cada ejecución realiza **una sola pasada** y emite JSON para automatización. Proyecto personal de portafolio centrado en validación, manejo de errores, observabilidad y pruebas.

## Capacidades implementadas

- Validación integral del JSON y de alertas antes de cualquier solicitud.
- Estados HEALTHY, DEGRADED y DOWN, con umbral global de latencia.
- Respuesta directa: no sigue redirecciones HTTP.
- Un intento de alerta Discord por objetivo DOWN, cuando está habilitado.
- Informe JSON, resultados parciales ante errores internos y códigos 0–3.
- Pruebas con transporte simulado y CI en GitHub Actions.

## Instalación

La versión mínima objetivo es CPython **3.11**; la [CI](.github/workflows/ci.yml) está configurada para comprobar **3.11 y 3.14** en Ubuntu. La nueva matriz requiere validación remota tras publicar el cambio; configurarla no acredita que haya pasado. La suite anterior fue validada en Python 3.13.5 y 3.14.6, pero esa evidencia no sustituye verificar las dependencias fijadas en cada versión. Necesitas Git y acceso al índice de paquetes para instalar.

```text
git clone https://github.com/Reload-ARTS/sentinel-monitor.git
cd sentinel-monitor
```

Windows, PowerShell:

```powershell
py -3.11 -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Linux/macOS (comprueba que `python3 --version` corresponde a una versión indicada):

```sh
python3 -m venv venv
./venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Los comandos usan el intérprete del entorno virtual sin necesitar activación. [requirements.txt](requirements.txt) fija las versiones de Requests, python-dotenv y sus dependencias transitivas para ejecución. [requirements-dev.txt](requirements-dev.txt) incluye ese archivo y añade pytest y sus dependencias para pruebas; colorama solo se instala en Windows. Son versiones concretas de una combinación a validar, no una declaración de compatibilidad con cualquier actualización. No hace falta instalar el proyecto como paquete.

Para desarrollar o ejecutar las pruebas, instala además el conjunto de pruebas:

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\venv\Scripts\python.exe -m pip check
```

```sh
./venv/bin/python -m pip install -r requirements-dev.txt
./venv/bin/python -m pip check
```

Los pins controlan versiones de paquetes, no el intérprete, el sistema operativo ni los hashes de los artefactos. Usa un venv limpio para reproducir el conjunto; pip no elimina paquetes ajenos ya instalados. Al actualizar una dependencia, revisa sus transitivas y ejecuta la suite en ambas versiones de la matriz. No se añaden gestores de paquetes ni un bloqueo con hashes en esta etapa.

## Objetivos HTTP

Edita [config/targets.json](config/targets.json). Los objetivos incluidos son una demostración con servicios externos y casos intencionales de timeout/DOWN: no garantizan disponibilidad ni duración fija. Sustitúyelos por servicios que tengas autorización para comprobar.

Ejemplo ilustrativo para un servicio local que debes iniciar por separado:

```json
{
  "settings": {"timeout_seconds": 5, "max_acceptable_latency_ms": 1000},
  "targets": [
    {"name": "Servicio local", "url": "http://127.0.0.1:8000/health", "expected_status": 200}
  ]
}
```

Ambos valores de `settings` son obligatorios: números finitos estrictamente positivos, sin booleanos. `targets` es una lista no vacía. Cada objetivo requiere nombre no vacío y único y URL absoluta HTTP/HTTPS sin credenciales ni caracteres de control. `expected_status` es opcional (200 por defecto), entero de 100 a 599. Se rechazan claves desconocidas, claves JSON duplicadas y codificación distinta de UTF-8 válido. No introduzcas secretos en nombres: aparecen en informes y alertas.

| Condición | Estado |
|---|---|
| HTTP esperado, latencia menor o igual al umbral | HEALTHY |
| HTTP esperado, latencia mayor al umbral | DEGRADED |
| HTTP inesperado, timeout o fallo de transporte | DOWN |

HTTP inesperado prevalece sobre latencia alta. Se compara la duración sin redondear. Un 302 frente a 200 es DOWN; puedes esperar explícitamente 302 si corresponde al servicio. La medición incluye solicitud y lectura de la respuesta; el timeout de Requests no garantiza un límite absoluto para la duración total.

## Alertas Discord

[.env.example](.env.example) propone una primera ejecución sin Discord:

```dotenv
ENABLE_ALERTS=false
WEBHOOK_URL=
```

Es una elección del ejemplo: **el programa usa true si ENABLE_ALERTS está ausente**. Solo acepta true/false, sin distinguir mayúsculas y recortando espacios exteriores. Con false no exige ni valida webhook. Con true exige uno válido antes del primer GET.

Para habilitar alertas, crea un webhook en un canal de pruebas de tu servidor Discord. Edita únicamente tu `.env` local: establece `ENABLE_ALERTS=true` y guarda la URL real en `WEBHOOK_URL`. La forma admitida es HTTPS en `discord.com`, ruta `/api/webhooks/ID/TOKEN` o `/api/vN/webhooks/ID/TOKEN`, ID numérico, token formado por letras, números, guion o guion bajo; sin credenciales, query ni fragmento y con puerto implícito o 443. La validación local no acredita que el token esté vigente ni que el canal sea el correcto.

`.env` se carga desde el **directorio de trabajo actual**. Las variables ya definidas en el proceso tienen prioridad. Para ejecutar sin Discord incluso si el archivo habilita alertas:

```powershell
$env:ENABLE_ALERTS = 'false'
.\venv\Scripts\python.exe -B -m src.checker
# La variable permanece en esta sesión: revisa su valor antes de habilitar alertas.
```

```sh
ENABLE_ALERTS=false ./venv/bin/python -B -m src.checker
```

No compartas `.env`, tokens ni URLs de webhook. `.env` está excluido de Git y la plantilla contiene solo valores seguros. El umbral reside en JSON: `MAX_LATENCY_THRESHOLD_MS` no es una opción del programa.

Solo DOWN genera alertas, nunca DEGRADED. POST tiene timeout de 5 segundos, sin redirecciones ni reintentos. Un fallo esperado de envío no altera la salud ni interrumpe el resto. `src/notifier.py` ya no tiene una demostración independiente: ejecuta el coordinador `src.checker`.

## Ejecución y resultados

Ejecuta desde la raíz del repositorio: `config/targets.json` y `.env` dependen del directorio actual. No existe una opción CLI para seleccionar otro archivo.

```powershell
.\venv\Scripts\python.exe -B -m src.checker
$LASTEXITCODE
```

```sh
./venv/bin/python -B -m src.checker
echo $?
```

**stdout** contiene un documento JSON y **stderr** contiene logs y diagnósticos. Para separarlos en PowerShell 7.4 o posterior (que preserva los bytes de stdout de programas nativos):

```powershell
.\venv\Scripts\python.exe -B -m src.checker > resultado.json 2> diagnostico.log
$codigo = $LASTEXITCODE
```

En Windows PowerShell 5.1, `>` utiliza UTF-16LE por defecto. Para conservar los bytes de salida y obtener JSON legible como UTF-8, delega la redirección en `cmd.exe` desde la raíz del repositorio:

```powershell
cmd.exe /d /c ".\venv\Scripts\python.exe -B -m src.checker > resultado.json 2> diagnostico.log"
$codigo = $LASTEXITCODE
```

Esta alternativa también sirve en PowerShell moderno: requiere Windows y `cmd.exe`; mantiene stderr separado y captura el código inmediatamente después del proceso. `/d` evita comandos AutoRun de cmd. Sentinel emite el JSON con caracteres no ASCII escapados, por lo que sus bytes son compatibles con UTF-8. El código 1 es un resultado válido cuando existe DOWN. Véase [redirección en PowerShell](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_redirection).

En Linux/macOS:

```sh
./venv/bin/python -B -m src.checker > resultado.json 2> diagnostico.log
codigo=$?
```

Los archivos sobrescriben la ejecución anterior. Elige ubicación y permisos y no los añadas al repositorio por defecto.

| Código | Significado |
|---|---|
| 0 | Completa sin DOWN; admite DEGRADED. |
| 1 | Completa con DOWN, incluso si la alerta falla. |
| 2 | Configuración inválida o ilegible; sin solicitudes. |
| 3 | Error interno; prevalece sobre DOWN observado. |

`execution_status` es `completed`, `not_started` (también para un error interno de preparación) o `incomplete`. Fallos de arranque del intérprete o dependencias ausentes quedan fuera del contrato JSON de la aplicación.

Ejemplo **ilustrativo**, sin alertas:

```json
{
  "schema_version": "1",
  "execution_status": "completed",
  "summary": {"total": 1, "checked": 1, "healthy": 0, "degraded": 0, "down": 1, "not_checked": 0},
  "targets": [{"name": "Servicio local", "status": "DOWN", "http_status": 503, "latency_ms": 12.5, "notification": "disabled"}],
  "not_checked": [],
  "errors": [],
  "exit_code": 1
}
```

Sin respuesta HTTP, `http_status` es null. `not_checked` contiene solo nombres de objetivos pendientes, sin salud ni notificación inventadas. Si no se establece un conjunto fiable, `summary.total` es null. Con total conocido: `healthy + degraded + down = checked` y `checked + not_checked = total`. Los errores raíz contienen `type` y `message`; un DOWN ordinario no exige un error raíz.

| notification | Significado |
|---|---|
| not_required | HEALTHY o DEGRADED. |
| disabled | DOWN con alertas deshabilitadas. |
| accepted | Discord respondió 200/204; no confirma lectura ni aviso móvil. |
| failed | El intento de envío falló. |
| not_attempted | DOWN comprobado; un error interno impidió iniciar la alerta requerida. |

## Ejecución programada

Sentinel no mantiene un servicio o bucle. **Cada pasada independiente puede volver a alertar los mismos DOWN**. Elige el intervalo y evita solapamientos; no hay deduplicación ni alertas de recuperación.

### Windows: Programador de tareas

Crea manualmente una tarea con una cuenta que tenga acceso al repositorio, entorno virtual y `.env`. Configura un desencadenador periódico y la acción «Iniciar un programa»:

- Programa: ruta absoluta a `sentinel-monitor\venv\Scripts\python.exe`.
- Argumentos: `-B -m src.checker`.
- Iniciar en: ruta absoluta a la raíz `sentinel-monitor`.

Selecciona «No iniciar una nueva instancia» si la tarea ya se ejecuta. Prueba manualmente la tarea y revisa el resultado: 1 indica DOWN, no necesariamente un fallo del planificador. El campo Programa no interpreta redirecciones de shell y esta acción no conserva stdout/stderr automáticamente. Para históricos, prepara y revisa por separado un wrapper que capture los canales y preserve el código. El proyecto no crea tareas.

### Linux: cron

Ejemplo orientativo cada cinco minutos. Sustituye rutas; el directorio de salida debe existir y ser escribible:

```cron
*/5 * * * * cd /ruta/sentinel-monitor && ENABLE_ALERTS=false /ruta/sentinel-monitor/venv/bin/python -B -m src.checker > /ruta/salidas/sentinel.json 2> /ruta/salidas/sentinel.log
```

El ejemplo fuerza alertas deshabilitadas y sobrescribe informes. Cron tiene un entorno reducido; no depende de activar venv ni de variables de tu terminal. Para Discord, configura `.env` y retira el override `ENABLE_ALERTS=false`. Cron no evita solapamientos: ajusta la periodicidad a duración y cantidad de objetivos. No se instaló ni ejecutó una tarea cron para verificar estas instrucciones.

## Pruebas y CI

Desde la raíz, sin envíos reales:

```powershell
.\venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q --tb=short
```

```sh
./venv/bin/python -B -m pytest -p no:cacheprovider -q --tb=short
```

La suite usa mocks y bloqueos de red para configuración, clasificación, informes y notificaciones. Conserva el plugin de logging: se utiliza `caplog`. La CI ejecuta pytest en pushes a main y pull requests hacia main; no despliega el proyecto. El badge enlaza su estado actual: una prueba local no demuestra una nueva ejecución remota satisfactoria.

## Organización y límites

- [src/config.py](src/config.py): lectura y validación JSON.
- [src/checker.py](src/checker.py): comprobación, coordinación e informe.
- [src/notifier.py](src/notifier.py): validación y envío Discord.
- [tests/](tests/): regresiones con transporte simulado.

No hay persistencia, historial de incidentes, concurrencia, reintentos, espera por rate limits ni integraciones Slack/Teams. La duración crece con los objetivos y timeouts. Los ejemplos externos dependen de Internet y no son deterministas. No se restringen destinos a una lista autorizada: usa objetivos de confianza.

La entrada está diseñada para procesos independientes. Al repetir `main()` dentro del mismo proceso, dotenv puede dejar valores en el entorno que prevalecen sobre cambios posteriores del archivo; logging se modifica temporalmente. No se presenta como API concurrente.

## Licencia

El README anterior indicaba MIT, pero el repositorio no incluye LICENSE. Queda pendiente incorporar el texto con autorización del titular; esta etapa no añade una licencia por iniciativa propia.
