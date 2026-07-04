import { defineConfig } from "vite"

const frontendPort = Number.parseInt(process.env.FRONTEND_PORT || "8080", 10)

export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: Number.isNaN(frontendPort) ? 8080 : frontendPort,
    strictPort: true,
  },
})
