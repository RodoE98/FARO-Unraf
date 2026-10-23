from fastapi import FastAPI, HTTPException, Request, Form
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import hashlib
from pydantic import BaseModel, Field
from typing import Optional
import os
import time
from ollama import AsyncClient, Client
import asyncio
from concurrent.futures import ThreadPoolExecutor

# Los únicos componentes reales de la raíz que necesitamos
from pylti1p3.tool_config import ToolConfJsonFile
from pylti1p3.request import Request as LTIRequest
from pylti1p3.message_launch import MessageLaunch
from pylti1p3.oidc_login import OIDCLogin

# Importaciones de tus módulos locales
from database import init_db, registrar_log, inicializar_tabla_profesores, registrar_feedback_profesor, es_profesor_autorizado, get_connection
from subtemas import SUBTEMAS_VALIDOS
from models import ChatResponse # Mantenemos ChatResponse de models
from busqueda_local import buscar_en_pdf
from busqueda_fichas import buscar_fichas, formatear_fichas, etiqueta_log, estado as estado_fichas

class CustomFastAPIOIDCLogin(OIDCLogin):
    def __init__(self, request: Request, tool_config):
        self._request = request
        lti_request = LTIRequest({
            'get': dict(request.query_params),
            'post': {}
        })
        super().__init__(lti_request, tool_config)

    def redirect(self, url):
        return RedirectResponse(url=url, status_code=302)


class CustomFastAPIMessageLaunch(MessageLaunch):
    def __init__(self, request: Request, tool_config, form_data: dict):
        self._request = request
        lti_request = LTIRequest({
            'get': {},
            'post': form_data
        })
        super().__init__(lti_request, tool_config)

app = FastAPI(title="Faro Chatbot UNRaf")

# Permitimos que Lovable se conecte (podés dejar "*" para desarrollo)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En desarrollo, el asterisco te salva la vida con las urls de Lovable
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIGURACIÓN DE CONCURRENCIA ---
executor = ThreadPoolExecutor(max_workers=3)

# --- [FIX] CONFIGURACIÓN DEL MODELO ---
# Todo se puede cambiar con variables de entorno, sin tocar el código.
# Ej:  LLM_MODEL=qwen2.5:7b uvicorn main:app --host 0.0.0.0 --port 8000
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")  # el backend corre en el mismo pod que Ollama
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:14b")                 # antes: 'phi3:mini' hardcodeado en 2 lugares
NUM_CTX = int(os.getenv("NUM_CTX", "8192"))                       # ventana de contexto (tokens). Usar SIEMPRE el mismo valor
                                                                  # en todas las llamadas: si cambia, Ollama recarga el modelo.
RAG_CHUNKS = int(os.getenv("RAG_CHUNKS", "4"))                    # fragmentos del PDF que se envían al modelo
MAX_CONTEXT_CHARS = int(os.getenv("MAX_CONTEXT_CHARS", "12000"))  # tope de seguridad (~3000 tokens) para el contexto del PDF
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "600"))                  # tope de respuesta (red de seguridad, no el control de largo)
RENDER_LATEX = os.getenv("RENDER_LATEX", "0") == "1"              # poner 1 SOLO si el frontend renderiza LaTeX (KaTeX/MathJax)
CLASSIFY_TOPIC = os.getenv("CLASSIFY_TOPIC", "0") == "1"          # poner 1 para llenar la columna 'subtema' que ven los profesores

# --- FICHAS DOCENTES (corpus de derivadas curado por la cátedra) ---
USE_FICHAS = os.getenv("USE_FICHAS", "1") == "1"                  # 0 = ignorar las fichas (sirve para comparar con/sin fichas)
FICHAS_MAX = int(os.getenv("FICHAS_MAX", "3"))                    # máximo de fichas que se envían al modelo por consulta
RAG_CHUNKS_CON_FICHAS = int(os.getenv("RAG_CHUNKS_CON_FICHAS", "2"))  # fragmentos del libro cuando SÍ hay fichas (las fichas son la fuente principal)

