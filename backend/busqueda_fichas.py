"""
busqueda_fichas.py - Busqueda sobre las fichas docentes curadas (corpus de derivadas).

Las fichas (fichas/fichas_derivadas.json, generado con scripts/build_fichas.py a partir del
documento de la catedra) estan en espanol y son la fuente PRINCIPAL del asistente; el libro de
OpenStax (busqueda_local.py) queda como material complementario.

Como funciona:
  - Se carga el JSON una sola vez (63 fichas: no hace falta ningun indice en disco).
  - Se normaliza el texto (minusculas, sin tildes, simbolos como ∂ o ∇ pasados a palabras,
    sin palabras vacias, plurales y terminaciones recortadas).
  - Ranking BM25 con pesos por campo (titulo y pregunta pesan mas que la respuesta) mas un
    bonus por frases exactas ("regla de la cadena", "plano tangente").
  - Si la pregunta menciona un tema que el propio documento declara SIN COBERTURA (apendice),
    no se devuelven fichas: devolver fichas "parecidas" confundiria al modelo, y se usa el libro.
  - Si ninguna ficha supera el umbral, se devuelve [] (el backend sigue como antes, solo con el libro).

Solo usa la biblioteca estandar.
"""
import json
import math
import os
import re
import unicodedata

RUTA_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fichas", "fichas_derivadas.json")

# ---------------------------------------------------------------- parametros de ajuste
STEM_LEN = 5            # largo maximo de la raiz de cada palabra ("derivada"/"derivar"/"derivacion" -> "deriv")
BM25_K1 = 1.2
BM25_B = 0.75
PESOS_CAMPO = {         # cuanto pesa cada campo de la ficha al buscar
    "titulo": 3.0, "pregunta": 3.0, "origen": 2.0,
    "respuesta": 1.0, "complemento": 1.0, "nota": 1.0, "ejemplo": 1.0,
    "relacionadas": 1.0, "prerrequisitos": 0.5,
}
BONUS_TITULO = 3.0      # bonus * (parecido entre la pregunta del alumno y el titulo de la ficha, 0..1)
BONUS_FRASE = 3.0       # puntos por cada par de palabras consecutivas que coincide con titulo/pregunta/origen
NORM_MIN = 0.90         # puntaje normalizado minimo de la mejor ficha (0..~1.5): que parte de la pregunta quedo "cubierta"
ABS_MIN = 2.0           # y puntaje bruto minimo (evita aceptar una ficha por una sola palabra muy comun)
UNKNOWN_W = 0.5         # peso de las palabras de la pregunta que no existen en ninguna ficha (0 = ignorarlas)
RATIO_MIN = 0.55        # una ficha adicional entra si llega a esta fraccion del puntaje de la mejor
# Preguntas LARGAS ("Tengo que calcular ... ¿me podes ayudar a resolverlo y explicarme ...?"): las palabras de relleno
# bajan el puntaje normalizado aunque la ficha sea la correcta. Si el puntaje BRUTO es alto, alcanza con una cobertura menor.
ABS_FUERTE = 10.0       # puntaje bruto a partir del cual se acepta una ficha...
NORM_MIN_FUERTE = 0.50  # ...con este puntaje normalizado minimo (los temas sin cobertura se descartan antes, por regla)

# ---------------------------------------------------------------- normalizacion
STOPWORDS = set("""
a al algo algun alguna algunas alguno algunos ante antes aqui asi aun aunque cada como con contra cual cuales
cuando cuanto cuanta de del desde donde dos el ella ellas ellos en entre era eran es esa esas ese eso esos esta
estan estas este esto estos fue ha hace hacen hacer han hasta hay la las le les lo los mas me mi mis mucho muy
nada ni no nos o os otra otro para pero poco por porque que quien quienes se ser si sin sobre son su sus tal
tambien te tengo ti tiene tienen todo todos tu tus un una unas uno unos usa usan usar vez y ya yo
puede pueden puedo podes podria podrias debe deben seria sera cuyo
quiero necesito explicame explica explicar explicas decime dime ayuda ayudame favor dudas duda entender entiendo
significa significan sirve sirven saber ejemplo ejemplos
""".split())

SIMBOLOS = [  # simbolo -> palabra (se aplica a la consulta y a las fichas)
    ("∂", " parcial "), ("∇", " gradiente "), ("∫", " integral "), ("√", " raiz "),
    ("≠", " distinto "), ("∞", " infinito "), ("→", " tiende "), ("′", " derivada "),
]

