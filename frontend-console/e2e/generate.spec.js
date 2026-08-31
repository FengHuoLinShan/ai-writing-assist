import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { expectNoPageOverflow } from "./helpers/responsive.js"
import { openWorkbench } from "./helpers/workbench.js"
import {
  createProject,
  cleanupProject,
  createDraft,
  createWorldBibleDraft,
  createWorldBiblePage,
  createEntity,
  createScene,
  getWorldBiblePage,
  listWorldBibleDrafts,
  waitForBackend,
} from "./helpers/api-client.js"

async function openPovWorkbench(page, project) {
  await openWorkbench(page, project, "writing")
  await page.locator('[data-action="open-owner-ai-drawer"]').click()
  const povWorkbench = page.locator('[data-action="owner-writing-pov-workbench"]')
  if (!await povWorkbench.isVisible()) await page.locator(".owner-ai-writing__more > summary").click()
  await povWorkbench.click()
  await expect(page.locator("#generate-mode-panel-pov_prose")).toBeVisible({ timeout: 10000 })
}

async function approveContext(page) {
  await expect(page.locator(SEL.modalTitle)).toContainText("AI 参考资料")
  const start = page.getByRole("button", { name: "按这份资料开始" })
  await expect(start).toBeEnabled()
  await start.click()
}