GEN_OPTIONS = {
    "temperature": 0.1,
    "seed": 42,                 # respuestas reproducibles para comparar cambios
    "num_ctx": NUM_CTX,
    "num_predict": MAX_TOKENS,
}

# Clientes únicos (antes se creaba un AsyncClient nuevo en cada request)
ollama_async = AsyncClient(host=OLLAMA_HOST)
ollama_sync = Client(host=OLLAMA_HOST)

# --- MODELOS DE DATOS ---
# Definimos ChatRequest aquí mismo para evitar confusiones de importación
class ChatRequest(BaseModel):
    user_id: str
    course_id: str
    role: str
    pregunta: str
    confidence: int = Field(..., ge=1, le=3)

class FeedbackProfesorRequest(BaseModel):
    email: str = Field(..., example="elias.profesor@unraf.edu.ar", description="Email del profesor autenticado")
    pregunta_original: str = Field(..., example="¿Qué es una dirección IP?", description="La pregunta que se le hizo al bot")
    respuesta_bot: str = Field(..., example="Es un número único...", description="La respuesta que arrojó el bot")
    calificacion: str = Field(..., example="negativo", description="Debe ser 'positivo' o 'negativo'")
    correccion_sugerida: Optional[str] = Field(None, example="Faltó explicar IPv4 e IPv6", description="Comentario o respuesta corregida por el docente (opcional)")

def hashear_usuario(username: str):
    return hashlib.sha256(username.encode()).hexdigest()

def _nombres_modelos(resp) -> list:
    """Extrae los nombres de modelos de ollama.list() (funciona con versiones nuevas y viejas del paquete)."""
    modelos = resp.get("models", []) if isinstance(resp, dict) else getattr(resp, "models", [])
    nombres = []
    for m in modelos:
        if isinstance(m, dict):
            n = m.get("model") or m.get("name")
        else:
            n = getattr(m, "model", None) or getattr(m, "name", None)
        if n:
            nombres.append(n)
    return nombres


def _modelo_disponible(nombres: list) -> bool:
    return LLM_MODEL in nombres or f"{LLM_MODEL}:latest" in nombres


async def _precalentar_modelo():
    """[FIX] Verifica que el modelo esté instalado y lo carga en VRAM al arrancar,
    así el primer alumno no espera la carga del modelo."""
    try:
        nombres = _nombres_modelos(await ollama_async.list())
        if not _modelo_disponible(nombres):
            print(f"!!! El modelo '{LLM_MODEL}' NO está instalado en Ollama. Ejecutá:  ollama pull {LLM_MODEL}")
            return
        await ollama_async.generate(model=LLM_MODEL, prompt="", keep_alive=-1, options={"num_ctx": NUM_CTX})
        print(f"--> Modelo '{LLM_MODEL}' cargado en memoria (num_ctx={NUM_CTX}).")
    except Exception as e:
        print(f"!!! No se pudo contactar a Ollama en {OLLAMA_HOST}: {e}")


@app.on_event("startup")
async def startup_event():
    init_db()
    inicializar_tabla_profesores()
    os.makedirs("uploads", exist_ok=True)
    # En segundo plano para no demorar el arranque del servidor
    app.state.warmup_task = asyncio.create_task(_precalentar_modelo())


@app.get("/api/health")
async def health():
    """[FIX] Lo usa run_runpod.ps1 para avisar si el backend o el modelo no están listos."""
    try:
        nombres = _nombres_modelos(await ollama_async.list())
        return {
            "status": "ok",
            "ollama_reachable": True,
            "model": LLM_MODEL,
            "model_available": _modelo_disponible(nombres),
            "fichas": estado_fichas() if USE_FICHAS else None,
        }
    except Exception as e:
        print(f"--> [HEALTH] Ollama no responde en {OLLAMA_HOST}: {e}")
        return {"status": "degraded", "ollama_reachable": False, "model": LLM_MODEL, "model_available": False}


