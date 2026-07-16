import { defineConfig } from "vite"

const frontendPort = Number.parseInt(process.env.FRONTEND_PORT || "8080", 10)

export default defineConfig({
  server: {
    host: "0.0.0.0",
    port: Number.isNaN(frontendPort) ? 8080 : frontendPort,
    strictPort: true,
    watch: {
      // Test sources and Playwright artifacts are not application inputs.
      // Watching them can reload a page while an E2E flow is still running.
      ignored: [
        "**/tests/**",
        "**/e2e/**",
        "**/test-results/**",
        "**/playwright-report/**",
      ],
    },
  },
})
