import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { AppHeader } from "@/components/AppHeader";
import { BottomNav } from "@/components/BottomNav";
import { useLti } from "@/lib/lti-context";

// Librerías para procesar el texto con fórmulas matemáticas que devuelve tu API
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css"; // Estilos para renderizar LaTeX

// 1. Estructura idéntica al JSON que te devolvió la URL (image_8e53cc.png)
interface ChatLogAlumno {
  id: number;
  user_id: string;
  course_id: string;
  role: string;
  subtema: string;
  pregunta_original: string; // Coincide con tu Backend
  respuesta_bot: string;      // Coincide con tu Backend
  timestamp: string;
  session_id?: string | null;
  // Fuente efectivamente entregada al modelo (prioridad: fichas docentes -> OpenStax -> conocimiento del modelo)
  fuente?: "FICHA" | "FICHA+OPENSTAX" | "OPENSTAX" | "NINGUNA" | null;
  fichas_ids?: string | null;
  sin_documentacion?: number | null;
  fragmentos?: {
    fichas: { id: string; titulo: string; texto: string }[];
    openstax: { chunk: string; seccion: string; paginas: number[]; score: number; texto: string; enviado: boolean }[];
    consulta_de_busqueda?: string | null;
  } | null;
}

const ETIQUETA_FUENTE: Record<string, { texto: string; clase: string }> = {
  "FICHA": { texto: "Ficha docente", clase: "bg-emerald-100 text-emerald-800" },
  "FICHA+OPENSTAX": { texto: "Ficha docente + OpenStax", clase: "bg-emerald-100 text-emerald-800" },
  "OPENSTAX": { texto: "OpenStax", clase: "bg-sky-100 text-sky-800" },
  "NINGUNA": { texto: "Sin documentación (conocimiento del modelo)", clase: "bg-amber-100 text-amber-800" },
};

export const Route = createFileRoute("/visualizarfeedback")({
  component: VisualizarLogsAlumnos,
});