# --- [FIX] SYSTEM PROMPT ---
# Reescrito para ser corto, 100% en español, sin reglas contradictorias y sin instrucciones
# específicas de un solo tema (antes los niveles hablaban sólo de derivadas parciales).
# El largo se controla con límites de palabras concretos, no con "sé extremadamente conciso".

_BASE_PROMPT = """Sos un profesor universitario argentino de matemática: riguroso, claro y preciso. Respondés siempre en español.

REGLAS:
1. Sé conciso: respondé sólo lo que se pregunta, sin introducciones enciclopédicas ni repetir la pregunta.
2. Mostrá los pasos clave del razonamiento y destacá el resultado final.
3. Si hay un cálculo, verificá cada paso antes de escribir el resultado. No inventes pasos ni resultados.
4. Si no estás seguro de algo, decilo en lugar de adivinar.
5. Terminá siempre con una idea completa, sin dejar oraciones a medias."""

# Con material del libro: respuesta anclada al contexto (igual que el diseño original).
_CON_CONTEXTO = """MATERIAL: recibirás fragmentos de un libro de texto (en inglés) como CONTEXTO. Basá tu respuesta en ese contexto y no agregues resultados que no se desprendan de él. Si el contexto no permite responder la pregunta, respondé exactamente esta frase y nada más: No puedo responder a esto basándome en el material proporcionado."""

# Sin material: antes el prompt seguía diciendo "usá EXCLUSIVAMENTE el contexto" aunque no hubiera ninguno.
# Con fichas de la cátedra: son la fuente principal y el libro (si llega) solo complementa.
_CON_FICHAS = """MATERIAL: recibirás FICHAS DE LA CÁTEDRA (material docente curado, en español) y, a veces, FRAGMENTOS DE UN LIBRO DE TEXTO (en inglés). Las fichas son tu fuente principal: usá sus definiciones, fórmulas y notas de precisión tal como figuran y respetá las condiciones e hipótesis que indican. Usá el libro sólo para complementar y, si algo lo contradice, seguí la ficha. No agregues resultados que no se desprendan de este material. Si el material no permite responder la pregunta, respondé exactamente esta frase y nada más: No puedo responder a esto basándome en el material proporcionado."""

_SIN_CONTEXTO = """MATERIAL: no se encontró material del libro para esta consulta. Respondé con tu conocimiento matemático estándar de nivel universitario, con especial cuidado en la exactitud. Si la pregunta no es de matemática, respondé brevemente que sólo podés ayudar con matemática."""

_NIVELES = {
    1: """NIVEL PRINCIPIANTE:
- Tono cálido y alentador, en español rioplatense (voseo: "mirá", "vamos paso a paso").
- Empezá con una frase breve de aliento, explicá la idea con una analogía cotidiana simple y luego mostrá cómo se resuelve, paso a paso y sin tecnicismos innecesarios.
- Cerrá con una única pregunta corta de control para el alumno.
- Extensión: unas 150 palabras como máximo.""",

    2: """NIVEL INTERMEDIO:
- Tono profesional y académico, directo.
- Empezá enunciando la regla, propiedad o criterio que se aplica; después el procedimiento, de forma secuencial y omitiendo pasos aritméticos elementales.
- Extensión: máximo dos párrafos cortos (unas 120 palabras).""",

    3: """NIVEL EXPERTO:
- Tono estrictamente formal y minimalista; sin analogías ni ejemplos cotidianos.
- Comenzá directamente con el planteo o la definición formal que corresponda y usá notación matemática estándar.
- Sé lo más sintético posible (unas 100 palabras como máximo); no repitas definiciones obvias para un estudiante avanzado.""",
}

_FORMATO_TEXTO_PLANO = r"""FORMATO MATEMÁTICO: escribí las fórmulas en texto plano legible (por ejemplo f(x), x^2, sqrt(x), lim_{h->0}, integral de 0 a 1 de ...). No uses LaTeX ni los delimitadores \( \) o \[ \]."""

