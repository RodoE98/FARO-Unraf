import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

export type LtiRole = "Learner" | "Instructor" | "Maestro";

export type LtiUser = {
  user_id: string;
  course_id: string;
  role: LtiRole;
  email: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "ai";
  text: string;
  /** When role==='ai', this links back to the user pregunta it answered */
  inReplyTo?: string;
};

type LtiContextValue = {
  user: LtiUser;
  setUser: (u: LtiUser) => void;
  messages: ChatMessage[];
  addMessage: (m: Omit<ChatMessage, "id">) => ChatMessage;
  resetMessages: () => void;
  /** ID del usuario / conversación actual (ej. "4821"). Cambia con cada "Nuevo usuario". */
  sessionId: string;
  /** Empieza de cero: vacía el chat y genera un ID nuevo que no esté en uso. */
  newSession: () => void;
  /** Retoma una conversación guardada (por ejemplo desde otro dispositivo): adopta su ID y carga sus mensajes. */
  loadSession: (code: string, msgs: { role: "user" | "ai"; text: string }[]) => void;
};

// Simulated LTI launch payload
const DEFAULT_LTI_USER: LtiUser = {
  user_id: "alumno-225",
  course_id: "unraf-intro-2026",
  role: "Learner",
  email: "alumno225@unraf.edu.ar",
};

const WELCOME: ChatMessage = {
  id: "welcome",
  role: "ai",
  text: "Hola, soy Faro. Estoy aquí para orientarte en tu trayectoria académica. ¿En qué puedo ayudarte hoy?",
};

const LtiContext = createContext<LtiContextValue | null>(null);

// ID numérico del piloto: entre ID_MIN y ID_MAX (ej. 4821). Se muestra como "#4821".
const ID_MIN = 100;
const ID_MAX = 25535;

function generarId(): string {
  const rango = ID_MAX - ID_MIN + 1;
  let n: number;
  try {
    n = crypto.getRandomValues(new Uint32Array(1))[0] % rango;
  } catch {
    n = Math.floor(Math.random() * rango);
  }
  return String(ID_MIN + n);
}

/** user_id que se manda al backend para un ID (ej. 4821 -> alumno-4821). */
export function idDeUsuario(id: string): string {
  return "alumno-" + id;
}

/**
 * Devuelve un ID que todavía no tiene ninguna conversación guardada en el backend (hay ~25.000 posibles, así que casi
 * siempre sale al primer intento). Si el backend no responde, se usa el primero que salió.
 */
async function generarIdLibre(candidato: string = generarId()): Promise<string> {
  let id = candidato;
  for (let intento = 0; intento < 8; intento++) {
    try {
      const base = import.meta.env.VITE_API_URL ?? "";
      const res = await fetch(`${base}/api/sesion/${id}`);
      if (res.status !== 200) return id; // 404 = libre (cualquier otro estado: no se puede verificar)
    } catch {
      return id;
    }
    id = generarId();
  }
  return id;
}

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function LtiProvider({ children }: { children: ReactNode }) {
  // PILOTO: el ID identifica a la vez a un usuario anónimo nuevo y a su conversación. Se genera al abrir la página y cada vez
  // que se pulsa "Nuevo usuario"; el user_id que ve el backend sale de ese mismo ID (alumno-<ID>).
  // Se genera después de montar (no en el render inicial) para que el servidor y el navegador no generen valores distintos.
  const [user, setUser] = useState<LtiUser>(DEFAULT_LTI_USER);
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME]);
  const [sessionId, setSessionId] = useState<string>("");

  useEffect(() => {
    const inicial = generarId();
    setSessionId(inicial);
    setUser((u) => ({ ...u, user_id: idDeUsuario(inicial) }));
    // Verifica en segundo plano que no esté en uso; si lo está y todavía no se escribió nada, se cambia por otro.
    let vigente = true;
    generarIdLibre(inicial).then((libre) => {
      if (!vigente) return;
      setSessionId((actual) => {
        if (actual !== inicial) return actual;
        return libre;
      });
      setUser((u) => (u.user_id === idDeUsuario(inicial) ? { ...u, user_id: idDeUsuario(libre) } : u));
    });
    return () => { vigente = false; };
  }, []);

  const addMessage = useCallback((m: Omit<ChatMessage, "id">): ChatMessage => {
    const msg: ChatMessage = { ...m, id: uid() };
    setMessages((prev) => [...prev, msg]);
    return msg;
  }, []);

  const resetMessages = useCallback(() => setMessages([WELCOME]), []);

  // Inmediato: el ID nuevo aparece en el acto (no espera al backend). Después se verifica en segundo plano que no esté en uso
  // y, en el caso rarísimo de que lo esté, se cambia por otro.
  const newSession = useCallback(() => {
    const id = generarId();
    setMessages([WELCOME]);
    setSessionId(id);
    setUser((u) => ({ ...u, user_id: idDeUsuario(id) }));
    generarIdLibre(id).then((libre) => {
      if (libre === id) return;
      setSessionId((actual) => (actual === id ? libre : actual));
      setUser((u) => (u.user_id === idDeUsuario(id) ? { ...u, user_id: idDeUsuario(libre) } : u));
    });
  }, []);

  const loadSession = useCallback((code: string, msgs: { role: "user" | "ai"; text: string }[]) => {
    setMessages([WELCOME, ...msgs.map((m) => ({ id: uid(), role: m.role, text: m.text }))]);
    setSessionId(code);
    setUser((u) => ({ ...u, user_id: idDeUsuario(code) }));
  }, []);

  const value = useMemo(
    () => ({ user, setUser, messages, addMessage, resetMessages, sessionId, newSession, loadSession }),
    [user, messages, addMessage, resetMessages, sessionId, newSession, loadSession],
  );

  return <LtiContext.Provider value={value}>{children}</LtiContext.Provider>;
}

export function useLti(): LtiContextValue {
  const ctx = useContext(LtiContext);
  if (!ctx) throw new Error("useLti must be used within <LtiProvider>");
  return ctx;
}
