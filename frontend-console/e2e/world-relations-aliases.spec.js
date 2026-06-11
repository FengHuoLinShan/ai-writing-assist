import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { createProject, deleteProject, waitForBackend } from "./helpers/api-client.js"

test.describe("世界对象 — 关系与别名", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "关系别名测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.evaluate((id) => {
      localStorage.setItem("novel_currentProjectId", id)
      localStorage.setItem("novel_currentProject", JSON.stringify({ id, title: "关系别名测试项目" }))
    }, project.id)
    await page.reload()

    await page.locator(SEL.navItem("world")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("世界对象")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await deleteProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  /*
   * BLOCKED: 后端缺少关系管理 API
   *
   * 前端 worldView.js 已实现关系创建/删除 UI，但后端 world 模块
   * 未提供以下端点：
   *   POST   /api/world/relationships
   *   DELETE /api/world/relationships/:id
   *
   * 当前调用返回 404 "请求的资源不存在：Not Found"。
   *
   * 实现计划：
   * 1. 在 backend/modules/world/api.py 添加关系 CRUD 路由
   * 2. 在 backend/modules/world/services.py 实现关系业务逻辑
   * 3. 确认 relationships 表已存在（alembic 迁移检查）
   * 4. 解除本测试的 fixme 标记并验证
   */
  test.fixme("创建关系并显示在列表中", async ({ page }) => {
    // Given: 已存在两个实体
    await page.locator("#btn-new-entity").click()
    await page.locator("#create-entity-name").fill("源对象")
    await page.locator("#create-entity-type").selectOption("character_ref")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    await page.locator("#btn-new-entity").click()
    await page.locator("#create-entity-name").fill("目标对象")
    await page.locator("#create-entity-type").selectOption("location")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    // 刷新获取实体 ID
    await page.reload()
    await page.locator(SEL.navItem("world")).click()
    await expect(page.locator(SEL.dataTable)).toContainText("源对象")
    await expect(page.locator(SEL.dataTable)).toContainText("目标对象")

    const sourceId = await page.locator("tr:has-text('源对象')").getAttribute("data-id")
    const targetId = await page.locator("tr:has-text('目标对象')").getAttribute("data-id")

    // When: 切换到关系子标签，创建关系
    await page.locator(SEL.subnavItem("relations")).click()
    await expect(page.locator(SEL.subnavItem("relations"))).toHaveClass(/active/)

    await page.locator('[data-action="create-relation"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建关系")

    await page.locator("#rel-source").fill(sourceId)
    await page.locator("#rel-target").fill(targetId)
    await page.locator("#rel-type").selectOption("ally_of")
    await page.locator("#rel-desc").fill("测试关系描述")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("关系已创建", { timeout: 10000 })

    // Then: 刷新后列表显示新关系
    await page.reload()
    await page.locator(SEL.navItem("world")).click()
    await page.locator(SEL.subnavItem("relations")).click()
    await expect(page.locator(SEL.dataTable)).toBeVisible()
    await expect(page.locator(SEL.dataTable)).toContainText("ally_of")
  })

  /*
   * BLOCKED: 后端缺少别名管理 API
   *
   * 前端 worldView.js 已实现别名创建/删除 UI，但后端 world 模块
   * 未提供以下端点：
   *   POST   /api/world/aliases
   *   DELETE /api/world/entities/:id/aliases
   *
   * 当前调用返回 404 "请求的资源不存在：Not Found"。
   *
   * 实现计划：
   * 1. 在 backend/modules/world/api.py 添加别名 CRUD 路由
   * 2. 在 backend/modules/world/services.py 实现别名业务逻辑
   *    （别名存储在 core_entities.aliases JSONB 字段中）
   * 3. 解除本测试的 fixme 标记并验证
   */
  test.fixme("创建别名并显示在列表中", async ({ page }) => {
    // Given: 已存在一个实体
    await page.locator("#btn-new-entity").click()
    await page.locator("#create-entity-name").fill("主角")
    await page.locator("#create-entity-type").selectOption("character_ref")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    // 刷新获取实体 ID
    await page.reload()
    await page.locator(SEL.navItem("world")).click()
    await expect(page.locator(SEL.dataTable)).toContainText("主角")
    const entityId = await page.locator("tr:has-text('主角')").getAttribute("data-id")

    // When: 切换到别名子标签，创建别名
    await page.locator(SEL.subnavItem("aliases")).click()
    await expect(page.locator(SEL.subnavItem("aliases"))).toHaveClass(/active/)

    await page.locator('[data-action="create-alias"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建别名")

    await page.locator("#alias-entity").fill(entityId)
    await page.locator("#alias-text").fill("小名")
    await page.locator("#alias-type").selectOption("nickname")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("别名已创建", { timeout: 10000 })

    // Then: 刷新后列表显示新别名
    await page.reload()
    await page.locator(SEL.navItem("world")).click()
    await page.locator(SEL.subnavItem("aliases")).click()
    await expect(page.locator(SEL.dataTable)).toBeVisible()
    await expect(page.locator(SEL.dataTable)).toContainText("小名")
    await expect(page.locator(SEL.dataTable)).toContainText("昵称")
  })
})
