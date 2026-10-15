import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Defaults match the README; the E2E suite runs an isolated stack on other ports.
const BACKEND_URL = process.env.AOS_API_URL ?? "http://127.0.0.1:8000";
const PORT = Number(process.env.AOS_WEB_PORT ?? 5173);

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: PORT,
    strictPort: true,
    proxy: {
      "/api": { target: BACKEND_URL, changeOrigin: true },
      "/health": { target: BACKEND_URL, changeOrigin: true },
      "/readyz": { target: BACKEND_URL, changeOrigin: true },
    },
  },
});
