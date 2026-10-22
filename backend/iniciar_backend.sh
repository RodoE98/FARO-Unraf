#!/bin/bash
# ============================================================
# iniciar_backend.sh  -  levanta TODO el backend en el pod de RunPod
#
# Uso (desde la carpeta backend/):   ./iniciar_backend.sh
#
# - Es seguro ejecutarlo varias veces (reinicia Ollama y el backend).
# - Despues de hacer Stop/Start del pod, volve a ejecutarlo: reinstala lo que
#   se haya perdido (Ollama, paquetes de Python) y re-descarga el modelo si hace falta.
# - Los logs quedan en /workspace/logs/  (backend.log y ollama.log)
# ============================================================
cd "$(dirname "$0")" || exit 1

export LLM_MODEL="${LLM_MODEL:-qwen2.5:14b}"
# El frontend ya renderiza LaTeX (remark-math + rehype-katex), asi que el modelo puede escribir $...$
export RENDER_LATEX="${RENDER_LATEX:-1}"
# Los modelos se guardan en /workspace (volumen persistente) para no re-descargarlos (~9 GB) en cada reinicio
export OLLAMA_MODELS="${OLLAMA_MODELS:-/workspace/ollama-models}"
LOG_DIR="${LOG_DIR:-/workspace/logs}"
mkdir -p "$LOG_DIR" "$OLLAMA_MODELS"

echo "== 1/6 Dependencias de Python"
if ! python3 -c "import fastapi, uvicorn, ollama, pylti1p3" 2>/dev/null; then
    echo "Faltan paquetes, instalando requirements.txt..."
    pip install -r requirements.txt || { echo "ERROR: fallo pip install"; exit 1; }
fi

echo "== 2/6 Ollama"
if ! command -v ollama >/dev/null 2>&1; then
    bash ./instalar_ollama.sh || { echo "ERROR: fallo la instalacion de Ollama"; exit 1; }
fi
pkill -x ollama 2>/dev/null
sleep 1
nohup ollama serve > "$LOG_DIR/ollama.log" 2>&1 &
for i in $(seq 1 30); do
    curl -sf http://localhost:11434/api/tags >/dev/null && break
    sleep 1
done
if ! curl -sf http://localhost:11434/api/tags >/dev/null; then
    echo "ERROR: Ollama no responde. Ultimas lineas de $LOG_DIR/ollama.log:"
    tail -n 20 "$LOG_DIR/ollama.log"
    exit 1
fi

echo "== 3/6 Modelo $LLM_MODEL"
if ! ollama list | awk 'NR>1 {print $1}' | grep -qx "$LLM_MODEL"; then
    echo "Descargando $LLM_MODEL (la primera vez son ~9 GB, puede demorar)..."
    ollama pull "$LLM_MODEL" || { echo "ERROR: fallo la descarga del modelo"; exit 1; }
fi

echo "== 4/6 Claves LTI"
# main.py carga private.key / public.key (segun lti_config.json) al importarse:
# si faltan, el backend se cae al arrancar. Solo se generan si no existen.
if [ ! -f private.key ] || [ ! -f public.key ]; then
    echo "Generando private.key y public.key..."
    python3 - <<'PY'
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
open("private.key", "wb").write(k.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
open("public.key", "wb").write(k.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
PY
fi

echo "== 5/6 Backend (uvicorn, puerto 8000)"
pkill -f "uvicorn main:app" 2>/dev/null
sleep 1
nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 > "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!

echo "== 6/6 Verificando que responda"
HEALTH=""
for i in $(seq 1 90); do
    HEALTH=$(curl -sf http://localhost:8000/api/health) && break
    HEALTH=""
    kill -0 "$BACKEND_PID" 2>/dev/null || break   # el proceso murio: no tiene sentido seguir esperando
    sleep 1
done

if [ -z "$HEALTH" ]; then
    echo ""
    echo "ERROR: el backend no arranco. Ultimas lineas de $LOG_DIR/backend.log:"
    echo "------------------------------------------------------------"
    tail -n 30 "$LOG_DIR/backend.log"
    exit 1
fi

echo "Health: $HEALTH"
echo ""
echo "============================================================"
echo " BACKEND LISTO"
if [ -n "$RUNPOD_POD_ID" ]; then
    echo " URL: https://${RUNPOD_POD_ID}-8000.proxy.runpod.net"
    echo " (Pod ID: ${RUNPOD_POD_ID})"
fi
echo " Ver logs en vivo:  tail -f $LOG_DIR/backend.log"
echo "============================================================"
