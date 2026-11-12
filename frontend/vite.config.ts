// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - tanstackStart, viteReact, tailwindcss, tsConfigPaths, cloudflare (build-only),
//     componentTagger (dev-only), VITE_* env injection, @ path alias, React/TanStack dedupe,
//     error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... } }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";
import { loadEnv } from "vite";

// Destino del proxy /api (solo lo usa el servidor de desarrollo, `npm run dev`).
// Se toma de VITE_API_URL (variable de entorno o archivo .env.local, que escriben run_local.ps1 / run_runpod.ps1),
// asi apunta al backend local o al Pod de RunPod sin editar este archivo. Sin variable: backend local.
const env = loadEnv(process.env.NODE_ENV ?? "development", process.cwd(), "VITE_");
const API_TARGET = (process.env.VITE_API_URL || env.VITE_API_URL || "http://localhost:8000").replace(/\/+$/, "");

// Redirect TanStack Start's bundled server entry to src/server.ts (our SSR error wrapper).
// @cloudflare/vite-plugin builds from this — wrangler.jsonc main alone is insufficient.
export default defineConfig({
  tanstackStart: {
    server: { entry: "server" },
  },
  vite: {
    server: {
      proxy: {
        "/api": {
          target: API_TARGET,
          changeOrigin: true,
          secure: false,
        },
      },
    },
  },
});
