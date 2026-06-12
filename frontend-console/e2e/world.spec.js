import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench, reloadWorkbench } from "./helpers/workbench.js"
import { createProject, cleanupProject, waitForBackend, createEntity, createCharacter, seedEntityArchive } from "./helpers/api-client.js"

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

    await openWorkbench(page, project, "world", "objects")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("对象库空态显示新建按钮", async ({ page }) => {
    await expect(page.locator(SEL.emptyState)).toBeVisible()
    await expect(page.locator("#btn-new-entity")).toBeVisible()
  })

  test("创建世界对象并显示在列表中", async ({ page }) => {
    // Given: 用户在对象库空态页面
    await expect(page.locator("#btn-new-entity")).toBeVisible()

    // When: 点击新建按钮，填写表单并提交
    await page.locator("#btn-new-entity").click()
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建世界对象")

    await page.locator("#create-entity-name").fill("测试城堡")
    await page.locator("#create-entity-type").selectOption("location")
    await page.locator("#create-entity-summary").fill("一座古老的城堡")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    // Then: 显示创建成功 toast
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    // 刷新页面验证列表
    await reloadWorkbench(page, "world", "objects")

    await expect(page.locator(SEL.dataTable)).toBeVisible()
    await expect(page.locator(SEL.dataTable)).toContainText("测试城堡")
    await expect(page.locator(SEL.dataTable)).toContainText("location")
  })

  test("编辑世界对象", async ({ page }) => {
    // Given: 已存在一个世界对象
    await page.locator("#btn-new-entity").click()
    await page.locator("#create-entity-name").fill("编辑前名称")
    await page.locator("#create-entity-type").selectOption("item")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    // 刷新以显示列表
    await reloadWorkbench(page, "world", "objects")
    await expect(page.locator(SEL.dataTable)).toContainText("编辑前名称")

    // When: 点击编辑按钮，修改字段并保存
    await page.locator('[data-action="edit-entity"]').first().click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑世界对象")

    await page.locator("#edit-entity-name").fill("编辑后名称")
    await page.locator("#edit-entity-type").selectOption("faction")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    // Then: 保存成功，刷新后列表更新
    await expect(page.locator(SEL.toastContainer)).toContainText("已保存", { timeout: 10000 })

    await reloadWorkbench(page, "world", "objects")
    await expect(page.locator(SEL.dataTable)).toContainText("编辑后名称")
    await expect(page.locator(SEL.dataTable)).toContainText("faction")
  })

  test("删除世界对象", async ({ page }) => {
    // Given: 已存在一个世界对象
    await page.locator("#btn-new-entity").click()
    await page.locator("#create-entity-name").fill("待删除对象")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    // 刷新以显示列表
    await reloadWorkbench(page, "world", "objects")
    await expect(page.locator(SEL.dataTable)).toContainText("待删除对象")

    // When: 点击删除按钮，确认删除
    await page.locator('[data-action="delete-entity"]').first().click()

    // confirmAction 使用自定义模态框，点击确认
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()

    // Then: 删除成功，刷新后列表为空
    await expect(page.locator(SEL.toastContainer)).toContainText("已删除", { timeout: 10000 })

    await reloadWorkbench(page, "world", "objects")
    await expect(page.locator(SEL.emptyState)).toBeVisible()
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

  test("合并实体到目标实体", async ({ page }) => {
    // Given: 通过 API 创建目标正史实体与候选草稿实体
    const target = await createEntity(testProjectId, {
      name: "目标实体",
      entity_type: "location",
      status: "canonical",
    })
    const candidate = await createEntity(testProjectId, {
      name: "候选实体",
      entity_type: "location",
      status: "draft",
    })

    await reloadWorkbench(page, "world", "objects")
    await expect(page.locator(SEL.dataTable)).toContainText("目标实体")
    await expect(page.locator(SEL.dataTable)).toContainText("候选实体")

    // When: 在候选实体行点击合并，输入目标 ID
    await page.locator('tr:has-text("候选实体") [data-action="merge-entity"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("合并对象")
    await page.locator("#merge-target-id").fill(target.id)
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    // Then: 提示合并完成
    await expect(page.locator(SEL.toastContainer)).toContainText("实体已合并", { timeout: 10000 })
  })

  test("回滚实体到指定场景索引", async ({ page }) => {
    const entity = await createEntity(testProjectId, {
      name: "待回滚实体",
      entity_type: "item",
      status: "canonical",
      summary: "原始摘要",
    })

    // 通过种子 API 写入 TextArchive 归档值（原始摘要 → 归档摘要）
    await seedEntityArchive(testProjectId, entity.id, "归档摘要", { sceneIndex: 5 })

    await reloadWorkbench(page, "world", "objects")
    await expect(page.locator(SEL.dataTable)).toContainText("待回滚实体")

    await page.locator('tr:has-text("待回滚实体") [data-action="rollback-entity"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("回滚对象")
    await page.locator("#rollback-scene-index").fill("5")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    // 回滚后实体的 summary 应恢复为归档值
    await expect(page.locator(SEL.toastContainer)).toContainText("回滚完成", { timeout: 10000 })
  })

  test("为人物添加知识边界", async ({ page }) => {
    // Given: 目标实体 + 人物实体/Character 行
    const target = await createEntity(testProjectId, {
      name: "秘密组织",
      entity_type: "faction",
      status: "canonical",
    })
    const charEntity = await createEntity(testProjectId, {
      name: "主角",
      entity_type: "character_ref",
      status: "canonical",
    })
    await createCharacter(testProjectId, {
      entity_id: charEntity.id,
      name: "主角",
    })

    await reloadWorkbench(page, "world", "objects")
    await expect(page.locator(SEL.dataTable)).toContainText("主角")
    await expect(page.locator(SEL.dataTable)).toContainText("秘密组织")

    // When: 点击人物行的"知识"按钮，填写知识条目
    await page.locator('tr:has-text("主角") [data-action="knowledge-entity"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("添加知识边界")
    await page.locator("#knowledge-target-id").fill(target.id)
    await page.locator("#knowledge-level").selectOption("partial")
    await page.locator("#knowledge-content").fill("知道组织存在，但不了解核心")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    // Then: 提示添加成功
    await expect(page.locator(SEL.toastContainer)).toContainText("知识边界已添加", { timeout: 10000 })
  })
})
