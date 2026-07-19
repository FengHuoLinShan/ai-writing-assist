import { defineConfig } from "vite"
import vue from "@vitejs/plugin-vue"

const frontendPort = Number.parseInt(process.env.FRONTEND_PORT || "8080", 10)
const contentSecurityPolicy = [
  "default-src 'self'",
  "script-src 'self' https://unpkg.com",
  "style-src 'self' 'unsafe-inline' https://unpkg.com",
  "img-src 'self' data:",
  "connect-src 'self' http://localhost:* http://127.0.0.1:* ws://localhost:* ws://127.0.0.1:*",
  "object-src 'none'",
  "base-uri 'self'",
  "frame-ancestors 'none'",
].join("; ")

export const frontendSecurityHeaders = Object.freeze({
  "Content-Security-Policy": contentSecurityPolicy,
  "X-Frame-Options": "DENY",
})

export default defineConfig({
  plugins: [vue()],
  server: {
    host: "0.0.0.0",
    port: Number.isNaN(frontendPort) ? 8080 : frontendPort,
    strictPort: true,
    headers: frontendSecurityHeaders,
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
  preview: {
    headers: frontendSecurityHeaders,
  },
})
