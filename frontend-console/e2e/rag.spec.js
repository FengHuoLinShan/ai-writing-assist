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

  test("修复查找页面优先展示用户可理解的状态", async ({ page }) => {
    await expect(page.locator(SEL.viewTitle)).toHaveText("查找")
    await expect(page.getByRole("heading", { name: "查找资料尚未准备好" })).toBeVisible()
    await expect(page.locator('[data-action="rebuild-index"]')).toHaveText("修复查找功能")
    await expect(page.locator(".rag-diagnostic-details")).toContainText("诊断详情")
  })

  test("键盘从修复页返回查找并可用浏览器后退恢复", async ({ page }) => {
    const returnToSearch = page.locator('.subnav-item[data-action="nav-search"]')
    await expect(returnToSearch).toHaveAttribute("type", "button")
    await returnToSearch.focus()
    await returnToSearch.press("Enter")

    const search = page.locator('.subnav-item[data-action="nav-search"]')
    await expect(page.locator("#rag-search-input")).toBeVisible()
    await expect(search).toHaveAttribute("aria-current", "page")

    await page.setViewportSize({ width: 390, height: 844 })
    await expectNoPageOverflow(page)
    await expectWithinViewport(search)

    await page.goBack()
    await expect(page.getByRole("heading", { name: "查找资料尚未准备好" })).toBeVisible()
    await expect(page.locator('[data-action="rebuild-index"]')).toBeVisible()
    await expectNoPageOverflow(page)
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
    await expect(input).toHaveCSS("min-height", "44px")
    await expect(searchButton).toHaveCSS("min-height", "42px")
  })

  test("390px 下问世界先给可打开引用，明确保存后才进入待处理", async ({ page }) => {
    const saves = []
    const sourceHash = "a".repeat(64)
    await page.route("**/api/world/ask-world", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          question: "旧塔铜铃何时响起",
          answer: "当前正式资料只确认换岗时会响起。",
          claims: [{ text: "旧塔铜铃只在守卫换岗时响起。", citation_keys: ["page:bell"] }],
          uncertainty: "是否还会因其他事件响起，当前资料没有说明。",
          no_answer: false,
          citations: [{
            citation_key: "page:bell",
            kind: "world_bible_page",
            title: "旧塔守卫规则",
            snippet: "铜铃只在换岗时响起。",
            source_hash: sourceHash,
            source_version: 3,
            page_id: "00000000-0000-0000-0000-000000000001",
            index_fresh: true,
          }],
          response_hash: "b".repeat(64),
          evidence_trace: {
            included_titles: ["旧塔守卫规则"],
            excluded_count: 0,
            truncated_titles: [],
            warnings: [],
            degraded: false,
            checks_run: ["作者可见性与项目隔离"],
            not_run: ["待处理候选"],
          },
          model: "internal-model-name",
          provider: "internal-provider-name",
          context_snapshot_id: "internal-snapshot-id",
        }),
      })
    })
    await page.route("**/api/world/ask-world/citations/open", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          status: "current",
          kind: "world_bible_page",
          title: "旧塔守卫规则",
          text: "铜铃只在换岗时响起。",
          source_hash: sourceHash,
          page_id: "00000000-0000-0000-0000-000000000001",
          warnings: [],
        }),
      })
    })
    await page.route("**/api/world/ask-world/suggestions", async (route) => {
      saves.push(route.request().postDataJSON())
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ suggestion: { id: "saved-ask-world", status: "pending" } }),
      })
    })

    await page.setViewportSize({ width: 390, height: 844 })
    await page.locator('.subnav-item[data-action="nav-search"]').click()
    await page.getByLabel("检索关键词").fill("旧塔铜铃何时响起")
    await page.locator('[data-action="ask-world"]').click()

    const answer = page.locator(".ask-world-card")
    await expect(answer).toContainText("当前正式资料只确认换岗时会响起")
    await expect(answer).toContainText("查看来源：旧塔守卫规则")
    await expect(answer).not.toContainText("internal-model-name")
    await expect(answer).not.toContainText("internal-snapshot-id")
    expect(saves).toHaveLength(0)

    await answer.locator('[data-action="open-ask-world-citation"]').click()
    await expect(page.locator(".ask-world-source")).toContainText("铜铃只在换岗时响起")
    await answer.locator('[data-action="save-ask-world-answer"]').click()
    await expect.poll(() => saves.length).toBe(1)
    await expect(answer).toContainText("不会直接改写正式设定")
    await expectNoPageOverflow(page)
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
