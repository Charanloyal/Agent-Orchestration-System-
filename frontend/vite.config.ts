import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Must match the address used to start uvicorn in the README.
const BACKEND_URL = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/health": { target: BACKEND_URL, changeOrigin: true },
    },
  },
});
