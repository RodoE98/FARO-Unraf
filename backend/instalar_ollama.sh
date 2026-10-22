#!/bin/bash
# ============================================================
# instalar_ollama.sh
# Instala zstd + Ollama en el pod (si no estan instalados).
# NO levanta el servidor ni descarga modelos: eso lo hace iniciar_backend.sh
# (normalmente no hace falta ejecutar este archivo a mano).
# ============================================================
set -e

if command -v ollama >/dev/null 2>&1; then
    echo "Ollama ya esta instalado."
    exit 0
fi

echo "Instalando zstd..."
apt-get update && apt-get install -y zstd

echo "Descargando e instalando Ollama..."
curl -fsSL https://ollama.com/install.sh | sh

echo "Ollama instalado."
