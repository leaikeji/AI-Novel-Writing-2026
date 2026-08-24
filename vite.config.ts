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
    rollupOptions: {
      // QwenPaw evaluates PawApp frontends from a Blob URL. Relative chunk
      // specifiers cannot be resolved from that origin, so every dynamic
      // import must be inlined into the single distributable module.
      output: { inlineDynamicImports: true },
    },
  },
});
