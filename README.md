# 🚀 Asistente Didáctico de Matemáticas - Backend (FastAPI + Ollama RAG)

Este repositorio contiene el backend asincrónico desarrollado en FastAPI para el asistente pedagógico virtual (Faro). Implementa una arquitectura RAG local corriendo en **RunPod** utilizando **Ollama** con el modelo `qwen2.5:14b` (RTX 3090, 24 GB de VRAM), permitiendo adaptar las respuestas en tiempo real según tres niveles de confianza pedagógica: Principiante, Intermedio y Avanzado.

---

## 🛠️ Arquitectura General del Sistema

El flujo de datos e inferencia se ejecuta al 100% dentro del hardware dedicado de la GPU de RunPod:

```text
[Cliente Frontend (Lovable)]
           │ (Streaming de Tokens)
           ▼
   [FastAPI (Puerto 8000)]
           │
           ├──► [Búsqueda RAG Local] ──► Consulta la base de conocimiento del PDF
           │
           └──► [Ollama Local (Puerto 11434)] ──► Inferencia de texto con 'qwen2.5:14b'
```

---

# 🟩 PARTE 1: Configuración y Despliegue del Backend (RunPod)

## Requisito previo: exponer el puerto 8000 en el Pod

En el dashboard de RunPod, en la configuración del Pod (o del template), agregar `8000` en **Expose HTTP Ports**. Sin esto la URL `https://<POD_ID>-8000.proxy.runpod.net` nunca responde, aunque el backend esté funcionando. Cambiar este ajuste reinicia el Pod.

## Primera instalación

Para optimizar el almacenamiento y el uso de red en el Pod, se utiliza `sparse-checkout` de Git para descargar exclusivamente la carpeta del backend.

Todos los comandos se ejecutan en la terminal de JupyterLab de RunPod (dentro de `/workspace`):

```bash
cd /workspace

# 1. Inicializar un repositorio vacío de Git
git init asistente-backend
cd asistente-backend

# 2. Vincular el repositorio remoto de GitHub
git remote add -f origin https://github.com/RodoE98/FARO-Unraf.git

# 3. Habilitar Sparse Checkout
git config core.sparseCheckout true

# 4. Indicar la carpeta a descargar !!SI SE UTILIZA CMD QUITAR COMILLAS DE "backend/"
echo "backend/" > .git/info/sparse-checkout

# 5. Descargar únicamente la carpeta backend
git pull origin main

# 6. Entrar a la carpeta y dar permisos de ejecución a los scripts
cd backend/
chmod +x iniciar_backend.sh instalar_ollama.sh

# 7. Levantar todo (instala dependencias y Ollama, descarga el modelo, levanta el backend)
./iniciar_backend.sh
```

La primera vez descarga ~9 GB (modelo `qwen2.5:14b`), por lo que puede demorar varios minutos. Al terminar imprime `BACKEND LISTO` junto con la URL del backend.

## Cada vez que se reinicia el Pod (Stop/Start)

En RunPod solo `/workspace` persiste entre reinicios: Ollama y los paquetes de Python se pierden. El modelo **no**, porque `iniciar_backend.sh` lo guarda en `/workspace/ollama-models`. Para volver a levantar todo:

```bash
cd /workspace/asistente-backend/backend
git pull origin main        # opcional: trae cambios nuevos del repositorio
./iniciar_backend.sh
```

## Qué hace `iniciar_backend.sh`

1. Verifica/instala las dependencias de Python (`requirements.txt`).
2. Verifica/instala Ollama y lo inicia en segundo plano.
3. Descarga el modelo si no está disponible.
4. Genera `private.key` / `public.key` si no existen (el backend los necesita al arrancar por `lti_config.json`).
5. Inicia uvicorn en segundo plano (puerto 8000), sin depender de la pestaña de JupyterLab.
6. Verifica `/api/health` y muestra el log si algo falla.

Logs: `/workspace/logs/backend.log` y `/workspace/logs/ollama.log` (`tail -f /workspace/logs/backend.log`).

## Configuración por variables de entorno (opcional)

Se pueden cambiar sin tocar el código, por ejemplo `LLM_MODEL=qwen2.5:7b ./iniciar_backend.sh`.

