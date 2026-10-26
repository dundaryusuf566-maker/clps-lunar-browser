import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// base "./" keeps every asset path relative, so the built site works from any
// sub-folder (GitHub Pages, a USB stick, the jury's laptop).
// During `npm run dev`, /api is forwarded to the engine server (python -m api.server).
export default defineConfig({
  base: "./",
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
