import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import { API_BASE, createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"
import { expectNoPageOverflow, expectWithinViewport } from "./helpers/responsive.js"

test.describe("RAG 检索模块", () => {
  let testProjectId = null
  let testProject = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "RAG 测试项目",
      genre: "scifi",
      language: "zh",
    })
    testProject = project
    testProjectId = project.id

    await openWorkbench(page, project, "rag", "status")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
      testProject = null
    }
  })

  test("修复查找页面优先展示用户可理解的状态", async ({ page }) => {
    await expect(page.locator(SEL.viewTitle)).toHaveText("查找")
    await expect(page.getByRole("heading", { name: "查找资料尚未准备好" })).toBeVisible()
    await expect(page.getByLabel("使用哪一版正文")).toBeVisible()
    await expect(page.locator(".rag-status-overview")).toBeVisible()
    await expect(page.locator('[data-action="rebuild-index"]')).toHaveText("修复查找功能")
    const diagnostics = page.locator(".rag-diagnostic-details")
    await expect(diagnostics).not.toHaveAttribute("open", "")
    await diagnostics.locator("summary").click()
    await expect(page.locator('[data-action="prewarm-rag"]')).toBeVisible()
  })

  test("键盘返回查找、浏览器后退并保留当前修复范围", async ({ page }) => {
    await page.getByLabel("使用哪一版正文").selectOption("working")
    await page.getByLabel("从第几章").fill("2")
    await page.getByLabel("到第几章").fill("4")
    const returnToSearch = page.locator('.rag-repair-card [data-action="nav-search"]')
    await expect(returnToSearch).toHaveAttribute("type", "button")
    await returnToSearch.focus()
    await returnToSearch.press("Enter")

    const searchInput = page.locator("#rag-search-input")
    await expect(searchInput).toBeVisible()
    await expect(page.locator(".view-header .subnav")).toHaveCount(0)

    await page.setViewportSize({ width: 390, height: 844 })
    await expectNoPageOverflow(page)
    await expectWithinViewport(searchInput)

    await page.goBack()
    await expect(page.getByRole("heading", { name: "查找资料尚未准备好" })).toBeVisible()
    await expect(page.locator('[data-action="rebuild-index"]')).toBeVisible()
    await expect(page.getByLabel("使用哪一版正文")).toHaveValue("working")
    await expect(page.getByLabel("从第几章")).toHaveValue("2")
    await expect(page.getByLabel("到第几章")).toHaveValue("4")
    await expectNoPageOverflow(page)
  })

  test("390px 下主操作和更多条件可见、可理解且无水平溢出", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.locator('.rag-repair-card [data-action="nav-search"]').click()

    const input = page.getByLabel("检索关键词")
    const searchButton = page.locator('[data-action="do-search"]')
    const searchKind = page.locator("#rag-search-kind")
    const contentMode = page.locator("#rag-content-mode")
    await expect(input).toBeVisible()
    await expect(page.getByText("想查什么", { exact: true })).toBeVisible()
    await expect(searchButton).toHaveText("查找资料")
    await expectWithinViewport(input)
    await expectWithinViewport(searchButton)
    await expectWithinViewport(searchKind)
    await expectWithinViewport(contentMode)
    await expectNoPageOverflow(page)
    await expect(input).toHaveCSS("min-height", "44px")
    await expect(searchButton).toHaveCSS("min-height", "44px")

    const advanced = page.locator('[data-role="rag-advanced-filters"]')
    await expect(advanced.locator('[data-role="rag-advanced-summary"]')).toHaveText("视角、章节和资料范围")
    await advanced.locator("summary").click()
    await expect(page.getByText("从哪里查", { exact: true })).toBeVisible()
    await expect(page.getByText("按谁能看到的内容查", { exact: true })).toBeVisible()
    await expect(page.locator("#rag-cutoff-field")).toBeHidden()
    await expect(page.locator("#rag-character-field")).toBeHidden()
    await page.locator("#rag-visibility-mode").selectOption("reader")
    await expect(page.locator("#rag-cutoff-field")).toBeVisible()
    await expect(page.locator("#rag-character-field")).toBeHidden()
    await page.locator("#rag-visibility-mode").selectOption("character")
    await expect(page.locator("#rag-character-field")).toBeVisible()
    await page.locator("#rag-visibility-mode").selectOption("author")
    await expect(page.locator("#rag-cutoff-field")).toBeHidden()
    const includePending = page.locator("#rag-include-pending")
    await expect(includePending).toBeDisabled()
    await expect(page.locator("#rag-include-pending-help")).toContainText("先勾选“世界设定”")
    await page.locator('[data-search-scope="world"]').check()
    await expect(includePending).toBeEnabled()
    await expect(page.locator("#rag-include-pending-help")).toContainText("还未采用")
    await expectNoPageOverflow(page)
  })

  test("AI 工具内查找保留抽屉、搜索状态和手机安全边界", async ({ page, browserErrors }) => {
    const failedApiResponses = []
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) {
        failedApiResponses.push(`${response.status()} ${response.request().method()} ${response.url()}`)
      }
    })
    await page.route("**/api/context/evidence/search", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          total: 1,
          hits: [{
            kind: "manuscript",
            title: "旧塔铜铃",
            snippet: "旧塔的铜铃在换岗时响起。",
            score: 0.92,
            chapter_index: 1,
            source_ref: { content_mode: "canonical", chapter_index: 1, version_number: 1 },
          }],
          warnings: [],
          degraded: false,
        }),
      })
    })
    await openWorkbench(page, testProject, "writing")
    await page.setViewportSize({ width: 375, height: 812 })

    const trigger = page.locator('[data-action="open-owner-ai-drawer"]')
    await trigger.click()
    const drawer = page.locator("[data-owner-ai-drawer]")
    const closeButton = page.locator('[data-action="close-owner-ai-drawer"]')
    await expect(closeButton).toBeFocused()
    await page.getByRole("tab", { name: "查找资料", exact: true }).click()
    await expect(page.locator(".owner-ai-drawer__hint")).toContainText("打开来源不会修改正文或设定")

    const [drawerBox, topbarBox, mobileNavBox] = await Promise.all([
      drawer.boundingBox(),
      page.locator("#topbar").boundingBox(),
      page.locator(".sidebar-mobile-nav").boundingBox(),
    ])
    expect(drawerBox.y).toBeGreaterThanOrEqual(topbarBox.y + topbarBox.height - 1)
    expect(drawerBox.y + drawerBox.height).toBeLessThanOrEqual(mobileNavBox.y + 1)
    await expect(closeButton).toHaveCSS("min-height", "44px")
    await expectNoPageOverflow(page)

    await page.keyboard.press("Escape")
    await expect(drawer).toHaveCount(0)
    await expect(trigger).toBeFocused()
    await expect(page).not.toHaveURL(/(?:\?|&)owner_ai=1/)

    await trigger.click()
    await expect(page.getByRole("tabpanel", { name: "查找资料" })).toBeVisible()
    const input = page.locator("#owner-ai-panel-evidence #rag-search-input")
    await input.fill("旧塔")
    await input.press("Enter")
    await expect(page).toHaveURL(/owner_ai=1/)
    await expect(page).toHaveURL(/owner_ai_mode=evidence/)
    await expect(page).toHaveURL(/q=%E6%97%A7%E5%A1%94/)
    await expect(drawer).toBeVisible()
    await expect(page.locator("#owner-ai-panel-evidence .rag-result-card")).toHaveCount(1)

    await page.goBack()
    await expect(drawer).toBeVisible()
    await expect(input).toHaveValue("")
    await expect(page.locator("#owner-ai-panel-evidence .rag-result-card")).toHaveCount(0)
    await page.goForward()
    await expect(input).toHaveValue("旧塔")
    await expect(page.locator("#owner-ai-panel-evidence .rag-result-card")).toHaveCount(1)

    await page.reload()
    await page.waitForFunction(() => !state.loading)
    await expect(page.getByRole("tab", { name: "查找资料", exact: true })).toHaveAttribute("aria-selected", "true")
    await expect(page.locator("#owner-ai-panel-evidence #rag-search-input")).toHaveValue("旧塔")
    await expect(page.locator("#owner-ai-panel-evidence .rag-result-card")).toHaveCount(1)

    await page.setViewportSize({ width: 812, height: 375 })
    await expectWithinViewport(closeButton)
    await expectNoPageOverflow(page)

    const switchedProject = await createProject({ title: "AI 抽屉查找切换目标", genre: "fantasy", language: "zh" })
    try {
      await openWorkbench(page, switchedProject, "writing")
      await expect(page.locator("[data-owner-ai-drawer]")).toHaveCount(0)
      await page.locator('[data-action="open-owner-ai-drawer"]').click()
      await page.getByRole("tab", { name: "查找资料", exact: true }).click()
      await expect(page.locator("#owner-ai-panel-evidence #rag-search-input")).toHaveValue("")
      await expect(page.locator("#owner-ai-panel-evidence .rag-result-card")).toHaveCount(0)
    } finally {
      await cleanupProject(switchedProject.id)
    }
    expect(browserErrors, `浏览器错误: ${JSON.stringify(browserErrors)}`).toHaveLength(0)
    expect(failedApiResponses, `失败 API: ${JSON.stringify(failedApiResponses)}`).toHaveLength(0)
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
    await page.locator('.rag-repair-card [data-action="nav-search"]').click()
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

    await page.locator('.rag-repair-card [data-action="nav-search"]').click()
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

  test("58 条证据按 20 条渐进展示并由 URL 前进后退恢复", async ({ page, browserErrors }) => {
    const browserErrorStart = browserErrors.length
    const failedApiResponses = []
    page.on("response", (response) => {
      if (response.url().includes("/api/") && response.status() >= 400) {
        failedApiResponses.push(`${response.status()} ${response.request().method()} ${response.url()}`)
      }
    })
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
            score: 0.92 - (index % 5) * 0.05,
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

    await page.locator('.rag-repair-card [data-action="nav-search"]').click()
    await page.getByLabel("检索关键词").fill("旧塔")
    await page.locator('[data-action="do-search"]').click()

    await expect(page).toHaveURL(/q=%E6%97%A7%E5%A1%94/)
    await expect(page.locator(".rag-result-card")).toHaveCount(20)
    await expect(page.getByRole("heading", { name: "查找结果" })).toBeVisible()
    await expect(page.locator(".rag-result-count")).toContainText("找到 58")
    await expect(page.locator(".rag-result-score-help")).toHaveText("匹配度仅用于本次结果排序")
    await expect(page.locator(".rag-result-score").first()).toContainText(/匹配度\s*92%/)
    await page.locator('[data-action="load-more-results"]').click()
    await expect(page.locator(".rag-result-card")).toHaveCount(40)
    await page.locator('[data-action="load-more-results"]').click()
    await expect(page.locator(".rag-result-card")).toHaveCount(58)
    await expect(page.locator('[data-action="load-more-results"]')).toHaveCount(0)

    const firstOpenButton = page.locator('[data-action="open-hit"]').first()
    await firstOpenButton.click()
    const drawer = page.locator("#rag-evidence-drawer")
    await expect(drawer).toContainText("旧塔的铜铃")
    await expect(drawer).toHaveAttribute("role", "dialog")
    await expect(drawer).toHaveAttribute("aria-modal", "true")
    await expect(page.locator('[data-action="close-drawer"]')).toBeFocused()
    await page.locator(".rag-evidence-overlay").click({ position: { x: 20, y: 20 } })
    await expect(drawer).toHaveCount(0)
    await expect(firstOpenButton).toBeFocused()

    await firstOpenButton.click()
    await expect(drawer).toContainText("旧塔的铜铃")
    await page.keyboard.press("Escape")
    await expect(drawer).toHaveCount(0)
    await expect(firstOpenButton).toBeFocused()

    await page.setViewportSize({ width: 375, height: 812 })
    await expect(firstOpenButton).toHaveCSS("min-height", "44px")
    await expectNoPageOverflow(page)
    await firstOpenButton.click()
    await expectWithinViewport(drawer)
    await expectNoPageOverflow(page)
    await expect(page.locator('[data-action="close-drawer"]')).toHaveCSS("min-height", "44px")
    await page.locator('[data-action="close-drawer"]').click()
    await expect(firstOpenButton).toBeFocused()

    await page.setViewportSize({ width: 812, height: 375 })
    await firstOpenButton.click()
    await expectWithinViewport(drawer)
    await expectWithinViewport(page.locator('[data-action="close-drawer"]'))
    await expectNoPageOverflow(page)
    await page.keyboard.press("Escape")
    await expect(firstOpenButton).toBeFocused()

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

    await page.reload()
    await expect(page.getByLabel("检索关键词")).toHaveValue("旧塔")
    await expect(page.locator(".rag-result-card")).toHaveCount(20)
    expect(requests).toEqual(["旧塔", "海港", "旧塔", "旧塔", "旧塔"])

    const switchedProject = await createProject({ title: "RAG 切换目标", genre: "fantasy", language: "zh" })
    try {
      await page.locator('[data-action="open-hit"]').first().click()
      await expect(drawer).toBeVisible()
      await openWorkbench(page, switchedProject, "rag", "search")
      await expect(page.locator("#rag-evidence-drawer")).toHaveCount(0)
      await expect(page.getByLabel("检索关键词")).toHaveValue("")
    } finally {
      await cleanupProject(switchedProject.id)
    }

    expect(browserErrors.slice(browserErrorStart), `浏览器错误: ${JSON.stringify(browserErrors.slice(browserErrorStart))}`).toHaveLength(0)
    expect(failedApiResponses, `失败 API: ${JSON.stringify(failedApiResponses)}`).toHaveLength(0)
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

    await page.locator('.rag-repair-card [data-action="nav-search"]').click()
    await page.locator("#rag-search-input").fill("不存在的词")
    await page.locator('[data-action="do-search"]').click()

    await expect(page.locator("#rag-results")).toContainText("没有找到匹配资料", { timeout: 10000 })
    await expect(page.locator("#rag-results")).toContainText("试试缩短关键词")
    await expect(page.locator('[data-action="retry-literal-search"]')).toHaveAttribute("type", "button")
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

    await page.locator('.rag-repair-card [data-action="nav-search"]').click()
    await page.locator("#rag-search-input").fill("铜铃")
    await page.locator('[data-action="do-search"]').click()

    // 小说检索页只展示统一证据接口校验过的命中；孤立的旧 RAG chunk 不应直接进入作者证据视图。
    await expect(page.locator("#rag-results")).toContainText("没有找到匹配资料", { timeout: 10000 })

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

  test("修复范围先就地校验，再提交真实修复任务", async ({ page }) => {
    await page.getByLabel("从第几章").fill("5")
    await page.getByLabel("到第几章").fill("2")
    await expect(page.locator("#rag-rebuild-range-error")).toContainText("结束章节不能小于起始章节")
    await expect(page.locator('[data-action="rebuild-index"]')).toBeDisabled()

    await page.getByLabel("从第几章").fill("1")
    await page.getByLabel("到第几章").fill("1")
    await page.locator('[data-action="rebuild-index"]').click()
    await expect(page.locator(SEL.toastContainer)).toContainText("索引", { timeout: 10000 })
  })
})
