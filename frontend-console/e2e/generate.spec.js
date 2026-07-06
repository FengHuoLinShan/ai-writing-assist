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

  test("编辑模板弹窗可查看提示词并创建新模板", async ({ page }) => {
    await page.getByRole("button", { name: "编辑模板" }).click()

    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑模板")
    await expect(page.locator("#generate-template-editor-prompt")).toHaveValue(/不预设对象类型/)

    await page.locator("#generate-template-editor-name").fill("DND 圣骑士")
    await page.locator("#generate-template-editor-prompt").fill("突出誓言、神术、阵营冲突。")
    await page.getByRole("button", { name: "新建模板" }).click()

    await expect(page.locator("#workspace-content")).toContainText("DND 圣骑士")
  })

  test("没有聊天或粘贴内容时给出警告", async ({ page }) => {
    await page.getByRole("button", { name: "生成对象（数据库草稿）" }).click()

    await expect(page.locator(SEL.toastContainer)).toContainText("请先聊天或粘贴已有对话到输入框", { timeout: 10000 })
  })
})
