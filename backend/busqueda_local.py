import pickle
import os
import re
import unicodedata

BIBLIOTECA = {
    "calculo1": "calculus-volume-1.pdf", 
    "calculo2": "calculus-volume-2.pdf", 
    "calculo3": "calculus-volume-3.pdf"
}

# Diccionario matemático estático para traducir términos clave en 0ms
DICCIONARIO_TECNICO = {
    "derivada": "derivative",
    "derivadas": "derivatives",
    "recta tangente": "tangent line",
    "limite": "limit",
    "limites": "limits",
    "integrales": "integrals",
    "integral": "integral",
    "serie": "series",
    "sucesion": "sequence",
    "sucesiones": "sequences",
    "convergencia": "convergence",
    "divergencia": "divergence",
    "potencias": "power series",
    "vector": "vector",
    "vectores": "vectors",
    "parcial": "partial",
    "superficie": "surface",
    "gradiente": "gradient",
    "stokes": "stokes",
    "optimizacion": "optimization",
    # [FIX] "lhopital" apuntaba a "l'hopital", que no es un termino del indice (el tokenizador del indice
    # lo deja como "pital"). Se agregan ademas los temas que las fichas declaran sin cobertura, para que
    # la consulta caiga en el libro y no quede sin contexto.
    "lhopital": "pital",
    "hopital": "pital",
    "derivacion": "differentiation",
    "implicita": "implicit",
    "concavidad": "concavity",
    "inflexion": "inflection",
    "rolle": "rolle",
    "trigonometrica": "trigonometric",
    "trigonometricas": "trigonometric",
    "seno": "sine",
    "coseno": "cosine"
}

INDICES_CARGADOS = {}


def _sin_tildes(texto):
    """[FIX] Los alumnos escriben con tildes ("límite", "derivación") y el diccionario y las listas de
    palabras clave estan sin tildes: antes esas palabras no coincidian con nada y la consulta quedaba sin contexto."""
    t = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in t if not unicodedata.combining(c))

def cargar_indice_en_memoria(nombre_libro_clave):
    """Carga el diccionario completo (.pkl) con matriz TF-IDF y chunks de texto."""
    if nombre_libro_clave in INDICES_CARGADOS:
        return INDICES_CARGADOS[nombre_libro_clave]
        
    # Ajustá la ruta según la estructura de tus carpetas (aquí asumo que están en /books)
    ruta_pkl = os.path.join(os.path.dirname(__file__), "books", f"{nombre_libro_clave}_index.pkl")
    
    # Si los dejaste en la raíz junto al script, podés usar este fallback:
    if not os.path.exists(ruta_pkl):
        ruta_pkl = f"indice_calculo.pkl" if nombre_libro_clave == "calculo1" else f"{nombre_libro_clave}_index.pkl"

    if os.path.exists(ruta_pkl):
        with open(ruta_pkl, "rb") as f:
            INDICES_CARGADOS[nombre_libro_clave] = pickle.load(f)
        return INDICES_CARGADOS[nombre_libro_clave]
    return None

def seleccionar_libro(texto_consulta):
    """Analiza el texto de la consulta y asigna el tomo correcto de OpenStax y su clave."""
    tema = str(texto_consulta).lower().strip()

    if any(w in tema for w in ["integracion multiple", "multiple", "triple", "multivariable", "parcial", "calculo vectorial", "vectores", "superficie", "gradiente", "stokes"]):
        return BIBLIOTECA["calculo3"], "calculo3"
    elif any(w in tema for w in ["serie", "sucesion", "converg", "diverg", "potencias", "ecuacion diferencial", "tecnicas de integracion", "fracciones parciales", "por partes"]):
        return BIBLIOTECA["calculo2"], "calculo2"
    
    return BIBLIOTECA["calculo1"], "calculo1"


