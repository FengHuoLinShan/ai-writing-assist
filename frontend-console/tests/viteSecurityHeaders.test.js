import { describe, expect, it } from "vitest"

import viteConfig, { frontendSecurityHeaders } from "../vite.config.js"

describe("frontend response security headers", () => {
  it("denies framing in both Vite dev and preview responses", () => {
    expect(frontendSecurityHeaders["Content-Security-Policy"]).toContain("frame-ancestors 'none'")
    expect(frontendSecurityHeaders["X-Frame-Options"]).toBe("DENY")
    expect(viteConfig.server.headers).toBe(frontendSecurityHeaders)
    expect(viteConfig.preview.headers).toBe(frontendSecurityHeaders)
  })
})

describe("frontend development API proxy", () => {
  it("forwards only /api routes without intercepting the frontend api.js module", () => {
    expect(viteConfig.server.proxy["^/api(?:/|$)"]).toMatchObject({
      target: "http://127.0.0.1:8000",
      changeOrigin: true,
    })
    expect(viteConfig.server.proxy).not.toHaveProperty("/api")
  })
})
