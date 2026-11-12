import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: { assetsDir: "integrity-assets", chunkSizeWarningLimit: 1800 },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8766",
      "/brand": "http://127.0.0.1:8766",
    },
  },
});
