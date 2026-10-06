import { chmod, mkdtemp, rm, stat, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"

import { describe, expect, it } from "vitest"

import viteConfig, {
  copyReadableRuntimeFile,
  frontendSecurityHeaders,
} from "../vite.config.js"

describe("frontend response security headers", () => {
  it("denies framing in both Vite dev and preview responses", () => {
    expect(frontendSecurityHeaders["Content-Security-Policy"]).toContain("frame-ancestors 'none'")
    expect(frontendSecurityHeaders["Content-Security-Policy"]).toContain("img-src 'self' data: blob:")
    expect(frontendSecurityHeaders["Content-Security-Policy"]).not.toContain("unpkg.com")
    expect(frontendSecurityHeaders["X-Frame-Options"]).toBe("DENY")
    expect(viteConfig.server.headers).toBe(frontendSecurityHeaders)
    expect(viteConfig.preview.headers).toBe(frontendSecurityHeaders)
  })
})

describe("frontend development API proxy", () => {
  it("forwards REST routes while serving the API source modules through Vite", () => {
    const [pattern, options] = Object.entries(viteConfig.server.proxy)[0]
    const matches = new RegExp(pattern)
    expect(options).toMatchObject({
      target: "http://127.0.0.1:8000",
      changeOrigin: true,
    })
    expect(viteConfig.server.proxy).not.toHaveProperty("/api")
    for (const path of ["/api", "/api/projects", "/api/health?fresh=1", "/api/world/entities/name.js"]) {
      expect(matches.test(path), path).toBe(true)
    }
    for (const path of ["/api.js", "/api/_shared.js", "/api/world.js?t=1", "/api/auth.js?import"]) {
      expect(matches.test(path), path).toBe(false)
    }
  })
})

describe("frontend production asset copy", () => {
  it("makes copied runtime files readable even when the checkout source is private", async () => {
    const directory = await mkdtemp(join(tmpdir(), "novelcraft-runtime-asset-"))
    const source = join(directory, "source.js")
    const destination = join(directory, "nested", "asset.js")

    try {
      await writeFile(source, "globalThis.runtimeReady = true\n")
      await chmod(source, 0o600)

      await copyReadableRuntimeFile(source, destination)

      expect((await stat(destination)).mode & 0o777).toBe(0o644)
    } finally {
      await rm(directory, { recursive: true, force: true })
    }
  })
})
