import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

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
  /** Código de la conversación actual (ej. FARO-7K3Q9X). Cambia en cada conversación nueva. */
  sessionId: string;
  /** Empieza una conversación nueva: vacía el chat y genera un código nuevo. */
  newSession: () => void;
  /** Retoma una conversación guardada (por ejemplo desde otro dispositivo): adopta su código y carga sus mensajes. */
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

// Sin 0/O/1/I/L para que se pueda dictar o copiar a mano sin confundirse.
const ALFABETO_CODIGO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";

function generarCodigoSesion(): string {
  const bytes = new Uint8Array(6);
  try {
    crypto.getRandomValues(bytes);
  } catch {
    for (let i = 0; i < bytes.length; i++) bytes[i] = Math.floor(Math.random() * 256);
  }
  return "FARO-" + Array.from(bytes, (b) => ALFABETO_CODIGO[b % ALFABETO_CODIGO.length]).join("");
}

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function LtiProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<LtiUser>(DEFAULT_LTI_USER);
  const [messages, setMessages] = useState<ChatMessage[]>([WELCOME]);
  // Un código por conversación: se genera al abrir la página y cada vez que se pulsa "Nueva conversación".
  const [sessionId, setSessionId] = useState<string>(() => generarCodigoSesion());

  const addMessage = useCallback((m: Omit<ChatMessage, "id">): ChatMessage => {
    const msg: ChatMessage = { ...m, id: uid() };
    setMessages((prev) => [...prev, msg]);
    return msg;
  }, []);

  const resetMessages = useCallback(() => setMessages([WELCOME]), []);

  const newSession = useCallback(() => {
    setMessages([WELCOME]);
    setSessionId(generarCodigoSesion());
  }, []);

  const loadSession = useCallback((code: string, msgs: { role: "user" | "ai"; text: string }[]) => {
    setMessages([WELCOME, ...msgs.map((m) => ({ id: uid(), role: m.role, text: m.text }))]);
    setSessionId(code);
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
