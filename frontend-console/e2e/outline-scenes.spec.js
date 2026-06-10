import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { createProject, deleteProject, waitForBackend } from "./helpers/api-client.js"

test.describe("Outline View — Scene 卡", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "Scene E2E 测试",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.evaluate((id) => {
      localStorage.setItem("novel_currentProjectId", id)
      localStorage.setItem("novel_currentProject", JSON.stringify({ id, title: "Scene E2E 测试" }))
    }, project.id)
    await page.reload()

    // 导航到大纲视图
    await page.locator(SEL.navItem("outline")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("大纲")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await deleteProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("默认显示 Scene 卡子标签", async ({ page }) => {
    // 默认子标签应为场景卡
    const scenesTab = page.locator('[data-action="nav-scenes"]')
    await expect(scenesTab).toHaveClass(/active/)

    // 应显示空态
    const emptyState = page.locator(SEL.emptyState)
    await expect(emptyState).toContainText("暂无 Scene")
  })

  test("创建 Scene 卡", async ({ page }) => {
    await page.evaluate(() => outlineView._showCreateSceneForm())
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建 Scene 卡")

    await page.locator("#create-scene-title").fill("初入江湖")
    await page.locator("#create-scene-tag").selectOption("inciting_incident")
    await page.locator("#create-scene-goal").fill("主角首次踏入江湖世界")
    await page.locator("#create-scene-conflict").fill("遭遇地痞挑衅")
    await page.locator("#create-scene-emotion").fill("紧张→愤怒→释然")
    await page.locator("#create-scene-must-happen").fill("主角必须展现实力")
    await page.locator("#create-scene-must-not").fill("不能暴露真实身份")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("Scene 卡已创建", { timeout: 10000 })

    // 手动刷新数据并重新渲染
    await page.evaluate(async () => {
      await outlineView.onEnter()
      const content = document.getElementById("workspace-content")
      if (content) content.innerHTML = await outlineView.render()
    })

    const card = page.locator(".scene-card").first()
    await expect(card).toContainText("初入江湖")
    await expect(card).toContainText("激励事件")
    await expect(card).toContainText("主角首次踏入江湖世界")
  })

  test("编辑 Scene 卡", async ({ page }) => {
    // 先创建一个 Scene
    await page.evaluate(() => outlineView._showCreateSceneForm())
    await page.locator("#create-scene-title").fill("原始标题")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("Scene 卡已创建", { timeout: 10000 })

    await page.evaluate(async () => {
      await outlineView.onEnter()
      const content = document.getElementById("workspace-content")
      if (content) content.innerHTML = await outlineView.render()
    })
    await expect(page.locator(".scene-card")).toContainText("原始标题")

    // 直接调用编辑方法
    await page.evaluate(() => {
      const id = outlineView._scenes[0]?.id
      if (id) outlineView._editScene(id)
    })
    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑 Scene 卡")

    await page.locator("#edit-scene-title").fill("修改后的标题")
    await page.locator("#edit-scene-goal").fill("新的目标")
    await page.locator("#edit-scene-tag").selectOption("rising_action")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存", { timeout: 10000 })

    // 手动刷新
    await page.evaluate(async () => {
      await outlineView.onEnter()
      const content = document.getElementById("workspace-content")
      if (content) content.innerHTML = await outlineView.render()
    })

    const card = page.locator(".scene-card").first()
    await expect(card).toContainText("修改后的标题")
    await expect(card).toContainText("冲突升级")
    await expect(card).toContainText("新的目标")
  })

  test("删除 Scene 卡", async ({ page }) => {
    // 先创建一个 Scene
    await page.evaluate(() => outlineView._showCreateSceneForm())
    await page.locator("#create-scene-title").fill("待删除 Scene")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("Scene 卡已创建", { timeout: 10000 })

    await page.evaluate(async () => {
      await outlineView.onEnter()
      const content = document.getElementById("workspace-content")
      if (content) content.innerHTML = await outlineView.render()
    })
    await expect(page.locator(".scene-card")).toContainText("待删除 Scene")

    // 直接调用删除方法
    await page.evaluate(() => {
      const id = outlineView._scenes[0]?.id
      if (id) outlineView._deleteScene(id)
    })

    // 确认对话框
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已删除", { timeout: 10000 })

    // 手动刷新
    await page.evaluate(async () => {
      await outlineView.onEnter()
      const content = document.getElementById("workspace-content")
      if (content) content.innerHTML = await outlineView.render()
    })

    // 验证列表为空
    await expect(page.locator(SEL.emptyState)).toContainText("暂无 Scene")
  })
})