# Notacion que, tal cual, se perderia (las letras sueltas se descartan). Se aplica a fichas Y consultas.
ALIAS_SIMETRICO = [
    (r"\bf\s*\(\s*x\s*,\s*y\b|\(\s*x\s*,\s*y\s*\)", " dos variables "),   # f(x,y), (x,y)
    (r"\bd_?\{?u\}?\s*f\b", " derivada direccional "),                           # D_u f, Duf
    (r"\bd\s*/\s*d[a-z]\b|\b[a-z]\s*'\s*\(", " derivada "),                     # d/dx, f'(x)
]
# Como lo dicen los alumnos vs. como figura en las fichas. Solo se aplica a la CONSULTA.
ALIAS_CONSULTA = [
    (r"\bmaxim\w*|\bminim\w*", " extremo "),   # "maximos y minimos" -> fichas de extremos
]

# Temas que el apendice del documento declara "mencionados sin desarrollo suficiente".
# Clave = nombre exacto en el JSON (temas_sin_cobertura); valor = expresion regular (sobre el texto
# normalizado, sin tildes) que delata que el alumno pregunta por ese tema. scripts/check_fichas.py avisa
# si el documento agrega un tema al apendice que no tiene regla aca.
TEMAS_SIN_COBERTURA = {
    "Derivadas trigonométricas como bloque sistemático": r"\btrigonom\w*|\bsenos?\b|\bcosenos?\b",
    "Derivación implícita": r"\bimplicit\w*",
    "Concavidad y puntos de inflexión": r"\bconcav\w*|\bconvex\w*|\binflexi\w*",
    "Teorema de Rolle como unidad independiente": r"\brolle\b",
    "Regla de L’Hôpital": r"\bl\s?'?\s?hopital\b|\blhopital\b",
    "Problemas de optimización mediante derivadas como procedimiento completo": r"\boptimiz\w*",
    "Estudio completo de funciones mediante derivadas como secuencia formal": r"\bestudio completo\b|\bestudiar (?:una |la )?funcion completa\b",
}


def normalizar(texto, es_consulta=False):
    t = str(texto)
    for sim, palabra in SIMBOLOS:
        t = t.replace(sim, palabra)
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    alias = ALIAS_SIMETRICO + (ALIAS_CONSULTA if es_consulta else [])
    for patron, reemplazo in alias:
        t = re.sub(patron, lambda m, r=reemplazo: m.group(0) + r, t)
    return t


def raiz(palabra):
    if len(palabra) > 3 and palabra.endswith("s"):
        palabra = palabra[:-1]
    return palabra[:STEM_LEN]


def tokenizar(texto, es_consulta=False):
    """Lista de raices (sin palabras vacias, sin letras sueltas)."""
    palabras = re.findall(r"[a-z0-9]+", normalizar(texto, es_consulta))
    return [raiz(p) for p in palabras if p not in STOPWORDS and len(p) > 1]


def _bigramas(tokens):
    return {(tokens[i], tokens[i + 1]) for i in range(len(tokens) - 1)}


# ---------------------------------------------------------------- carga e indice (una vez)
_DATOS = None
_INDICE = None


def _cargar():
    global _DATOS, _INDICE
    if _INDICE is not None:
        return _INDICE
    try:
        with open(RUTA_JSON, "r", encoding="utf-8") as f:
            _DATOS = json.load(f)
    except Exception as e:
        print(f"--> [FICHAS] No se pudo cargar {RUTA_JSON}: {e}. Se continúa sin fichas.")
        _DATOS, _INDICE = {"fichas": []}, {"docs": [], "idf": {}, "avg_len": 1.0}
        return _INDICE

    docs, df = [], {}
    for ficha in _DATOS["fichas"]:
        tf, longitud = {}, 0.0
        for campo, peso in PESOS_CAMPO.items():
            for tok in tokenizar(ficha.get(campo, "")):
                tf[tok] = tf.get(tok, 0.0) + peso
                longitud += peso
        frases = set()
        for campo in ("titulo", "pregunta", "origen"):
            frases |= _bigramas(tokenizar(ficha.get(campo, "")))
        docs.append({"ficha": ficha, "tf": tf, "len": longitud, "frases": frases,
                     "titulo": set(tokenizar(ficha.get("titulo", "")))})
        for tok in tf:
            df[tok] = df.get(tok, 0) + 1

    n = len(docs)
    idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
    avg = sum(d["len"] for d in docs) / max(n, 1)
    _INDICE = {"docs": docs, "idf": idf, "avg_len": avg or 1.0}
    print(f"--> [FICHAS] {n} fichas cargadas (versión {_DATOS.get('version', '?')}).")
    return _INDICE


def estado():
    """Resumen para /api/health."""
    _cargar()
    return {"fichas": len(_DATOS["fichas"]), "version": _DATOS.get("version", "")}


