// defineConfig comes from vitest/config, not vite: the vite one does not type
// the `test` block, and tsc would reject it.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const API = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    // The api's paths go through to it, so in development the client and the
    // api share an origin: no CORS, and <audio> loads /jobs/{id}/audio/...
    // directly. Client routes live under /songs, never /jobs.
    proxy: { "/jobs": API, "/health": API },
  },
  build: {
    // three.js ships in the guitar's lazy chunk, about 605 kB before gzip
    // and 155 kB after. Vite's 500 kB default would warn on every build.
    // The limit applies to every chunk, not only that one: the entry chunk
    // (about 177 kB now, from `npm run build`) would not warn until it passed
    // 650 kB, so keep an eye on it.
    chunkSizeWarningLimit: 650,
  },
  test: {
    globals: true,
    environment: "node",
  },
});
