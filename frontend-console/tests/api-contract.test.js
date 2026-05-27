import { describe, expect, it } from "vitest"
import { readFileSync, readdirSync } from "node:fs"
import { dirname, join } from "node:path"
import { fileURLToPath } from "node:url"

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)))

function viewFiles() {
  const viewsDir = join(projectRoot, "views")
  return readdirSync(viewsDir)
    .filter((name) => name.endsWith(".js"))
    .map((name) => join(viewsDir, name))
}

function definedApiMethods() {
  const apiSource = readFileSync(join(projectRoot, "api.js"), "utf8")
  const groups = [...apiSource.matchAll(/\n\s{2}([a-zA-Z0-9_]+):\s*\{/g)]
    .map((match) => [match[1], match.index])
  const methods = new Set()

  for (let i = 0; i < groups.length; i++) {
    const [group, start] = groups[i]
    const end = i + 1 < groups.length ? groups[i + 1][1] : apiSource.length
    const block = apiSource.slice(start, end)
    for (const match of block.matchAll(/\n\s{4}(?:\/\*\*[\s\S]*?\*\/\s*)?async\s+([a-zA-Z0-9_]+)\s*\(/g)) {
      methods.add(`${group}.${match[1]}`)
    }
  }

  return methods
}

function usedApiMethods() {
  const methods = new Map()
  for (const file of viewFiles()) {
    const source = readFileSync(file, "utf8")
    for (const match of source.matchAll(/api\.([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)/g)) {
      const key = `${match[1]}.${match[2]}`
      const line = source.slice(0, match.index).split("\n").length
      if (!methods.has(key)) methods.set(key, [])
      methods.get(key).push(`${file}:${line}`)
    }
  }
  return methods
}

describe("前后端 API 契约", () => {
  it("视图调用的 api.* 方法必须在 api.js 中定义", () => {
    const defined = definedApiMethods()
    const missing = [...usedApiMethods().entries()]
      .filter(([method]) => !defined.has(method))
      .map(([method, locations]) => `${method} (${locations.join(", ")})`)

    expect(missing).toEqual([])
  })

  it("视图不直接 fetch 相对 /api 路径，避免绕过 API_BASE_URL", () => {
    const violations = []
    for (const file of viewFiles()) {
      const source = readFileSync(file, "utf8")
      for (const match of source.matchAll(/fetch\(\s*([`'"])\/api\//g)) {
        const line = source.slice(0, match.index).split("\n").length
        violations.push(`${file}:${line}`)
      }
    }

    expect(violations).toEqual([])
  })
})
