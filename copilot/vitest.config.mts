import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

const src = (pkg: string) => fileURLToPath(new URL(`./packages/${pkg}/src/index.ts`, import.meta.url));

// Tests run against the TypeScript sources, so no build step is needed first.
export default defineConfig({
  resolve: {
    alias: {
      "@copilot/core": src("core"),
      "@copilot/connectors": src("connectors"),
    },
  },
  test: { include: ["packages/*/src/**/*.test.ts"] },
});
