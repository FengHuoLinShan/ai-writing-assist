import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const here = dirname(fileURLToPath(import.meta.url))
const styles = readFileSync(resolve(here, "../styles.css"), "utf8")

describe("RP reading comfort", () => {
  it("keeps streaming distinct without animating every chunk", () => {
    expect(styles).toMatch(/\.rp-story-scroll\s*\{[^}]*calc\(\(100vw - 640px\) \/ 2\)/s)
    expect(styles).not.toMatch(/\.rp-story-scroll\s*\{[^}]*scroll-behavior:\s*smooth/s)
    expect(styles).toMatch(/\.rp-message--streaming\s*\{[^}]*border-left:\s*2px solid var\(--rp-accent\)/s)
  })

  it("keeps message actions discoverable and removes optional motion", () => {
    expect(styles).toMatch(/\.rp-message__actions\s*\{[^}]*opacity:\s*0\.68/s)
    expect(styles).toMatch(/\.rp-message__actions button\s*\{[^}]*font-size:\s*13px/s)
    expect(styles).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*\.entry-card,[\s\S]*\.rp-message__actions\s*\{\s*transition:\s*none;/s)
  })
})
