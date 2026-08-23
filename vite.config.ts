import { defineConfig } from "vite";

export default defineConfig({
  build: {
    lib: {
      entry: "frontend/src/index.ts",
      formats: ["es"],
      fileName: () => "index.js",
    },
    outDir: "frontend/dist",
    emptyOutDir: true,
    sourcemap: true,
  },
});
