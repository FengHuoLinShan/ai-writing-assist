import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const __dirname = dirname(fileURLToPath(import.meta.url))
const indexHtml = readFileSync(resolve(__dirname, "../index.html"), "utf8")
const theme = readFileSync(resolve(__dirname, "../editorial-theme.css"), "utf8")

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

  it("keeps the paper, navy and vermillion language across all three themes", () => {
    expect(theme).toMatch(/:root\s*\{[\s\S]*--archive-paper:[^;]+;[\s\S]*--archive-ink:[^;]+;[\s\S]*--archive-red:[^;]+;/)
    expect(theme).toMatch(/\[data-theme="warm"\]\s*\{[\s\S]*--archive-paper:[^;]+;[\s\S]*--archive-red:[^;]+;/)
    expect(theme).toMatch(/\[data-theme="dark"\]\s*\{[\s\S]*--archive-paper:[^;]+;[\s\S]*--archive-red:[^;]+;/)
  })

  it("gives functional buttons and form fields visible interaction hierarchy", () => {
    expect(theme).toMatch(/\.btn-primary\s*\{[^}]*background:\s*var\(--archive-ink\);[^}]*box-shadow:[^}]*var\(--archive-red\)/s)
    expect(theme).toMatch(/\.form-input,[\s\S]*\.form-select,[\s\S]*\.form-textarea,[\s\S]*border-left:\s*3px solid var\(--archive-ink\);/)
    expect(theme).toMatch(/\.form-input:focus,[\s\S]*\.form-select:focus,[\s\S]*border-left:\s*3px solid var\(--archive-red\);/)
  })

  it("styles shared and nested tabs as archive index controls", () => {
    expect(theme).toContain(".subnav-item")
    expect(theme).toContain(".generate-subtabs .generate-subtab")
    expect(theme).toContain(".settings-tab-nav .tab-btn")
    expect(theme).toContain(".cockpit-tab")
    expect(theme).toContain(".map-view-mode.is-active")
    expect(theme).toContain(".world-object-view-toggle .btn")
  })

  it("covers every workspace family and preserves compact mobile controls", () => {
    for (const view of ["writing", "scene", "world", "outline", "rag", "generate", "map", "settings", "project-settings"]) {
      expect(theme).toContain(`[data-workspace-view="${view}"]`)
    }
    expect(theme).toMatch(/@media \(max-width: 760px\)[\s\S]*\.btn\s*\{[^}]*min-height:\s*42px;/s)
    expect(theme).toMatch(/@media \(prefers-reduced-motion: reduce\)/)
  })

  it("assigns non-project workspaces a restrained folio and poster mark", () => {
    const marks = {
      writing: "文",
      world: "界",
      map: "图",
      rag: "索",
      outline: "纲",
      scene: "景",
      generate: "生",
      settings: "设",
      "project-settings": "策",
    }

    for (const [view, mark] of Object.entries(marks)) {
      expect(theme).toMatch(new RegExp(`data-workspace-view="${view}"\\]\\s*\\{[^}]*--archive-folio:[^;]+;[^}]*--archive-mark:\\s*"${mark}";`, "s"))
    }
    expect(theme).toContain('#workspace-content:not([data-workspace-view="project"])::before')
    expect(theme).toContain('#workspace-content[data-workspace-view="project"]::before')
  })

  it("uses the art direction on low-risk presentation surfaces", () => {
    expect(theme).toContain('#workspace-content:not([data-workspace-view="project"]) > .empty-state::before')
    expect(theme).toContain("content: var(--archive-mark);")
    expect(theme).toContain("counter-reset: archive-settings-section;")
    expect(theme).toContain("counter-increment: archive-settings-section;")
    expect(theme).toContain('#workspace-content[data-workspace-view="generate"] .generate-chat-panel::after')
    expect(theme).toContain("#modal-content")
    expect(theme).toMatch(/#main-layout,[\s\S]*#workspace\s*\{[^}]*background-color:\s*var\(--archive-paper\);/s)
  })

  it("keeps settings technology ornaments behind the interaction layer", () => {
    expect(theme).toContain('#workspace-content[data-workspace-view="settings"]::after')
    expect(theme).toContain('#workspace-content[data-workspace-view="project-settings"]::after')
    expect(theme).toContain('content: "⚙︎";')
    expect(theme).toMatch(/\.global-settings-view,[\s\S]*\.project-settings-view\s*\{[^}]*position:\s*relative;[^}]*z-index:\s*1;/s)
    expect(theme).toMatch(/content:\s*"⚙︎";[\s\S]*pointer-events:\s*none;[\s\S]*z-index:\s*0;/s)
  })
})
