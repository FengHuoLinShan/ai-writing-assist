import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

test.describe("生成中心模块", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
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

    await page.route("**/api/world/object-draft-chat", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          reply: "可以设计成旧友型反派，动机来自一次被误解的牺牲。",
          model: "deepseek-v4-flash",
          provider: "fake",
        }),
      })
    })

    await page.route("**/api/world/object-drafts/generate", async (route) => {
      const postBody = route.request().postDataJSON()
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          quality_mode: postBody.quality_mode,
          model: postBody.quality_mode === "pro" ? "deepseek-v4-pro" : "deepseek-v4-flash",
          provider: "fake",
          entity: {
            id: "entity-generate-e2e",
            novel_id: testProjectId,
            entity_type: postBody.template || "character",
            name: "沈无咎",
            summary: "旧友型反派，公开温和，暗中推动主角面对旧秩序。",
            status: "draft",
            content_json: {},
          },
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
    await expect(page.locator("#view-title")).toContainText("生成中心")
    await expect(page.locator("#topbar-generate-note")).toContainText("先自由聊")
    await expect(page.locator("#workspace-content")).toContainText("人物")
    await expect(page.locator("#workspace-content")).toContainText("高质量")
    await expect(page.locator("#workspace-content")).toContainText("生成对象（数据库草稿）")
    await expect(page.locator("#workspace-content")).toContainText("自由对话")
    await expect(page.locator("#workspace-content")).toContainText("任务")
    await expect(page.locator("#workspace-content")).toContainText("上下文预览")
    await expect(page.locator("#workspace-content")).not.toContainText("粘贴已有对话")
  })

  test("自由聊天不会打开 AI 参考资料确认", async ({ page }) => {
    await page.locator("#generate-chat-input").fill("帮我设计一个反派")
    await page.getByRole("button", { name: "发送" }).click()

    await expect(page.locator("#generate-chat-messages")).toContainText("旧友型反派")
    await expect(page.locator(SEL.modalTitle)).not.toHaveText("AI 参考资料")
  })

  test("粘贴外部对话后生成数据库草稿", async ({ page }) => {
    await page.locator("#generate-chat-input").fill("外部 Chatbox：反派不是纯恶人。")
    await page.locator("#generate-quality-pro").check()
    await page.getByRole("button", { name: "生成对象（数据库草稿）" }).click()

    await expect(page.locator("#generate-result")).toContainText("沈无咎", { timeout: 15000 })
    await expect(page.locator("#generate-result")).toContainText("draft")
    await expect(page.locator("#generate-result")).toContainText("打开世界对象")
  })

  test("任务标签可执行上下文编译", async ({ page }) => {
    await page.getByRole("button", { name: "任务" }).click()
    await page.locator("#gen-task").fill("生成剧情线")

    await page.getByRole("button", { name: "执行任务" }).click()

    await expect(page.locator("#gen-task-output")).toContainText("已加载 2 段上下文", { timeout: 15000 })
    await expect(page.locator("#gen-task-output")).toContainText("characters")
  })

  test("上下文预览标签展示最近一次编译结果", async ({ page }) => {
    await page.getByRole("button", { name: "任务" }).click()
    await page.locator('[data-preset="plot"]').click()
    await page.getByRole("button", { name: "执行任务" }).click()
    await expect(page.locator("#gen-task-output")).toContainText("已加载 2 段上下文", { timeout: 15000 })

    await page.getByRole("button", { name: "上下文预览" }).click()

    await expect(page.locator("#workspace-content")).toContainText("上下文预览")
    await expect(page.locator("#workspace-content")).toContainText("任务：生成剧情线")
  })

  test("没有聊天或粘贴内容时给出警告", async ({ page }) => {
    await page.getByRole("button", { name: "生成对象（数据库草稿）" }).click()

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
    await page.locator("#gen-viewpoint-character").fill("")
    await page.locator("#gen-task").fill("写角色视角场景")
    await page.getByRole("button", { name: "执行任务" }).click()

    await expect(page.locator(SEL.toastContainer)).toContainText("角色视角模式必须选择或输入视角人物 ID", { timeout: 10000 })
    expect(compileCalled).toBeFalsy()
  })

  test("角色视角模式提交 reveal_mode=character 与视角人物 ID", async ({ page }) => {
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
    await page.locator("#gen-viewpoint-character").fill("00000000-0000-0000-0000-000000000123")
    await page.locator("#gen-task").fill("写角色视角场景")
    await page.getByRole("button", { name: "执行任务" }).click()

    await expect(page.locator("#workspace-content")).toContainText("误以为", { timeout: 10000 })
    await expect(page.locator("#workspace-content")).not.toContainText("隐藏真相")
    expect(requests.at(-1).reveal_mode).toBe("character")
    expect(requests.at(-1).character_ids).toEqual(["00000000-0000-0000-0000-000000000123"])
    expect(requests.at(-1).viewpoint_character_id).toBe("00000000-0000-0000-0000-000000000123")
  })

  test("编辑模板弹窗可查看提示词并创建新模板", async ({ page }) => {
    await page.getByRole("button", { name: "编辑模板" }).click()

    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑模板")
    await expect(page.locator("#generate-template-editor-prompt")).toHaveValue(/不预设对象类型/)

    await page.locator("#generate-template-editor-name").fill("DND 圣骑士")
    await page.locator("#generate-template-editor-prompt").fill("突出誓言、神术、阵营冲突。")
    await page.getByRole("button", { name: "新建模板" }).click()

    await expect(page.locator("#generate-template-row")).toContainText("DND 圣骑士", { timeout: 10000 })
  })
})
