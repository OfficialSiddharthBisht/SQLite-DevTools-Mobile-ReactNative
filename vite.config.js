import { defineConfig } from "vite";

export default defineConfig({
  root: "src",
  base: "/SQLite-DevTools-Mobile-ReactNative/",
  build: {
    outDir: "../dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    open: true,
  },
});
