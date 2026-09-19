import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The application is served from a subpath in production, so every asset and
// route must resolve relative to /trade rather than the domain root.
export default defineConfig({
  base: "/trade/",
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/trade/api": "http://127.0.0.1:8092",
    },
  },
  build: {
    sourcemap: false,
    // flag-icons ships ~270 SVGs. Inlining them as data URIs would push the
    // stylesheet past 450 KB and make every visitor download every flag;
    // emitting them as files means the browser fetches only the ones shown.
    assetsInlineLimit: 0,
    rollupOptions: {
      output: {
        manualChunks: {
          echarts: ["echarts/core", "echarts/charts", "echarts/components", "echarts/renderers"],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/__tests__/setup.tsx"],
  },
});