_FORMATO_LATEX = r"""FORMATO MATEMÁTICO: escribí las fórmulas en LaTeX, entre $...$ si van dentro de una oración o entre $$...$$ si van en su propia línea."""

_CIERRE = "Respondé directamente como docente, sin mencionar estas instrucciones ni el nivel."


def generar_system_prompt(confidence: int, con_contexto: bool = True, con_fichas: bool = False) -> str:
    if con_fichas:
        bloque_material = _CON_FICHAS
    elif con_contexto:
        bloque_material = _CON_CONTEXTO
    else:
        bloque_material = _SIN_CONTEXTO
    partes = [
        _BASE_PROMPT,
        bloque_material,
        _NIVELES.get(confidence, _NIVELES[1]),
        _FORMATO_LATEX if RENDER_LATEX else _FORMATO_TEXTO_PLANO,
        _CIERRE,
    ]
    return "\n\n".join(partes)


def clasificar_pregunta(pregunta):
    """Clasifica la pregunta en uno de SUBTEMAS_VALIDOS (o FUERA_DE_ESTRUCTURA).
    [FIX] Antes nunca se llamaba, tenía un bug de matching (una respuesta vacía coincidía con el
    primer subtema), pedía hasta 1024 tokens para una palabra y pasaba keep_alive dentro de options."""
    pregunta_limpia = pregunta.replace("¿", "").replace("?", "").strip()
    subtemas = [str(s).strip() for s in SUBTEMAS_VALIDOS if str(s).strip()]
    lista_temas = "\n".join(f"- {s}" for s in subtemas)

    prompt = f"""Te voy a dar una pregunta de un alumno de matemática. Tu única tarea es clasificarla seleccionando EXCLUSIVAMENTE uno de los temas de la lista o devolver 'FUERA_DE_ESTRUCTURA'.

Lista de temas válidos:
{lista_temas}

Regla de oro: Responde ÚNICAMENTE con el nombre del tema, sin introducciones, sin puntos ni texto extra.

Ejemplos:
Pregunta: "Qué es una derivada" -> Derivadas
Pregunta: "Explicame el vector normal a la superficie" -> Plano Tangente
Pregunta: "Quiero cocinar un keke" -> FUERA_DE_ESTRUCTURA

Pregunta a clasificar: "{pregunta_limpia}"
Respuesta:"""

    try:
        response = ollama_sync.generate(
            model=LLM_MODEL,
            prompt=prompt,
            # mismo num_ctx que el chat: si difiere, Ollama recarga el modelo en cada llamada
            options={"temperature": 0, "num_ctx": NUM_CTX, "num_predict": 32},
            keep_alive=-1,
        )

        bruta = response["response"].strip().replace("Respuesta:", "").strip()
        print(f"--> [DEBUG OLLAMA OUT] El modelo respondió textualmente: '{bruta}'")

        linea = bruta.split("\n")[0].strip().strip("\"'`. ").lower()
        if not linea or "fuera_de_estructura" in linea:
            return "FUERA_DE_ESTRUCTURA"

        # 1) coincidencia exacta (sin distinguir mayúsculas)
        for s in subtemas:
            if s.lower() == linea:
                print(f"--> [DEBUG MATCH] Mapeado a: '{s}'")
                return s

        # 2) el modelo agregó texto extra: elegimos el subtema más largo que aparezca mencionado
        candidatos = [s for s in subtemas if s.lower() in bruta.lower()]
        if candidatos:
            elegido = max(candidatos, key=len)
            print(f"--> [DEBUG MATCH] Mapeado a: '{elegido}'")
            return elegido

        return "FUERA_DE_ESTRUCTURA"

    except Exception as e:
        print(f"Error en clasificación: {e}")
        return "FUERA_DE_ESTRUCTURA"


