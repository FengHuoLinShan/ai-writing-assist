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

  it("keeps the entry choice on the selected theme", () => {
    expect(styles).toMatch(/\.entry-choice,[\s\S]*\.rp-list-page,[\s\S]*--rp-bg:\s*#fff;/s)
    expect(styles).toMatch(/\[data-theme="night"\] \.entry-choice,[\s\S]*--rp-bg:\s*var\(--bg-base\)/s)
    expect(styles).toMatch(/\[data-theme="ink"\] \.entry-choice,[\s\S]*--rp-bg:\s*var\(--bg-base\)/s)
    expect(styles).toMatch(/\.entry-card\s*\{[^}]*background:\s*var\(--rp-panel\);[^}]*color:\s*var\(--rp-heading\);/s)
  })
})
