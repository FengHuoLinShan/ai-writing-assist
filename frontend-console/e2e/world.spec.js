import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { createProject, deleteProject, waitForBackend } from "./helpers/api-client.js"

test.describe("世界对象模块", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "世界对象测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.evaluate((id) => {
      localStorage.setItem("novel_currentProjectId", id)
      localStorage.setItem("novel_currentProject", JSON.stringify({ id, title: "世界对象测试项目" }))
    }, project.id)
    await page.reload()

    // 导航到世界视图
    await page.locator(SEL.navItem("world")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("世界对象")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await deleteProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("对象库空态显示新建按钮", async ({ page }) => {
    await expect(page.locator(SEL.emptyState)).toBeVisible()
    await expect(page.locator("#btn-new-entity")).toBeVisible()
  })

  test("创建世界对象并显示在列表中", async ({ page }) => {
    await page.evaluate(() => worldView._showCreateForm())
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建世界对象")

    await page.locator("#create-entity-name").fill("测试城堡")
    await page.locator("#create-entity-type").selectOption("location")
    await page.locator("#create-entity-summary").fill("一座古老的城堡")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    // 等待创建成功 toast
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    // router 同视图导航会跳过 onEnter，需要手动刷新数据并重新渲染
    await page.evaluate(async () => {
      await worldView.onEnter()
      const content = document.getElementById("workspace-content")
      if (content) content.innerHTML = await worldView.render()
    })

    await expect(page.locator(SEL.dataTable)).toBeVisible()
    await expect(page.locator(SEL.dataTable)).toContainText("测试城堡")
    await expect(page.locator(SEL.dataTable)).toContainText("location")
  })

  test("编辑世界对象", async ({ page }) => {
    // 先创建一个对象
    await page.evaluate(() => worldView._showCreateForm())
    await page.locator("#create-entity-name").fill("编辑前名称")
    await page.locator("#create-entity-type").selectOption("item")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    // 手动刷新数据并重新渲染
    await page.evaluate(async () => {
      await worldView.onEnter()
      const content = document.getElementById("workspace-content")
      if (content) content.innerHTML = await worldView.render()
    })
    await expect(page.locator(SEL.dataTable)).toContainText("编辑前名称")

    // 直接调用编辑方法
    await page.evaluate(() => {
      const id = worldView._entities[0]?.id || worldView._entities[0]?.entity_id
      if (id) worldView.editEntity(id)
    })
    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑世界对象")

    await page.locator("#edit-entity-name").fill("编辑后名称")
    await page.locator("#edit-entity-type").selectOption("faction")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    // 等待保存成功 toast 并刷新
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存", { timeout: 10000 })
    await page.evaluate(async () => {
      await worldView.onEnter()
      const content = document.getElementById("workspace-content")
      if (content) content.innerHTML = await worldView.render()
    })
    await expect(page.locator(SEL.dataTable)).toContainText("编辑后名称")
  })

  test("删除世界对象", async ({ page }) => {
    // 先创建一个对象
    await page.evaluate(() => worldView._showCreateForm())
    await page.locator("#create-entity-name").fill("待删除对象")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    // 手动刷新数据并重新渲染
    await page.evaluate(async () => {
      await worldView.onEnter()
      const content = document.getElementById("workspace-content")
      if (content) content.innerHTML = await worldView.render()
    })
    await expect(page.locator(SEL.dataTable)).toContainText("待删除对象")

    // 直接调用删除方法
    await page.evaluate(() => {
      const id = worldView._entities[0]?.id || worldView._entities[0]?.entity_id
      if (id) worldView.deleteEntity(id)
    })

    // confirmAction 使用自定义模态框，点击确认
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()

    // 等待删除成功 toast 并刷新
    await expect(page.locator(SEL.toastContainer)).toContainText("已删除", { timeout: 10000 })
    await page.evaluate(async () => {
      await worldView.onEnter()
      const content = document.getElementById("workspace-content")
      if (content) content.innerHTML = await worldView.render()
    })
    await expect(page.locator("#workspace-content")).not.toContainText("待删除对象")
  })

  test("关系子标签显示", async ({ page }) => {
    await page.locator(SEL.subnavItem("relations")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("世界对象")
    await expect(page.locator(SEL.subnavItem("relations"))).toHaveClass(/active/)
    await expect(page.locator(SEL.emptyState)).toBeVisible()
  })

  test("别名子标签显示", async ({ page }) => {
    await page.locator(SEL.subnavItem("aliases")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("世界对象")
    await expect(page.locator(SEL.subnavItem("aliases"))).toHaveClass(/active/)
    await expect(page.locator(SEL.emptyState)).toBeVisible()
  })
})
