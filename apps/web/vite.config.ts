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
        manualChunks(id) {
          if (id.includes("node_modules/echarts")) {
            return "echarts";
          }
          if (
            id.includes("node_modules/react") ||
            id.includes("node_modules/react-dom") ||
            id.includes("node_modules/react-router") ||
            id.includes("node_modules/@tanstack/react-query")
          ) {
            return "react";
          }
          return undefined;
        },
      },
    },
  },
});
