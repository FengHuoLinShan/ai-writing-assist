import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const __dirname = dirname(fileURLToPath(import.meta.url))
const indexHtml = readFileSync(resolve(__dirname, "../index.html"), "utf8")

function getCspPolicy() {
  const match = indexHtml.match(
    /<meta\s+http-equiv="Content-Security-Policy"\s+content="([^"]+)"/i,
  )
  return match?.[1] ?? ""
}

describe("index.html CSP baseline", () => {
  it("keeps scripts on self without unsafe-inline or external CDNs", () => {
    const policy = getCspPolicy()

    expect(policy).toContain("script-src 'self'")
    expect(policy).not.toContain("unpkg.com")
    expect(policy).not.toContain("script-src 'unsafe-inline'")
    expect(policy).not.toMatch(/script-src[^;]*'unsafe-inline'/)
  })

  it("allows self-hosted styles and local backend connections", () => {
    const policy = getCspPolicy()

    expect(policy).toContain("style-src 'self' 'unsafe-inline'")
    expect(policy).toContain("connect-src 'self' http://localhost:* http://127.0.0.1:*")
  })

  it("does not globally load Leaflet resources before the map view is opened", () => {
    expect(indexHtml).not.toContain("leaflet@1.9.4/dist/leaflet.css")
    expect(indexHtml).not.toContain("leaflet@1.9.4/dist/leaflet.js")
    expect(indexHtml).not.toMatch(/<link[^>]+leaflet/i)
    expect(indexHtml).not.toMatch(/<script[^>]+leaflet/i)
  })

  it("blocks plugin objects and fixes base URI to this origin", () => {
    const policy = getCspPolicy()

    expect(policy).toContain("object-src 'none'")
    expect(policy).toContain("base-uri 'self'")
  })
})
