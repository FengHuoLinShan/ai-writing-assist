import { describe, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { dirname, resolve } from "node:path"

const __dirname = dirname(fileURLToPath(import.meta.url))
const styles = readFileSync(resolve(__dirname, "../styles.css"), "utf8")

describe("global typography tokens", () => {
  it("keeps the shared hidden utility available for popovers and status UI", () => {
    expect(styles).toMatch(/\.hidden\s*\{\s*display:\s*none\s*!important;\s*\}/s)
  })

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

  it("lets modal action buttons wrap instead of clipping long footer rows", () => {
    expect(styles).toMatch(/#modal-footer\s*\{[^}]*flex-wrap:\s*wrap;/s)
    expect(styles).toMatch(/#modal-footer \.btn\s*\{[^}]*white-space:\s*normal;/s)
  })

  it("keeps modal sizing and world bible AI semantic style hooks", () => {
    expect(styles).toMatch(/#modal-content\.modal-content--large\s*\{/)
    expect(styles).toMatch(/#modal-content\.modal-content--full\s*\{/)
    expect(styles).toMatch(/\.bible-ai-sidebar\s*\{/)
    expect(styles).toMatch(/\.bible-ai-message--assistant/)
    expect(styles).toMatch(/\.world-bible-suggestion-preview\s*\{/)
  })

  it("fully styles collapsible workspace rails and progress summaries", () => {
    expect(styles).toMatch(/--workspace-main-share:\s*64fr;/)
    expect(styles).toMatch(/\.workspace-rail > summary::\-webkit-details-marker\s*\{\s*display:\s*none;/s)
    expect(styles).toMatch(/\.workspace-rail__summary:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--accent\);/s)
    expect(styles).toMatch(/\.workflow-progress > summary::\-webkit-details-marker\s*\{\s*display:\s*none;/s)
    expect(styles).toMatch(/\.workflow-progress__compact:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--accent\);/s)
    expect(styles).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*\.workspace-rail__icon,[\s\S]*\.workflow-progress__chevron/)
  })
})
