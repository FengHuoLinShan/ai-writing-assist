import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, resolve } from "node:path"

const __dirname = dirname(fileURLToPath(import.meta.url))
const styles = readFileSync(resolve(__dirname, "../styles.css"), "utf8")

describe("global typography tokens", () => {
  it("prefers native Simplified Chinese UI fonts", () => {
    expect(styles).toMatch(/--font-ui:[^;]*"PingFang SC"[^;]*"Hiragino Sans GB"[^;]*;/)
  })

  it("keeps shared letter spacing neutral for Chinese UI text", () => {
    expect(styles).toMatch(/--tracking-tight:\s*0;/)
    expect(styles).toMatch(/--tracking-normal:\s*0;/)
  })

  it("uses compact page-title typography instead of display sizing", () => {
    expect(styles).toMatch(/#view-title\s*\{[^}]*font-size:\s*var\(--text-xl\);/s)
    expect(styles).toMatch(/#view-title\s*\{[^}]*line-height:\s*var\(--leading-snug\);/s)
    expect(styles).toMatch(/#view-title\s*\{[^}]*letter-spacing:\s*0;/s)
    expect(styles).toMatch(/#view-title\s*\{[^}]*margin-left:\s*0;/s)
  })

  it("does not use negative offsets for prominent Chinese titles", () => {
    expect(styles).toMatch(/\.editor-title\s*\{[^}]*margin-left:\s*0;/s)
    expect(styles).toMatch(/\.project-header h1\s*\{[^}]*margin-left:\s*0;/s)
  })
})
