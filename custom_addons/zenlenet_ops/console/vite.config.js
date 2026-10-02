import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  base: "/zenlenet_ops/static/console/",
  plugins: [react()],
  build: {
    outDir: "../static/console",
    emptyOutDir: true,
  },
});
