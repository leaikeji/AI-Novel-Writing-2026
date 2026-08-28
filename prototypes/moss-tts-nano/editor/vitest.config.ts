import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    include: ["editor/editor-spike.test.ts"],
    testTimeout: 30_000,
  },
});
