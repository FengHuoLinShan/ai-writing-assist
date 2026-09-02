import { readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const __dirname = dirname(fileURLToPath(import.meta.url))
const indexHtml = readFileSync(resolve(__dirname, "../index.html"), "utf8")
const styles = readFileSync(resolve(__dirname, "../styles.css"), "utf8")
const theme = readFileSync(resolve(__dirname, "../editorial-theme.css"), "utf8")
const mapWorkspace = readFileSync(resolve(__dirname, "../vue/views/map/MapWorkspaceView.vue"), "utf8")
const mapStyles = mapWorkspace.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1] || ""
const writingDesk = readFileSync(resolve(__dirname, "../vue/views/writing/writing-desk.css"), "utf8")
const worldSidebar = readFileSync(resolve(__dirname, "../vue/views/world/components/WorldSidebarToolCard.vue"), "utf8")

function themeBlock(selector) {
  return theme.match(new RegExp(`${selector.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&")}\\s*\\{([\\s\\S]*?)\\n\\}`))?.[1] || ""
}

function token(block, name) {
  return block.match(new RegExp(`${name}:\\s*(#[0-9A-F]{6});`, "i"))?.[1]
}

function luminance(hex) {
  const channels = hex.slice(1).match(/../g).map((value) => Number.parseInt(value, 16) / 255)
    .map((value) => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
}

function contrast(foreground, background) {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a)
  return (values[0] + 0.05) / (values[1] + 0.05)
}

