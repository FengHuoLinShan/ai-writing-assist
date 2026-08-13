import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const __dirname = dirname(fileURLToPath(import.meta.url))
const indexHtml = readFileSync(resolve(__dirname, "../index.html"), "utf8")
const styles = readFileSync(resolve(__dirname, "../styles.css"), "utf8")
const theme = readFileSync(resolve(__dirname, "../editorial-theme.css"), "utf8")
const mapWorkspace = readFileSync(resolve(__dirname, "../vue/views/map/MapWorkspaceView.vue"), "utf8")

describe("editorial archive theme", () => {
  it("loads after the legacy stylesheet so the rollout stays incremental", () => {
    expect(indexHtml.indexOf('href="styles.css"')).toBeGreaterThan(-1)
    expect(indexHtml.indexOf('href="editorial-theme.css"')).toBeGreaterThan(
      indexHtml.indexOf('href="styles.css"'),
    )
  })

  it("does not keep the obsolete global action strip", () => {
    expect(indexHtml).not.toContain('id="workspace-header"')
    expect(indexHtml).not.toContain('id="view-actions"')
  })

  it("defines the --nc-* token layer for sticky, night and ink themes", () => {
    expect(theme).toMatch(/:root\s*\{[\s\S]*--nc-bg:\s*#FFFFFF;[\s\S]*--nc-ink:\s*#37352F;[\s\S]*--nc-accent:\s*#2383E2;[\s\S]*--nc-hairline:\s*#E9E9E7;/)
    expect(theme).toMatch(/\[data-theme="night"\]\s*\{[\s\S]*--nc-bg:\s*#111114;[\s\S]*--nc-ink:\s*#E5E2DC;[\s\S]*--nc-accent:\s*#D9A441;[\s\S]*--nc-hairline:\s*#26262A;/)
    expect(theme).toMatch(/\[data-theme="ink"\]\s*\{[\s\S]*--nc-bg:\s*#F7F3EA;[\s\S]*--nc-ink:\s*#1F2321;[\s\S]*--nc-accent:\s*#C03F2B;[\s\S]*--nc-hairline:\s*#D8D2CC;/)
  })

  it("keeps the --archive-* compatibility aliases as pure forwards", () => {
    expect(theme).toMatch(/--archive-paper:\s*var\(--nc-bg\);/)
    expect(theme).toMatch(/--archive-paper-raised:\s*var\(--nc-surface\);/)
    expect(theme).toMatch(/--archive-ink:\s*var\(--nc-ink\);/)
    expect(theme).toMatch(/--archive-red:\s*var\(--nc-accent\);/)
    expect(theme).toMatch(/--archive-rule:\s*var\(--nc-hairline\);/)
    expect(theme).toMatch(/--archive-rule-strong:\s*var\(--nc-hairline-strong\);/)
  })

  it("leaves color, radius and shadow tokens solely to the editorial layer", () => {
    expect(styles).not.toMatch(/^\s*--(bg-base|bg-panel|text-primary|accent|success|warning|error|border|shadow-sm|radius-sm|line-subtle):/m)
    expect(theme).toMatch(/--bg:\s*var\(--bg-base\);/)
    expect(theme).toMatch(/--text-dim:\s*var\(--text-tertiary\);/)
    expect(theme).toMatch(/--bg-alt:\s*var\(--bg-active\);/)
    expect(theme).toMatch(/--accent-dim:\s*var\(--accent-hover\);/)
  })

  it("gives functional buttons and form fields visible interaction hierarchy", () => {
    expect(theme).toMatch(/\.btn-primary\s*\{[^}]*background:\s*var\(--nc-accent\);[^}]*color:\s*#FFFFFF;/s)
    expect(theme).toMatch(/\.form-input,[\s\S]*\.form-select,[\s\S]*\.form-textarea,[\s\S]*border:\s*1px solid var\(--nc-hairline-strong\);/)
    expect(theme).toMatch(/\.form-input:focus,[\s\S]*\.form-select:focus,[\s\S]*border:\s*1px solid var\(--nc-accent\);/)
  })

  it("styles shared and nested tabs as clean index controls", () => {
    expect(theme).toContain(".subnav-item")
    expect(theme).toContain(".generate-subtabs .generate-subtab")
    expect(theme).toContain(".settings-tab-nav .tab-btn")
    expect(theme).toContain(".cockpit-tab")
    expect(theme).not.toContain(".map-view-mode")
    expect(mapWorkspace).toContain(".atlas-tabs button.active")
    expect(theme).toContain(".world-object-view-toggle .btn")
    expect(theme).toMatch(/\.subnav-item\.active,[\s\S]*box-shadow:\s*inset 0 -2px 0 var\(--nc-accent\);/)
  })

  it("covers every workspace family and preserves compact mobile controls", () => {
    for (const view of ["writing", "world", "outline", "rag", "generate", "map", "settings", "project-settings"]) {
      expect(theme).toContain(`[data-workspace-view="${view}"]`)
    }
    expect(theme).toMatch(/@media \(max-width: 760px\)[\s\S]*\.btn\s*\{[^}]*min-height:\s*42px;/s)
    expect(theme).toMatch(/@media \(prefers-reduced-motion: reduce\)/)
  })

  it("drops the retired archive folio, poster mark and settings ornaments", () => {
    expect(theme).not.toContain("--archive-folio")
    expect(theme).not.toContain("--archive-section")
    expect(theme).not.toContain("--archive-mark")
    expect(theme).not.toContain("archive-settings-section")
    expect(theme).not.toContain("⚙")
    expect(theme).not.toContain('content: var(--archive-mark);')
    expect(theme).not.toContain('[data-theme="warm"]')
    expect(theme).not.toContain('[data-theme="dark"]')
    expect(styles).not.toMatch(/main-layout--immersive\s+#workspace-content::before/)
  })

  it("restyles the global chrome with hairline separation and theme surfaces", () => {
    expect(theme).toMatch(/#topbar\s*\{[^}]*background:\s*var\(--nc-bg\);[^}]*border-bottom:\s*1px solid var\(--nc-hairline\);[^}]*backdrop-filter:\s*none;/s)
    expect(theme).toMatch(/#sidebar\s*\{[^}]*background:\s*var\(--nc-surface\);[^}]*border-right:\s*1px solid var\(--nc-hairline\);/s)
    expect(theme).toMatch(/#main-layout,[\s\S]*#workspace\s*\{[^}]*background-color:\s*var\(--nc-bg\);/s)
    expect(theme).toMatch(/outline:\s*2px solid var\(--nc-accent\);/)
  })

  it("ships the three-dot theme switcher skin behind the shell contract", () => {
    expect(theme).toMatch(/\.topbar-theme\s*\{[^}]*display:\s*flex;[^}]*gap:\s*8px;/s)
    expect(theme).toMatch(/button\.theme-dot\s*\{[^}]*width:\s*14px;[^}]*border:\s*1px solid var\(--nc-hairline-strong\);[^}]*border-radius:\s*50%;/s)
    expect(theme).toMatch(/\.theme-dot\[data-theme-value="sticky"\]\s*\{[^}]*background:\s*#FFFFFF;/s)
    expect(theme).toMatch(/\.theme-dot\[data-theme-value="night"\]\s*\{[^}]*background:\s*#111114;/s)
    expect(theme).toMatch(/\.theme-dot\[data-theme-value="ink"\]\s*\{[^}]*background:\s*#C03F2B;/s)
    expect(theme).toMatch(/\.theme-dot\.is-active\s*\{[^}]*box-shadow:\s*0 0 0 2px var\(--nc-bg\),\s*0 0 0 4px var\(--nc-accent\);/s)
  })

  it("animates theme switching and honors reduced motion", () => {
    expect(theme).toMatch(/html,[\s\S]*body,[\s\S]*#topbar,[\s\S]*#sidebar,[\s\S]*#workspace-content\s*\{[^}]*transition:\s*background-color 250ms ease, color 250ms ease, border-color 250ms ease;/s)
    expect(theme).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*transition:\s*none;/s)
  })

  it("keeps the writing sheet editor focus-visible ring intact (pages/writing.md §8.7)", () => {
    const desk = readFileSync(resolve(__dirname, "../vue/views/writing/writing-desk.css"), "utf8")
    expect(desk).toMatch(/\.writing-sheet \.novel-editor:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--archive-red\);/s)
  })

  it("keeps night-theme disabled buttons on neutral paper instead of a light slab", () => {
    expect(theme).toMatch(/\[data-theme="night"\] \.btn:disabled,\s*\[data-theme="night"\] \.btn\.disabled\s*\{[^}]*background:\s*var\(--archive-paper-raised\);[^}]*color:\s*var\(--archive-ink-soft\);/s)
    expect(theme).toMatch(/\[data-theme="night"\] \.btn-text:disabled,\s*\[data-theme="night"\] \.btn-text\.disabled\s*\{[^}]*background:\s*transparent;/s)
    expect(styles).toMatch(/\[data-theme="night"\] \.rp-send-button:disabled\s*\{[^}]*background:\s*var\(--rp-accent-soft\);/s)
  })
})
