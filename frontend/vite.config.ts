import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
export default defineConfig(({ mode }) => {
  const apiTarget =
    loadEnv(mode, ".", "CAREERPILOT_").CAREERPILOT_API_TARGET ||
    "http://127.0.0.1:8000";
  return {
    base: "./",
    plugins: [vue()],
    build: {
      assetsInlineLimit: 1_000_000,
      rollupOptions: { output: { inlineDynamicImports: true } },
    },
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: { "/api": { target: apiTarget, changeOrigin: false } },
    },
    preview: {
      proxy: {
        "/api": { target: "http://127.0.0.1:8000", changeOrigin: false },
      },
    },
  };
});