function VisualizarLogsAlumnos() {
  const { user } = useLti(); 
  const [logs, setLogs] = useState<ChatLogAlumno[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const cargarLogsAlumnos = async () => {
    try {
      setLoading(true);
      setError(null);
      
      const baseUrl = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
      // Si el entorno LTI no provee email todavía, usamos el tuyo por defecto para las pruebas
      const emailDocente = user?.email || "profesor@unraf.edu.ar"; 
      
      const response = await fetch(
        `${baseUrl}/api/logs-maestros?email_profesor=${encodeURIComponent(emailDocente)}`
      );

      if (!response.ok) {
        if (response.status === 403) {
          throw new Error("Acceso denegado: Este email no figura como profesor autorizado.");
        }
        throw new Error(`Error del servidor backend: ${response.status}`);
      }

      const data = await response.json();
      setLogs(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Error de conexión con el backend");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    cargarLogsAlumnos();
  }, [user?.email]);

  return (
    <div className="min-h-screen bg-slate-50 pb-24">
      <AppHeader anonymousId="Docente" />

      <main className="pt-24 px-4 md:px-12 max-w-4xl mx-auto flex flex-col gap-6 font-sans">
        
        {/* Fila del Título */}
        <div className="flex justify-between items-center border-b border-slate-200 pb-4">
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Panel de Monitoreo Áulico</h1>
            <p className="text-sm text-slate-500">Historial de interacciones y consultas de alumnos</p>
          </div>
          <button 
            onClick={cargarLogsAlumnos}
            className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl text-sm font-bold transition-all shadow-md active:scale-95"
          >
            🔄 Actualizar Datos
          </button>
        </div>

        {/* Tarjeta de métricas */}
        <div className="bg-white border border-slate-200 p-4 rounded-xl shadow-sm max-w-xs">
          <span className="text-xs font-bold text-slate-400 uppercase tracking-wider">Consultas Registradas</span>
          <span className="text-3xl font-black text-slate-800 block mt-1">{logs.length}</span>
        </div>

        {/* Controladores de Estado */}
        {loading && <div className="text-center p-12 text-slate-400 italic">Leyendo logs_pedagogicos.db...</div>}
        {error && <div className="text-center p-6 bg-red-50 text-red-600 border border-red-200 rounded-xl font-bold">{error}</div>}

        {/* Despliegue de los Logs */}
        {!loading && !error && (
          <div className="flex flex-col gap-4">
            {logs.length === 0 ? (
              <div className="text-center p-12 bg-white border border-slate-200 rounded-xl text-slate-400 italic">
                No se encontraron chats guardados en la tabla de logs.
              </div>
            ) : (
              logs.map((log) => (
                <div key={log.id} className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm flex flex-col gap-3">
                  
                  {/* Encabezado del log */}
                  <div className="flex justify-between items-center border-b border-slate-100 pb-2 text-xs text-slate-400 font-medium">
                    <span>Eje Temático: <strong className="text-indigo-600 uppercase">{log.subtema || "General"}</strong></span>
                    <span>Sesión: <strong className="font-mono text-slate-600">{log.session_id || "—"}</strong></span>
                    <span>{log.timestamp ? new Date(log.timestamp).toLocaleString("es-AR") : "Sin fecha"}</span>
                  </div>

                  {/* Fuente efectivamente recuperada */}
                  {log.fuente ? (
                    <div className="flex flex-col gap-2 text-xs">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-bold text-slate-500">FUENTE:</span>
                        <span className={"rounded-full px-3 py-1 font-semibold " + (ETIQUETA_FUENTE[log.fuente]?.clase ?? "bg-slate-100 text-slate-700")}>
                          {ETIQUETA_FUENTE[log.fuente]?.texto ?? log.fuente}
                        </span>
                        {log.fichas_ids && <span className="font-mono text-slate-600">Fichas: {log.fichas_ids}</span>}
                        {log.fragmentos?.openstax?.some((x) => x.enviado) && (
                          <span className="font-mono text-slate-600">
                            OpenStax: {log.fragmentos.openstax.filter((x) => x.enviado).map((x) => `sec. ${x.seccion}`).join(", ")}
                          </span>
                        )}
                        {log.sin_documentacion ? <span className="font-semibold text-amber-700">Respondió sin documentación recuperada</span> : null}
                      </div>
                      {log.fragmentos && (log.fragmentos.fichas.length > 0 || log.fragmentos.openstax.length > 0) && (
                        <details className="rounded-lg border border-slate-100 bg-slate-50 p-3">
                          <summary className="cursor-pointer font-semibold text-slate-600">Ver el material que recibió el modelo</summary>
                          <div className="mt-2 flex flex-col gap-3">
                            {log.fragmentos.consulta_de_busqueda && (
                              <p className="text-slate-500">Repregunta: se buscó con la pregunta anterior + la actual.</p>
                            )}
                            {log.fragmentos.fichas.map((f) => (
                              <pre key={f.id} className="whitespace-pre-wrap font-sans text-slate-700">{f.texto}</pre>
                            ))}
                            {log.fragmentos.openstax.map((x) => (
                              <div key={x.chunk} className={x.enviado ? "" : "opacity-50"}>
                                <p className="font-mono text-slate-500">
                                  OpenStax · {x.chunk} · sec. {x.seccion} · págs. {x.paginas?.join("–")} · puntaje {x.score}
                                  {x.enviado ? "" : " · (no entró en el prompt: contexto recortado)"}
                                </p>
                                <pre className="whitespace-pre-wrap font-sans text-slate-700">{x.texto}</pre>
                              </div>
                            ))}
                          </div>
                        </details>
                      )}
                    </div>
                  ) : (
                    <div className="text-xs text-slate-400 italic">Registro anterior al seguimiento de fuentes.</div>
                  )}

                  {/* Bloques de contenido */}
                  <div className="grid grid-cols-1 gap-4 text-sm">
                    {/* Tarjeta de la Pregunta */}
                    <div className="bg-slate-50 p-3 rounded-xl border border-slate-100">
                      <span className="font-bold text-xs text-blue-600 block mb-1">PREGUNTA DEL ESTUDIANTE:</span>
                      <p className="text-slate-800 font-medium">{log.pregunta_original}</p>
                    </div>

                    {/* Tarjeta de la Respuesta del Bot (Con soporte Markdown/LaTeX) */}
                    <div className="bg-slate-50 p-4 rounded-xl border border-slate-100 prose prose-slate max-w-none">
                      <span className="font-bold text-xs text-emerald-600 block mb-2">RESPUESTA DEL BOT:</span>
                      <div className="text-slate-700 leading-relaxed overflow-x-auto">
                        <ReactMarkdown 
                          remarkPlugins={[remarkMath]} 
                          rehypePlugins={[rehypeKatex]}
                        >
                          {log.respuesta_bot}
                        </ReactMarkdown>
                      </div>
                    </div>
                  </div>

                </div>
              ))
            )}
          </div>
        )}
      </main>
      <BottomNav />
    </div>
  );
}