| Variable | Valor por defecto | Descripción |
|---|---|---|
| `LLM_MODEL` | `qwen2.5:14b` | Modelo de Ollama a usar |
| `NUM_CTX` | `8192` | Ventana de contexto (tokens) |
| `RAG_CHUNKS` | `4` | Fragmentos del PDF enviados al modelo |
| `MAX_CONTEXT_CHARS` | `12000` | Tope de caracteres del contexto del PDF |
| `MAX_TOKENS` | `1000` | Tope de tokens por respuesta. Si una respuesta lo alcanza, se le avisa al alumno («La respuesta se cortó… escribí «seguí»») y queda marcado en `backend.log` |
| `HISTORIAL_MAX_MENSAJES` | `6` | Mensajes previos de la conversación que se le pasan al modelo (6 = las últimas 3 vueltas) |
| `HISTORIAL_MSG_MAX_CHARS` | `2500` | Largo máximo de cada mensaje del historial |
| `HISTORIAL_MAX_CHARS` | `6000` | Largo total máximo del historial (se descartan los más viejos) |
| `RENDER_LATEX` | `1` con `iniciar_backend.sh` (`0` si se corre `uvicorn` a mano) | El modelo escribe las fórmulas en LaTeX (`$...$`). El frontend ya lo renderiza con KaTeX |
| `CLASSIFY_TOPIC` | `0` | Poner `1` para completar la columna `subtema` del panel docente |
| `OLLAMA_HOST` | `http://localhost:11434` | Dirección de Ollama |
| `OLLAMA_NUM_PARALLEL` | `4` | Consultas que Ollama atiende a la vez (cada una reserva ~1.5 GB de VRAM); con GPU de 24 GB o menos, usar 2 |
| `USE_FICHAS` | `1` | `0` ignora las fichas docentes (sirve para comparar respuestas con y sin fichas) |
| `FICHAS_MAX` | `3` | Máximo de fichas que se envían al modelo por consulta |
| `RAG_CHUNKS_CON_FICHAS` | `2` | Fragmentos del libro que se agregan cuando sí hay fichas |

## Fichas docentes (corpus de derivadas)

El asistente responde en primer lugar con las **fichas curadas por la cátedra** (`backend/fichas/fichas_derivadas.json`: 63 fichas, versión 0.4) y usa el libro de OpenStax sólo como complemento.

**Qué pasa con cada consulta:**

