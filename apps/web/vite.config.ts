import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The browser talks to the API through this dev proxy, so no CORS settings are needed locally.
const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env;
const api = env?.DMS_API_URL ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true, proxy: { "/api": api } },
  preview: { port: 5173, proxy: { "/api": api } },
});