test.describe("生成中心模块", () => {
  let testProjectId = null
  let worldSuggestionRequests = []
  let pageDraftApplyRequests = []
  let worldTaskResults = new Map()

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    worldSuggestionRequests = []
    pageDraftApplyRequests = []
    worldTaskResults = new Map()
    const project = await createProject({
      title: "生成测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    const promptTemplates = [
      { id: "builtin:none", name: "不带模板", object_template: "none", prompt_text: "不预设对象类型", is_builtin: true, version_number: 1 },
      { id: "builtin:character", name: "人物", object_template: "character", prompt_text: "聚焦人物卡", is_builtin: true, version_number: 1 },
      { id: "builtin:event", name: "事件", object_template: "event", prompt_text: "聚焦事件卡", is_builtin: true, version_number: 1 },
      { id: "builtin:item", name: "物品", object_template: "item", prompt_text: "聚焦物品卡", is_builtin: true, version_number: 1 },
      { id: "builtin:location", name: "地点", object_template: "location", prompt_text: "聚焦地点卡", is_builtin: true, version_number: 1 },
      { id: "builtin:faction", name: "组织", object_template: "faction", prompt_text: "聚焦组织卡", is_builtin: true, version_number: 1 },
      { id: "builtin:rule", name: "规则设定", object_template: "rule", prompt_text: "聚焦规则设定", is_builtin: true, version_number: 1 },
    ]

    await page.route("**/api/world/generation-prompt-templates", async (route) => {
      const method = route.request().method()
      const url = route.request().url()
      if (method === "GET") {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ items: promptTemplates, total: promptTemplates.length }),
        })
        return
      }
      if (method === "POST" && !url.includes("/copy")) {
        const body = route.request().postDataJSON()
        const created = {
          id: `e2e-template-${promptTemplates.length + 1}`,
          name: body.name,
          object_template: body.object_template,
          prompt_text: body.prompt_text,
          is_builtin: false,
          version_number: 1,
        }
        promptTemplates.push(created)
        await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(created) })
        return
      }
      if (method === "POST" && url.includes("/copy")) {
        const body = route.request().postDataJSON()
        const idMatch = url.match(/\/generation-prompt-templates\/([^/]+)\/copy/)
        const sourceId = idMatch ? idMatch[1] : "builtin:none"
        const source = promptTemplates.find((t) => t.id === sourceId) || promptTemplates[0]
        const copied = {
          ...source,
          id: `e2e-template-${promptTemplates.length + 1}`,
          is_builtin: false,
          version_number: 1,
          name: body.name || source.name,
        }
        promptTemplates.push(copied)
        await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(copied) })
        return
      }
      if (method === "PUT") {
        const body = route.request().postDataJSON()
        const idMatch = url.match(/\/generation-prompt-templates\/([^/]+)/)
        const templateId = idMatch ? idMatch[1] : null
        const item = promptTemplates.find((t) => t.id === templateId)
        if (item) {
          item.name = body.name ?? item.name
          item.prompt_text = body.prompt_text ?? item.prompt_text
          item.version_number += 1
        }
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(item) })
        return
      }
      await route.fulfill({ status: 405, body: "Method not allowed" })
    })

    await page.route("**/api/world/generation-center/chat", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          reply: "可以设计成旧友型反派，动机来自一次被误解的牺牲。",
          model: "account-model",
          provider: "fake",
          source_snapshot: { kind: "project" },
        }),
      })
    })

    const fulfillWorldTask = async (route, postBody, result) => {
      worldTaskResults.set(postBody.operation_id, result)
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({ task_id: postBody.operation_id, status: "pending" }),
      })
    }
    await page.route("**/api/world/generation-center/suggestions/task", async (route) => {
      const postBody = route.request().postDataJSON()
      worldSuggestionRequests.push(postBody)
      const targetKind = postBody.target.kind
      if (targetKind === "world_bible_page" || targetKind === "world_bible_new_page") {
        const createNew = targetKind === "world_bible_new_page"
        await fulfillWorldTask(route, postBody, {
            model: "account-model",
            provider: "fake",
            source_snapshot: postBody.source_context,
            result: {
              kind: targetKind,
              proposal: {
                operation: createNew ? "create_new" : "replace_existing",
                target_page_id: createNew ? null : postBody.target.page_id,
                design_rationale: "同时强化创意核心和规则因果。",
                review_notes: ["作者可继续调整细节"],
                page: {
                  title: createNew ? "龙息潮汐纪" : "重构后的北境规则",
                  page_type: "background",
                  free_text: createNew ? "潮汐改变龙息矿脉与迁徙路径。" : "北境的交易与通行规则。",
                  sections_json: [{
                    section_id: createNew ? "ai-tide-rules" : "trade-rules",
                    section_type: "markdown",
                    title: "运作逻辑",
                    body_markdown: "龙息潮每九日回流，并为势力资源争夺提供可验证的因果链。",
                    sort_order: 0,
                    linked_asset_ref_hashes: [],
                    projection_policy: "eligible",
                    sensitivity_hint: "author_safe",
                  }],
                  linked_asset_refs_json: [],
                },
              },
              suggestion: {
                id: createNew ? "suggestion-new-page-e2e" : "suggestion-existing-page-e2e",
                novel_id: testProjectId,
                target_type: "world_bible_page_draft",
                status: "pending",
                payload_json: {},
              },
            },
        })
        return
      }
      await fulfillWorldTask(route, postBody, {
          model: "account-model",
          provider: "fake",
          source_snapshot: { kind: "project" },
          result: {
            kind: "core_entity",
            proposal: {
              entity_type: postBody.target.template || "character",
              name: "沈无咎",
              summary: "旧友型反派，公开温和，暗中推动主角面对旧秩序。",
              content_json: {},
            },
            suggestion: {
              id: "suggestion-generate-e2e",
              novel_id: testProjectId,
              target_type: "core_entity_draft",
              status: "pending",
              result_ref_json: { type: "core_entity_compatibility", id: "generated-candidate-e2e" },
              payload_json: {
                entity_type: postBody.target.template || "character",
                name: "沈无咎",
                summary: "旧友型反派，公开温和，暗中推动主角面对旧秩序。",
              },
            },
          },
      })
    })

    await page.route("**/api/tasks/**", async (route) => {
      const taskId = new URL(route.request().url()).pathname.split("/").at(-1)
      const result = worldTaskResults.get(taskId)
      if (!result || route.request().method() !== "GET") return route.fallback()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: taskId,
          task_type: "world_generation_suggestion",
          status: "done",
          progress: 1,
          result,
        }),
      })
    })

    await page.route("**/api/world/generation-center/suggestions/*/apply-page-draft*", async (route) => {
      const body = route.request().postDataJSON()
      pageDraftApplyRequests.push(body)
      const sourcePageId = worldSuggestionRequests.at(-1)?.source_context?.page_id || null
      const draft = await createWorldBibleDraft(testProjectId, {
        page_id: sourcePageId,
        title: body.page.title,
        page_type: body.page.page_type,
        free_text: body.page.free_text,
        sections_json: body.page.sections_json,
        linked_asset_refs_json: body.page.linked_asset_refs_json,
      })
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          suggestion: { id: "applied-page-e2e", status: "accepted" },
          draft,
        }),
      })
    })

    await page.route("**/api/evidence/compilation/compile", async (route) => {
      const body = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          novel_id: body.novel_id,
          task: body.task,
          scope: body.scope,
          reveal_mode: body.reveal_mode,
          total_tokens: 1200,
          budget_tokens: body.budget_tokens || 4000,
          context_fingerprint: "a".repeat(64),
          selection_state: { status: "ready", counts: { required: 1, automatic: 1, author_pinned: 0, excluded: 0, omitted: 0 }, effective_range: {}, excluded_items: [], omitted_items: [] },
          blockers: [],
          sections: [
            { key: "project", tier: 0, token_count: 200, truncated: false, title: "项目概况", preview: "视觉基线参考资料 · fantasy", status: "canonical", activation_reason: "当前项目", sources: [{ type: "project", id: body.novel_id, label: "当前作品", status: "canonical" }], items: [{ key: "project:item", title: "项目概况", preview: "视觉基线参考资料 · fantasy", status: "canonical", selection_state: "required", can_exclude: false }] },
            { key: "characters", tier: 1, token_count: 1000, truncated: true, title: "相关人物", preview: "与当前任务关系最紧密的人物资料。", status: "canonical", activation_reason: "与任务目标相关", sources: [{ type: "character", id: "character-1", label: "相关人物资料", status: "canonical" }], items: [{ key: "character:item", title: "相关人物资料", preview: "与当前任务关系最紧密的人物资料。", status: "canonical", selection_state: "automatic", can_exclude: false }], truncated_reason: "超过资料长度后保留相关部分" },
          ],
          evicted: ["rag_chunks"],
          truncated: ["characters"],
          warnings: [],
        }),
      })
    })

    await page.route("**/api/evidence/compilation/confirm", async (route) => {
      const body = route.request().postDataJSON()
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "confirmation-e2e",
          novel_id: body.novel_id,
          action: body.action,
          task: body.task,
          scope: body.scope,
          context_mode: body.context_mode,
          include_pending_objects: body.include_pending_objects,
          excluded_asset_ids: body.excluded_asset_ids || {},
          selected_asset_ids: { project: [body.novel_id] },
          user_note: body.user_note || null,
          warnings: [],
          result_refs: [],
          result_status: "confirmed",
          stale_reasons: [],
          compiled_at: new Date().toISOString(),
          created_at: new Date().toISOString(),
          context_fingerprint: "a".repeat(64),
          selection_state: { status: "ready", counts: {}, effective_range: {}, excluded_items: [], omitted_items: [] },
          blockers: [],
          sections: [],
          budget_events: [],
        }),
      })
    })

    await page.route("**/api/evidence/compilation/render", async (route) => {
      const body = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ markdown: `# 任务参考资料\n\n${body.task}` }),
      })
    })

    await openWorkbench(page, project, "generate")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("生成中心页面加载", async ({ page }) => {
    await expect(page.locator("#topbar-module")).toContainText("人物与世界")
    await expect(page.locator("#topbar-view-note")).toContainText("需要 AI 时就在本页打开工具")
    await expect(page.locator("#workspace-content")).toContainText("人物")
    await expect(page.locator("#workspace-content")).toContainText("加强复核")
    await expect(page.locator("#workspace-content")).toContainText("生成世界对象建议")
    await expect(page.getByRole("tablist", { name: "AI 工具类别" })).toBeVisible()
    await expect(page.getByRole("tab", { name: "设定共创" })).toHaveAttribute("aria-selected", "true")
    await expect(page.getByRole("tab", { name: "整理资料" })).toBeVisible()
    await expect(page.getByRole("tab", { name: "查找资料" })).toBeVisible()
    await expect(page.getByRole("tablist", { name: "生成模式" })).toHaveCount(0)
    await expect(page.locator('[data-section="world-direction"]')).not.toHaveAttribute("open", "")
    await expect(page.locator('[data-section="world-direction"] > summary')).toContainText("世界对象 · 不带模板")
    expect(await page.locator('[data-action="generate-world-suggestion"]').evaluate((element) => element.closest("form")?.classList.contains("generate-composer"))).toBe(true)
    await expect(page.locator('[data-action="converge-world"]')).toHaveCount(0)
    await expect(page.locator("#generate-object-template")).toHaveValue("builtin:none")
    await expect(page.locator("#workspace-content")).not.toContainText("粘贴已有对话")
  })

  test("零章节项目在角色视角正文给出前置条件并前往写作台", async ({ page }) => {
    const project = await page.evaluate(() => state.currentProject)
    await openPovWorkbench(page, project)
    await expect(page.getByText("角色视角正文需要先准备章节")).toBeVisible()
    await expect(page.getByRole("button", { name: "生成角色视角正文" })).toHaveCount(0)
    await expect(page.locator("#generate-pov-chapter")).toHaveCount(0)
    await expect(page.locator("#generate-pov-scene")).toHaveCount(0)

    await page.setViewportSize({ width: 390, height: 844 })
    await expectNoPageOverflow(page)
    await page.getByRole("button", { name: "去写作台创建第一章" }).click()
    await expect(page.locator("#topbar-module")).toContainText("写作")
    await expect(page.getByRole("button", { name: "新建章节", exact: true })).toBeVisible()
  })

  test("角色视角正文保留表单、路由位置和项目隔离", async ({ page, projectFactory, browserErrors }) => {
    const project = await page.evaluate(() => state.currentProject)
    const character = await createEntity(testProjectId, { name: "林舟", entity_type: "character", status: "canonical", summary: "谨慎的巡港人" })
    await createDraft(testProjectId, 1, "第一章 潮门初启", "潮声退到石阶之外，露出一道从未被记载的门。")
    await createScene(testProjectId, {
      scene_index: 0,
      title: "退潮后的石门",
      narrative_tag: "opening",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 24 }],
      goal: "判断是否公开石门",
      core_conflict: "保护同行者，还是抢先留下证据",
    })
    await openPovWorkbench(page, project)
    await page.locator("#generate-pov-chapter").selectOption("1")
    await expect(page.locator("#generate-pov-scene option")).toHaveCount(2)
    await page.locator("#generate-pov-scene").selectOption({ label: "退潮后的石门" })
    await page.locator("#generate-pov-character").selectOption(character.id)
    await page.locator("#generate-pov-instruction").fill("保持克制，让林舟先观察刻痕。")

    const generate = page.locator('[data-action="generate-pov-prose"]')
    await expect(generate).toHaveText("生成正文建议")
    expect(await generate.evaluate((element) => element.closest("form") !== null)).toBe(true)
    await expect(page.locator("#workspace-content")).toContainText("角色只会知道自己应当知道的事")
    await expect(page.locator("#workspace-content")).not.toContainText("逐事实可见性过滤链")
    await expect(page.locator("#workspace-content")).not.toContainText("结构化 POV 面板")

    await generate.click()
    await expect(page.locator(SEL.modalTitle)).toContainText("AI 参考资料")
    await page.locator("#modal-footer").getByRole("button", { name: "取消" }).click()
    await expect(page.locator("#generate-pov-instruction")).toHaveValue("保持克制，让林舟先观察刻痕。")

    await page.reload()
    await page.waitForFunction(() => !state.loading)
    await expect(page.getByRole("tab", { name: "写作建议" })).toHaveAttribute("aria-selected", "true")
    await expect(page).toHaveURL(/owner_ai_mode=pov_prose/)
    await expect(page.locator("#generate-pov-scene")).toHaveValue(/.+/)
    await expect(page.locator("#generate-pov-character")).toHaveValue(character.id)
    await expect(page.locator("#generate-pov-instruction")).toHaveValue("保持克制，让林舟先观察刻痕。")

    await page.evaluate(() => window.router.navigate("outline"))
    await expect(page.locator("#topbar-module")).toContainText("故事结构")
    await page.goBack()
    await expect(page.getByRole("tab", { name: "写作建议" })).toHaveAttribute("aria-selected", "true")
    await expect(page.locator("#generate-pov-instruction")).toHaveValue("保持克制，让林舟先观察刻痕。")
    await page.goForward()
    await expect(page.locator("#topbar-module")).toContainText("故事结构")
    await page.goBack()
    await expect(page.locator("#generate-pov-instruction")).toHaveValue("保持克制，让林舟先观察刻痕。")

    const otherProject = await projectFactory({ title: "另一本书", genre: "fantasy", language: "zh" })
    await openPovWorkbench(page, otherProject)
    await expect(page.getByText("角色视角正文需要先准备章节")).toBeVisible()
    await openPovWorkbench(page, project)
    await expect(page.locator("#generate-pov-instruction")).toHaveValue("保持克制，让林舟先观察刻痕。")

    await page.setViewportSize({ width: 390, height: 844 })
    await generate.scrollIntoViewIfNeeded()
    await expectNoPageOverflow(page)
    expect((await generate.boundingBox()).height).toBeGreaterThanOrEqual(44)
    expect(browserErrors, `浏览器错误: ${JSON.stringify(browserErrors)}`).toHaveLength(0)
  })

  test("生成中心模式与高级任务控件可用键盘和名称访问", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 })
    const generateTabs = page.getByRole("tablist", { name: "AI 工具类别" })
    const worldTab = generateTabs.getByRole("tab", { name: "设定共创", exact: true })
    const taskTab = generateTabs.getByRole("tab", { name: "整理资料", exact: true })
    await expectNoPageOverflow(page)
    for (const tab of await generateTabs.getByRole("tab").all()) {
      expect((await tab.boundingBox()).height).toBeGreaterThanOrEqual(44)
    }
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.locator("html").evaluate((element) => { element.style.fontSize = "125%" })
    await expectNoPageOverflow(page)
    await page.locator("html").evaluate((element) => { element.style.fontSize = "" })
    await expect(worldTab).toHaveAttribute("aria-selected", "true")
    await worldTab.focus()
    await page.keyboard.press("ArrowRight")
    await expect(taskTab).toBeFocused()
    await expect(worldTab).toHaveAttribute("aria-selected", "true")

    await taskTab.click()
    await expect(page.getByRole("tabpanel", { name: "整理资料" })).toBeVisible()
    await page.getByText("更多条件", { exact: true }).click()
    await expect(page.getByLabel("参考范围")).toBeVisible()
    await expect(page.getByLabel("当前章节")).toBeVisible()
    await expect(page.getByLabel("资料长度上限")).toBeVisible()
    await expect(page.getByLabel("可参考的信息")).toBeVisible()
  })

  test("世界共创聊天先确认本次参考资料", async ({ page }) => {
    await page.locator("#generate-chat-input").fill("帮我设计一个反派")
    await page.getByRole("button", { name: "发送" }).click()

    await expect(page.locator(SEL.modalTitle)).toContainText("AI 参考资料")
    const start = page.getByRole("button", { name: "按这份资料开始" })
    await expect(start).toBeEnabled()
    await start.click()
    await expect(page.locator("#generate-chat-messages")).toContainText("旧友型反派")
  })

  test("世界共创输入区在桌面、手机和矮窗口不遮挡操作", async ({ page }) => {
    const composer = page.locator("#generate-chat-input")
    const send = page.locator('[data-action="send-chat-message"]')
    await composer.fill("推敲潮汐城市的夜间交通规则")
    await composer.evaluate((element) => { element.style.height = "144px" })

    for (const viewport of [
      { width: 1440, height: 900 },
      { width: 390, height: 844 },
      { width: 812, height: 375 },
    ]) {
      await page.setViewportSize(viewport)
      await send.evaluate((element) => element.scrollIntoView({ block: "center" }))
      await expect(composer).toBeVisible()
      await expect(send).toBeVisible()
      await expectNoPageOverflow(page)
      const inputBox = await composer.boundingBox()
      const sendBox = await send.boundingBox()
      expect(inputBox).not.toBeNull()
      expect(sendBox).not.toBeNull()
      expect(sendBox.y).toBeGreaterThanOrEqual(inputBox.y + inputBox.height)
      expect(sendBox.height).toBeGreaterThanOrEqual(44)
      if (viewport.width <= 760) expect(sendBox.y + sendBox.height).toBeLessThanOrEqual(viewport.height - 64)
    }
  })

  test("手机参考资料栏支持键盘、刷新、历史和作品隔离", async ({ page, browserErrors }) => {
    let secondProject = null
    const key = `workspace-rail:${testProjectId}:generate:assistant`
    try {
      await page.setViewportSize({ width: 375, height: 812 })
      await page.evaluate((storageKey) => sessionStorage.removeItem(storageKey), key)
      await page.reload({ waitUntil: "domcontentloaded" })
      await page.waitForFunction(() => !state.loading)

      const rail = page.locator(".generate-side-rail")
      const summary = rail.locator(":scope > summary")
      await expect(rail).not.toHaveAttribute("open", "")
      await summary.focus()
      await page.keyboard.press("Enter")
      await expect(rail).toHaveAttribute("open", "")

      await page.reload({ waitUntil: "domcontentloaded" })
      await expect(rail).toHaveAttribute("open", "")
      await page.evaluate(() => window.router.navigate("outline"))
      await expect(page.locator("#topbar-module")).toContainText("故事结构")
      await page.goBack()
      await expect(rail).toHaveAttribute("open", "")

      secondProject = await createProject({ title: "参考栏隔离对照作品", genre: "fantasy", language: "zh" })
      await openWorkbench(page, secondProject, "generate")
      await expect(rail).not.toHaveAttribute("open", "")
      await openWorkbench(page, { id: testProjectId, title: "生成测试项目", genre: "fantasy", language: "zh" }, "generate")
      await expect(rail).toHaveAttribute("open", "")
      expect(browserErrors, `浏览器错误: ${JSON.stringify(browserErrors)}`).toHaveLength(0)
    } finally {
      if (secondProject?.id) await cleanupProject(secondProject.id)
    }
  })

  test("世界共创失败保留问题并可原位重试", async ({ page }) => {
    const chatRoute = "**/api/world/generation-center/chat"
    let attempts = 0
    await page.unroute(chatRoute)
    await page.route(chatRoute, async (route) => {
      attempts += 1
      if (attempts === 1) {
        await route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: "暂时无法回复" }) })
        return
      }
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ reply: "重试后已恢复" }) })
    })

    await page.locator("#generate-chat-input").fill("不要丢掉这个问题")
    await page.getByRole("button", { name: "发送", exact: true }).click()
    await approveContext(page)
    const retry = page.getByRole("button", { name: "再试一次" })
    await expect(retry).toBeVisible()
    await expect(retry).toBeFocused()
    await retry.click()
    await approveContext(page)
    await expect(page.locator("#generate-chat-messages")).toContainText("重试后已恢复")
    await expect(page.locator(".generate-chat-message.user")).toHaveCount(1)
    expect(attempts).toBe(2)
  })

  test("刷新中断聊天后恢复确定的本地终态，不重复或接受迟到回复", async ({ page }) => {
    const chatRoute = "**/api/world/generation-center/chat"
    let releaseRoute
    let chatRequests = 0
    let completeRoute
    const routeFinished = new Promise((resolve) => { completeRoute = resolve })
    const delayedChatHandler = async (route) => {
      chatRequests += 1
      await new Promise((resolve) => { releaseRoute = resolve })
      try {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({ reply: "不应显示的迟到回复" }),
        })
      } catch {} finally { completeRoute() }
    }
    await page.route(chatRoute, delayedChatHandler)

    try {
      await page.locator("#generate-chat-input").fill("刷新前的问题")
      await page.getByRole("button", { name: "发送" }).click()
      await approveContext(page)
      await expect(page.locator("#generate-chat-messages")).toContainText("正在理解你的目标")
      await expect.poll(() => chatRequests).toBe(1)

      await page.reload({ waitUntil: "domcontentloaded" })
      await expect(page.locator("#generate-chat-messages")).toContainText("刷新前的问题")
      await expect(page.locator("#generate-chat-messages")).toContainText("上次回复在离开或刷新时尚未返回")
      releaseRoute()
      await routeFinished
      await expect(page.locator("#generate-chat-messages")).not.toContainText("不应显示的迟到回复")
      await page.locator("#generate-chat-input").fill("确认后再试")
      await expect(page.getByRole("button", { name: "发送" })).toBeEnabled()
      expect(chatRequests).toBe(1)
    } finally {
      releaseRoute?.()
      if (!page.isClosed()) await page.unroute(chatRoute, delayedChatHandler)
    }
  })

  test("粘贴外部对话后生成世界对象建议", async ({ page, browserErrors }) => {
    await page.route("**/api/world/entities/generated-candidate-e2e?*", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "generated-candidate-e2e",
          novel_id: testProjectId,
          name: "沈无咎",
          entity_type: "character",
          status: "candidate",
          summary: "旧友型反派，公开温和，暗中推动主角面对旧秩序。",
          importance_level: "important",
          suggested_action: "create_new",
          content_json: { _meta: { suggestion_id: "suggestion-generate-e2e", compatibility_shadow: true, source: "ai_generated" } },
        }),
      })
    })
    await page.locator("#generate-chat-input").fill("外部 Chatbox：反派不是纯恶人。")
    await page.locator("#generate-quality-pro").check()
    await page.getByRole("button", { name: "生成世界对象建议" }).click()
    await approveContext(page)

    await expect(page.locator("#generate-result")).toContainText("沈无咎", { timeout: 15000 })
    await expect(page.locator("#generate-result")).toContainText("待处理")
    await expect(page.locator("#generate-result")).not.toContainText("已发布")
    await expect(page.locator("#generate-result")).toContainText("去待处理审阅")

    await page.getByRole("button", { name: "去待处理审阅" }).click()
    await expect(page).toHaveURL(/world\/review\?kind=objects.*entity_id=generated-candidate-e2e.*review_item=generated-candidate-e2e/)
    await expect(page.locator(".world-review-decision")).toContainText("决定是否采用“沈无咎”")
    await expect(page.locator(".world-review-decision")).toContainText("旧友型反派")
    await expect(page.locator(".world-review-decision")).toContainText("人物 · 重要设定")

    await page.reload()
    await expect(page.locator(".world-review-decision")).toContainText("决定是否采用“沈无咎”")
    await page.goBack()
    await expect(page.locator("#generate-chat-messages")).toContainText("外部 Chatbox：反派不是纯恶人。")
    await page.goForward()
    await expect(page.locator(".world-review-decision")).toContainText("决定是否采用“沈无咎”")

    await page.setViewportSize({ width: 390, height: 844 })
    await expect(page.locator(".world-review-workbench")).toHaveClass(/is-detail-open/)
    const backToQueue = page.getByRole("button", { name: "返回队列" })
    await expect.poll(async () => (await backToQueue.boundingBox())?.height || 0).toBeGreaterThanOrEqual(44)
    const ignore = page.getByRole("button", { name: "忽略", exact: true })
    await ignore.scrollIntoViewIfNeeded()
    await expect.poll(async () => {
      const actionBox = await ignore.boundingBox()
      const navBox = await page.locator(".sidebar-mobile-nav").boundingBox()
      return Boolean(actionBox && navBox && actionBox.y + actionBox.height <= navBox.y)
    }).toBe(true)
    const returnToAi = page.getByRole("button", { name: "返回继续完善" })
    await returnToAi.scrollIntoViewIfNeeded()
    await returnToAi.click()
    await expect(page.getByRole("dialog", { name: "AI 工具" })).toBeVisible()
    await expect(page.locator("#generate-chat-messages")).toContainText("外部 Chatbox：反派不是纯恶人。")
    expect(browserErrors).toEqual([])
  })

  test("生成中心直接新建整页提案，编辑后只进入世界书工作稿", async ({ page }) => {
    const directionSummary = page.locator('[data-section="world-direction"] > summary')
    await directionSummary.click()
    await page.getByRole("button", { name: "新建世界书页" }).click()
    await expect(directionSummary).toContainText("新建世界书页")
    await directionSummary.click()
    await expect(page.getByRole("button", { name: "新建世界书页" })).toHaveClass(/active/)

    await page.locator("#generate-chat-input").fill("创建一页关于龙息潮的世界规则")
    await page.getByRole("button", { name: "生成新页提案" }).click()
    await expect(page.locator("#generate-result")).toContainText("龙息潮汐纪", { timeout: 15000 })

    await page.locator("#generate-page-title").fill("作者修订·龙息潮汐纪")
    await page.locator("#generate-page-free-text").fill("作者确定的潮汐经济与迁徙逻辑。")
    await page.getByRole("button", { name: "应用到工作稿" }).click()

    await expect(page.locator("#topbar-module")).toContainText("人物与世界", { timeout: 15000 })
    await expect(page.locator(".world-bible-workspace")).toContainText("作者修订·龙息潮汐纪")
    expect(worldSuggestionRequests.at(-1).target).toEqual(expect.objectContaining({
      kind: "world_bible_new_page",
      page_type: expect.any(String),
    }))
    expect(pageDraftApplyRequests.at(-1).page.title).toBe("作者修订·龙息潮汐纪")
  })

  test("整页提案刷新后恢复同一 pending suggestion 的作者编辑，并只写服务器工作稿", async ({ page }) => {
    const sourcePage = await createWorldBiblePage(testProjectId, {
      page_type: "background",
      title: "北境旧规则",
      free_text: "canonical 基线内容。",
      sections_json: [],
    })
    const before = await getWorldBiblePage(testProjectId, sourcePage.id)
    const generationUrl = `${new URL(page.url()).origin}/#workbench/${testProjectId}/generate?tab=world&source_page_id=${sourcePage.id}&target=world_bible_page`
    const editedSectionsText = '[{"section_id":"author-rule","section_type":"markdown","title":"作者规则","body_markdown":"作者确认的九日潮汐因果。","sort_order":0,"linked_asset_ref_hashes":[],"projection_policy":"eligible","sensitivity_hint":"author_safe"}]'
    const restoredPayload = {
      operation: "replace_existing",
      target_page_id: sourcePage.id,
      design_rationale: "同时强化创意核心和规则因果。",
      review_notes: ["作者可继续调整细节"],
      page: {
        title: "重构后的北境规则",
        page_type: "background",
        free_text: "北境的交易与通行规则。",
        sections_json: [{
          section_id: "trade-rules",
          section_type: "markdown",
          title: "运作逻辑",
          body_markdown: "龙息潮每九日回流，并为势力资源争夺提供可验证的因果链。",
          sort_order: 0,
          linked_asset_ref_hashes: [],
          projection_policy: "eligible",
          sensitivity_hint: "author_safe",
        }],
        linked_asset_refs_json: [],
      },
    }
    const suggestionRoute = "**/api/world/suggestions?*"
    await page.route(suggestionRoute, async (route) => {
      const url = new URL(route.request().url())
      if (
        url.searchParams.get("novel_id") !== testProjectId
        || url.searchParams.get("status") !== "pending"
        || url.searchParams.get("review_group") !== "generation_center"
      ) {
        await route.fallback()
        return
      }
      expect(route.request().method()).toBe("GET")
      expect(url.searchParams.get("novel_id")).toBe(testProjectId)
      expect(url.searchParams.get("status")).toBe("pending")
      expect(url.searchParams.get("review_group")).toBe("generation_center")
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [{
            id: "suggestion-existing-page-e2e",
            novel_id: testProjectId,
            source_module: "world",
            review_group: "generation_center",
            target_type: "world_bible_page_draft",
            status: "pending",
            payload_json: restoredPayload,
          }],
          total: 1,
        }),
      })
    })

    try {
      await page.goto(generationUrl)
      await page.reload()
      await page.waitForFunction(() => !state.loading, { timeout: 10000 })
      await expect(page.locator(".generate-world-source-bar")).toContainText("北境旧规则")
      await expect(page.getByRole("button", { name: "生成整页提案" })).toBeVisible()
      await page.locator("#generate-chat-input").fill("增加交易机制并检查因果闭环")
      await page.getByRole("button", { name: "生成整页提案" }).click()
      await approveContext(page)
      await expect(page.locator("#generate-result")).toContainText("重构后的北境规则", { timeout: 15000 })
      await page.locator("#generate-page-title").fill("作者恢复后的标题")
      await page.locator("#generate-page-free-text").fill("作者恢复后的概览与 Unicode：潮汐 🐉")
      await page.locator('[data-section="advanced-page-data"] summary').click()
      await page.locator("#generate-page-sections").fill(editedSectionsText)

      await page.reload()
      await page.waitForFunction(() => !state.loading, { timeout: 10000 })
      await expect(page.locator('[data-state="recovered-page-proposal"]')).toContainText("已恢复上次未应用的提案编辑")
      await expect(page.locator("#generate-page-title")).toHaveValue("作者恢复后的标题")
      await expect(page.locator("#generate-page-free-text")).toHaveValue("作者恢复后的概览与 Unicode：潮汐 🐉")
      await expect(page.locator("#generate-page-sections")).toHaveValue(editedSectionsText)
      await expect(page.locator('[data-section="advanced-page-data"]')).not.toHaveJSProperty("open", true)

      await page.getByRole("button", { name: "应用到工作稿" }).click()
      await expect(page.locator(".world-bible-workspace")).toContainText("作者恢复后的标题", { timeout: 15000 })
      const drafts = await listWorldBibleDrafts(testProjectId)
      const appliedDraft = drafts.items.find((draft) => draft.page_id === sourcePage.id)
      expect(appliedDraft).toEqual(expect.objectContaining({
        title: "作者恢复后的标题",
        free_text: "作者恢复后的概览与 Unicode：潮汐 🐉",
        sections_json: JSON.parse(editedSectionsText),
      }))
      const after = await getWorldBiblePage(testProjectId, sourcePage.id)
      expect(after.title).toBe(before.title)
      expect(after.free_text).toBe(before.free_text)
    } finally {
      if (!page.isClosed()) await page.unroute(suggestionRoute)
    }
  })

  test("完善现有页时保留 canonical，并按页面与目标隔离对话", async ({ page }) => {
    const sourcePage = await createWorldBiblePage(testProjectId, {
      page_type: "background",
      title: "北境交易旧规",
      free_text: "这是已发布基线内容。",
      sections_json: [],
    })
    const before = await getWorldBiblePage(testProjectId, sourcePage.id)
    const generationUrl = `${new URL(page.url()).origin}/#workbench/${testProjectId}/generate?tab=world&source_page_id=${sourcePage.id}&target=world_bible_page`
    await page.goto(generationUrl)
    await page.reload()
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })

    await expect(page.locator(".generate-world-source-bar")).toContainText("北境交易旧规")
    await page.locator("#generate-chat-input").fill("增加一个新的交易机制，并检查因果闭环")
    await page.getByRole("button", { name: "生成整页提案" }).click()
    await approveContext(page)
    await expect(page.locator("#generate-result")).toContainText("重构后的北境规则", { timeout: 15000 })
    await page.locator("#generate-page-title").fill("作者定稿·北境规则")
    await page.getByRole("button", { name: "应用到工作稿" }).click()

    await expect(page.locator(".world-bible-workspace")).toContainText("作者定稿·北境规则", { timeout: 15000 })
    const after = await getWorldBiblePage(testProjectId, sourcePage.id)
    expect(after.title).toBe(before.title)
    expect(after.free_text).toBe(before.free_text)

    await page.goto(generationUrl)
    await page.reload()
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })
    await page.locator("#generate-chat-input").fill("只属于页面完善会话")
    await page.getByRole("button", { name: "发送" }).click()
    await approveContext(page)
    await page.locator('[data-section="world-direction"] > summary').click()
    await page.getByRole("button", { name: "世界对象" }).click()
    await expect(page.locator("#generate-chat-messages")).not.toContainText("只属于页面完善会话")
    await page.locator("#generate-chat-input").fill("基于这页创建一个商会对象")
    await page.getByRole("button", { name: "生成世界对象建议" }).click()
    await approveContext(page)
    expect(worldSuggestionRequests.at(-1).source_context).toEqual(expect.objectContaining({
      kind: "world_bible_page",
      page_id: sourcePage.id,
    }))
    expect(worldSuggestionRequests.at(-1).target.kind).toBe("core_entity")

    await page.locator('[data-section="world-direction"] > summary').click()
    await page.getByRole("button", { name: "完善当前页" }).click()
    await expect(page.locator("#generate-chat-messages")).toContainText("只属于页面完善会话")
    await expect(page.locator("#generate-include-world-synopsis")).toBeChecked()
  })

  test("任务参考资料在当前流程完成并适配窄屏", async ({ page, browserErrors }) => {
    const failedResponses = []
    page.on("response", (response) => { if (response.status() >= 400) failedResponses.push({ status: response.status(), url: response.url() }) })
    await page.locator('[data-action="owner-task-context"]').click()
    await page.setViewportSize({ width: 375, height: 812 })
    const task = page.locator("#gen-task")
    const run = page.getByRole("button", { name: "整理参考资料" })
    const resultActions = page.locator(".generate-task-output-actions")
    await expect(page.getByLabel("常用任务（可选）")).toHaveValue("custom")
    await expect(resultActions).toHaveCount(0)
    await expect(task).toBeInViewport()
    await expect(run).toBeInViewport()
    await expectNoPageOverflow(page)
    await page.emulateMedia({ reducedMotion: "reduce" })
    await page.locator("html").evaluate((element) => { element.style.fontSize = "125%" })
    await task.focus()
    await expect(task).toBeInViewport()
    await expectNoPageOverflow(page)
    await page.locator("html").evaluate((element) => { element.style.fontSize = "" })
    await task.fill("生成剧情线")
    await expect(resultActions).toHaveCount(0)

    await run.click()

    await expect(page.locator("#gen-task-output")).toContainText("已准备 2 类参考资料", { timeout: 15000 })
    await expect(resultActions).toBeVisible()
    await expect(resultActions.getByRole("button")).toHaveCount(2)
    await expect(resultActions.getByRole("button", { name: "查看完整资料" })).toHaveClass(/btn-primary/)
    await expect(resultActions.getByRole("button", { name: "带到世界设定对话" })).not.toHaveClass(/btn-primary/)
    await expect(resultActions.locator('[data-action="copy-task-md"], [data-action="export-task-md"]')).toHaveCount(0)
    await expect(page.locator("#gen-task-output")).toContainText("相关人物")
    await expect(page.locator(".generate-context-overview")).not.toContainText("author_safe")
    await expect(page.locator(".generate-context-diagnostics")).not.toHaveAttribute("open", "")
    await expect(page.getByRole("tabpanel", { name: "整理资料" })).toBeVisible()

    await resultActions.getByRole("button", { name: "带到世界设定对话" }).click()
    const categories = page.getByRole("tablist", { name: "AI 工具类别" })
    await expect(categories.getByRole("tab", { name: "设定共创", exact: true })).toHaveAttribute("aria-selected", "true")
    await expect(page.locator("#generate-chat-messages")).toContainText("生成剧情线")
    await expect(page.locator("#generate-chat-messages")).toContainText("已整理 2 类参考资料")
    await categories.getByRole("tab", { name: "整理资料", exact: true }).click()
    await expect(resultActions).toBeVisible()

    await expectNoPageOverflow(page)
    expect((await run.boundingBox()).height).toBeGreaterThanOrEqual(44)
    await page.setViewportSize({ width: 812, height: 375 })
    await expectNoPageOverflow(page)
    expect(failedResponses).toEqual([])
    expect(browserErrors).toEqual([])
  })

  test("完整参考资料可刷新、返回并按项目隔离", async ({ page, projectFactory, browserErrors }) => {
    const project = await page.evaluate(() => state.currentProject)
    await page.locator('[data-action="owner-task-context"]').click()
    await page.locator("#gen-task-preset").selectOption("plot")
    await expect(page.locator("#gen-task")).toHaveValue("基于当前设定梳理主线、支线和伏笔推进。")
    await page.getByRole("button", { name: "整理参考资料" }).click()
    await expect(page.locator("#gen-task-output")).toContainText("已准备 2 类参考资料", { timeout: 15000 })

    await page.getByRole("button", { name: "查看完整资料" }).click()

    await expect(page.locator("#workspace-content")).toContainText("完整参考资料")
    await expect(page.locator("#workspace-content")).toContainText("任务：基于当前设定梳理主线")
    await expect(page.locator("#gen-preview-output")).toContainText("已准备 2 类参考资料")
    await expect(page.locator("#gen-preview-output")).toContainText("基于当前设定梳理主线")

    await page.reload({ waitUntil: "domcontentloaded" })
    await expect(page.locator("#gen-preview-output")).toContainText("已准备 2 类参考资料", { timeout: 10000 })
    await expect(page).toHaveURL(/owner_ai_mode=preview/)
    await page.getByRole("button", { name: "返回调整" }).click()
    await expect(page.locator("#gen-task-preset")).toHaveValue("plot")
    await expect(page.locator("#gen-task")).toHaveValue("基于当前设定梳理主线、支线和伏笔推进。")

    const secondProject = await projectFactory({ title: "参考资料隔离项目", genre: "fantasy" })
    await openWorkbench(page, secondProject, "generate")
    await page.locator('[data-action="owner-task-context"]').click()
    await expect(page.locator("#gen-task-output")).not.toContainText("已准备 2 类参考资料")
    await openWorkbench(page, project, "generate")
    await page.locator('[data-action="owner-task-context"]').click()
    await page.getByRole("button", { name: "查看完整资料" }).click()
    await expect(page.locator("#gen-preview-output")).toContainText("已准备 2 类参考资料")
    expect(browserErrors).toEqual([])
  })

  test("任务草稿可跨类别、刷新和浏览器前进恢复，并按项目隔离", async ({ page }) => {
    let secondProject
    try {
      await page.locator('[data-action="owner-task-context"]').click()
      await page.locator("#gen-task").fill("刷新后继续整理的任务")
      await page.getByText("更多条件", { exact: true }).click()
      await page.locator("#gen-scope").selectOption("chapter")
      await expect.poll(() => page.evaluate((id) => {
        const prefix = `generate_world_workspace_state_v2_${id}`
        return Object.keys(localStorage)
          .filter((key) => key.startsWith(prefix))
          .map((key) => JSON.parse(localStorage.getItem(key))?.taskForm?.task)
          .find(Boolean) || ""
      }, testProjectId)).toBe("刷新后继续整理的任务")

      await page.locator('[data-action="owner-evidence"]').click()
      await page.locator('[data-action="owner-task-context"]').click()
      await expect(page.locator("#gen-task")).toHaveValue("刷新后继续整理的任务")
      await expect(page.locator("#gen-scope")).toHaveValue("chapter")
      await expect(page).toHaveURL(/owner_ai_mode=task/)

      await page.reload({ waitUntil: "domcontentloaded" })
      await expect(page.locator("#gen-task")).toHaveValue("刷新后继续整理的任务", { timeout: 10000 })
      await page.goBack()
      await page.goForward()
      await expect(page.locator("#gen-task")).toHaveValue("刷新后继续整理的任务", { timeout: 10000 })

      secondProject = await createProject({ title: "任务隔离项目", genre: "fantasy", language: "zh" })
      await openWorkbench(page, secondProject, "generate")
      await page.locator('[data-action="owner-task-context"]').click()
      await expect(page.locator("#gen-task")).toHaveValue("")
    } finally {
      if (secondProject?.id) await cleanupProject(secondProject.id)
    }
  })

  test("整理失败时聚焦就地错误并可重试", async ({ page }) => {
    await page.route("**/api/evidence/compilation/compile", async (route) => {
      await route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ detail: "资料服务暂时忙碌" }) })
    }, { times: 1 })
    await page.locator('[data-action="owner-task-context"]').click()
    await page.locator("#gen-task").fill("检查失败恢复")
    await page.getByRole("button", { name: "整理参考资料" }).click()

    const error = page.locator(".generate-task-error")
    await expect(error).toContainText("当前任务内容仍保留")
    await expect(error).not.toContainText("资料服务暂时忙碌")
    await expect(error).toBeFocused()
    await page.getByRole("button", { name: "重试" }).click()
    await expect(page.locator("#gen-task-output")).toContainText("已准备 2 类参考资料", { timeout: 15000 })
  })

  test("没有聊天或粘贴内容时给出警告", async ({ page }) => {
    await page.getByRole("button", { name: "生成世界对象建议" }).click()

    await expect(page.locator(SEL.toastContainer)).toContainText("请先聊天、粘贴已有对话，或选择一条相邻探索", { timeout: 10000 })
  })

  test("角色视角模式缺少视角人物时不提交编译", async ({ page }) => {
    let compileCalled = false
    await page.route("**/api/evidence/compilation/compile", async (route) => {
      compileCalled = true
      await route.fulfill({ status: 500, body: JSON.stringify({ detail: "should not call" }) })
    })

    await page.locator('[data-action="owner-task-context"]').click()
    await page.locator(".gen-form-section summary").click()
    await page.locator("#gen-reveal").selectOption("character")
    await page.locator("#gen-task").fill("写角色视角场景")
    await page.getByRole("button", { name: "整理参考资料" }).click()

    await expect(page.locator(SEL.toastContainer)).toContainText("角色视角模式必须选择视角人物", { timeout: 10000 })
    expect(compileCalled).toBeFalsy()
  })

  test("按名称选择生成上下文，payload 仍提交稳定 ID", async ({ page }) => {
    const relatedEntity = await createEntity(testProjectId, {
      name: "北境密钥",
      entity_type: "item",
      status: "canonical",
      summary: "用于打开王宫暗门",
    })
    const viewpointCharacter = await createEntity(testProjectId, {
      name: "顾临渊",
      entity_type: "character",
      status: "canonical",
      summary: "此次潜入行动的视角人物",
    })
    const scene = await createScene(testProjectId, {
      scene_index: 0,
      title: "潜入王宫",
      goal: "取得密信",
      narrative_tag: "draft",
      chapter_ids: [],
      scene_chunks: [],
    })
    const requests = []
    await page.route("**/api/evidence/compilation/compile", async (route) => {
      const body = route.request().postDataJSON()
      requests.push(body)
      const warnings = body.reveal_mode === "character"
        ? ["POV Knowledge: 角色误以为铜铃只是普通遗物"]
        : ["Author Notes: 隐藏真相：铜铃属于旧王密探"]

      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          novel_id: body.novel_id,
          task: body.task,
          scope: body.scope,
          reveal_mode: body.reveal_mode,
          budgets: [],
          warnings,
          section_count: 1,
          sections_present: ["characters"],
          sections: [{ key: "characters", tier: "standard", token_count: 600, truncated: false }],
          evicted: [],
          truncated: [],
        }),
      })
    })

    await page.locator('[data-action="owner-task-context"]').click()
    await page.locator(".gen-form-section summary").click()
    await page.locator("#gen-reveal").selectOption("character")

    const selectReference = async (rootSelector, query, label) => {
      const root = page.locator(rootSelector)
      await root.locator("[data-reference-query]").fill(query)
      await root.locator("[data-reference-result]", { hasText: label }).click()
      await expect(root.locator("[data-reference-selected]")).toContainText(label)
    }
    await selectReference("#gen-entities-picker", "北境密钥", "北境密钥")
    await selectReference("#gen-characters-picker", "顾临渊", "顾临渊")
    await selectReference("#gen-scene-picker", "潜入王宫", "潜入王宫")
    await selectReference("#gen-viewpoint-character-picker", "顾临渊", "顾临渊")
    await page.locator("#gen-task").fill("写角色视角场景")
    await page.getByRole("button", { name: "整理参考资料" }).click()

    await expect(page.locator("#workspace-content")).toContainText("误以为", { timeout: 10000 })
    await expect(page.locator("#gen-task-output")).not.toContainText("隐藏真相")
    expect(requests.at(-1).reveal_mode).toBe("character")
    expect(requests.at(-1).entity_ids).toEqual([relatedEntity.id])
    expect(requests.at(-1).character_ids).toEqual([viewpointCharacter.id])
    expect(requests.at(-1).scene_id).toBe(scene.id)
    expect(requests.at(-1).viewpoint_character_id).toBe(viewpointCharacter.id)
  })

  test("编辑模板弹窗可查看提示词并创建新模板", async ({ page }) => {
    await page.locator('[data-section="world-direction"] > summary').click()
    await page.getByRole("button", { name: "编辑对象模板" }).click()

    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑模板")
    await expect(page.locator("#generate-template-editor-prompt")).toHaveValue(/不预设固定创作框架/)

    await page.locator("#generate-template-editor-name").fill("DND 圣骑士")
    await page.locator("#generate-template-editor-prompt").fill("突出誓言、神术、阵营冲突。")
    await page.getByRole("button", { name: "新建模板" }).click()

    await expect(page.locator("#generate-template-row")).toContainText("DND 圣骑士", { timeout: 10000 })
  })
})
