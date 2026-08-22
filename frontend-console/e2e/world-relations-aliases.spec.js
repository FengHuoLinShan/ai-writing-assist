import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { reloadWorkbench } from "./helpers/workbench.js"
import {
  createAlias,
  createEntity,
  createRelation,
  listAliases,
  listRelations,
  waitForBackend,
} from "./helpers/api-client.js"

test.describe("世界对象 — 关系与别名", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ projectFactory, openProjectWorkbench }) => {
    const project = await projectFactory({
      title: "关系别名测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openProjectWorkbench(project, "world", "objects")
  })

  /*
   * 关系管理 API 已就绪：POST /api/world/relations、DELETE /api/world/relations/:id
   * 前端 worldView.js 通过"关系"子标签提供创建/删除 UI。
   */
  test("创建关系后可删除并从列表移除", async ({ page }) => {
    // Given: 已存在两个实体
    await page.locator("#btn-new-entity").click()
    await page.locator("#create-entity-name").fill("源对象")
    await page.locator("#create-entity-type").selectOption("character")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    await page.locator("#btn-new-entity").click()
    await page.locator("#create-entity-name").fill("目标对象")
    await page.locator("#create-entity-type").selectOption("location")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    // 刷新获取实体 ID
    await reloadWorkbench(page, "world", "objects")
    await expect(page.locator(".world-object-card-grid")).toContainText("源对象")
    await expect(page.locator(".world-object-card-grid")).toContainText("目标对象")

    const sourceId = await page.locator(".world-object-card", { hasText: "源对象" }).getAttribute("data-id")
    const targetId = await page.locator(".world-object-card", { hasText: "目标对象" }).getAttribute("data-id")

    // When: 切换到关系子标签，创建关系
    await page.locator(SEL.subnavItem("relations")).click()
    await expect(page.locator(SEL.subnavItem("relations"))).toHaveClass(/active/)

    await page.locator('[data-action="create-relation"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建关系")

    await page.locator("#rel-source").selectOption(sourceId)
    await page.locator("#rel-target").selectOption(targetId)
    await page.locator("#rel-type").selectOption("ally_of")
    await page.locator("#rel-desc").fill("测试关系描述")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("关系已创建", { timeout: 10000 })

    // Then: 刷新后列表显示新关系
    await reloadWorkbench(page, "world", "objects")
    await page.locator(SEL.subnavItem("relations")).click()
    await expect(page.locator(SEL.dataTable)).toBeVisible()
    await expect(page.locator(SEL.dataTable)).toContainText("盟友")

    const relationRow = page.locator("tr", { hasText: "盟友" })
    await expect(relationRow).toHaveCount(1)
    await relationRow.locator('[data-action="delete-relation"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("确认操作")
    await page.locator(SEL.modalFooter).getByRole("button", { name: "确认删除" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已删除", { timeout: 10000 })
    await expect(page.locator(SEL.workspaceContent)).not.toContainText("测试关系描述")
  })

  /*
   * 别名管理 API 已就绪：POST /api/world/aliases、DELETE /api/world/entities/:id/aliases
   * 前端 worldView.js 通过"别名"子标签提供创建/删除 UI。
   */
  test("创建别名并显示在列表中", async ({ page }) => {
    // Given: 已存在一个实体
    await page.locator("#btn-new-entity").click()
    await page.locator("#create-entity-name").fill("主角")
    await page.locator("#create-entity-type").selectOption("character")
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已创建", { timeout: 10000 })

    // 刷新获取实体 ID
    await reloadWorkbench(page, "world", "objects")
    await expect(page.locator(".world-object-card-grid")).toContainText("主角")
    const entityId = await page.locator(".world-object-card", { hasText: "主角" }).getAttribute("data-id")

    // When: 通过兼容深链进入别名管理，创建别名
    await reloadWorkbench(page, "world", "aliases")
    await expect(page).toHaveURL(new RegExp(`world/aliases`))

    await page.locator('[data-action="create-alias"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建别名")

    await page.locator("#alias-entity").selectOption(entityId)
    await page.locator("#alias-text").fill("小名")
    await page.locator("#alias-type").selectOption("nickname")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("别名已创建", { timeout: 10000 })
    await expect(page.locator(SEL.dataTable)).toContainText("小名", { timeout: 10000 })

    await createAlias(testProjectId, {
      entity_id: entityId,
      alias: "代号",
      alias_type: "alias",
    })

    // Then: 刷新后列表按对象聚合显示别名
    await reloadWorkbench(page, "world", "aliases")
    await expect(page.locator(SEL.dataTable)).toBeVisible()
    await expect(page.locator(`${SEL.dataTable} tbody td[rowspan="2"]`, { hasText: "主角" })).toHaveCount(1)
    await expect(page.locator(SEL.dataTable)).toContainText("小名")
    await expect(page.locator(SEL.dataTable)).toContainText("昵称")
    await expect(page.locator(SEL.dataTable)).toContainText("代号")
    await expect(page.locator(SEL.dataTable)).toContainText("别名")
  })

  test("待处理别名和关系使用统一筛选结构并保留 URL 语义", async ({ page }) => {
    await reloadWorkbench(page, "world", "review-aliases")
    await page.getByRole("button", { name: "更多筛选", exact: true }).click()
    await page.getByLabel("按场景序号筛选待处理别名", { exact: true }).fill("3")
    await page.getByLabel("待处理别名详细类型范围", { exact: true }).selectOption("custom")
    await page.getByLabel("待处理别名每页数量", { exact: true }).selectOption("50")
    await page.locator('[data-action="apply-alias-review-filters"]').last().click()
    await expect(page).toHaveURL(/scene_index=3/)
    await expect(page).toHaveURL(/type_kind=custom/)
    await expect(page).toHaveURL(/page_size=50/)

    await reloadWorkbench(page, "world", "review-relations")
    await page.getByRole("button", { name: "更多筛选", exact: true }).click()
    await page.getByLabel("按详细类型筛选待处理关系", { exact: true }).selectOption("friend_of")
    await page.getByLabel("待处理关系最低强度", { exact: true }).fill("0.7")
    await page.getByLabel("待处理关系引用证据", { exact: true }).selectOption("true")
    await page.getByLabel("待处理关系每页数量", { exact: true }).selectOption("50")
    await page.locator('[data-action="apply-relation-review-filters"]').last().click()
    await expect(page).toHaveURL(/relation_type=friend_of/)
    await expect(page).toHaveURL(/strength_min=0.7/)
    await expect(page).toHaveURL(/has_quote=true/)
    await expect(page).toHaveURL(/page_size=50/)
  })

  test("普通别名和单条关系可在决策栏直接采用", async ({ page }) => {
    const source = await createEntity(testProjectId, { name: "决策栏源对象", entity_type: "character", status: "canonical" })
    const target = await createEntity(testProjectId, { name: "决策栏目标对象", entity_type: "character", status: "canonical" })
    await createAlias(testProjectId, { entity_id: source.id, alias: "直接采用别名", alias_type: "name", status: "candidate" })
    await createRelation(testProjectId, { source_id: source.id, target_id: target.id, relation_type: "friend_of", description: "直接采用关系", strength: 0.7, status: "candidate" })

    await reloadWorkbench(page, "world", "review-aliases")
    await page.locator(".review-member-row", { hasText: "直接采用别名" }).click()
    const aliasDecision = page.locator(".world-alias-decision")
    await expect(aliasDecision).toContainText("目标对象（保留）")
    await expect(aliasDecision).toContainText("待并入别名")
    await expect(page.locator(SEL.modalOverlay)).toHaveClass(/hidden/)
    await aliasDecision.locator('[data-action="confirm-alias-merge"]').click()
    await expect(page.locator(SEL.toastContainer)).toContainText("别名已采用", { timeout: 10000 })

    await reloadWorkbench(page, "world", "review-relations")
    await page.locator(".review-group-card", { hasText: "直接采用关系" }).click()
    const relationDecision = page.locator(".world-relation-decision")
    await expect(relationDecision).toContainText("每组只需拖一次")
    await expect(page.locator(SEL.modalOverlay)).toHaveClass(/hidden/)
    await relationDecision.locator(`[data-person-id="${source.id}"]`).dragTo(relationDecision.locator('[data-relation-slot="source"]'))
    await expect(relationDecision.locator('[data-relation-slot="source"]')).toContainText(source.name)
    await expect(relationDecision.locator('[data-relation-slot="target"]')).toContainText(target.name)
    await relationDecision.locator('[data-action="confirm-relation-decision"]').click()
    await expect(page.locator(SEL.toastContainer)).toContainText("关系决策已保存", { timeout: 10000 })

    const aliases = await listAliases(testProjectId, { display_state: "active", limit: 100 })
    expect(aliases.items.some((item) => item.alias === "直接采用别名")).toBe(true)
    const relations = await listRelations(testProjectId, { status: "canonical", limit: 50 })
    expect(relations.items.some((item) => item.description === "直接采用关系")).toBe(true)
  })

  test("同类关系证据只拖一次人物卡并一次请求完成归并", async ({ page }) => {
    const source = await createEntity(testProjectId, { name: "关系归并源", entity_type: "character", status: "canonical" })
    const target = await createEntity(testProjectId, { name: "关系归并目标", entity_type: "character", status: "canonical" })
    await createRelation(testProjectId, {
      source_id: source.id,
      target_id: target.id,
      relation_type: "friend",
      description: "朋友证据一",
      strength: 0.8,
      quote: "他们以朋友相称。",
      status: "candidate",
      review_meta: {
        source: "deep_import",
        scene_index: 3,
        source_chapter_index: 2,
        evidence_refs: [{ scene_index: 3, quote: "他们以朋友相称。" }],
      },
    })
    await createRelation(testProjectId, {
      source_id: source.id,
      target_id: target.id,
      relation_type: "朋友",
      description: "朋友证据二",
      strength: 0.7,
      quote: "两人互相帮助。",
      status: "candidate",
      review_meta: {
        source: "deep_import",
        scene_index: 4,
        source_chapter_index: 3,
        evidence_refs: [{ scene_index: 4, quote: "两人互相帮助。" }],
      },
    })

    await reloadWorkbench(page, "world", "review-relations")
    const card = page.locator(".review-group-card").filter({ hasText: source.name })
    await expect(card).toContainText(target.name)
    await expect(card).toContainText("2 条候选")
    await expect(card).not.toContainText(source.id)
    await card.locator('[data-action="prepare-relation-review"]').click()
    const decision = page.locator(".world-relation-decision")
    await expect(decision.locator('[data-relation-slot="source"]')).toContainText("拖入人物")
    await decision.locator(`[data-person-id="${source.id}"]`).dragTo(decision.locator('[data-relation-slot="source"]'))
    await expect(decision.locator('[data-relation-slot="target"]')).toContainText(target.name)
    await expect(decision).toContainText("本次处理 2 条候选")
    let batchRequests = 0
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().includes("/api/world/relations/review-batch")) batchRequests += 1
    })
    await decision.locator('[data-action="confirm-relation-decision"]').click()
    await page.locator(SEL.modalFooter).getByRole("button", { name: "确认采用" }).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("关系决策已保存", { timeout: 10000 })
    expect(batchRequests).toBe(1)

    const canonical = await listRelations(testProjectId, { status: "canonical", limit: 50 })
    const deprecated = await listRelations(testProjectId, { status: "deprecated", limit: 50 })
    const merged = canonical.items.filter((item) => item.relation_type === "friend_of")
    expect(merged).toHaveLength(1)
    expect(merged[0].target_id).toBe(target.id)
    expect(merged[0].quote).toContain("他们以朋友相称。")
    expect(merged[0].quote).toContain("两人互相帮助。")
    expect(deprecated.items).toHaveLength(1)
  })

  test("别名自定义类型在 390px 工作台原样采用", async ({ page }) => {
    const entity = await createEntity(testProjectId, {
      name: "别名所属对象",
      entity_type: "character",
      status: "canonical",
    })
    await createAlias(testProjectId, {
      entity_id: entity.id,
      alias: "自定义别名",
      alias_type: "别称",
      status: "candidate",
      confidence: 0.96,
    })
    await page.setViewportSize({ width: 390, height: 844 })
    await reloadWorkbench(page, "world", "review-aliases")

    const row = page.locator(".review-member-row").filter({ hasText: "自定义别名" })
    await expect(row).toContainText("自定义")
    await expect(row).not.toContainText(entity.id)
    await row.locator('[data-action="prepare-alias-review"]').click()
    await expect(page.locator("#alias-inline-type")).toHaveValue("__custom_detail_type__")
    await expect(page.locator("#alias-inline-type-custom")).toHaveValue("别称")
    await expect(page.locator(".world-review-queue")).toBeHidden()
    const decisionBox = await page.locator(".world-review-decision").boundingBox()
    expect(decisionBox.x).toBeGreaterThanOrEqual(0)
    expect(Math.ceil(decisionBox.x + decisionBox.width)).toBeLessThanOrEqual(390)
    let batchRequests = 0
    page.on("request", (request) => {
      if (request.method() === "POST" && request.url().includes("/api/world/aliases/review-batch")) batchRequests += 1
    })
    await page.locator('[data-action="confirm-alias-merge"]').click()
    await expect(page.locator(SEL.toastContainer)).toContainText("别名已采用", { timeout: 10000 })
    expect(batchRequests).toBe(1)

    const aliases = await listAliases(testProjectId, { display_state: "active", limit: 100 })
    const adopted = aliases.items.find((item) => item.alias === "自定义别名")
    expect(adopted.alias_type).toBe("别称")
    expect(adopted.status).toBe("canonical")
  })

  test("390px 显式选择后聚焦决策区，返回时恢复队列焦点", async ({ page }) => {
    const entity = await createEntity(testProjectId, {
      name: "移动端焦点对象",
      entity_type: "character",
      status: "canonical",
    })
    await createAlias(testProjectId, {
      entity_id: entity.id,
      alias: "移动端焦点别名",
      alias_type: "name",
      status: "candidate",
    })

    await page.setViewportSize({ width: 390, height: 844 })
    await reloadWorkbench(page, "world", "review-aliases")
    const row = page.locator(".review-member-row", { hasText: "移动端焦点别名" })
    await row.click()

    const back = page.getByRole("button", { name: "返回队列", exact: true })
    await expect(back).toBeFocused()
    await expect(page.locator(".world-review-decision")).toBeVisible()
    await expect(page.locator(".world-review-queue")).toBeHidden()

    await back.click()
    await expect(row).toBeFocused()
    await expect(page.locator(".world-review-queue")).toBeVisible()
  })

  test("390px 关系决策可点选配对且没有横向溢出", async ({ page }) => {
    const source = await createEntity(testProjectId, { name: "窄屏关系源", entity_type: "character", status: "canonical" })
    const target = await createEntity(testProjectId, { name: "窄屏关系目标", entity_type: "character", status: "canonical" })
    await createRelation(testProjectId, { source_id: source.id, target_id: target.id, relation_type: "friend_of", description: "窄屏关系", strength: 0.7, status: "candidate" })

    await page.setViewportSize({ width: 390, height: 844 })
    await reloadWorkbench(page, "world", "review-relations")
    const card = page.locator(".review-group-card").filter({ hasText: "窄屏关系" })
    await card.locator('[data-action="prepare-relation-review"]').click()
    await expect(page.getByRole("button", { name: "返回队列", exact: true })).toBeFocused()

    const decision = page.locator(".world-relation-decision")
    await decision.locator(`[data-person-id="${target.id}"]`).click()
    await decision.locator('[data-relation-slot="target"]').click()
    await expect(decision.locator('[data-relation-slot="source"]')).toContainText(source.name)
    await expect(decision.locator('[data-relation-slot="target"]')).toContainText(target.name)
    const actionBox = await decision.locator('[data-action="confirm-relation-decision"]').boundingBox()
    expect(actionBox.height).toBeGreaterThanOrEqual(44)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  })

  test("同一对象对的不同关系事实各拖一次后依次采用", async ({ page }) => {
    const source = await createEntity(testProjectId, { name: "分别采用源", entity_type: "character", status: "canonical" })
    const target = await createEntity(testProjectId, { name: "分别采用目标", entity_type: "character", status: "canonical" })
    await createRelation(testProjectId, { source_id: source.id, target_id: target.id, relation_type: "friend_of", description: "曾是朋友", strength: 0.6, status: "candidate" })
    await createRelation(testProjectId, { source_id: source.id, target_id: target.id, relation_type: "enemy_of", description: "后来为敌", strength: 0.9, status: "candidate" })

    await reloadWorkbench(page, "world", "review-relations")
    const adoptedTypes = []
    for (let index = 0; index < 2; index += 1) {
      const card = page.locator(".review-group-card").filter({ hasText: source.name })
      await card.locator('[data-action="prepare-relation-review"]').click()
      const decision = page.locator(".world-relation-decision")
      adoptedTypes.push(await decision.locator("#relation-inline-type").inputValue())
      await decision.locator(`[data-person-id="${source.id}"]`).dragTo(decision.locator('[data-relation-slot="source"]'))
      await decision.locator('[data-action="confirm-relation-decision"]').click()
      await expect(page.locator(SEL.toastContainer)).toContainText("关系决策已保存", { timeout: 10000 })
      if (index === 0) await reloadWorkbench(page, "world", "review-relations")
    }
    expect(adoptedTypes.sort()).toEqual(["enemy_of", "friend_of"])

    const canonical = await listRelations(testProjectId, { status: "canonical", limit: 50 })
    const adopted = canonical.items.filter((item) => item.source_id === source.id && item.target_id === target.id)
    expect(adopted.map((item) => item.relation_type).sort()).toEqual(["enemy_of", "friend_of"])
  })
})
