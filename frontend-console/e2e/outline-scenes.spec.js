import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench, reloadWorkbench } from "./helpers/workbench.js"
import { createEntity, createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

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

    await openWorkbench(page, project, "outline", "scenes")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
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
    // Given: 用户在 Scene 卡空态页面
    await expect(page.locator(SEL.emptyState)).toContainText("暂无 Scene")

    // When: 点击新建 Scene 按钮，填写表单并提交
    await page.locator('[data-action="create-scene"]').click()
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

    // Then: 刷新页面后列表显示新 Scene 卡
    await reloadWorkbench(page, "outline", "scenes")

    const card = page.locator(".scene-card").first()
    await expect(card).toContainText("初入江湖")
    await expect(card).toContainText("激励事件")
    await expect(card).toContainText("主角首次踏入江湖世界")
  })

  test("编辑 Scene 卡", async ({ page }) => {
    // Given: 已存在一个 Scene 卡
    await page.locator('[data-action="create-scene"]').click()
    await page.locator("#create-scene-title").fill("原始标题")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("Scene 卡已创建", { timeout: 10000 })

    // 刷新以显示列表
    await reloadWorkbench(page, "outline", "scenes")
    await expect(page.locator(".scene-card")).toContainText("原始标题")

    // When: 点击编辑按钮，修改字段并保存
    await page.locator('[data-action="edit-scene"]').first().click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑 Scene 卡")

    await page.locator("#edit-scene-title").fill("修改后的标题")
    await page.locator("#edit-scene-goal").fill("新的目标")
    await page.locator("#edit-scene-tag").selectOption("rising_action")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存", { timeout: 10000 })

    // Then: 刷新后列表更新
    await reloadWorkbench(page, "outline", "scenes")
    await expect(page.locator(".scene-card")).toContainText("修改后的标题")
    await expect(page.locator(".scene-card")).toContainText("冲突升级")
    await expect(page.locator(".scene-card")).toContainText("新的目标")
  })

  test("删除 Scene 卡", async ({ page }) => {
    // Given: 已存在一个 Scene 卡
    await page.locator('[data-action="create-scene"]').click()
    await page.locator("#create-scene-title").fill("待删除 Scene")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("Scene 卡已创建", { timeout: 10000 })

    // 刷新以显示列表
    await reloadWorkbench(page, "outline", "scenes")
    await expect(page.locator(".scene-card")).toContainText("待删除 Scene")

    // When: 点击删除按钮，确认删除
    await page.locator('[data-action="delete-scene"]').first().click()

    // 确认对话框
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已删除", { timeout: 10000 })

    // Then: 刷新后列表为空
    await reloadWorkbench(page, "outline", "scenes")
    await expect(page.locator(SEL.emptyState)).toContainText("暂无 Scene")
  })

  test("上移/下移 Scene 卡调整顺序", async ({ page }) => {
    // Given: 已存在两个 Scene 卡
    await page.locator('[data-action="create-scene"]').click()
    await page.locator("#create-scene-title").fill("Scene A")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("Scene 卡已创建", { timeout: 10000 })

    await page.locator('[data-action="create-scene"]').click()
    await page.locator("#create-scene-title").fill("Scene B")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("Scene 卡已创建", { timeout: 10000 })

    // 刷新以显示列表
    await reloadWorkbench(page, "outline", "scenes")
    await expect(page.locator(".scene-card").filter({ hasText: "Scene A" })).toHaveCount(1)
    await expect(page.locator(".scene-card").filter({ hasText: "Scene B" })).toHaveCount(1)

    // When: 点击第二个 Scene 的上移
    const secondCard = page.locator(".scene-card").nth(1)
    await secondCard.locator('[data-action="move-scene-up"]').click()

    // Then: 提示顺序已更新，且列表顺序已交换
    await expect(page.locator(SEL.toastContainer)).toContainText("Scene 顺序已更新", { timeout: 10000 })
    const titles = await page.locator(".scene-card .scene-card-title").allTextContents()
    expect(titles).toEqual(["Scene B", "Scene A"])
  })

  test("AI 生成结构弹窗", async ({ page }) => {
    // Given: 用户在大纲 Scene 标签
    await expect(page.locator('[data-action="generate-structure"]')).toBeVisible()

    // When: 点击 AI 生成结构
    await page.locator('[data-action="generate-structure"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("AI 生成剧情结构")
    await expect(page.locator("#generate-structure-start")).toBeVisible()
    await expect(page.locator("#generate-structure-end")).toBeVisible()

    // 关闭弹窗
    await page.locator(SEL.modalClose).click()
    await expect(page.locator(SEL.modalOverlay)).not.toBeVisible()
  })

  test("管理伏笔与揭示计划", async ({ page }) => {
    // 伏笔子标签：创建后可见、可切换状态
    await page.locator('[data-action="nav-foreshadowing"]').click()
    await expect(page.locator(SEL.emptyState)).toContainText("暂无伏笔")

    await page.locator('[data-action="create-foreshadowing"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建伏笔计划")

    await page.locator("#create-foreshadowing-name").fill("古剑封印")
    await page.locator("#create-foreshadowing-summary").fill("主角会在前期接触古剑")
    await page.locator("#create-foreshadowing-seed").fill("2")
    await page.locator("#create-foreshadowing-payoff").fill("8")
    await page.locator("#create-foreshadowing-status").selectOption("draft")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("伏笔计划已创建", { timeout: 10000 })

    await reloadWorkbench(page, "outline", "foreshadowing")
    await expect(page.locator(SEL.dataTable)).toContainText("古剑封印")

    await page.locator(".foreshadowing-status-select").first().selectOption("active")
    await expect(page.locator(SEL.toastContainer)).toContainText("伏笔状态已更新", { timeout: 10000 })
    await expect(page.locator(".data-table")).toContainText("激活")

    // 揭示子标签：创建后可见
    await page.locator('[data-action="nav-reveals"]').click()
    await expect(page.locator(SEL.emptyState)).toContainText("暂无揭示")

    await page.locator('[data-action="create-reveal"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建揭示计划")

    const entity = await createEntity(testProjectId, {
      name: "古剑",
      entity_type: "artifact",
      status: "canonical",
    })

    await page.locator("#create-reveal-target-type").fill("world_entity")
    await page.locator("#create-reveal-target-id").fill(entity.id)
    await page.locator("#create-reveal-secret").fill("古剑其实封印着魔神")
    await page.locator("#create-reveal-chapter").fill("4")
    await page.locator("#create-reveal-content").fill("第一次揭示古剑异动")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("揭示计划已创建", { timeout: 10000 })

    await reloadWorkbench(page, "outline", "reveals")
    await expect(page.locator(SEL.dataTable)).toContainText("world_entity")
    await expect(page.locator(SEL.dataTable)).toContainText("古剑其实封印着魔神")
  })
})
