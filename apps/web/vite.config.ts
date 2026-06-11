import { defineConfig } from "vite";

export default defineConfig({
  server: {
    host: "127.0.0.1",
    port: 5173,
  },
  build: {
    rollupOptions: {
      output: {
        // Keep the charting engine and framework in cacheable vendor chunks.
        manualChunks: {
          echarts: ["echarts/core", "echarts/charts", "echarts/components", "echarts/renderers"],
          react: ["react", "react-dom", "react-router", "@tanstack/react-query"],
        },
      },
    },
  },
});