def tema_sin_cobertura(pregunta):
    """Devuelve el nombre del tema del apendice al que apunta la pregunta, o None."""
    texto = normalizar(pregunta, es_consulta=True)
    for nombre, patron in TEMAS_SIN_COBERTURA.items():
        if re.search(patron, texto):
            return nombre
    return None


def puntuar(pregunta):
    """[(puntaje, normalizado, ficha)] de mayor a menor, SIN aplicar umbrales (para depurar/calibrar).

    'normalizado' = puntaje / suma del peso (idf) de las palabras de la pregunta: mide que proporcion de lo que
    pregunto el alumno esta cubierta por la ficha, y permite comparar preguntas cortas con largas.
    """
    indice = _cargar()
    consulta = tokenizar(pregunta, es_consulta=True)
    if not consulta:
        return []
    idf, avg = indice["idf"], indice["avg_len"]
    idf_desconocida = UNKNOWN_W * (max(idf.values()) if idf else 0.0)
    cota = sum(idf.get(t, idf_desconocida) for t in set(consulta)) or 1.0
    frases_q = _bigramas(consulta)
    q_set = set(consulta)
    resultados = []
    for d in indice["docs"]:
        s = 0.0
        for tok in set(consulta):
            f = d["tf"].get(tok)
            if not f:
                continue
            s += idf.get(tok, 0.0) * (f * (BM25_K1 + 1)) / (f + BM25_K1 * (1 - BM25_B + BM25_B * d["len"] / avg))
        s += BONUS_FRASE * len(frases_q & d["frases"])
        union = q_set | d["titulo"]
        if union and (q_set & d["titulo"]):
            s += BONUS_TITULO * len(q_set & d["titulo"]) / len(union)
        if s > 0:
            resultados.append((s, s / cota, d["ficha"]))
    resultados.sort(key=lambda x: x[0], reverse=True)
    return resultados


def buscar_fichas(pregunta, limite=3):
    """Fichas relevantes para la pregunta (lista de dicts, la mejor primero) o [] si no hay ninguna confiable."""
    if tema_sin_cobertura(pregunta):
        return []
    ranking = puntuar(pregunta)
    if not ranking:
        return []
    mejor, norm_mejor, _ = ranking[0]
    pasa_normal = norm_mejor >= NORM_MIN and mejor >= ABS_MIN
    pasa_fuerte = mejor >= ABS_FUERTE and norm_mejor >= NORM_MIN_FUERTE
    if not (pasa_normal or pasa_fuerte):
        return []
    elegidas = []
    for s, norm, ficha in ranking[:limite]:
        if s >= RATIO_MIN * mejor:
            elegidas.append(dict(ficha, score=round(s, 2), score_norm=round(norm, 2)))
    return elegidas


def buscar_fichas_repregunta(pregunta, pregunta_previa, limite=3):
    """Para repreguntas ("no entendi por que dividiste por 5") que solas no encuentran ficha: busca con la pregunta
    anterior + la actual. Una ficha solo se acepta si la pregunta ACTUAL tambien coincide con ella (puntaje >= ABS_MIN):
    asi un cambio de tema ("receta de keke") no arrastra las fichas de la pregunta anterior."""
    if not pregunta_previa:
        return []
    fichas = buscar_fichas(pregunta_previa + "\n" + pregunta, limite=limite)
    if not fichas:
        return []
    propio = {f["id"]: sc for sc, _, f in puntuar(pregunta)}
    return [f for f in fichas if propio.get(f["id"], 0.0) >= ABS_MIN]


# ---------------------------------------------------------------- formato para el modelo y para el log
def formatear_fichas(fichas):
    """Texto en espanol que se inyecta en el prompt del modelo."""
    bloques = []
    for f in fichas:
        lineas = [f"[FICHA {f['id']} · {f['titulo']}]", f"Pregunta: {f['pregunta']}", f"Respuesta: {f['respuesta']}"]
        if f.get("complemento"):
            lineas.append(f"Complemento: {f['complemento']}")
        if f.get("ejemplo"):
            lineas.append(f"Ejemplo: {f['ejemplo']}")
        if f.get("nota"):
            lineas.append(f"Nota de precisión: {f['nota']}")
        bloques.append("\n".join(lineas))
    return "\n\n".join(bloques)


def etiqueta_log(fichas):
    """Texto corto para la columna 'subtema' del log (la ve el profesor al revisar)."""
    if not fichas:
        return ""
    base = f"{fichas[0]['id']} {fichas[0]['titulo']}"
    extra = [f["id"] for f in fichas[1:]]
    return base + (f" (+ {', '.join(extra)})" if extra else "")