1. Se buscan fichas relevantes (en memoria, en milisegundos; ver `busqueda_fichas.py`).
2. Si hay, el modelo recibe hasta 3 fichas (fuente principal) más 2 fragmentos del libro (complemento).
3. Si no hay ninguna ficha confiable, se responde como antes, sólo con el libro. Esto ocurre con preguntas fuera de tema y con los temas que el propio documento declara **sin cobertura** (derivación implícita, concavidad e inflexión, regla de L'Hôpital, Rolle, optimización, derivadas trigonométricas, estudio completo de funciones).
   Las preguntas largas y naturales ("Tengo que calcular… ¿me podés ayudar a resolverlo y explicarme…?") también encuentran su ficha: si el puntaje bruto es alto, se acepta aunque las palabras de relleno bajen el puntaje normalizado.
4. **Repreguntas:** el frontend envía los últimos mensajes de la charla y el backend se los pasa al modelo. Si una repregunta sola no encuentra ficha ("no entendí por qué dividiste por 5"), se reintenta con la pregunta anterior + la actual, y sólo se aceptan fichas que también coincidan con la pregunta actual (así un cambio de tema no arrastra fichas viejas).
5. La columna "Eje temático" del panel docente muestra las fichas usadas, por ejemplo `DER-08 Regla de la cadena (+ PAR-10, PAR-11)`. Ante una respuesta incorrecta permite distinguir si falló la ficha, la búsqueda o el modelo.

**Actualizar el corpus** cuando la cátedra entregue una versión nueva del documento (desde `backend/`):

```bash
pip install python-docx              # sólo para este script; el servidor no lo necesita
# 1. Reemplazar el .docx dentro de backend/fichas/ (o pasar su ruta como argumento)
python scripts/build_fichas.py       # regenera fichas/fichas_derivadas.json
python scripts/check_fichas.py       # mide la calidad de la búsqueda
git add fichas && git commit -m "Actualizar fichas" && git push
```

`build_fichas.py` valida el documento y falla, en lugar de generar un JSON incompleto, si el índice no coincide con las fichas, falta un campo obligatorio, cambia la cantidad de fichas declarada por sección o aparece una etiqueta desconocida. `check_fichas.py` además avisa si el apéndice del documento declara un tema sin cobertura que no tiene regla en `busqueda_fichas.TEMAS_SIN_COBERTURA`.

**Calidad de la búsqueda.** Sobre 83 preguntas de prueba (`scripts/preguntas_eval_fichas.json`), la ficha correcta queda en primer lugar en el 84 % de los casos y entre las 3 primeras en el 90-94 %; las preguntas fuera de tema o sin cobertura se rechazan correctamente en el 100 %. Son preguntas escritas por el equipo de desarrollo, no de alumnos reales: conviene agregar ahí preguntas reales (con la ficha esperada) a medida que aparezcan en los logs. Limitación conocida: la búsqueda es por palabras, así que formulaciones muy alejadas del texto de las fichas (por ejemplo "e a la x" en lugar de "exponencial") pueden no encontrar la ficha.

## Solución de problemas

Desde la terminal del Pod:

```bash
curl -s localhost:8000/api/health
```

- **`Connection refused`**: el backend no está corriendo. Ejecutar `./iniciar_backend.sh` y leer el error que imprime (o `tail -n 50 /workspace/logs/backend.log`).
- **Responde JSON o `{"detail":"Not Found"}`, pero la URL del proxy no abre**: falta exponer el puerto 8000 (ver requisito previo).
- **`"model_available": false`**: el modelo no está instalado. Ejecutar `ollama pull qwen2.5:14b` y reiniciar con `./iniciar_backend.sh`.
- **Las respuestas no usan las fichas**: revisar `curl -s localhost:8000/api/health`. Si `fichas` es `null`, está `USE_FICHAS=0`; si el log dice `No se pudo cargar ... fichas_derivadas.json`, falta el archivo (`git pull`).
- **`{"detail":"Not Found"}` en `/api/health`**: el Pod tiene un `main.py` viejo. Ejecutar `git pull origin main` y `./iniciar_backend.sh`.

---

# 🟦 PARTE 2: Configuración y Despliegue del Frontend (Local)

El frontend se deberá desplegar en el entorno local de la máquina del usuario.

## Opción rápida (Windows)

Hacer doble clic en `run_runpod.bat`. Pide el Pod ID, verifica que el backend y el modelo estén listos en RunPod, configura `.env.local`, instala dependencias y levanta el frontend en `http://localhost:8080`. **El backend debe estar levantado antes** (Parte 1).

## Opción manual

A partir de esta instancia todos los comandos se deberán ejecutar dentro de la terminal de VSCode o Git Bash (Windows).

### Requisitos previos

Antes de ejecutar estos comandos, verificar que la computadora tenga instalado:

- Git
- Node.js
- npm
- VSCode

```bash
# 1. Crear una carpeta de trabajo
mkdir faro
cd faro

# 2. Generar un repositorio vacio de Git
git init asistente-frontend
cd asistente-frontend

# 3. Vincular con el respositorio
git remote add -f origin https://github.com/RodoE98/FARO-Unraf.git
git config core.sparseCheckout true

# 4. Indicar la carpeta del cliente y realizar el Pull
# !!SI SE UTILIZA CMD Seguir estos comandos

# USO con CMD
echo frontend/ > .git/info/sparse-checkout
git checkout main
git pull origin main
cd frontend/

# USO con git
echo "frontend/" > .git/info/sparse-checkout
git pull origin main
cd frontend/


# 5. Configurar la URL del backend
# Dentro de la carpeta frontend/, crear un archivo llamado .env.local con el siguiente contenido:
VITE_API_URL=https://<TU_POD_ID>-8000.proxy.runpod.net
# Reemplazar <TU_POD_ID> por el identificador real del pod de RunPod.

# Instalar dependencias del proyecto
# Dentro de la terminal
npm install

# Levantar el entorno de desarrollo local (Vite)
npm run dev
```
