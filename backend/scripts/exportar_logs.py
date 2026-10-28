"""
exportar_logs.py - Exporta los logs del piloto a un CSV (se abre directo en Excel) y muestra un resumen de fuentes.

Uso (desde la carpeta backend/):
    python scripts/exportar_logs.py                      # -> exports/logs_AAAA-MM-DD_HHMM.csv
    python scripts/exportar_logs.py --desde 2026-10-29   # solo consultas desde esa fecha (UTC)
    python scripts/exportar_logs.py --sesion 4821            # solo una conversación

Columnas: id, fecha (UTC), sesion, usuario (hash), rol, fuente, fichas, sin_documentacion, tema, pregunta, respuesta,
fragmentos_openstax (sección y páginas de cada fragmento entregado), texto_fragmentos (JSON completo).

El resumen final sirve para comprobar la prioridad acordada: fichas docentes -> OpenStax -> conocimiento del modelo.
"""
import argparse
import csv
import json
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(BASE, "logs_pedagogicos.db")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--desde", help="fecha AAAA-MM-DD (UTC)")
    ap.add_argument("--sesion", help="ID de sesión, ej. 4821")
    ap.add_argument("--db", default=DB)
    a = ap.parse_args()

    if not os.path.exists(a.db):
        sys.exit(f"No encuentro la base de datos: {a.db}")
    con = sqlite3.connect(a.db)
    con.row_factory = sqlite3.Row
    columnas = [r[1] for r in con.execute("PRAGMA table_info(chat_logs)")]
    extra = [c for c in ("session_id", "fuente", "fichas_ids", "sin_documentacion", "fragmentos") if c in columnas]
    sel = "id, user_id, role, subtema, pregunta, respuesta, timestamp" + "".join(f", {c}" for c in extra)
    sql, params = f"SELECT {sel} FROM chat_logs WHERE 1=1", []
    if a.desde:
        sql += " AND timestamp >= ?"; params.append(a.desde)
    if a.sesion:
        sql += " AND session_id = ?"; params.append(a.sesion.strip().upper())
    filas = con.execute(sql + " ORDER BY id", params).fetchall()

    os.makedirs(os.path.join(BASE, "exports"), exist_ok=True)
    ruta = os.path.join(BASE, "exports", f"logs_{datetime.now():%Y-%m-%d_%H%M}.csv")
    cuenta = Counter()
    sin_doc = 0
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: Excel respeta los acentos
        w = csv.writer(f)
        w.writerow(["id", "fecha_utc", "sesion", "usuario_hash", "rol", "fuente", "fichas", "sin_documentacion",
                    "tema", "pregunta", "respuesta", "fragmentos_openstax", "texto_fragmentos"])
        for r in filas:
            d = dict(r)
            frag = json.loads(d["fragmentos"]) if d.get("fragmentos") else None
            libro = ""
            if frag:
                libro = "; ".join(f"{x['libro']} sec.{x['seccion']} págs.{x['paginas']}" for x in frag["openstax"] if x.get("enviado"))
            fuente = d.get("fuente") or "(sin registro)"
            cuenta[fuente] += 1
            sin_doc += 1 if d.get("sin_documentacion") else 0
            w.writerow([d["id"], d["timestamp"], d.get("session_id") or "", d["user_id"], d["role"], fuente,
                        d.get("fichas_ids") or "", d.get("sin_documentacion") if d.get("sin_documentacion") is not None else "",
                        d["subtema"], d["pregunta"], d["respuesta"], libro, d.get("fragmentos") or ""])
    print(f"{len(filas)} consultas exportadas a {ruta}\n")
    print("Fuente efectivamente entregada al modelo:")
    for k in ("FICHA", "FICHA+OPENSTAX", "OPENSTAX", "NINGUNA", "(sin registro)"):
        if cuenta.get(k):
            print(f"  {k:<16}{cuenta[k]:>5}  ({cuenta[k] / len(filas):.0%})")
    print(f"\nRespondidas sin documentación recuperada: {sin_doc}")


if __name__ == "__main__":
    main()
