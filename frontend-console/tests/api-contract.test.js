import { describe, expect, it, vi } from "vitest"
import { readFileSync, readdirSync } from "node:fs"
import { dirname, join, relative } from "node:path"
import { fileURLToPath } from "node:url"

import "../apiContracts.js"
import "../api.js"
import {
  applyMapEditor as applyMapEditorForE2E,
  listMaps as listMapsForE2E,
} from "../e2e/helpers/api-client.js"

const projectRoot = dirname(dirname(fileURLToPath(import.meta.url)))
const {
  API_CONTRACTS,
  contractPath,
  contractRequest,
  getApiContract,
} = globalThis.apiContracts

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
  const methods = new Set()
  const runtimeApi = globalThis.window?.api
  for (const [groupName, group] of Object.entries(runtimeApi || {})) {
    if (!group || typeof group !== "object") continue
    for (const [methodName, method] of Object.entries(group)) {
      if (typeof method === "function") methods.add(`${groupName}.${methodName}`)
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
    expect(contractPath("world.getReviewTypeCatalog"))
      .toBe("/world/review-type-catalog")
    expect(contractPath("world.listRelationReviewGroups", {}, {
      novel_id: "novel-1",
      q: "克莱恩",
      scene_index: 9,
      skip: 20,
      limit: 20,
    })).toBe("/world/relations/review-groups?novel_id=novel-1&q=%E5%85%8B%E8%8E%B1%E6%81%A9&scene_index=9&skip=20&limit=20")
    expect(contractPath("world.reviewRelationsBatch", {}, { novel_id: "novel-1" }))
      .toBe("/world/relations/review-batch?novel_id=novel-1")
    expect(getApiContract("world.reviewRelationsBatch").requiredBody)
      .toEqual(["confirmed", "decisions"])
    expect(contractPath("world.listAliasReviewGroups", {}, {
      novel_id: "novel-1",
      type_kind: "custom",
      limit: 50,
    })).toBe("/world/aliases/review-groups?novel_id=novel-1&type_kind=custom&limit=50")
    expect(contractPath("world.reviewAliasesBatch", {}, { novel_id: "novel-1" }))
      .toBe("/world/aliases/review-batch?novel_id=novel-1")
    expect(getApiContract("world.reviewAliasesBatch").requiredBody)
      .toEqual(["confirmed", "decisions"])
    expect(contractPath("world.replaceLocationLayouts", { mapId: "map-1" }, { novel_id: "novel-1" }))
      .toBe("/world/maps/map-1/location-layouts?novel_id=novel-1")
    expect(getApiContract("world.updateTerrainLayer").method).toBe("PATCH")
    expect(contractPath("world.updateTerrainLayer", { mapId: "map-1", layerId: "layer-1" }, { novel_id: "novel-1" }))
      .toBe("/world/maps/map-1/terrain/layers/layer-1?novel_id=novel-1")
    expect(getApiContract("world.deleteTerrainLayer").method).toBe("DELETE")
    expect(getApiContract("world.applyMapEditor")).toMatchObject({
      method: "POST",
      requiredBody: ["expected_revision", "commands"],
    })
    expect(contractPath("world.applyMapEditor", { mapId: "map-1" }, { novel_id: "novel-1" }))
      .toBe("/world/maps/map-1/editor/apply?novel_id=novel-1")
    expect(contractPath("world.getMapLayerTree", { mapId: "map-1" }, { novel_id: "novel-1" }))
      .toBe("/world/maps/map-1/layer-tree?novel_id=novel-1")
    expect(contractPath("world.getMapPaths", { mapId: "map-1" }, { novel_id: "novel-1", status: "all" }))
      .toBe("/world/maps/map-1/paths?novel_id=novel-1&status=all")
    expect(contractPath("world.getMapPathArchiveImpact", { mapId: "map-1", pathId: "path-1" }, { novel_id: "novel-1" }))
      .toBe("/world/maps/map-1/paths/path-1/archive-impact?novel_id=novel-1")
    expect(contractPath("world.getEntityMapPresence", { id: "entity-1" }, { novel_id: "novel-1" }))
      .toBe("/world/entities/entity-1/map-presence?novel_id=novel-1")
    expect(contractPath("world.getMapTimeline", { mapId: "map-1" }, {
      novel_id: "novel-1",
      from_scene_index: 2,
      to_scene_index: 9,
      tracks: "journey,status",
      include_candidates: true,
      skip: 0,
      limit: 500,
    })).toBe("/world/maps/map-1/timeline?novel_id=novel-1&from_scene_index=2&to_scene_index=9&tracks=journey%2Cstatus&include_candidates=true&skip=0&limit=500")
    expect(contractPath("world.getMapStateAt", { mapId: "map-1" }, {
      novel_id: "novel-1",
      scene_index: 9,
      focus_entity_id: "entity-1",
    })).toBe("/world/maps/map-1/state-at?novel_id=novel-1&scene_index=9&focus_entity_id=entity-1")
    expect(getApiContract("world.getMapStateAt").requiredQuery)
      .toEqual(["novel_id", "scene_index"])
    expect(contractPath("world.listProjectMapObservationInbox", {}, { novel_id: "novel-1" }))
      .toBe("/world/maps/project-observations/inbox?novel_id=novel-1")
    expect(contractPath("world.assignProjectMapObservation", { observationId: "obs-1" }, { novel_id: "novel-1" }))
      .toBe("/world/maps/project-observations/obs-1/assign?novel_id=novel-1")
    expect(getApiContract("world.assignProjectMapObservation").requiredBody)
      .toEqual(["map_id", "expected_updated_at"])
    expect(getApiContract("world.assignProjectMapObservation").hasBody).toBe(true)
    expect(getApiContract("world.confirmMapObservation").requiredBody)
      .toEqual(["expected_updated_at"])
    expect(getApiContract("world.confirmMapObservation").hasBody).toBe(true)

    expect(contractPath("imports.startStage", { stage: "scenes" }))
      .toBe("/imports/stages/scenes")
    expect(contractPath("imports.startStage", { stage: "world_objects" }))
      .toBe("/imports/stages/world-objects")
    expect(contractPath("imports.startStage", { stage: "plot_structure" }))
      .toBe("/imports/stages/plot-structure")
    expect(contractPath("imports.startMapObservationEnrichment"))
      .toBe("/imports/stages/map-observations")
    expect(getApiContract("imports.deepImport").requiredBody)
      .toEqual(["adoption_policy", "authorization_confirmed"])
    expect(getApiContract("imports.startStage").requiredBody)
      .toEqual(["adoption_policy", "authorization_confirmed"])
    expect(getApiContract("imports.startMapObservationEnrichment").requiredBody)
      .toEqual(["novel_id", "start_chapter", "end_chapter", "high_quality", "adoption_policy", "authorization_confirmed"])
    expect(contractPath("outline.analyze")).toBe("/outline/analyze")
    expect(getApiContract("outline.analyze")).toMatchObject({
      method: "POST",
      timeoutKind: "aiTaskSubmit",
      timeout: 600000,
    })
    expect(contractPath("outline.generate")).toBe("/outline/generate")
    expect(getApiContract("outline.generate")).toMatchObject({
      method: "POST",
      timeoutKind: "aiTaskSubmit",
      timeout: 600000,
    })
    expect(contractPath("outline.applyStructurePreview"))
      .toBe("/outline/generate/apply")
    expect(getApiContract("outline.applyStructurePreview").requiredBody)
      .toEqual(["novel_id", "context_confirmation_id", "source_task_id", "draft_structure", "confirmed"])
    expect(getApiContract("outline.applyStructurePreview")).toMatchObject({
      method: "POST",
      timeoutKind: "aiPreviewApply",
      timeout: 600000,
    })
    expect(contractPath("outline.getStoryOutline", {}, { novel_id: "novel-1" }))
      .toBe("/outline/story-outline?novel_id=novel-1")
    expect(contractPath("outline.listStoryOutlineRevisions", {}, {
      novel_id: "novel-1",
      skip: 0,
      limit: 20,
    })).toBe("/outline/story-outline/revisions?novel_id=novel-1&skip=0&limit=20")
    expect(contractPath("outline.getStoryOutlineRevision", { revisionId: "rev-1" }, {
      novel_id: "novel-1",
    })).toBe("/outline/story-outline/revisions/rev-1?novel_id=novel-1")
    expect(contractPath("outline.restoreStoryOutlineRevision", { revisionId: "rev-1" }, {
      novel_id: "novel-1",
    })).toBe("/outline/story-outline/revisions/rev-1/apply?novel_id=novel-1")
    expect(contractPath("outline.generateStoryOutline"))
      .toBe("/outline/story-outline/generate")
    expect(getApiContract("outline.generateStoryOutline")).toMatchObject({
      method: "POST",
      timeoutKind: "aiTaskSubmit",
      timeout: 600000,
    })
    expect(contractPath("outline.applyStoryOutlinePreview"))
      .toBe("/outline/story-outline/generate/apply")
    expect(getApiContract("outline.applyStoryOutlinePreview")).toMatchObject({
      method: "POST",
      timeoutKind: "aiPreviewApply",
      timeout: 600000,
    })
    expect(contractPath("outline.previewSceneFusion", {}, { novel_id: "novel-1" }))
      .toBe("/outline/scene-workbench/fusion/preview?novel_id=novel-1")
    expect(getApiContract("outline.previewSceneFusion")).toMatchObject({
      method: "POST",
      timeoutKind: "llmGenerate",
      timeout: 2100000,
    })

    expect(getApiContract("context.confirm")).toMatchObject({
      method: "POST",
      timeoutKind: "contextConfirm",
      timeout: 600000,
    })
    expect(getApiContract("context.compile")).toMatchObject({
      method: "POST",
      timeoutKind: "contextCompile",
      timeout: 600000,
    })
    expect(getApiContract("context.render")).toMatchObject({
      method: "POST",
      timeoutKind: "contextCompile",
      timeout: 600000,
    })
    expect(contractPath("context.evidenceHealth", {}, { novel_id: "novel-1" }))
      .toBe("/context/evidence-health?novel_id=novel-1")
    expect(contractPath("context.listRetrievalTraces", {}, {
      novel_id: "novel-1",
      content_mode: "canonical",
      limit: 20,
    })).toBe("/context/retrieval-traces?novel_id=novel-1&content_mode=canonical&limit=20")
    for (const name of [
      "context.searchEvidence",
      "context.grepEvidence",
      "context.readEvidence",
    ]) {
      expect(getApiContract(name)).toMatchObject({
        method: "POST",
        timeoutKind: "ragSearch",
        timeout: 2100000,
      })
    }
    expect(contractPath("generate.listPromptTemplateRevisions", { templateId: "tpl-1" }, { novel_id: "novel-1" }))
      .toBe("/world/generation-prompt-templates/tpl-1/revisions?novel_id=novel-1")
    expect(getApiContract("generate.worldChat")).toMatchObject({
      method: "POST",
      timeoutKind: "llmGenerate",
      timeout: 2100000,
    })
    expect(getApiContract("generate.generateWorldSuggestion")).toMatchObject({
      method: "POST",
      timeoutKind: "llmGenerate",
      timeout: 2100000,
    })
    expect(getApiContract("generate.applyWorldPageDraft")).toMatchObject({
      method: "POST",
      timeoutKind: "aiPreviewApply",
      timeout: 600000,
    })
    expect(contractPath(
      "generate.applyWorldPageDraft",
      { suggestionId: "suggestion-1" },
      { novel_id: "novel-1" },
    )).toBe("/world/generation-center/suggestions/suggestion-1/apply-page-draft?novel_id=novel-1")
    expect(contractPath("tasks.cancel", { taskId: "task-1" }, { novel_id: "novel-1" }))
      .toBe("/tasks/task-1/cancel?novel_id=novel-1")
    expect(contractPath("tasks.retry", { taskId: "task-1" }, { novel_id: "novel-1" }))
      .toBe("/tasks/task-1/retry?novel_id=novel-1")
    expect(getApiContract("rag.search")).toMatchObject({
      method: "POST",
      timeoutKind: "ragSearch",
      timeout: 2100000,
    })
    expect(getApiContract("rag.prewarm")).toMatchObject({
      method: "POST",
      timeoutKind: "ragPrewarm",
      timeout: 600000,
    })

    expect(contractPath("writing.runConflictAiReview", { checkId: "check-1" }))
      .toBe("/writing/conflict-checks/check-1/ai-review")
    expect(getApiContract("writing.runConflictAiReview")).toMatchObject({
      timeoutKind: "llmGenerate",
      timeout: 2100000,
    })
    expect(contractPath("writing.requestConflictAiSuggestion", { itemId: "item-1" }))
      .toBe("/writing/conflict-check-items/item-1/ai-suggestion")
    expect(getApiContract("writing.generate")).toMatchObject({
      timeoutKind: "aiTaskSubmit",
      timeout: 600000,
    })
    expect(contractPath("writing.adoptDraftCandidate", { draftId: "draft-1" }, { novel_id: "novel-1" }))
      .toBe("/writing/drafts/draft-1/adopt?novel_id=novel-1")
    expect(contractPath("writing.checkpoint", { draftId: "draft-1" }, { novel_id: "novel-1" }))
      .toBe("/writing/drafts/draft-1/checkpoint?novel_id=novel-1")
    expect(contractPath("writing.discard", { draftId: "draft-1" }, { novel_id: "novel-1" }))
      .toBe("/writing/drafts/draft-1/discard?novel_id=novel-1")
    expect(contractPath("writing.enqueueConflictAiReview", { checkId: "check-1" }))
      .toBe("/writing/conflict-checks/check-1/ai-review-task")
  })

  it("contractRequest 校验 requiredBody 并生成不可改写 method 的请求", () => {
    expect(() => contractRequest(
      "outline.generateStoryOutline",
      {},
      {},
      {
        body: {
          novel_id: "novel-1",
          author_intent: "写一部长篇",
          planned_scale: "百万字",
          coverage: "全书",
          selected_character_ids: [],
          selected_entity_ids: [],
        },
      },
    )).toThrow(/include_current_outline.*outline\.generateStoryOutline/)
    expect(() => contractRequest(
      "outline.applyStoryOutlinePreview",
      {},
      {},
      {
        body: {
          novel_id: "novel-1",
          source_task_id: "task-1",
          title: "总纲",
          creative_core: {},
          outline_markdown: "正文",
          major_storylines: [],
          macro_movements: [],
          open_decisions: [],
          base_revision_id: null,
          idempotency_key: "story-outline-key",
        },
      },
    )).toThrow(/confirmed.*outline\.applyStoryOutlinePreview/)

    expect(() => contractRequest(
      "world.applyMapEditor",
      { mapId: "map-1" },
      { novel_id: "novel-1" },
      { body: { expected_revision: 3 } },
    )).toThrow(/commands.*world\.applyMapEditor/)
    expect(() => contractRequest(
      "world.applyMapEditor",
      { mapId: "map-1" },
      { novel_id: "novel-1" },
      { body: { expected_revision: 3, commands: undefined } },
    )).toThrow(/commands.*world\.applyMapEditor/)

    const requestSpec = contractRequest(
      "world.applyMapEditor",
      { mapId: "map-1" },
      { novel_id: "novel-1" },
      {
        method: "DELETE",
        timeout: 4321,
        body: { expected_revision: 3, commands: [] },
      },
    )

    expect(requestSpec).toEqual({
      path: "/world/maps/map-1/editor/apply?novel_id=novel-1",
      method: "POST",
      options: {
        method: "POST",
        timeout: 4321,
        body: JSON.stringify({ expected_revision: 3, commands: [] }),
      },
    })
    expect(() => contractRequest(
      "world.assignProjectMapObservation",
      { observationId: "obs-1" },
      { novel_id: "novel-1" },
      { body: { map_id: null, expected_updated_at: "2026-07-16T00:00:00Z" } },
    )).not.toThrow()
  })

  it("E2E 地图适配器通过共享契约生成请求", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ editor_revision: 4 }),
    })
    vi.stubGlobal("fetch", fetchMock)

    try {
      await expect(applyMapEditorForE2E("novel-1", "map-1", {
        expected_revision: 3,
        commands: [],
      })).resolves.toEqual({ editor_revision: 4 })

      expect(fetchMock).toHaveBeenCalledTimes(1)
      const [url, options] = fetchMock.mock.calls[0]
      expect(url).toMatch(/\/api\/world\/maps\/map-1\/editor\/apply\?novel_id=novel-1$/)
      expect(options).toMatchObject({
        method: "POST",
        body: JSON.stringify({ expected_revision: 3, commands: [] }),
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
      })
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it("E2E GET 请求与浏览器客户端使用相同的安全头规则", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue([]),
    })
    vi.stubGlobal("fetch", fetchMock)

    try {
      await listMapsForE2E("novel-1")

      const [, options] = fetchMock.mock.calls[0]
      expect(options.headers).toEqual({ Accept: "application/json" })
      expect(options).not.toHaveProperty("timeout")
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it("E2E 共享契约的 timeout 会真正中止 fetch", async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => {
        const error = new Error("Aborted")
        error.name = "AbortError"
        reject(error)
      }, { once: true })
    }))
    vi.stubGlobal("fetch", fetchMock)

    try {
      const assertion = expect(listMapsForE2E("novel-1"))
        .rejects.toThrow("timed out after 15000ms")
      await vi.advanceTimersByTimeAsync(15000)
      await assertion
    } finally {
      vi.useRealTimers()
      vi.unstubAllGlobals()
    }
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
