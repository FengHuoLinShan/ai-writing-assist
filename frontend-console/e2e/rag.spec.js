import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import { API_BASE, createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"
import { expectNoPageOverflow, expectWithinViewport } from "./helpers/responsive.js"

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

  test("键盘切换搜索子标签并公开当前页", async ({ page }) => {
    const status = page.locator('.subnav-item[data-action="nav-status"]')
    const search = page.locator('.subnav-item[data-action="nav-search"]')
    await expect(status).toHaveAttribute("type", "button")
    await expect(status).toHaveAttribute("aria-current", "page")
    await expect(search).toHaveAttribute("type", "button")
    await expect(search).not.toHaveAttribute("aria-current", /.+/)

    await search.focus()
    await search.press("Enter")
    await expect(page.locator("#rag-search-input")).toBeVisible()
    await expect(search).toHaveAttribute("aria-current", "page")
    await expect(status).not.toHaveAttribute("aria-current", /.+/)

    await page.setViewportSize({ width: 390, height: 844 })
    await expectNoPageOverflow(page)
    await expectWithinViewport(search)
    await expectWithinViewport(status)

    await status.focus()
    await status.press(" ")
    await expect(page.locator('[data-action="rebuild-index"]')).toBeVisible()
    await expect(status).toHaveAttribute("aria-current", "page")
    await expect(search).not.toHaveAttribute("aria-current", /.+/)
  })

  test("390px 下检索输入和主操作可见且无水平溢出", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.locator('.subnav-item[data-action="nav-search"]').click()

    const input = page.getByLabel("检索关键词")
    const searchButton = page.locator('[data-action="do-search"]')
    await expect(input).toBeVisible()
    await expectWithinViewport(input)
    await expectWithinViewport(searchButton)
    await expectNoPageOverflow(page)
    await expect(input).toHaveCSS("min-height", "40px")
    await expect(searchButton).toHaveCSS("min-height", "40px")
  })

  test("倒置章节范围在请求前提示并保留条件，修正后才检索", async ({ page }) => {
    const requests = []
    await page.route("**/api/context/evidence/search", async (route) => {
      requests.push(route.request().postDataJSON())
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ hits: [], total: 0, warnings: [], degraded: false }),
      })
    })

    await page.locator('.subnav-item[data-action="nav-search"]').click()
    await page.getByLabel("检索关键词").fill("旧塔")
    await page.locator('[data-role="rag-advanced-filters"] summary').click()
    await page.locator("#rag-chapter-from").fill("10")
    await page.locator("#rag-chapter-to").fill("5")
    await page.locator('[data-action="do-search"]').click()

    await expect(page.locator("#rag-chapter-range-error")).toHaveText("起始章不能大于结束章")
    await expect(page.locator("#rag-chapter-from")).toHaveValue("10")
    await expect(page.locator("#rag-chapter-to")).toHaveValue("5")
    expect(requests).toHaveLength(0)
    await expect(page.locator("#rag-results")).not.toContainText("未找到匹配结果")

    await page.setViewportSize({ width: 390, height: 844 })
    await expectNoPageOverflow(page)

    await page.locator("#rag-chapter-to").fill("10")
    await page.locator('[data-action="do-search"]').click()
    await expect.poll(() => requests.length).toBe(1)
    expect(requests[0]).toMatchObject({ chapter_from: 10, chapter_to: 10 })
  })

  test("58 条证据按 20 条渐进展示并由 URL 前进后退恢复", async ({ page }) => {
    const requests = []
    await page.route("**/api/context/evidence/search", async (route) => {
      const payload = route.request().postDataJSON()
      requests.push(payload.query)
      const prefix = payload.query === "海港" ? "海港结果" : "旧塔结果"
      const count = payload.query === "海港" ? 3 : 58
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          total: count,
          hits: Array.from({ length: count }, (_, index) => ({
            kind: "manuscript",
            title: `${prefix} ${index + 1}`,
            snippet: `${payload.query}的固定证据 ${index + 1}`,
            chapter_index: index + 1,
            source_ref: {
              content_mode: "canonical",
              chapter_index: index + 1,
              version_number: 1,
              source_content_hash: `hash-${index + 1}`,
            },
          })),
          warnings: [],
          degraded: false,
        }),
      })
    })
    await page.route("**/api/context/evidence/read", async (route) => {
      const payload = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          title: "第一章",
          text: "旧塔的铜铃在夜里响起。",
          highlight_start: 0,
          highlight_end: 2,
          source_ref: payload.source_ref,
          scene_refs: [],
          object_refs: [],
          warnings: [],
        }),
      })
    })

    await page.locator('.subnav-item[data-action="nav-search"]').click()
    await page.getByLabel("检索关键词").fill("旧塔")
    await page.locator('[data-action="do-search"]').click()

    await expect(page).toHaveURL(/q=%E6%97%A7%E5%A1%94/)
    await expect(page.locator(".rag-result-card")).toHaveCount(20)
    await expect(page.locator(".rag-result-count")).toContainText("找到 58")
    await page.locator('[data-action="load-more-results"]').click()
    await expect(page.locator(".rag-result-card")).toHaveCount(40)
    await page.locator('[data-action="load-more-results"]').click()
    await expect(page.locator(".rag-result-card")).toHaveCount(58)
    await expect(page.locator('[data-action="load-more-results"]')).toHaveCount(0)

    await page.locator('[data-action="open-hit"]').first().click()
    await expect(page.locator("#rag-evidence-drawer")).toContainText("旧塔的铜铃")
    await page.locator('[data-action="close-drawer"]').click()

    const searchInput = page.getByLabel("检索关键词")
    await searchInput.fill("海港")
    await expect(searchInput).toHaveValue("海港")
    await searchInput.press("Enter")
    await expect(page).toHaveURL(/q=%E6%B5%B7%E6%B8%AF/)
    await expect(page.locator(".rag-result-card")).toHaveCount(3)
    await expect(page.locator("#rag-results")).toContainText("海港结果 1")

    await page.goBack()
    await expect(page).toHaveURL(/q=%E6%97%A7%E5%A1%94/)
    await expect(page.getByLabel("检索关键词")).toHaveValue("旧塔")
    await expect(page.locator(".rag-result-card")).toHaveCount(20)
    await expect(page.locator("#rag-results")).toContainText("旧塔结果 1")
    expect(requests).toEqual(["旧塔", "海港", "旧塔"])

    await page.goBack()
    await expect(page).not.toHaveURL(/(?:\?|&)q=/)
    await expect(page.getByLabel("检索关键词")).toHaveValue("")
    await expect(page.locator(".rag-result-card")).toHaveCount(0)

    await page.goForward()
    await expect(page).toHaveURL(/q=%E6%97%A7%E5%A1%94/)
    await expect(page.getByLabel("检索关键词")).toHaveValue("旧塔")
    await expect(page.locator(".rag-result-card")).toHaveCount(20)
    expect(requests).toEqual(["旧塔", "海港", "旧塔", "旧塔"])
  })

  test("搜索空结果", async ({ page }) => {
    // Mock 搜索接口返回空结果，避免新项目无索引导致 API 报错
    await page.route("**/api/context/evidence/search", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ hits: [], total: 0, warnings: [], degraded: false }),
      })
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
