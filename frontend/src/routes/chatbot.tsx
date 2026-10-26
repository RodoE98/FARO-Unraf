import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { BottomNav } from "@/components/BottomNav";
import { Icon } from "@/components/Icon";
import { useLti } from "@/lib/lti-context";

// Librerías para renderizar Markdown y Ecuaciones Matemáticas (LaTeX)
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css"; // Estilos de KaTeX para los símbolos matemáticos

export const Route = createFileRoute("/chatbot")({
  head: () => ({
    meta: [
      { title: "Faro UNRaf — Chatbot del estudiante" },
      {
        name: "description",
        content:
          "Chateá con Faro y registrá tu nivel de confianza académica de forma anónima.",
      },
      { property: "og:title", content: "Faro UNRaf — Chatbot" },
      {
        property: "og:description",
        content: "Orientación académica anónima en tiempo real.",
      },
    ],
  }),
  component: StudentChat,
});

function StudentChat() {
  const { user, messages, addMessage, sessionId, newSession, loadSession } = useLti();
  const [input, setInput] = useState("");
  const [streamedText, setStreamedText] = useState(""); // 👈 Nuevo estado para el texto en tiempo real
  
  // Nivel pedagógico estricto para conectar con main.py (1: Principiante, 2: Intermedio, 3: Avanzado)
  const [confidence, setConfidence] = useState<number>(1);
  const [saved, setSaved] = useState(false);
  const [codigoCopiado, setCodigoCopiado] = useState(false);
  // Retomar una conversación con su código (por ejemplo, desde otro dispositivo)
  const [retomando, setRetomando] = useState(false);
  const [codigoIngresado, setCodigoIngresado] = useState("");
  const [errorCodigo, setErrorCodigo] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const [sending, setSending] = useState(false);

const send = async () => {
    const text = input.trim();
    if (!text || sending) return;

    // Historial de esta charla (sin el saludo ni los errores de conexión) para que el modelo entienda las repreguntas.
    // `messages` todavía NO incluye la pregunta actual; el backend se queda con los últimos mensajes que le entran.
    const historial = messages
      .filter((m) => m.id !== "welcome" && !m.text.startsWith("No pude conectarme"))
      .slice(-6)
      .map((m) => ({ role: m.role === "ai" ? "assistant" : "user", text: m.text }));

    const userMsg = addMessage({ role: "user", text });
    setInput("");
    setSending(true);
    setStreamedText(""); // 👈 Limpiamos el texto temporal anterior

    try {
      const base = import.meta.env.VITE_API_URL ?? "";
      const res = await fetch(`${base}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_id: user.user_id,
          course_id: user.course_id,
          role: user.role,
          pregunta: text,
          confidence: confidence, 
          historial,
          session_id: sessionId,
        }),
      });

      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(errorText || `HTTP ${res.status}`);
      }

      const reader = res.body?.getReader();
      const decoder = new TextDecoder("utf-8");
      if (!reader) throw new Error("No hay lector.");

      let textoAcumulado = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        textoAcumulado += chunk;

        // 🌟 ESTO SÍ HACE QUE REACT RE-RENDERICE LETRA POR LETRA:
        setStreamedText(textoAcumulado);
      }

      // ✨ Cuando el bucle termina, guardamos el mensaje completo en el historial global
      addMessage({ role: "ai", text: textoAcumulado, inReplyTo: userMsg.id });
      setStreamedText(""); // Limpiamos el temporal

    } catch (err) {
      addMessage({
        role: "ai",
        text: `No pude conectarme con el servidor. ${err instanceof Error ? err.message : ""}`,
        inReplyTo: userMsg.id,
      });
    } finally {
      setSending(false);
    }
  };

  const copiarCodigo = async () => {
    try {
      await navigator.clipboard.writeText(sessionId);
      setCodigoCopiado(true);
      setTimeout(() => setCodigoCopiado(false), 2000);
    } catch {
      // Sin permiso de portapapeles: el código igual está a la vista para copiarlo a mano.
    }
  };

  const nuevaConversacion = () => {
    if (sending) return;
    newSession();
    setInput("");
    setStreamedText("");
  };

  const retomarConversacion = async () => {
    if (sending) return;
    // Acepta "FARO-7K3Q9X" o solo "7K3Q9X"
    let codigo = codigoIngresado.trim().toUpperCase();
    if (/^[A-Z0-9]{6}$/.test(codigo)) codigo = `FARO-${codigo}`;
    if (!/^[A-Z0-9-]{4,40}$/.test(codigo)) {
      setErrorCodigo("El código no es válido. Tiene la forma FARO-XXXXXX.");
      return;
    }
    setErrorCodigo("");
    try {
      const base = import.meta.env.VITE_API_URL ?? "";
      const res = await fetch(`${base}/api/sesion/${encodeURIComponent(codigo)}`);
      if (res.status === 404) {
        setErrorCodigo("No encontré ninguna conversación con ese código.");
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      loadSession(data.session_id, data.mensajes);
      setRetomando(false);
      setCodigoIngresado("");
      setInput("");
      setStreamedText("");
    } catch {
      setErrorCodigo("No pude conectarme con el servidor. Probá de nuevo.");
    }
  };

  const save = () => {
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const obtenerNombreNivel = (nivel: number) => {
    if (nivel === 1) return "Principiante";
    if (nivel === 2) return "Intermedio";
    return "Avanzado";
  };

return (
    <div className="min-h-screen bg-surface pb-32 md:pb-12">
      <AppHeader anonymousId="225" />

      <main className="pt-24 px-4 md:px-20 max-w-4xl mx-auto flex flex-col gap-6">
        <section>
          <p className="text-on-surface-variant">
            Tu identificador anónimo:{" "}
            <span className="font-bold text-primary">#225</span>
          </p>
          {/* Código de la conversación: el alumno lo anota en las actividades y encuestas para que se pueda vincular */}
          <div className="mt-3 flex flex-wrap items-center gap-2 rounded-xl border border-outline-variant/60 bg-white/70 px-4 py-3">
            <div className="flex flex-col mr-auto">
              <span className="text-xs text-on-surface-variant">Código de esta conversación</span>
              <span className="font-mono text-lg font-bold tracking-wider text-primary select-all">{sessionId}</span>
            </div>
            <button
              type="button"
              onClick={copiarCodigo}
              className="inline-flex items-center gap-1 rounded-full border border-outline-variant px-3 py-2 text-sm text-on-surface-variant hover:bg-surface-container-highest"
            >
              <Icon name={codigoCopiado ? "check" : "content_copy"} />
              {codigoCopiado ? "Copiado" : "Copiar"}
            </button>
            <button
              type="button"
              onClick={nuevaConversacion}
              disabled={sending}
              className="inline-flex items-center gap-1 rounded-full bg-primary px-4 py-2 text-sm font-medium text-on-primary disabled:opacity-50"
            >
              <Icon name="add_comment" />
              Nueva conversación
            </button>
            <button
              type="button"
              onClick={() => { setRetomando((v) => !v); setErrorCodigo(""); }}
              disabled={sending}
              className="inline-flex items-center gap-1 rounded-full border border-outline-variant px-3 py-2 text-sm text-on-surface-variant hover:bg-surface-container-highest disabled:opacity-50"
            >
              <Icon name="login" />
              Tengo un código
            </button>
            {retomando && (
              <div className="basis-full flex flex-col gap-2 pt-2">
                <div className="flex flex-wrap items-center gap-2">
                  <input
                    value={codigoIngresado}
                    onChange={(e) => setCodigoIngresado(e.target.value)}
                    onKeyDown={(e) => { if (e.key === "Enter") retomarConversacion(); }}
                    placeholder="FARO-XXXXXX"
                    className="min-w-0 flex-1 rounded-full border border-outline-variant bg-white px-4 py-2 font-mono uppercase tracking-wider outline-none focus:border-primary"
                  />
                  <button
                    type="button"
                    onClick={retomarConversacion}
                    className="rounded-full bg-secondary px-4 py-2 text-sm font-medium text-on-secondary"
                  >
                    Retomar conversación
                  </button>
                </div>
                {errorCodigo && <p className="text-sm text-red-600">{errorCodigo}</p>}
              </div>
            )}
          </div>
        </section>

        {/* Chat */}
        <section className="flex flex-col h-[520px] md:h-[65vh] rounded-2xl overflow-hidden border border-outline-variant/60 card-shadow bg-white/70 backdrop-blur">
          <div
            ref={scrollRef}
            className="flex-1 overflow-y-auto p-4 flex flex-col gap-3 bg-white/40"
            style={{ scrollbarWidth: "thin" }}
          >
            {messages.map((m, i) => {
              // Función interna clave para normalizar los delimitadores matemáticos de Phi-3 a formato $ y $$ válidos
              const formatearTextoMatematico = (texto: string) => {
                if (m.role !== "ai") return texto;
                return texto
                  // Convierte bloques de ecuaciones escapados \[ ... \] o crudos [ ... ] a $$ ... $$
                  .replace(/\\\[/g, "$$").replace(/\\\]/g, "$$")
                  // Convierte fórmulas en línea escapadas \( ... \) o crudas ( ... ) a $ ... $
                  .replace(/\\Ref/g, "$").replace(/\\\)/g, "$")
                  .replace(/\\\(/g, "$");
              };

              return (
                <div
                  key={i}
                  className={
                    "max-w-[85%] px-4 py-3 text-[15px] leading-relaxed animate-in fade-in slide-in-from-bottom-1 duration-300 " +
                    (m.role === "ai"
                      ? "self-start bg-surface-container-highest text-on-surface-variant rounded-2xl rounded-tl-sm"
                      : "self-end bg-primary text-on-primary rounded-2xl rounded-tr-sm shadow-sm")
                  }
                >
                  {/* Si el mensaje viene de la IA, lo procesamos con el formateador antes del renderizado */}
                  {m.role === "ai" ? (
                    <div className="prose prose-sm max-w-none text-on-surface-variant custom-markdown">
                      <ReactMarkdown
                        remarkPlugins={[remarkMath]}
                        rehypePlugins={[rehypeKatex]}
                      >
                        {formatearTextoMatematico(m.text)}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    m.text
                  )}
                </div>
              );
            })}

            {/* 🌟 BURBUJA TEMPORAL EN STREAMING (Muestra la respuesta de TinyLlama en tiempo real) */}
            {streamedText && (
              <div className="max-w-[85%] self-start bg-surface-container-highest text-on-surface-variant rounded-2xl rounded-tl-sm px-4 py-3 text-[15px] leading-relaxed animate-in fade-in duration-200">
                <div className="prose prose-sm max-w-none text-on-surface-variant custom-markdown">
                  <ReactMarkdown
                    remarkPlugins={[remarkMath]}
                    rehypePlugins={[rehypeKatex]}
                  >
                    {streamedText
                      .replace(/\\\[/g, "$$").replace(/\\\]/g, "$$")
                      .replace(/\\Ref/g, "$").replace(/\\\)/g, "$")
                      .replace(/\\\(/g, "$")}
                  </ReactMarkdown>
                </div>
              </div>
            )}

            {/* Cartel "Escribiendo..." modificado: Solo se muestra si está enviando pero todavía no llegó la primera palabra */}
            {sending && !streamedText && (
              <div className="self-start bg-surface-container-highest text-on-surface-variant rounded-2xl rounded-tl-sm px-4 py-3 text-[15px] italic opacity-80 animate-pulse">
                Escribiendo…
              </div>
            )}
          </div>

          <div className="p-3 border-t border-outline-variant/60 bg-white flex items-center gap-2">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
              placeholder="Escribe un mensaje..."
              disabled={sending}
              className="flex-1 bg-surface-container-low rounded-full px-4 py-2.5 outline-none focus:ring-2 focus:ring-secondary text-[15px] transition-all disabled:opacity-60"
            />
            <button
              onClick={send}
              disabled={sending}
              aria-label="Enviar"
              className="w-11 h-11 grid place-items-center bg-primary text-on-primary rounded-full active:scale-90 transition-transform shadow-md hover:bg-primary-container disabled:opacity-60"
            >
              <Icon name="send" />
            </button>
          </div>
        </section>

        {/* Selector de Nivel Pedagógico Estricto (1 al 3) */}
        <section className="rounded-2xl border border-outline-variant/60 card-shadow bg-white/70 backdrop-blur p-6 flex flex-col gap-4">
          <div className="flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-[20px] font-bold text-primary">
              <Icon name="monitoring" filled className="text-secondary" />
              Nivel Pedagógico
            </h2>
            <div className="bg-secondary-container text-on-secondary-container px-3 py-1 rounded-full text-sm font-bold">
              {obtenerNombreNivel(confidence)}
            </div>
          </div>
          <p className="text-on-surface-variant">
            ¿Con qué nivel de profundidad te gustaría que te responda el docente virtual?
          </p>

          <div className="grid grid-cols-3 gap-2 py-2">
            <button
              onClick={() => setConfidence(1)}
              className={`py-3 px-2 rounded-xl text-xs sm:text-sm font-bold transition-all border ${
                confidence === 1
                  ? "bg-secondary text-white border-secondary shadow-md"
                  : "bg-surface-container-low text-on-surface-variant border-outline-variant hover:bg-surface-container-high"
              }`}
            >
              1. Principiante
            </button>
            <button
              onClick={() => setConfidence(2)}
              className={`py-3 px-2 rounded-xl text-xs sm:text-sm font-bold transition-all border ${
                confidence === 2
                  ? "bg-secondary text-white border-secondary shadow-md"
                  : "bg-surface-container-low text-on-surface-variant border-outline-variant hover:bg-surface-container-high"
              }`}
            >
              2. Intermedio
            </button>
            <button
              onClick={() => setConfidence(3)}
              className={`py-3 px-2 rounded-xl text-xs sm:text-sm font-bold transition-all border ${
                confidence === 3
                  ? "bg-secondary text-white border-secondary shadow-md"
                  : "bg-surface-container-low text-on-surface-variant border-outline-variant hover:bg-surface-container-high"
              }`}
            >
              3. Avanzado
            </button>
          </div>

          <button
            onClick={save}
            className="w-full py-4 bg-primary text-on-primary rounded-xl font-bold flex items-center justify-center gap-2 shadow-md hover:bg-primary-container active:scale-[0.98] transition-all"
          >
            <Icon name={saved ? "check_circle" : "save"} filled={saved} />
            {saved ? "CONFIGURACIÓN GUARDADA" : "GUARDAR CONFIGURACIÓN"}
          </button>
        </section>

        <section className="text-center py-6">
          <p className="italic text-on-surface-variant/80">
            "La educación es el encendido de una llama, no el llenado de un recipiente."
          </p>
        </section>
      </main>

      <BottomNav />
    </div>
  );
}