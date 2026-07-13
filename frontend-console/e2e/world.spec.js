import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench, reloadWorkbench } from "./helpers/workbench.js"
import { createProject, cleanupProject, waitForBackend, createEntity, createCharacter, seedEntityArchive } from "./helpers/api-client.js"
import { expectNoPageOverflow, runResponsiveMatrix } from "./helpers/responsive.js"

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

    await runResponsiveMatrix(page, async () => {
      await expectNoPageOverflow(page)
      await expect(page.locator(SEL.dataTable)).toBeVisible()
    }, [
      { width: 900, height: 800 },
      { width: 600, height: 800 },
      { width: 390, height: 844 },
    ])
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

  test("待处理对象可微调后采用", async ({ page }) => {
    const candidate = await createEntity(testProjectId, {
      name: "待微调星门",
      entity_type: "location",
      status: "candidate",
      summary: "原始概要",
      content_json: { _meta: { source: "deep_import", needs_review: true } },
    })
    await reloadWorkbench(page, "world", "review-objects")

    const row = page.locator(`tr[data-id="${candidate.id}"]`)
    await expect(row).toContainText("待微调星门")
    await row.locator('[data-action="edit-entity"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑后采用世界对象")

    await page.locator("#edit-entity-name").fill("已微调星门")
    await page.locator("#edit-entity-summary").fill("作者微调后的概要")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已编辑并采用", {
      timeout: 10000,
    })

    await reloadWorkbench(page, "world", "objects")
    await expect(page.locator(SEL.dataTable)).toContainText("已微调星门")
    await expect(page.locator(SEL.dataTable)).toContainText("作者微调后的概要")
  })

  test("别名建议和高相似名称在待处理中合并展示", async ({ page }) => {
    const target = await createEntity(testProjectId, {
      name: "林岚",
      entity_type: "character",
      status: "canonical",
    })
    await createEntity(testProjectId, {
      name: "岚姐",
      entity_type: "character",
      status: "candidate",
      content_json: { _meta: {
        suggested_action: "link_to_existing",
        suggested_existing_entity_id: target.id,
        suggested_existing_entity_name: target.name,
      } },
    })
    await createEntity(testProjectId, {
      name: "克莱恩",
      entity_type: "character",
      status: "candidate",
    })
    await createEntity(testProjectId, {
      name: "克莱恩·莫雷蒂",
      entity_type: "character",
      status: "candidate",
    })

    await reloadWorkbench(page, "world", "review-objects")

    const aliasGroup = page.locator(
      `.world-candidate-alias-group[data-target-id="${target.id}"]`,
    )
    await expect(aliasGroup).toContainText("已有对象")
    await expect(aliasGroup).toContainText("林岚")
    await expect(aliasGroup).toContainText("岚姐")

    const similarGroup = page.locator(".world-candidate-similar-group")
    await expect(similarGroup).toContainText("克莱恩")
    await expect(similarGroup).toContainText("克莱恩·莫雷蒂")
    await expect(similarGroup.locator('[data-action="merge-entity"]')).toHaveCount(2)
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

    // When: 打开行内更多菜单并点击删除，确认删除
    await page.locator('.data-table tbody tr .action-menu-btn').first().click()
    await page.locator('[data-action="delete-entity"]').click()

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
    // Given: 通过 API 创建目标正史实体与待处理候选实体
    const target = await createEntity(testProjectId, {
      name: "目标实体",
      entity_type: "location",
      status: "canonical",
    })
    const candidate = await createEntity(testProjectId, {
      name: "候选实体",
      entity_type: "location",
      status: "candidate",
      content_json: {
        _meta: {
          suggested_action: "merge_with_existing",
          suggested_existing_entity_name: target.name,
        },
      },
    })

    await reloadWorkbench(page, "world", "candidates")
    await expect(page.locator(SEL.dataTable)).toContainText("候选实体")

    // When: 在待处理列表中点击合并，输入目标 ID
    await page.locator('tr:has-text("候选实体") [data-action="merge-entity"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("合并对象")
    await page.locator("#merge-target-id").selectOption(target.id)
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    // Then: 提示合并完成
    await expect(page.locator(SEL.toastContainer)).toContainText("实体已合并", { timeout: 10000 })
  })

  test("候选合并后当前页和分页总数保持一致", async ({ page }) => {
    const target = await createEntity(testProjectId, {
      name: "同名目标",
      entity_type: "location",
      status: "canonical",
    })
    const candidates = []
    for (let i = 1; i <= 21; i += 1) {
      candidates.push(await createEntity(testProjectId, {
        name: `同名候选 ${String(i).padStart(2, "0")}`,
        entity_type: "location",
        status: "candidate",
        content_json: {
          _meta: {
            suggested_action: "merge_with_existing",
            suggested_existing_entity_name: target.name,
          },
        },
      }))
    }

    await reloadWorkbench(page, "world", "candidates")
    await expect(page.locator(SEL.dataTable)).toContainText("同名候选 01")
    await expect(page.locator(SEL.dataTable)).toContainText("同名候选 02")
    await expect(page.getByText("共 21 条")).toBeVisible()

    await page.locator(SEL.tableRow(candidates[0].id)).locator('[data-action="merge-entity"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("合并对象")
    await page.locator("#merge-target-query").fill("同名目标")
    await page.locator("#merge-target-search").click()
    await expect(page.locator("#merge-target-id")).toContainText("同名目标")
    await page.locator("#merge-target-id").selectOption(target.id)
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    await expect(page.locator(SEL.toastContainer)).toContainText("实体已合并", { timeout: 10000 })
    await expect(page.locator(SEL.dataTable)).not.toContainText("同名候选 01")
    await expect(page.locator(SEL.dataTable)).toContainText("同名候选 02")
    await expect(page.getByText("共 21 条")).toHaveCount(0)
    await expect(page.locator(`${SEL.dataTable} tbody tr`)).toHaveCount(20)
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

    await page.locator('tr:has-text("待回滚实体") .action-menu-btn').click()
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

    // When: 打开人物行的更多菜单并点击"知识"按钮，填写知识条目
    await page.locator('tr:has-text("主角") .action-menu-btn').click()
    await page.locator('tr:has-text("主角") [data-action="knowledge-entity"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("添加知识边界")
    await page.locator("#knowledge-target-id").selectOption(target.id)
    await page.locator("#knowledge-level").selectOption("partial")
    await page.locator("#knowledge-content").fill("知道组织存在，但不了解核心")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    // Then: 提示添加成功
    await expect(page.locator(SEL.toastContainer)).toContainText("知识边界已添加", { timeout: 10000 })
  })

  test("按类型过滤对象", async ({ page }) => {
    await createEntity(testProjectId, { name: "测试地点", entity_type: "location", status: "canonical" })
    await createEntity(testProjectId, { name: "测试组织", entity_type: "faction", status: "canonical" })

    await reloadWorkbench(page, "world", "objects")
    await expect(page.locator(SEL.dataTable)).toContainText("测试地点")
    await expect(page.locator(SEL.dataTable)).toContainText("测试组织")

    await page.locator("#filter-entity-type").selectOption("location")
    await page.locator('[data-action="apply-filters"]').click()

    await expect(page.locator(SEL.dataTable)).toContainText("测试地点")
    await expect(page.locator(SEL.dataTable)).not.toContainText("测试组织")
  })

  test("按名称搜索对象", async ({ page }) => {
    await createEntity(testProjectId, { name: "搜索目标", entity_type: "item", status: "canonical" })
    await createEntity(testProjectId, { name: "其他对象", entity_type: "item", status: "canonical" })

    await reloadWorkbench(page, "world", "objects")
    await expect(page.locator(SEL.dataTable)).toContainText("搜索目标")

    await page.locator("#filter-q").fill("搜索目标")
    await page.locator('[data-action="apply-filters"]').click()

    await expect(page.locator(SEL.dataTable)).toContainText("搜索目标")
    await expect(page.locator(SEL.dataTable)).not.toContainText("其他对象")
  })

  test("对象库分页", async ({ page }) => {
    for (let i = 0; i < 22; i++) {
      await createEntity(testProjectId, { name: `分页对象 ${i}`, entity_type: "item", status: "canonical" })
    }

    await reloadWorkbench(page, "world", "objects")
    await expect(page.locator(SEL.dataTable)).toContainText("分页对象 0")
    await expect(page.locator(SEL.workspaceContent)).toContainText("第 1 / 2 页，共 22 条")

    const firstPageRows = await page.locator(`${SEL.dataTable} tbody tr`).allTextContents()
    expect(firstPageRows).toHaveLength(20)

    // 默认每页 20 条，应出现分页信息
    await expect(page.locator('[data-action="next-page"]')).toBeVisible()
    await page.locator('[data-action="next-page"]').click()

    await expect(page.locator(SEL.workspaceContent)).toContainText("第 2 / 2 页，共 22 条")
    await expect(page.locator('[data-action="next-page"]')).toBeDisabled()
    await expect(page.locator('[data-action="prev-page"]')).toBeEnabled()

    const secondPageRows = await page.locator(`${SEL.dataTable} tbody tr`).allTextContents()
    expect(secondPageRows).toHaveLength(2)
    expect(secondPageRows).not.toEqual(firstPageRows.slice(0, 2))
    expect(secondPageRows.join("\n")).toContain("分页对象")
  })
})
