import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The browser only ever talks to our backend; the PLK API key stays server-side.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
