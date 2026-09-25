// defineConfig comes from vitest/config, not vite: the vite one does not type
// the `test` block, and tsc would reject it.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "node",
  },
});
