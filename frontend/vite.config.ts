import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          react: ["react", "react-dom", "@tanstack/react-query"],
          charts: ["recharts"],
          icons: ["lucide-react"],
        },
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
  },
});
