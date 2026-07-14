import { describe, expect, it } from "vitest"
import { readFileSync, readdirSync } from "node:fs"
import { dirname, join, relative } from "node:path"
import { fileURLToPath } from "node:url"

import "../apiContracts.js"

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)))
const { API_CONTRACTS, contractPath, getApiContract } = globalThis.apiContracts

function viewFiles() {
  const viewsDir = join(projectRoot, "views")
  return readdirSync(viewsDir)
    .filter((name) => name.endsWith(".js"))
    .map((name) => join(viewsDir, name))
}

function jsFilesRecursively(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name)
    if (entry.isDirectory()) return jsFilesRecursively(path)
    return entry.isFile() && entry.name.endsWith(".js") ? [path] : []
  })
}

function productionJsFiles() {
  const rootFiles = readdirSync(projectRoot, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".js"))
    .map((entry) => join(projectRoot, entry.name))
  return [
    ...rootFiles,
    ...["shared", "ui", "views"].flatMap((directory) => (
      jsFilesRecursively(join(projectRoot, directory))
    )),
  ]
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
    for (const match of block.matchAll(/\n\s{4}(?:\/\*\*[\s\S]*?\*\/\s*)?(?:async\s+)?([a-zA-Z0-9_]+)\s*[\(=:]/g)) {
      methods.add(`${group}.${match[1]}`)
    }
  }

  const settingsStart = apiSource.indexOf("const settingsApi = {")
  const settingsEnd = apiSource.indexOf("api.settings = settingsApi")
  if (settingsStart >= 0 && settingsEnd > settingsStart) {
    const settingsBlock = apiSource.slice(settingsStart, settingsEnd)
    for (const match of settingsBlock.matchAll(/\n\s{2}([a-zA-Z0-9_]+):\s*\(?/g)) {
      methods.add(`settings.${match[1]}`)
    }
  }

  return methods
}

function stripNonCodeText(source) {
  const out = [...source]
  let state = "code"
  let templateExpressionDepth = 0

  function blank(index) {
    if (out[index] !== "\n") out[index] = " "
  }

  for (let i = 0; i < source.length; i += 1) {
    const char = source[i]
    const next = source[i + 1]

    if (state === "code") {
      if (char === "/" && next === "/") {
        blank(i)
        blank(i + 1)
        i += 1
        state = "line-comment"
      } else if (char === "/" && next === "*") {
        blank(i)
        blank(i + 1)
        i += 1
        state = "block-comment"
      } else if (char === "'" || char === "\"") {
        blank(i)
        state = char === "'" ? "single" : "double"
      } else if (char === "`") {
        blank(i)
        state = "template"
      }
    } else if (state === "line-comment") {
      blank(i)
      if (char === "\n") state = "code"
    } else if (state === "block-comment") {
      blank(i)
      if (char === "*" && next === "/") {
        blank(i + 1)
        i += 1
        state = "code"
      }
    } else if (state === "single" || state === "double") {
      blank(i)
      if (char === "\\") {
        blank(i + 1)
        i += 1
      } else if (
        (state === "single" && char === "'")
        || (state === "double" && char === "\"")
      ) {
        state = "code"
      }
    } else if (state === "template") {
      if (char === "$" && next === "{") {
        templateExpressionDepth = 1
        i += 1
        state = "template-expression"
      } else {
        blank(i)
        if (char === "\\") {
          blank(i + 1)
          i += 1
        } else if (char === "`") {
          state = "code"
        }
      }
    } else if (state === "template-expression") {
      if (char === "'" || char === "\"") {
        blank(i)
        state = char === "'" ? "template-single" : "template-double"
      } else if (char === "`") {
        blank(i)
        state = "nested-template"
      } else if (char === "{") {
        templateExpressionDepth += 1
      } else if (char === "}") {
        templateExpressionDepth -= 1
        if (templateExpressionDepth === 0) state = "template"
      }
    } else if (state === "template-single" || state === "template-double") {
      blank(i)
      if (char === "\\") {
        blank(i + 1)
        i += 1
      } else if (
        (state === "template-single" && char === "'")
        || (state === "template-double" && char === "\"")
      ) {
        state = "template-expression"
      }
    } else if (state === "nested-template") {
      blank(i)
      if (char === "\\") {
        blank(i + 1)
        i += 1
      } else if (char === "`") {
        state = "template-expression"
      }
    }
  }

  return out.join("")
}