# --- ENDPOINT PRINCIPAL MODIFICADO ---
@app.post("/api/chat")
async def chat_endpoint(chat_data: ChatRequest, request: Request):
    loop = asyncio.get_event_loop()
    user_hash = hashear_usuario(chat_data.user_id)

    print("\n================ DATO RECIBIDO DEL FRONT ================")
    print(f"Pregunta de: {chat_data.user_id} -> '{chat_data.pregunta}'")
    print("=========================================================\n")

    # --- FICHAS DOCENTES (fuente principal) ---
    # Búsqueda en memoria sobre 63 fichas: tarda milisegundos, no hace falta un hilo aparte.
    fichas = []
    if USE_FICHAS:
        try:
            fichas = buscar_fichas(chat_data.pregunta, limite=FICHAS_MAX)
        except Exception as e:
            print(f"--> [FICHAS] Error en la búsqueda, se continúa sin fichas: {e}")
    if fichas:
        print("--> [FICHAS] " + ", ".join(f"{f['id']} (puntaje {f['score']}, norm {f['score_norm']})" for f in fichas))
    else:
        print("--> [FICHAS] Ninguna ficha relevante: se responde con el libro (OpenStax).")

    # --- BÚSQUEDA LOCAL DIRECTA EN PDF (RAG) ---
    print("3. Consultando biblioteca de PDFs con la pregunta directa...")
    inicio_rag = time.perf_counter()

    # [FIX] Antes: limite_chunks=5 fijo (el comentario decía 2) y sin tope de tamaño,
    # lo que desbordaba la ventana de contexto de phi3 y truncaba el prompt en silencio.
    contexto_pdf = await loop.run_in_executor(
        executor, lambda: buscar_en_pdf(chat_data.pregunta, limite_chunks=RAG_CHUNKS_CON_FICHAS if fichas else RAG_CHUNKS)
    )
    if isinstance(contexto_pdf, (list, tuple)):
        contexto_pdf = "\n\n---\n\n".join(str(c) for c in contexto_pdf)
    contexto_pdf = str(contexto_pdf).strip() if contexto_pdf else ""
    if len(contexto_pdf) > MAX_CONTEXT_CHARS:
        print(f"--> [AVISO] Contexto PDF recortado de {len(contexto_pdf)} a {MAX_CONTEXT_CHARS} caracteres.")
        contexto_pdf = contexto_pdf[:MAX_CONTEXT_CHARS]

    print(f"⏱️ [TIEMPO] Búsqueda local en PDF: {time.perf_counter() - inicio_rag:.4f} segundos")

    # La columna 'subtema' del log (la que ve el profesor) pasa a indicar qué fichas se usaron:
    # así, ante una respuesta incorrecta, se sabe si falló la ficha, la búsqueda o el modelo.
    tema_log = etiqueta_log(fichas) if fichas else "Consulta General / RAG"
    if fichas and contexto_pdf:
        fuente_info = "FICHAS + PDF LOCAL"
    elif fichas:
        fuente_info = "FICHAS"
    elif contexto_pdf:
        fuente_info = "PDF LOCAL (Inglés)"
    else:
        fuente_info = "CONOCIMIENTO GENERAL"

    # [FIX] El prompt del sistema depende de qué material hay (fichas / libro / ninguno)
    system_content = generar_system_prompt(chat_data.confidence, con_contexto=bool(contexto_pdf), con_fichas=bool(fichas))

    if fichas:
        bloque_libro = f"""FRAGMENTOS DEL LIBRO DE TEXTO (en inglés):
{contexto_pdf}

""" if contexto_pdf else ""
        full_prompt = f"""FICHAS DE LA CÁTEDRA:
{formatear_fichas(fichas)}

{bloque_libro}PREGUNTA DEL ESTUDIANTE:
{chat_data.pregunta}"""
    elif contexto_pdf:
        full_prompt = f"""CONTEXTO (fragmentos de un libro de texto en inglés):
{contexto_pdf}

PREGUNTA DEL ESTUDIANTE:
{chat_data.pregunta}"""
    else:
        full_prompt = chat_data.pregunta

    print(f"4. Iniciando flujo Ollama Nativo Asincrónico (Modo: {fuente_info}, modelo: {LLM_MODEL})...")

    async def generador_de_respuesta():
        respuesta_completa = ""
        tokens_generados = 0
        inicio_gen = time.perf_counter()
        primer_token = False

        try:
            # 🚀 LLAMADA ASINCRÓNICA NATIVA: No bloquea el loop de FastAPI durante el prefill
            # [FIX] keep_alive va como argumento de nivel superior (dentro de options Ollama lo ignora).
            response_stream = await ollama_async.chat(
                model=LLM_MODEL,
                messages=[
                    {'role': 'system', 'content': system_content},
                    {'role': 'user', 'content': full_prompt},
                ],
                options=GEN_OPTIONS,
                keep_alive=-1,
                stream=True
            )

            # 🌟 Iteramos usando 'async for' para liberar recursos mientras llega cada token
            async for chunk in response_stream:
                if await request.is_disconnected():
                    print("!!! CLIENTE DESCONECTADO: Cancelando Ollama en la GPU/CPU.")
                    # [FIX] Cerramos el stream explícitamente para que Ollama deje de generar
                    try:
                        await response_stream.aclose()
                    except Exception:
                        pass
                    return

                token = chunk['message']['content']
                respuesta_completa += token
                tokens_generados += 1

                if not primer_token:
                    print(f"⏱️ [TIEMPO] TTFT (Primer token real): {time.perf_counter() - inicio_gen:.4f} segundos")
                    primer_token = True

                yield token

            print(f"⏱️ [TIEMPO] Generación completa: {time.perf_counter() - inicio_gen:.4f} segundos ({tokens_generados} tokens)")

        except Exception as e:
            print(f"ERROR EN STREAM: {e}")
            yield f"\n[Error en el servidor: {str(e)}]"
            return

        # Registro en BD (la respuesta ya fue entregada completa al alumno)
        # [FIX] Antes estaba dentro del mismo try: si fallaba el log, se le mostraba el error al alumno
        # pegado al final de una respuesta correcta. Ahora un fallo de log sólo se imprime en consola.
        try:
            tema = tema_log
            if CLASSIFY_TOPIC:
                tema = await loop.run_in_executor(executor, clasificar_pregunta, chat_data.pregunta)
            await loop.run_in_executor(
                executor,
                registrar_log,
                user_hash,
                chat_data.course_id,
                chat_data.role,
                tema,
                chat_data.pregunta,
                respuesta_completa
            )
        except Exception as e:
            print(f"ERROR AL REGISTRAR LOG: {e}")

    return StreamingResponse(generador_de_respuesta(), media_type="text/plain")

