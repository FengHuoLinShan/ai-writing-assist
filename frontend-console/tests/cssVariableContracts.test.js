import { readdirSync, readFileSync } from "node:fs"
import { dirname, extname, join, relative, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const sourceExtensions = new Set([".css", ".js", ".vue"])
const skippedDirectories = new Set(["dist", "e2e", "node_modules", "prototypes", "tests"])
const rootDefinitionFiles = new Set(["editorial-theme.css", "styles.css"])

const ownedVariableContracts = [
  {
    file: "styles.css",
    names: new Set(["--project-paper", "--project-paper-raised", "--project-ink", "--project-ink-soft", "--project-red", "--project-line"]),
    owner: /(?:^|, )\.project-catalog(?:$|[ .:[#])/,
    consumer: /\.project-/,
  },
  {
    file: "styles.css",
    names: new Set(["--project-visual-bg", "--project-visual-fg", "--project-visual-accent"]),
    owner: /(?:^|, )\.project-card(?:$|[ .:[#])/,
    consumer: /\.project-card/,
  },
  {
    file: "styles.css",
    names: new Set(["--rp-bg", "--rp-panel", "--rp-soft", "--rp-accent-soft", "--rp-text", "--rp-heading", "--rp-muted", "--rp-dim", "--rp-border", "--rp-accent", "--rp-danger-soft", "--rp-warning-soft"]),
    owner: /\.rp-(?:list|story)-page/,
    consumer: /\.rp-/,
  },
  {
    file: "styles.css",
    names: new Set(["--rp-confirm-accent", "--rp-confirm-accent-soft", "--rp-confirm-border", "--rp-confirm-muted", "--rp-confirm-panel"]),
    owner: /(?:^|, )\.rp-adaptive-confirm(?:$|[ .:[#])/,
    consumer: /\.rp-adaptive-confirm/,
  },
]

const dynamicVariableContracts = [
  {
    file: "styles.css",
    name: "--rp-popover-arrow-x",
    consumer: /\.rp-adaptive-confirm__arrow/,
    injectedBy: [{
      file: "vue/views/interaction/RpAdaptiveConfirmPopover.vue",
      patterns: [/class="rp-adaptive-confirm"/, /:style="popoverStyle"/, /["']--rp-popover-arrow-x["']\s*:/],
    }],
  },
  {
    file: "styles.css",
    name: "--world-bible-type-color",
    consumer: /\.world-bible-/,
    injectedBy: [
      {
        file: "vue/views/world/bible/WorldBibleTab.vue",
        patterns: [/class="world-bible-(?:category|page-card)/, /["']--world-bible-type-color["']\s*:/],
      },
      {
        file: "vue/views/world/bible/useWorldBible.js",
        patterns: [/class="world-bible-category-(?:preset|manager-card)/, /style="--world-bible-type-color:/],
      },
      {
        file: "vue/views/world/library/WorldLibraryCards.vue",
        patterns: [/class="world-bible-page-card/, /["']--world-bible-type-color["']\s*:/],
      },
    ],
  },
]

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    if (entry.isDirectory() && skippedDirectories.has(entry.name)) return []
    const path = join(directory, entry.name)
    return entry.isDirectory() ? sourceFiles(path) : sourceExtensions.has(extname(path)) ? [path] : []
  })
}

function maskComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, (comment) => comment.replace(/[^\n]/g, " "))
}

function selectorAt(source, index) {
  const open = source.lastIndexOf("{", index)
  if (open < 0) return ""
  const previousClose = source.lastIndexOf("}", open - 1)
  return source.slice(previousClose + 1, open).replace(/\s+/g, " ").trim()
}

function declarationRecords(source) {
  return [...source.matchAll(/(?:^|[;{])\s*(--[\w-]+)\s*:/gm)].map((match) => ({
    name: match[1],
    selector: selectorAt(source, match.index),
  }))
}

function usageRecords(source) {
  return [...source.matchAll(/var\(\s*(--[\w-]+)\s*\)/g)].map((match) => ({
    index: match.index,
    name: match[1],
    selector: selectorAt(source, match.index),
  }))
}

function lineNumber(source, index) {
  return source.slice(0, index).split("\n").length
}

function hasActualInjector(contract, sourceMap) {
  return contract.injectedBy.some(({ file, patterns }) => {
    const source = sourceMap.get(file) || ""
    return patterns.every((pattern) => pattern.test(source))
  })
}

function scanCssVariableContracts(sources) {
  const entries = sources.map(([path, source]) => ({ path, source: maskComments(source) }))
  const sourceMap = new Map(entries.map(({ path, source }) => [path, source]))
  const declarationsByFile = new Map(entries.map(({ path, source }) => [path, declarationRecords(source)]))
  const globalDefinitions = new Set(entries.flatMap(({ path }) => (
    rootDefinitionFiles.has(path)
      ? (declarationsByFile.get(path) || []).filter(({ selector }) => selector === ":root").map(({ name }) => name)
      : []
  )))

  return entries.flatMap(({ path, source }) => usageRecords(source).flatMap((usage) => {
    if (globalDefinitions.has(usage.name)) return []

    const sameRuleDefinition = (declarationsByFile.get(path) || []).some((definition) => (
      definition.name === usage.name && definition.selector === usage.selector
    ))
    if (sameRuleDefinition) return []

    const owned = ownedVariableContracts.some((contract) => (
      contract.file === path
      && contract.names.has(usage.name)
      && contract.consumer.test(usage.selector)
      && (declarationsByFile.get(path) || []).some((definition) => (
        definition.name === usage.name
        && !definition.selector.includes("[data-theme=")
        && contract.owner.test(definition.selector)
      ))
    ))
    if (owned) return []

    const dynamic = dynamicVariableContracts.some((contract) => (
      contract.file === path
      && contract.name === usage.name
      && contract.consumer.test(usage.selector)
      && hasActualInjector(contract, sourceMap)
    ))
    return dynamic ? [] : [`${path}:${lineNumber(source, usage.index)} ${usage.name}`]
  }))
}

describe("CSS variable contracts", () => {
  it("uses the production scanner for root, declaration, owner and theme boundaries", () => {
    expect(scanCssVariableContracts([
      ["styles.css", ":root { --shared: red; } .consumer { color: var(--shared); }"],
    ])).toEqual([])
    expect(scanCssVariableContracts([
      ["component.css", ".owner { --local: red; color: var(--local); }"],
    ])).toEqual([])
    expect(scanCssVariableContracts([
      ["component.css", ".owner { --local: red; }\n.consumer { color: var(--local); }"],
    ])).toEqual(["component.css:2 --local"])
    expect(scanCssVariableContracts([
      ["component.css", '[data-theme="night"] { --theme-only: red; }\n.consumer { color: var(--theme-only); }'],
    ])).toEqual(["component.css:2 --theme-only"])
    expect(scanCssVariableContracts([
      ["component.css", ".button--active:hover { color: var(--active); }"],
    ])).toEqual(["component.css:1 --active"])
  })

  it("defines every production CSS variable used without an explicit fallback", () => {
    const sources = sourceFiles(root).map((path) => [relative(root, path), readFileSync(path, "utf8")])
    expect(scanCssVariableContracts(sources)).toEqual([])
  })
})
