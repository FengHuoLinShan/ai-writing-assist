import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import {
  createProject,
  cleanupProject,
  createWorldBibleDraft,
  createWorldBiblePage,
  createEntity,
  createScene,
  getWorldBiblePage,
  waitForBackend,
} from "./helpers/api-client.js"

test.describe("生成中心模块", () => {
  let testProjectId = null
  let worldSuggestionRequests = []
  let pageDraftApplyRequests = []

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    worldSuggestionRequests = []
    pageDraftApplyRequests = []
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
          model: "deepseek-v4-flash",
          provider: "fake",
          source_snapshot: { kind: "project" },
        }),
      })
    })

    await page.route("**/api/world/generation-center/suggestions", async (route) => {
      const postBody = route.request().postDataJSON()
      worldSuggestionRequests.push(postBody)
      const targetKind = postBody.target.kind
      if (targetKind === "world_bible_page" || targetKind === "world_bible_new_page") {
        const createNew = targetKind === "world_bible_new_page"
        await route.fulfill({
          status: 201,
          contentType: "application/json",
          body: JSON.stringify({
            model: "deepseek-v4-flash",
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
          }),
        })
        return
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          model: postBody.quality_mode === "pro" ? "deepseek-v4-pro" : "deepseek-v4-flash",
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
              payload_json: {
                entity_type: postBody.target.template || "character",
                name: "沈无咎",
                summary: "旧友型反派，公开温和，暗中推动主角面对旧秩序。",
              },
            },
          },
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

    await page.route("**/api/context/compile", async (route) => {
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
          sections: [
            { key: "project", tier: "core", token_count: 200, truncated: false },
            { key: "characters", tier: "standard", token_count: 1000, truncated: true },
          ],
          evicted: ["rag_chunks"],
          truncated: ["characters"],
          warnings: [],
        }),
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
    await expect(page.locator("#topbar-module")).toContainText("生成中心")
    await expect(page.locator("#topbar-view-note")).toContainText("先自由聊")
    await expect(page.locator("#workspace-content")).toContainText("人物")
    await expect(page.locator("#workspace-content")).toContainText("高质量")
    await expect(page.locator("#workspace-content")).toContainText("生成世界对象建议")
    await expect(page.locator("#workspace-content")).toContainText("世界设定")
    await expect(page.locator("#workspace-content")).toContainText("任务")
    await expect(page.locator("#workspace-content")).toContainText("上下文预览")
    await expect(page.locator("#workspace-content")).not.toContainText("粘贴已有对话")
  })

  test("世界共创聊天不会打开 AI 参考资料确认", async ({ page }) => {
    await page.locator("#generate-chat-input").fill("帮我设计一个反派")
    await page.getByRole("button", { name: "发送" }).click()

    await expect(page.locator("#generate-chat-messages")).toContainText("旧友型反派")
    await expect(page.locator(SEL.modalTitle)).not.toHaveText("AI 参考资料")
  })

  test("粘贴外部对话后生成世界对象建议", async ({ page }) => {
    await page.locator("#generate-chat-input").fill("外部 Chatbox：反派不是纯恶人。")
    await page.locator("#generate-quality-pro").check()
    await page.getByRole("button", { name: "生成世界对象建议" }).click()

    await expect(page.locator("#generate-result")).toContainText("沈无咎", { timeout: 15000 })
    await expect(page.locator("#generate-result")).toContainText("待处理")
    await expect(page.locator("#generate-result")).not.toContainText("已发布")
    await expect(page.locator("#generate-result")).toContainText("前往待处理")
  })

  test("生成中心直接新建整页提案，编辑后只进入世界书工作稿", async ({ page }) => {
    await page.getByRole("button", { name: "新建世界书页" }).click()
    await expect(page.getByRole("button", { name: "新建世界书页" })).toHaveClass(/active/)

    await page.locator("#generate-chat-input").fill("创建一页关于龙息潮的世界规则")
    await page.getByRole("button", { name: "生成新页提案" }).click()
    await expect(page.locator("#generate-result")).toContainText("龙息潮汐纪", { timeout: 15000 })

    await page.locator("#generate-page-title").fill("作者修订·龙息潮汐纪")
    await page.locator("#generate-page-free-text").fill("作者确定的潮汐经济与迁徙逻辑。")
    await page.getByRole("button", { name: "应用到工作稿" }).click()

    await expect(page.locator("#topbar-module")).toContainText("世界对象", { timeout: 15000 })
    await expect(page.locator(".world-bible-workspace")).toContainText("作者修订·龙息潮汐纪")
    expect(worldSuggestionRequests.at(-1).target).toEqual(expect.objectContaining({
      kind: "world_bible_new_page",
      page_type: expect.any(String),
    }))
    expect(pageDraftApplyRequests.at(-1).page.title).toBe("作者修订·龙息潮汐纪")
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
    await page.getByRole("button", { name: "世界对象" }).click()
    await expect(page.locator("#generate-chat-messages")).not.toContainText("只属于页面完善会话")
    await page.locator("#generate-chat-input").fill("基于这页创建一个商会对象")
    await page.getByRole("button", { name: "生成世界对象建议" }).click()
    expect(worldSuggestionRequests.at(-1).source_context).toEqual(expect.objectContaining({
      kind: "world_bible_page",
      page_id: sourcePage.id,
    }))
    expect(worldSuggestionRequests.at(-1).target.kind).toBe("core_entity")

    await page.getByRole("button", { name: "完善当前页" }).click()
    await expect(page.locator("#generate-chat-messages")).toContainText("只属于页面完善会话")
    await expect(page.locator("#generate-include-world-synopsis")).toBeChecked()
  })

  test("任务标签可执行上下文编译", async ({ page }) => {
    await page.getByRole("button", { name: "任务" }).click()
    await page.locator("#gen-task").fill("生成剧情线")

    await page.getByRole("button", { name: "编译上下文" }).click()

    await expect(page.locator("#gen-task-output")).toContainText("已加载 2 段上下文", { timeout: 15000 })
    await expect(page.locator("#gen-task-output")).toContainText("characters")
  })

  test("上下文预览标签展示最近一次编译结果", async ({ page }) => {
    await page.getByRole("button", { name: "任务" }).click()
    await page.locator('[data-preset="plot"]').click()
    await page.getByRole("button", { name: "编译上下文" }).click()
    await expect(page.locator("#gen-task-output")).toContainText("已加载 2 段上下文", { timeout: 15000 })

    await page.getByRole("button", { name: "上下文预览" }).click()

    await expect(page.locator("#workspace-content")).toContainText("上下文预览")
    await expect(page.locator("#workspace-content")).toContainText("任务：生成剧情线")
  })

  test("没有聊天或粘贴内容时给出警告", async ({ page }) => {
    await page.getByRole("button", { name: "生成世界对象建议" }).click()

    await expect(page.locator(SEL.toastContainer)).toContainText("请先聊天或粘贴已有对话到输入框", { timeout: 10000 })
  })

  test("角色视角模式缺少视角人物时不提交编译", async ({ page }) => {
    let compileCalled = false
    await page.route("**/api/context/compile", async (route) => {
      compileCalled = true
      await route.fulfill({ status: 500, body: JSON.stringify({ detail: "should not call" }) })
    })

    await page.getByRole("button", { name: "任务" }).click()
    await page.locator(".gen-form-section summary").click()
    await page.locator("#gen-reveal").selectOption("character")
    await page.locator("#gen-task").fill("写角色视角场景")
    await page.getByRole("button", { name: "编译上下文" }).click()

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
    await page.route("**/api/context/compile", async (route) => {
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

    await page.getByRole("button", { name: "任务" }).click()
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
    await page.getByRole("button", { name: "编译上下文" }).click()

    await expect(page.locator("#workspace-content")).toContainText("误以为", { timeout: 10000 })
    await expect(page.locator("#workspace-content")).not.toContainText("隐藏真相")
    expect(requests.at(-1).reveal_mode).toBe("character")
    expect(requests.at(-1).entity_ids).toEqual([relatedEntity.id])
    expect(requests.at(-1).character_ids).toEqual([viewpointCharacter.id])
    expect(requests.at(-1).scene_id).toBe(scene.id)
    expect(requests.at(-1).viewpoint_character_id).toBe(viewpointCharacter.id)
  })

  test("编辑模板弹窗可查看提示词并创建新模板", async ({ page }) => {
    await page.getByRole("button", { name: "编辑对象模板" }).click()

    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑模板")
    await expect(page.locator("#generate-template-editor-prompt")).toHaveValue(/不预设固定创作框架/)

    await page.locator("#generate-template-editor-name").fill("DND 圣骑士")
    await page.locator("#generate-template-editor-prompt").fill("突出誓言、神术、阵营冲突。")
    await page.getByRole("button", { name: "新建模板" }).click()

    await expect(page.locator("#generate-template-row")).toContainText("DND 圣骑士", { timeout: 10000 })
  })
})