function mixHex(first, second, firstWeight) {
  const values = [first, second].map((hex) => hex.slice(1).match(/../g).map((value) => Number.parseInt(value, 16)))
  return `#${values[0].map((value, index) => Math.round(value * firstWeight + values[1][index] * (1 - firstWeight)).toString(16).padStart(2, "0")).join("")}`
}

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
    expect(theme).toMatch(/:root\s*\{[\s\S]*--nc-bg:\s*#FFFFFF;[\s\S]*--nc-ink:\s*#37352F;[\s\S]*--nc-accent:\s*#1B6FB8;[\s\S]*--nc-hairline:\s*#E9E9E7;/)
    expect(theme).toMatch(/\[data-theme="night"\]\s*\{[\s\S]*--nc-bg:\s*#111114;[\s\S]*--nc-ink:\s*#E5E2DC;[\s\S]*--nc-accent:\s*#D9A441;[\s\S]*--nc-hairline:\s*#26262A;/)
    expect(theme).toMatch(/\[data-theme="ink"\]\s*\{[\s\S]*--nc-bg:\s*#F7F3EA;[\s\S]*--nc-ink:\s*#1F2321;[\s\S]*--nc-accent:\s*#C03F2B;[\s\S]*--nc-hairline:\s*#D8D2CC;/)
  })

  it("keeps necessary text and primary actions at normal-text contrast", () => {
    const themes = [themeBlock(":root"), themeBlock('[data-theme="night"]'), themeBlock('[data-theme="ink"]')]
    for (const block of themes) {
      for (const background of [token(block, "--nc-bg"), token(block, "--nc-surface")]) {
        expect(contrast(token(block, "--nc-dim"), background)).toBeGreaterThanOrEqual(4.5)
      }
    }
    for (const block of themes) {
      const foreground = token(block, "--nc-on-accent")
      const accent = token(block, "--nc-accent")
      expect(contrast(foreground, accent)).toBeGreaterThanOrEqual(4.5)
      expect(contrast(foreground, mixHex(accent, token(block, "--nc-ink"), 0.85))).toBeGreaterThanOrEqual(4.5)
    }
    expect(theme).toMatch(/--text-on-accent:\s*var\(--nc-on-accent\);/)
  })

  it("uses the on-accent token on every text-bearing accent surface", () => {
    expect(styles).toMatch(/\.btn-primary\s*\{[^}]*color:\s*var\(--text-on-accent\);/s)
    expect(styles).toMatch(/\.btn-primary:hover\s*\{[^}]*color:\s*var\(--text-on-accent\);/s)
    expect(styles).toMatch(/\.btn-fab\s*\{[^}]*color:\s*var\(--text-on-accent\);/s)
    expect(styles).toMatch(/\.outline-float-chapter\.current\s*\{[^}]*color:\s*var\(--text-on-accent\);/s)
    expect(styles).toMatch(/\.badge-new\s*\{[^}]*color:\s*var\(--text-on-accent\);/s)
    expect(styles.match(/\.btn\.btn-primary\.settings-btn-loading::after\s*\{[^}]*color:\s*var\(--text-on-accent\);/gs)).toHaveLength(2)
    expect(theme).toMatch(/\.btn-primary\s*\{[^}]*color:\s*var\(--text-on-accent\);/s)
    expect(theme).toMatch(/\.btn-primary:hover\s*\{[^}]*color:\s*var\(--text-on-accent\);/s)
    expect(theme).toMatch(/\.btn-fab\s*\{[^}]*color:\s*var\(--text-on-accent\);/s)
    expect(writingDesk).toMatch(/\.outline-float-chapter\.current\s*\{[^}]*color:\s*var\(--text-on-accent\);/s)
    expect(worldSidebar).toMatch(/\.world-sidebar-tools__action\.is-primary\s*\{[^}]*color:\s*var\(--text-on-accent\);/s)
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
    expect(theme).toMatch(/\.btn-primary\s*\{[^}]*background:\s*var\(--nc-accent\);[^}]*color:\s*var\(--text-on-accent\);/s)
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

  it("keeps Map UI on defined semantic tokens with readable three-theme combinations", () => {
    const declaredTokens = new Set([...`${styles}\n${theme}`.matchAll(/(?:^|[;{])\s*(--[\w-]+)\s*:/gm)].map((match) => match[1]))
    const usedTokens = new Set([...mapStyles.matchAll(/var\(\s*(--[\w-]+)/g)].map((match) => match[1]))
    expect([...usedTokens].filter((name) => !declaredTokens.has(name))).toEqual([])
    expect(mapStyles).not.toMatch(/var\(\s*--[\w-]+\s*,/)

    const imageViewport = mapStyles.match(/\.atlas-image-viewport\{[^}]*\}/)?.[0] || ""
    expect(imageViewport).toMatch(/background:#20242C;color:#FFFFFF/)
    expect(mapStyles.replace(imageViewport, "")).not.toMatch(/#[0-9A-F]{3,8}\b/i)

    for (const block of [themeBlock(":root"), themeBlock('[data-theme="night"]'), themeBlock('[data-theme="ink"]')]) {
      for (const background of [token(block, "--nc-bg"), token(block, "--nc-surface"), token(block, "--nc-surface-muted")]) {
        expect(contrast(token(block, "--nc-body"), background)).toBeGreaterThanOrEqual(4.5)
      }
      for (const background of [token(block, "--nc-bg"), token(block, "--nc-surface")]) {
        expect(contrast(token(block, "--nc-dim"), background)).toBeGreaterThanOrEqual(4.5)
      }
      expect(contrast(token(block, "--nc-bg"), token(block, "--nc-ink"))).toBeGreaterThanOrEqual(4.5)
    }
    expect(contrast("#FFFFFF", "#20242C")).toBeGreaterThanOrEqual(4.5)
  })

  it("keeps Map typography, tabs and 390px hit targets within the page contract", () => {
    expect(mapStyles).toMatch(/\.atlas-eyebrow\{[^}]*font-size:var\(--text-xs\)/)
    expect(mapStyles).toMatch(/\.atlas-options label\{[^}]*font-size:var\(--text-sm\)/)
    expect(mapStyles).toMatch(/\.atlas-edit p\{[^}]*font-size:var\(--text-sm\)/)
    expect(mapStyles).toMatch(/\.atlas-evidence-grid \.atlas-candidate-note\{color:var\(--text-body\)/)
    expect(mapStyles).toMatch(/\.atlas-tabs button\{[^}]*border-bottom:2px solid transparent[^}]*font-size:var\(--text-base\)/)
    expect(mapStyles).toMatch(/\.atlas-tabs button\.active\{[^}]*border-color:var\(--accent\);color:var\(--text-primary\)/)
    expect(mapStyles).toMatch(/@media\(max-width:760px\)\{[^}]*\.atlas-primary-actions,[^}]*\.atlas-source\{flex-wrap:wrap\}/s)
    expect(mapStyles).toMatch(/@media\(max-width:760px\)[\s\S]*\.atlas-tabs button\{[^}]*flex:1 1 0;min-width:0;min-height:42px/)
    expect(mapStyles).toMatch(/@media\(max-width:760px\)[\s\S]*\.atlas-tree button,\.atlas-annotation\{min-height:42px\}/)
    expect(mapStyles).toMatch(/@media\(max-width:760px\)[\s\S]*\.atlas-header>div,\.atlas-source>div,\.atlas-page-header>div\{[^}]*min-width:0;overflow-wrap:anywhere/)
    expect(mapStyles).toMatch(/@media\(max-width:760px\)[\s\S]*\.atlas-upload-modal input\[type="file"\]\{max-width:100%\}/)
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
    expect(theme).toMatch(/button\.theme-dot\s*\{[^}]*width:\s*28px;[^}]*background:\s*transparent;/s)
    expect(theme).toMatch(/button\.theme-dot::before\s*\{[^}]*width:\s*14px;[^}]*border:\s*1px solid var\(--nc-hairline-strong\);/s)
    expect(theme).toMatch(/\.theme-dot\[data-theme-value="sticky"\]::before\s*\{[^}]*background:\s*#FFFFFF;/s)
    expect(theme).toMatch(/\.theme-dot\[data-theme-value="night"\]::before\s*\{[^}]*background:\s*#111114;/s)
    expect(theme).toMatch(/\.theme-dot\[data-theme-value="ink"\]::before\s*\{[^}]*background:\s*#C03F2B;/s)
    expect(theme).toMatch(/\.theme-dot\.is-active::before\s*\{[^}]*box-shadow:\s*0 0 0 2px var\(--nc-bg\),\s*0 0 0 4px var\(--nc-accent\);/s)
    expect(theme).toMatch(/@media \(max-width: 760px\)[\s\S]*?button\.theme-dot\s*\{[^}]*width:\s*42px;[^}]*height:\s*42px;/s)
    expect(styles).toMatch(/@media \(max-width: 760px\)[\s\S]*?#topbar \.topbar-center > :not\(#topbar-project\)\s*\{[^}]*display:\s*none;[\s\S]*?#topbar-project\s*\{[^}]*max-width:\s*none;[\s\S]*?\.avatar\s*\{[^}]*width:\s*42px;[^}]*height:\s*42px;/s)
  })

  it("animates theme switching and honors reduced motion", () => {
    expect(theme).toMatch(/html,[\s\S]*body,[\s\S]*#topbar,[\s\S]*#sidebar,[\s\S]*#workspace-content\s*\{[^}]*transition:\s*background-color 250ms ease, color 250ms ease, border-color 250ms ease;/s)
    expect(theme).toMatch(/@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*transition:\s*none;/s)
  })

  it("keeps the writing sheet editor focus-visible ring intact (pages/writing.md §8.7)", () => {
    expect(writingDesk).toMatch(/\.writing-sheet \.novel-editor:focus-visible\s*\{[^}]*outline:\s*2px solid var\(--archive-red\);/s)
    expect(theme).toMatch(/:where\([^)]*summary[^)]*\):focus-visible\s*\{[^}]*outline:\s*2px solid var\(--nc-accent\);/s)
  })

  it("keeps Scene Lens touch targets at 44px on 390px screens", () => {
    expect(writingDesk).toMatch(/@media \(max-width: 390px\)[\s\S]*\.scene-lens--mobile > summary\s*\{[^}]*min-height:\s*44px;/s)
    expect(writingDesk).toMatch(/@media \(max-width: 390px\)[\s\S]*\.scene-lens--mobile \.scene-lens__load \.btn\s*\{[^}]*min-height:\s*44px;/s)
  })

  it("stacks Today decisions without horizontal overflow at 390px", () => {
    expect(styles).toMatch(/@media \(max-width: 760px\)[\s\S]*\.today-attention-row\s*\{[^}]*flex-direction:\s*column;/s)
    expect(styles).toMatch(/@media \(max-width: 760px\)[\s\S]*\.today-attention-row__meta\s*\{[^}]*flex-wrap:\s*wrap;/s)
    expect(styles).toMatch(/@media \(max-width: 760px\)[\s\S]*\.today-attention-row__meta \.btn\s*\{[^}]*width:\s*100%;/s)
  })

  it("keeps night-theme disabled buttons on neutral paper instead of a light slab", () => {
    expect(theme).toMatch(/\[data-theme="night"\] \.btn:disabled,\s*\[data-theme="night"\] \.btn\.disabled\s*\{[^}]*background:\s*var\(--archive-paper-raised\);[^}]*color:\s*var\(--archive-ink-soft\);/s)
    expect(theme).toMatch(/\[data-theme="night"\] \.btn-text:disabled,\s*\[data-theme="night"\] \.btn-text\.disabled\s*\{[^}]*background:\s*transparent;/s)
    expect(styles).toMatch(/\[data-theme="night"\] \.rp-send-button:disabled\s*\{[^}]*background:\s*var\(--rp-accent-soft\);/s)
  })
})