def buscar_en_pdf(pregunta_alumno, limite_chunks=3, detalle=None):
    """
    Busca de forma ultra rápida en el índice invertido utilizando pesos TF-IDF 
    y devuelve los bloques de texto (chunks) más relevantes consolidados.
    Si se pasa una lista en `detalle`, se le agrega un dict por fragmento recuperado (libro, id, sección, páginas,
    puntaje y texto): sirve para dejar registrado en el log qué material se le dio al modelo.
    """
    pregunta_alumno = _sin_tildes(pregunta_alumno)

    # 1. Selección del Libro
    libro_archivo, libro_clave = seleccionar_libro(pregunta_alumno)
    
    # 2. Tokenizar y limpiar la pregunta del alumno
    pregunta_limpia = "".join(c for c in pregunta_alumno.lower() if c.isalnum() or c in [" "]).strip()
    palabras_alumno = [p for p in pregunta_limpia.split() if len(p) > 3]

    # 3. Traducir palabras clave usando el diccionario estático
    palabras_ingles = []
    for p in palabras_alumno:
        if p in DICCIONARIO_TECNICO:
            palabras_ingles.append(DICCIONARIO_TECNICO[p])
        else:
            for clave, traduccion in DICCIONARIO_TECNICO.items():
                if clave in p or p in clave:
                    palabras_ingles.append(traduccion)

    # Si no hubo traducción técnica directa, usamos los términos originales
    if not palabras_ingles:
        palabras_ingles = palabras_alumno[:3]

    print(f"   [RAG] Libro detectado: {libro_archivo} | Palabras de búsqueda: {palabras_ingles}")
    
    if not palabras_ingles:
        return None
        
    # 4. Carga del paquete de indexación mapeado en memoria
    paquete_datos = cargar_indice_en_memoria(libro_clave)
    if not paquete_datos:
        print(f"   [AVISO] No se encontró el índice binario estructurado para {libro_clave}.")
        return None

    # Desempaquetamos la nueva estructura del .pkl
    indice_invertido = paquete_datos["index"]
    referencias_chunks = paquete_datos["chunks_reference"]

    # Diccionario para acumular los scores de relevancia por chunk
    scores_candidatos = {}

    # Acumulamos el score de relevancia matemática de los chunks candidatos
    for palabra in palabras_ingles:
        if palabra in indice_invertido:
            for chunk_id, score_tf_idf in indice_invertido[palabra].items():
                scores_candidatos[chunk_id] = scores_candidatos.get(chunk_id, 0.0) + score_tf_idf

    if not scores_candidatos:
        print(f"   [AVISO] No se encontraron coincidencias en el vocabulario para: {palabras_ingles}")
        return None

    # Ordenamos los candidatos de mayor a menor relevancia
    candidatos_ordenados = sorted(scores_candidatos.items(), key=lambda x: x[1], reverse=True)
    top_candidatos = candidatos_ordenados[:limite_chunks]

    # Concatener los mejores fragmentos en un único string de contexto para alimentar tu LLM/Ollama
    contexto_consolidado = ""
    print(f"   [ÉXITO RAG] Se encontraron {len(top_candidatos)} chunks relevantes ordenados por TF-IDF:")
    
    for rank, (chunk_id, score_final) in enumerate(top_candidatos, 1):
        ref = referencias_chunks[chunk_id]
        print(f"       -> [{rank}] ID: {chunk_id} (Score: {score_final:.4f}) | Sección: {ref['seccion']} | Páginas PDF: {ref['paginas']}")
        
        if detalle is not None:
            detalle.append({"libro": libro_archivo, "chunk": chunk_id, "seccion": ref["seccion"],
                            "paginas": ref["paginas"], "score": round(float(score_final), 4), "texto": ref["contenido"]})

        # Le inyectamos una pequeña cabecera al texto para guiar al modelo si es necesario
        contexto_consolidado += f"--- [Fragmento de la Sección {ref['seccion']}, Páginas del PDF: {ref['paginas']}] ---\n"
        contexto_consolidado += f"{ref['contenido']}\n\n"

    return contexto_consolidado.strip()