import { existsSync, readFileSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

import { legacyRuntimeAssets } from "../vite.config.js"

const __dirname = dirname(fileURLToPath(import.meta.url))
const indexHtml = readFileSync(resolve(__dirname, "../index.html"), "utf8")

/**
 * AO-14 清单一致性测试：用独立实现（本文件内的解析，不复用 vite.config 的
 * parseClassicScriptAssets）从 index.html 抽取 classic `<script src>`，与
 * vite.config.js 实际使用的拷贝清单互为对照。任何一侧漂移（往 index.html
 * 增删脚本却没同步构建行为、或解析逻辑被改坏）都会让本测试变红。
 */
function extractDeclaredClassicScripts(html) {
  const declared = []
  for (const match of html.matchAll(/<script\b[^>]*>/gi)) {
    const tag = match[0]
    if (/type\s*=\s*("module"|'module')/i.test(tag)) continue
    const src = tag.match(/\bsrc\s*=\s*"([^"]+)"/i)?.[1]
    if (src) declared.push(src)
  }
  return declared
}

function extractDeclaredModuleScripts(html) {
  const declared = []
  for (const match of html.matchAll(/<script\b[^>]*type\s*=\s*("module"|'module')[^>]*>/gi)) {
    const src = match[0].match(/\bsrc\s*=\s*"([^"]+)"/i)?.[1]
    if (src) declared.push(src)
  }
  return declared
}

describe("classic runtime script manifest single source (AO-14)", () => {
  it("拷贝清单与 index.html 声明的 classic 脚本逐项一致（保持文档顺序）", () => {
    expect(legacyRuntimeAssets).toEqual(extractDeclaredClassicScripts(indexHtml))
  })

  it("index.html 的 type=module 入口由 Vite 打包，不进入拷贝清单", () => {
    const moduleEntries = extractDeclaredModuleScripts(indexHtml)
    expect(moduleEntries.length).toBeGreaterThan(0)
    for (const entry of moduleEntries) {
      expect(legacyRuntimeAssets).not.toContain(entry)
    }
  })

  it("拷贝清单非空，且每个资产都能在仓库中找到源文件", () => {
    expect(legacyRuntimeAssets.length).toBeGreaterThan(0)
    for (const asset of legacyRuntimeAssets) {
      expect(existsSync(resolve(__dirname, "..", asset)), `missing source: ${asset}`).toBe(true)
    }
  })
})
