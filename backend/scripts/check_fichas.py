"""
check_fichas.py - Controla la calidad de la busqueda sobre las fichas (como los otros check_*.py).

Uso (desde la carpeta backend/):
    python scripts/check_fichas.py              # todas las preguntas de prueba
    python scripts/check_fichas.py --split dev  # solo un subconjunto (dev / test)
    python scripts/check_fichas.py -v           # muestra tambien los aciertos

Mide:
  - Aciertos en preguntas cubiertas: la ficha correcta es la 1ra (top-1) o esta entre las 3 primeras (top-3).
  - Rechazos correctos: preguntas fuera de tema o de temas sin cobertura NO deben devolver fichas.
  - Deriva del apendice: avisa si el documento declara un tema sin cobertura que no tiene regla en busqueda_fichas.py.

Las preguntas estan en scripts/preguntas_eval_fichas.json. Conviene agregar ahi preguntas REALES de alumnos
(con la ficha que deberia responderlas) a medida que aparezcan en los logs.
"""
import argparse
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
import busqueda_fichas as bf  # noqa: E402

RUTA_CASOS = os.path.join(BASE, "scripts", "preguntas_eval_fichas.json")


def cargar_casos(split="all"):
    with open(RUTA_CASOS, "r", encoding="utf-8") as f:
        casos = json.load(f)["casos"]
    return [c for c in casos if split in ("all", c.get("split"))]


def evaluar(casos):
    """Devuelve (metricas, detalle). detalle = lista de dicts con lo que se devolvio por caso."""
    detalle = []
    for c in casos:
        res = bf.buscar_fichas(c["q"], limite=3)
        ids = [f["id"] for f in res]
        esperadas = c["esperadas"]
        if esperadas:
            top1 = bool(ids) and ids[0] in esperadas
            top3 = any(i in esperadas for i in ids)
            ok = top1
        else:
            top1 = top3 = None
            ok = not ids
        mejor = bf.puntuar(c["q"])[:1]
        detalle.append({**c, "devueltas": ids, "top1": top1, "top3": top3, "ok": ok,
                        "mejor_score": round(mejor[0][0], 2) if mejor else 0.0,
                        "mejor_norm": round(mejor[0][1], 2) if mejor else 0.0,
                        "mejor_id": mejor[0][2]["id"] if mejor else None})
    cub = [d for d in detalle if d["esperadas"]]
    neg = [d for d in detalle if not d["esperadas"]]
    m = {
        "n_cubiertas": len(cub),
        "top1": sum(d["top1"] for d in cub) / max(len(cub), 1),
        "top3": sum(d["top3"] for d in cub) / max(len(cub), 1),
        "sin_ficha_en_cubiertas": sum(1 for d in cub if not d["devueltas"]) / max(len(cub), 1),
        "n_rechazables": len(neg),
        "rechazo_correcto": sum(d["ok"] for d in neg) / max(len(neg), 1),
    }
    for tipo in ("fuera_de_tema", "sin_cobertura"):
        sub = [d for d in neg if d["tipo"] == tipo]
        m["rechazo_" + tipo] = (sum(d["ok"] for d in sub) / len(sub)) if sub else None
        m["n_" + tipo] = len(sub)
    return m, detalle


def imprimir(m, detalle, verbose=False):
    print(f"  Preguntas cubiertas ({m['n_cubiertas']}): ficha correcta primera = {m['top1']:.0%} | entre las 3 primeras = {m['top3']:.0%}"
          f" | sin ninguna ficha = {m['sin_ficha_en_cubiertas']:.0%}")
    print(f"  Preguntas que NO deben traer ficha ({m['n_rechazables']}): rechazadas correctamente = {m['rechazo_correcto']:.0%}"
          f"  (fuera de tema {m['rechazo_fuera_de_tema']:.0%} de {m['n_fuera_de_tema']}, "
          f"sin cobertura {m['rechazo_sin_cobertura']:.0%} de {m['n_sin_cobertura']})")
    for d in detalle:
        if d["ok"] and not verbose:
            continue
        marca = "OK  " if d["ok"] else "FALLA"
        esp = "/".join(d["esperadas"]) or "(ninguna)"
        print(f"    {marca} [{d['tipo']}] \"{d['q']}\"  esperaba {esp}  devolvió {d['devueltas'] or '[]'}"
              f"  (mejor: {d['mejor_id']} puntaje {d['mejor_score']}, norm {d['mejor_norm']})")


def revisar_apendice():
    bf._cargar()
    declarados = bf._DATOS.get("temas_sin_cobertura", [])
    sin_regla = [t for t in declarados if t not in bf.TEMAS_SIN_COBERTURA]
    sobrantes = [t for t in bf.TEMAS_SIN_COBERTURA if t not in declarados]
    if sin_regla:
        print("  AVISO: temas del apéndice del documento SIN regla en busqueda_fichas.TEMAS_SIN_COBERTURA:")
        for t in sin_regla:
            print("     -", t)
    if sobrantes:
        print("  AVISO: reglas en TEMAS_SIN_COBERTURA que ya no figuran en el apéndice (¿ahora hay ficha?):")
        for t in sobrantes:
            print("     -", t)
    if not sin_regla and not sobrantes:
        print(f"  Apéndice: los {len(declarados)} temas sin cobertura tienen regla. OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="all", choices=["all", "dev", "test"])
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    info = bf.estado()
    print(f"Fichas cargadas: {info['fichas']} (versión {info['version']})")
    print(f"Conjunto: {a.split}")
    m, det = evaluar(cargar_casos(a.split))
    imprimir(m, det, a.verbose)
    revisar_apendice()


if __name__ == "__main__":
    main()
