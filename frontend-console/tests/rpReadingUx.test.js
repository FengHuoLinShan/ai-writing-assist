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
    expect(styles).toMatch(/\.rp-partial-note,[^{]*\.rp-stream-status\s*\{[^}]*color:\s*var\(--rp-text\)/s)
    expect(styles).toMatch(/\.rp-load-failure button\s*\{[^}]*background:\s*var\(--rp-heading\);[^}]*color:\s*var\(--rp-bg\)/s)
  })

  it("keeps message actions discoverable and removes optional motion", () => {
    expect(styles).not.toMatch(/\.rp-message__actions\s*\{[^}]*opacity:/s)
    expect(styles).toMatch(/\.rp-message__actions button\s*\{[^}]*color:\s*var\(--rp-text\);[^}]*font-size:\s*13px/s)
    expect(styles).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*\.entry-card,[\s\S]*\.rp-message__actions\s*\{\s*transition:\s*none;/s)
    expect(styles).toMatch(/\.rp-button-spinner\s*\{[^}]*animation:\s*rp-spin 700ms linear infinite/s)
    expect(styles).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*\.rp-button-spinner\s*\{[^}]*animation:\s*none;/s)
    expect(styles).toMatch(/\.rp-send-button\.is-loading,[^{]*\.rp-stop-button\.is-loading\s*\{[^}]*color:\s*var\(--text-on-accent\)/s)
    expect(styles).toMatch(/\[data-theme="night"\] \.rp-send-button:disabled:not\(\.is-loading\)/)
    expect(styles).toMatch(/\.rp-mutation-button--retry\s*\{[^}]*inline-size:\s*9rem/s)
    expect(styles).toMatch(/\.rp-mutation-button--conflict\s*\{[^}]*inline-size:\s*13rem/s)
  })

  it("keeps the entry choice on the selected theme", () => {
    expect(styles).toMatch(/\.main-layout--immersive #workspace\s*\{[^}]*background:\s*var\(--bg-base\);/s)
    expect(styles).toMatch(/\.entry-card\s*\{[^}]*background:\s*var\(--rp-panel\);[^}]*color:\s*var\(--rp-heading\);/s)
    expect(styles).toMatch(/\.entry-choice,[^{]*\{[^}]*--rp-muted:\s*var\(--text-secondary\);[^}]*--rp-border:\s*var\(--text-secondary\);/s)
  })
})