@app.on_event("shutdown")
def shutdown_event():
    print("Cerrando servidor... Matando procesos colgados de Ollama.")
    executor.shutdown(wait=False)
    # OPCIONAL: Si estás en Windows y querés matar a Ollama al cerrar todo
    # os.system("taskkill /IM ollama_llama_server.exe /F")

# Inicializamos la lectura del archivo de configuración que creaste recién
CONFIG_LTI_PATH = os.path.join(os.path.dirname(__file__), 'lti_config.json')
tool_conf = ToolConfJsonFile(CONFIG_LTI_PATH)

# ENDPOINT 1: Inicio del flujo OIDC
@app.api_route("/lti/login", methods=["GET", "POST"])
async def lti_login(request: Request):
    try:
        oidc_login = CustomFastAPIOIDCLogin(request, tool_conf)
        target_link_uri = "http://127.0.0.1:8000/lti/launch"
        return oidc_login.redirect(target_link_uri)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error en Login OIDC: {str(e)}")


# ENDPOINT 2: Lanzamiento definitivo
@app.post("/lti/launch")
async def lti_launch(request: Request, state: str = Form(...), id_token: str = Form(...)):
    try:
        form_data = {"state": state, "id_token": id_token}
        message_launch = CustomFastAPIMessageLaunch(request, tool_conf, form_data)
        launch_data = message_launch.get_launch_data()
        
        user_name = launch_data.get('name', 'Usuario_LTI')
        user_email = launch_data.get('email', '')  # Email que manda Moodle
        
        # --- VALIDACIÓN CON TU DATABASE.PY ---
        if not user_email or not es_profesor_autorizado(user_email):
            print(f"\n[ACCESO DENEGADO] {user_name} ({user_email}) intentó entrar pero no es profesor autorizado.")
            raise HTTPException(
                status_code=403, 
                detail="Acceso denegado: Tu cuenta no está registrada como profesor autorizado."
            )
        # --------------------------------------

        context = launch_data.get('https://purl.imsglobal.org/spec/lti/claim/context', {})
        course_title = context.get('title', 'Curso_Test')
        
        print(f"\n[LTI ACCESO PROFESOR] {user_name} ({user_email}) validado correctamente.")
        
        # Redirección al frontend pasándole el rol para que la interfaz sepa que es un profe
        frontend_url = f"http://localhost:5173/chat?user={user_name}&course={course_title}&role=professor"
        return RedirectResponse(url=frontend_url, status_code=303)
        
    except HTTPException as http_ex:
        raise http_ex
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Fallo en validación de Token Moodle: {str(e)}")


