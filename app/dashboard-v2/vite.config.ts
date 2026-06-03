import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Served by FastAPI at /dashboard/ with assets under /statics/ (separate mount).
// base "/" keeps asset URLs absolute (/statics/...), matching app/dashboard/__init__.py.
export default defineConfig({
  plugins: [react()],
  define: {
    "import.meta.env.VITE_BASE_API": JSON.stringify(
      process.env.VITE_BASE_API || "/api/"
    ),
  },
  build: {
    outDir: "build",
    assetsDir: "statics",
    emptyOutDir: true,
    chunkSizeWarningLimit: 1500,
  },
});
