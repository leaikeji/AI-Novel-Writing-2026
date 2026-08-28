import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["manifest-player/manifest-player.test.ts"],
  },
});
