import { defineConfig } from "vite";

const isElectron = process.env.BUILD_TARGET === "electron";

export default defineConfig({
  root: "src",
  base: isElectron ? "./" : "/SQLite-DevTools-Mobile-ReactNative/",
  build: {
    outDir: "../dist",
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    open: true,
  },
});