# ENDPOINT 3: JWKS
@app.get("/lti/jwks")
async def lti_jwks():
    return tool_conf.get_jwks()

@app.post("/api/feedback", status_code=201)
async def guardar_feedback_profesor(data: FeedbackProfesorRequest):
    """
    Endpoint para que los profesores validen o corrijan las respuestas del bot.
    Almacena los datos de auditoría de forma relacional en la base de datos.
    """
    # Validación rápida de la calificación
    if data.calificacion not in ["positivo", "negativo"]:
        raise HTTPException(
            status_code=400, 
            detail="La calificación es inválida. Debe ser exactamente 'positivo' o 'negativo'."
        )
        
    try:
        # 🌟 EL MAPEO CLAVE:
        # Pasamos las variables del Front (pregunta_original) a los parámetros de la DB (pregunta)
        registrar_feedback_profesor(
            email=data.email,
            pregunta=data.pregunta_original,       # Mapeado a 'pregunta' que sí existe en la DB
            respuesta=data.respuesta_bot,          # Mapeado a 'respuesta' que sí existe en la DB
            calificacion=data.calificacion,
            correccion=data.correccion_sugerida    # Mapeado a 'correccion'
        )
        return {
            "status": "success", 
            "message": "Feedback de auditoría pedagógica registrado correctamente."
        }
        
    except Exception as e:
        print(f"--> [ERROR CRÍTICO DB]: {str(e)}")
        if "FOREIGN KEY" in str(e) or "constraint failed" in str(e):
            raise HTTPException(
                status_code=400,
                detail=f"Error de integridad: El email '{data.email}' no corresponde a un profesor autorizado."
            )
        raise HTTPException(
            status_code=500, 
            detail=f"Error interno al procesar el guardado en la base de datos: {str(e)}"
        )

@app.get("/api/logs-maestros")
async def obtener_logs_para_profesores(email_profesor: str):
    # Validamos primero con tu función local si es un profesor activo
    if not es_profesor_autorizado(email_profesor):
        raise HTTPException(status_code=403, detail="Acceso denegado: No eres un profesor autorizado.")
        
    try:
        conn = get_connection()
        cursor = conn.cursor()
        # Traemos el historial de lo que preguntaron los alumnos
        cursor.execute("SELECT id, user_id, course_id, role, subtema, pregunta, respuesta, timestamp FROM chat_logs ORDER BY id DESC")
        rows = cursor.fetchall()
        conn.close()
        
        logs = []
        for row in rows:
            logs.append({
                "id": row[0],
                "user_id": row[1],
                "course_id": row[2],
                "role": row[3],
                "subtema": row[4],
                "pregunta_original": row[5], # Mapeado para que Lovable lo lea directo
                "respuesta_bot": row[6],      # Mapeado para que Lovable lo lea directo
                "timestamp": row[7]
            })
        return logs
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al leer los logs: {str(e)}")