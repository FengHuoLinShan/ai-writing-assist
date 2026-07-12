import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import { API_BASE, createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

test.describe("RAG 检索模块", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "RAG 测试项目",
      genre: "scifi",
      language: "zh",
    })
    testProjectId = project.id

    await openWorkbench(page, project, "rag", "status")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("索引状态页面显示", async ({ page }) => {
    // ragView 使用 data-action 而非 data-subview
    await expect(page.locator('[data-action="nav-status"]')).toHaveClass(/active/)
    // 新项目的 RAG 状态可能是空或后端未连接，只保证视图标题和子导航正确即可
    await expect(page.locator(SEL.viewTitle)).toHaveText("小说检索")
  })

  test("切换到搜索子标签", async ({ page }) => {
    await page.locator('.subnav-item[data-action="nav-search"]').click()
    await expect(page.locator('.subnav-item[data-action="nav-search"]')).toHaveClass(/active/)
    // 只验证搜索输入框存在
    await expect(page.locator("#rag-search-input")).toBeVisible()
  })

  test("搜索空结果", async ({ page }) => {
    // Mock 搜索接口返回空结果，避免新项目无索引导致 API 报错
    await page.route("**/api/rag/retrieve**", async (route) => {
      await route.fulfill({ status: 200, body: JSON.stringify({ chunks: [], total: 0, query: "不存在的词", warnings: [], degraded: false }) })
    })

    await page.locator('.subnav-item[data-action="nav-search"]').click()
    await page.locator("#rag-search-input").fill("不存在的词")
    await page.locator('[data-action="do-search"]').click()

    await expect(page.locator("#rag-results")).toContainText("未找到匹配结果", { timeout: 10000 })
  })

  test("通过真实 RAG chunk 搜索并验证 embedding 降级元数据", async ({ page }) => {
    await page.evaluate(async ({ apiBase, projectId }) => {
      const resp = await fetch(`${apiBase}/rag/chunks?novel_id=${projectId}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({
          source_type: "chapter_text",
          source_id: "00000000-0000-0000-0000-000000000001",
          chapter_index: 1,
          chunk_index: 0,
          start_offset: 0,
          end_offset: 12,
          text: "铜铃在雨夜响起，旧档案缺页随风翻开。",
          summary: "铜铃异常",
          entity_ids: [],
          character_ids: [],
          thread_ids: [],
          visibility: "author_only",
          importance: 0.8,
          embedding_status: "failed",
          embedding_error: "test embedding unavailable",
          index_warnings: ["embedding 降级为关键词检索"],
        }),
      })
      if (!resp.ok) throw new Error(await resp.text())
    }, { apiBase: API_BASE, projectId: testProjectId })

    await page.locator('.subnav-item[data-action="nav-search"]').click()
    await page.locator("#rag-search-input").fill("铜铃")
    await page.locator('[data-action="do-search"]').click()

    // 小说检索页只展示统一证据接口校验过的命中；孤立的旧 RAG chunk 不应直接进入作者证据视图。
    await expect(page.locator("#rag-results")).toContainText("未找到匹配结果", { timeout: 10000 })

    const result = await page.evaluate(async ({ apiBase, projectId }) => {
      const resp = await fetch(`${apiBase}/rag/retrieve?novel_id=${projectId}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({ query: "铜铃", mode: "search", top_k: 5 }),
      })
      if (!resp.ok) throw new Error(await resp.text())
      return resp.json()
    }, { apiBase: API_BASE, projectId: testProjectId })

    expect(result.chunks.some((chunk) => chunk.text.includes("铜铃"))).toBeTruthy()
    expect(result.chunks.some((chunk) => chunk.embedding_status === "failed")).toBeTruthy()
    expect(result.chunks.some((chunk) => chunk.embedding_error === "test embedding unavailable")).toBeTruthy()
    expect(result.chunks.some((chunk) => chunk.index_warnings.includes("embedding 降级为关键词检索"))).toBeTruthy()
    expect(result.degraded).toBeTruthy()
    expect(result.warnings).toContain("embedding 降级为关键词检索")
  })

  test("重建索引按钮可点击", async ({ page }) => {
    await page.locator('[data-action="rebuild-index"]').click()
    // 重建索引会提交异步任务，至少应该显示 toast
    await expect(page.locator(SEL.toastContainer)).toContainText("索引", { timeout: 10000 })
  })
})