function collectUsedApiMethods(sources) {
  const methods = new Map()
  for (const [file, source] of sources.entries()) {
    const codeOnly = stripNonCodeText(source)
    for (const match of codeOnly.matchAll(/api\.([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)/g)) {
      const key = `${match[1]}.${match[2]}`
      const line = source.slice(0, match.index).split("\n").length
      if (!methods.has(key)) methods.set(key, [])
      methods.get(key).push(`${relative(projectRoot, file)}:${line}`)
    }
  }
  return methods
}

function usedApiMethods() {
  const sources = new Map()
  for (const file of viewFiles()) {
    sources.set(file, readFileSync(file, "utf8"))
  }
  return collectUsedApiMethods(sources)
}

function formatMissingApiMethods(used, defined) {
  return [...used.entries()]
    .filter(([method]) => !defined.has(method))
    .map(([method, locations]) => `${method}\n  ${locations.join("\n  ")}`)
}

describe("前后端 API 契约", () => {
  it("index.html 在 api.js 之前加载 apiContracts.js", () => {
    const html = readFileSync(join(projectRoot, "index.html"), "utf8")
    const scripts = [...html.matchAll(/<script[^>]+src="([^"]+)"/g)].map((match) => match[1])

    expect(scripts.indexOf("apiContracts.js")).toBeGreaterThanOrEqual(0)
    expect(scripts.indexOf("apiContracts.js")).toBeLessThan(scripts.indexOf("api.js"))
    expect(html).toMatch(/<script\s+type="module"\s+src="api\.js"><\/script>/)
  })

  it("封闭测试令牌不再从 Web Storage 读取或写入", () => {
    const productionFiles = productionJsFiles()
    const combined = productionFiles
      .map((file) => readFileSync(file, "utf8"))
      .join("\n")

    expect(combined).not.toContain("novel_app_access_token")
  })

  it("API module executes before authenticated error mirroring and app startup", () => {
    const html = readFileSync(join(projectRoot, "index.html"), "utf8")
    const apiIndex = html.indexOf('<script type="module" src="api.js"></script>')
    const loggerIndex = html.indexOf('<script type="module" src="errorLogger.js"></script>')
    const appIndex = html.indexOf('<script type="module" src="app.js"></script>')

    expect(apiIndex).toBeGreaterThanOrEqual(0)
    expect(loggerIndex).toBeGreaterThan(apiIndex)
    expect(appIndex).toBeGreaterThan(apiIndex)
    expect(loggerIndex).toBeLessThan(appIndex)
  })

  it("API_CONTRACTS 注册的 wrapper 必须在 api.js 中存在", () => {
    const defined = definedApiMethods()
    const missing = Object.keys(API_CONTRACTS).filter((key) => !defined.has(key))

    expect(missing).toEqual([])
  })

  it("高风险契约暴露代表性 method/path/timeout", () => {
    expect(getApiContract("world.getEntity").method).toBe("GET")
    expect(contractPath("world.getEntity", { id: "entity-1" }, { novel_id: "novel-1" }))
      .toBe("/world/entities/entity-1?novel_id=novel-1")

    expect(contractPath("imports.startStage", { stage: "scenes" }))
      .toBe("/imports/stages/scenes")
    expect(contractPath("imports.startStage", { stage: "world_objects" }))
      .toBe("/imports/stages/world-objects")
    expect(contractPath("imports.startStage", { stage: "plot_structure" }))
      .toBe("/imports/stages/plot-structure")
    expect(getApiContract("imports.deepImport").requiredBody)
      .toEqual(["adoption_policy", "authorization_confirmed"])
    expect(getApiContract("imports.startStage").requiredBody)
      .toEqual(["adoption_policy", "authorization_confirmed"])
    expect(contractPath("outline.applyStructurePreview"))
      .toBe("/outline/generate/apply")
    expect(getApiContract("outline.applyStructurePreview").requiredBody)
      .toEqual(["novel_id", "context_confirmation_id", "source_task_id", "draft_structure", "confirmed"])
    expect(contractPath("outline.applyChapterScenePreview"))
      .toBe("/outline/chapter-scenes/apply")
    expect(getApiContract("outline.applyChapterScenePreview").requiredBody)
      .toEqual(["novel_id", "context_confirmation_id", "source_task_id", "draft_scenes", "confirmed"])
    expect(contractPath("outline.previewSceneFusion", {}, { novel_id: "novel-1" }))
      .toBe("/outline/scene-workbench/fusion/preview?novel_id=novel-1")
    expect(getApiContract("outline.previewSceneFusion")).toMatchObject({
      method: "POST",
      timeoutKind: "llmGenerate",
      timeout: 90000,
    })

    expect(getApiContract("context.confirm")).toMatchObject({
      method: "POST",
      timeoutKind: "contextConfirm",
      timeout: 90000,
    })
    expect(contractPath("context.evidenceHealth", {}, { novel_id: "novel-1" }))
      .toBe("/context/evidence-health?novel_id=novel-1")
    expect(contractPath("context.listRetrievalTraces", {}, {
      novel_id: "novel-1",
      content_mode: "canonical",
      limit: 20,
    })).toBe("/context/retrieval-traces?novel_id=novel-1&content_mode=canonical&limit=20")
    expect(contractPath("generate.listPromptTemplateRevisions", { templateId: "tpl-1" }, { novel_id: "novel-1" }))
      .toBe("/world/generation-prompt-templates/tpl-1/revisions?novel_id=novel-1")
    expect(contractPath("tasks.cancel", { taskId: "task-1" }, { novel_id: "novel-1" }))
      .toBe("/tasks/task-1/cancel?novel_id=novel-1")
    expect(contractPath("tasks.retry", { taskId: "task-1" }, { novel_id: "novel-1" }))
      .toBe("/tasks/task-1/retry?novel_id=novel-1")
    expect(getApiContract("rag.search")).toMatchObject({
      method: "POST",
      timeoutKind: "ragSearch",
      timeout: 60000,
    })
    expect(getApiContract("rag.prewarm")).toMatchObject({
      method: "POST",
      timeoutKind: "ragPrewarm",
      timeout: 75000,
    })

    expect(contractPath("writing.runConflictAiReview", { checkId: "check-1" }))
      .toBe("/writing/conflict-checks/check-1/ai-review")
    expect(contractPath("writing.adoptDraftCandidate", { draftId: "draft-1" }, { novel_id: "novel-1" }))
      .toBe("/writing/drafts/draft-1/adopt?novel_id=novel-1")
    expect(contractPath("writing.checkpoint", { draftId: "draft-1" }, { novel_id: "novel-1" }))
      .toBe("/writing/drafts/draft-1/checkpoint?novel_id=novel-1")
    expect(contractPath("writing.discard", { draftId: "draft-1" }, { novel_id: "novel-1" }))
      .toBe("/writing/drafts/draft-1/discard?novel_id=novel-1")
    expect(contractPath("writing.enqueueConflictAiReview", { checkId: "check-1" }))
      .toBe("/writing/conflict-checks/check-1/ai-review-task")
  })

  it("视图调用的 api.* 方法必须在 api.js 中定义", () => {
    const defined = definedApiMethods()
    const missing = formatMissingApiMethods(usedApiMethods(), defined)

    expect(missing).toEqual([])
  })

  it("扫描 API 调用时忽略字符串和模板静态文本里的 URL", () => {
    const used = collectUsedApiMethods(new Map([
      [join(projectRoot, "views/exampleView.js"), `
        const literal = "https://api.example.com/v1"
        const html = \`<input placeholder="https://api.example.com/v1" />\`
        api.projects.list()
      `],
    ]))

    expect([...used.keys()]).toEqual(["projects.list"])
  })

  it("缺失 API 方法按相对路径和行号输出", () => {
    const used = collectUsedApiMethods(new Map([
      [join(projectRoot, "views/exampleView.js"), "\napi.missing.method()\n"],
    ]))

    expect(formatMissingApiMethods(used, new Set())).toEqual([
      "missing.method\n  views/exampleView.js:2",
    ])
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
