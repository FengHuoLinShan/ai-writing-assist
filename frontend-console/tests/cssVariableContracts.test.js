import { readdirSync, readFileSync } from "node:fs"
import { dirname, extname, join, relative, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const sourceExtensions = new Set([".css", ".js", ".vue"])
const skippedDirectories = new Set(["dist", "e2e", "node_modules", "prototypes", "tests"])
const dynamicVariables = new Set(["--rp-popover-arrow-x", "--world-bible-type-color"])
const themeBlockPattern = /\[data-theme=["'](?:night|ink)["']\][^{]*\{[^}]*\}/gs

function declarations(source) {
  return new Set([...source.matchAll(/(?:^|[;{])\s*(--[\w-]+)\s*:/gm)].map((match) => match[1]))
}

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    if (entry.isDirectory() && skippedDirectories.has(entry.name)) return []
    const path = join(directory, entry.name)
    return entry.isDirectory() ? sourceFiles(path) : sourceExtensions.has(extname(path)) ? [path] : []
  })
}

function lineNumber(source, index) {
  return source.slice(0, index).split("\n").length
}

function unresolvedVariables(source, definitions) {
  return [...source.matchAll(/var\(\s*(--[\w-]+)\s*\)/g)]
    .filter((match) => !definitions.has(match[1]))
}

describe("CSS variable contracts", () => {
  it("recognizes declarations without mistaking BEM pseudo selectors for definitions", () => {
    expect([...declarations(":root { --actual-token: #fff; }")]).toEqual(["--actual-token"])
    expect([...declarations(".button--active:hover { color: red; }")]).toEqual([])
  })

  it("does not promote scoped or theme-only definitions to shared contracts", () => {
    const consumer = ".consumer { color: var(--component-only); }"
    const componentDefinitions = declarations(".owner { --component-only: red; }")
    expect(unresolvedVariables(consumer, declarations(consumer))[0][1]).toBe("--component-only")
    expect(componentDefinitions.has("--component-only")).toBe(true)

    const themeOnly = '[data-theme="night"] { --theme-only: red; color: var(--theme-only); }'
    const baseDefinitions = declarations(themeOnly.replace(themeBlockPattern, ""))
    expect(unresolvedVariables(themeOnly, baseDefinitions)[0][1]).toBe("--theme-only")
  })

  it("defines every production CSS variable used without an explicit fallback", () => {
    const files = sourceFiles(root)
    const sources = files.map((path) => [path, readFileSync(path, "utf8")])
    const globalDefinitions = new Set(
      sources
        .filter(([path]) => ["editorial-theme.css", "styles.css"].includes(relative(root, path)))
        .flatMap(([, source]) => [...source.matchAll(/:root\s*\{([^}]*)\}/gs)])
        .flatMap((match) => [...declarations(match[1])]),
    )
    const missing = sources.flatMap(([path, source]) => {
      const baseDefinitions = declarations(source.replace(themeBlockPattern, ""))
      const availableDefinitions = new Set([...globalDefinitions, ...baseDefinitions, ...dynamicVariables])
      return unresolvedVariables(source, availableDefinitions)
        .map((match) => `${relative(root, path)}:${lineNumber(source, match.index)} ${match[1]}`)
    })

    expect(missing).toEqual([])
  })
})
