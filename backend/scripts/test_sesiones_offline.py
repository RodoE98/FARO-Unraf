"""Prueba de regresion SIN modelo: reproduce las sesiones del piloto del 13/11 (7560, 13791, 18229) en los tres niveles contra
el backend real, con un Ollama falso que guarda lo que recibiria el modelo. Comprueba lo que el backend controla:
fichas recuperadas, resumen de la sesion, notas docentes, reglas del nivel y de objecion.

Uso (desde backend/):   python3 scripts/test_sesiones_offline.py
Para probar las RESPUESTAS reales del modelo usar regresion_modelo.py (necesita Ollama).
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
os.environ.setdefault("CLASSIFY_TOPIC", "0")

creadas = []
for nombre, cmd in (("private.key", ["openssl", "genrsa", "-out", "private.key", "2048"]),
                    ("public.key", ["openssl", "rsa", "-in", "private.key", "-pubout", "-out", "public.key"])):
    if not os.path.exists(nombre):
        subprocess.run(cmd, check=True, capture_output=True)
        creadas.append(nombre)

import database  # noqa: E402
database.DB_PATH = os.path.join(tempfile.mkdtemp(), "test.db")
from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402

VISTO = {}


class OllamaFalso:
    async def list(self):
        return {"models": [{"model": main.LLM_MODEL}]}

    async def generate(self, **kw):
        return {}

    async def chat(self, **kw):
        VISTO["messages"] = kw["messages"]

        async def gen():
            yield {"message": {"content": "Respuesta de prueba. Por lo tanto el resultado es 3."}, "done": False}
            yield {"message": {"content": "\n\n¿Entendiste?"}, "done": True, "done_reason": "stop"}
        return gen()


main.ollama_async = OllamaFalso()
fallos = []


def check(cond, msg):
    print(("  ok  " if cond else "  FALLA ") + msg)
    if not cond:
        fallos.append(msg)


def turno(c, sesion, nivel, pregunta, hist):
    r = c.post("/api/chat", json={"user_id": f"alumno-{sesion}", "course_id": "x", "role": "student", "pregunta": pregunta,
                                  "confidence": nivel, "historial": list(hist), "session_id": str(sesion)})
    assert r.status_code == 200, r.text
    msgs = VISTO["messages"]
    hist += [{"role": "user", "text": pregunta}, {"role": "assistant", "text": "Respuesta de prueba. Por lo tanto el resultado es 3.\n\n¿Entendiste?"}]
    return msgs[0]["content"], msgs[-1]["content"]


def fichas_de(usuario):
    import re
    return re.findall(r"\[FICHA ([A-Z]+-\d+)", usuario)


GUION = json.load(open(os.path.join(BASE, "scripts", "guion_piloto_13_11.json"), encoding="utf-8"))
MARCAS = {1: ("NIVEL PRINCIPIANTE", "Idea en palabras"), 2: ("NIVEL INTERMEDIO", "ANTES de reemplazar"), 3: ("NIVEL AVANZADO", "hipótesis EXACTAS")}

with TestClient(main.app) as c:
    for nivel, sesion in ((1, 18229), (2, 7560), (3, 13791)):
        print(f"\n=== Nivel {nivel} (sesion {sesion}) ===")
        hist = []
        for i, t in enumerate(GUION["turnos"], 1):
            sysm, usr = turno(c, sesion, nivel, t["pregunta"], hist)
            f = fichas_de(usr)
            if i == 1:
                check(MARCAS[nivel][0] in sysm and MARCAS[nivel][1] in sysm, f"prompt del nivel {nivel} con su estructura propia")
                for otro in (1, 2, 3):
                    if otro != nivel:
                        check(MARCAS[otro][0] not in sysm, f"no mezcla el prompt del nivel {otro}")
            for clave, valor in t.get("espera", {}).items():
                if clave == "fichas_incluyen":
                    check(all(x in f for x in valor), f"t{i} fichas {f} incluyen {valor}")
                elif clave == "fichas_no_incluyen":
                    check(not any(x in f for x in valor), f"t{i} fichas {f} NO incluyen {valor}")
                elif clave == "hay_fichas":
                    check(bool(f), f"t{i} recupera fichas ({f})")
                elif clave == "system_contiene":
                    for s in valor:
                        check(s in sysm, f"t{i} el system prompt contiene «{s[:50]}»")
                elif clave == "usuario_contiene":
                    for s in valor:
                        check(s in usr, f"t{i} el mensaje al modelo contiene «{s[:50]}»")
                elif clave == "system_no_contiene":
                    for s in valor:
                        check(s not in sysm, f"t{i} el system prompt NO contiene «{s[:50]}»")

print("\nRESULTADO:", "TODO OK" if not fallos else f"{len(fallos)} FALLA(S)")
for nombre in creadas:
    os.remove(nombre)
os._exit(0 if not fallos else 1)
