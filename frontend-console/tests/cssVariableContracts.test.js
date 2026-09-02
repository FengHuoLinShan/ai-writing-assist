import { readdirSync, readFileSync } from "node:fs"
import { dirname, extname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..")
const dynamicVariables = new Set(["--rp-popover-arrow-x", "--world-bible-type-color"])

function sourceFiles(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    return entry.isDirectory() ? sourceFiles(path) : [path]
  }).filter((path) => [".css", ".vue"].includes(extname(path)))
}

describe("CSS variable contracts", () => {
  it("defines every variable used without an explicit fallback", () => {
    const files = [resolve(root, "styles.css"), resolve(root, "editorial-theme.css"), ...sourceFiles(resolve(root, "vue"))]
    const sources = files.map((path) => [path, readFileSync(path, "utf8")])
    const definitions = new Set(sources.flatMap(([, source]) => [...source.matchAll(/(--[\w-]+)\s*:/g)].map((match) => match[1])))
    const missing = sources.flatMap(([path, source]) => [...source.matchAll(/var\(\s*(--[\w-]+)\s*\)/g)]
      .filter((match) => !definitions.has(match[1]) && !dynamicVariables.has(match[1]))
      .map((match) => `${path.slice(root.length + 1)}: ${match[1]}`))

    expect(missing).toEqual([])
  })
})
