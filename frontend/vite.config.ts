import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Vite config per ADR-0019. Dev server proxies /api/* to the FastAPI
// backend so the React app talks to the same URL space at dev and at
// build time (FastAPI mounts frontend/dist later — see ADR-0019 §"文件布局").
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    // Bind explicitly to 127.0.0.1 so Vite is reachable over both IPv4
    // AND IPv6 (vite's default "localhost" resolves to ::1 only on
    // macOS, which trips IPv4-only tools — curl without -6, the
    // system HTTP proxy at :7890, etc — even though the browser
    // works fine).
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      // Phase 1 B slice 4: backend serves uploaded images at
      // /files/_attachments/<name>. Without proxying, the dev server
      // returns the SPA HTML fallback and the preview img tag breaks.
      "/files": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
