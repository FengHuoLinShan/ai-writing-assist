import { test, expect } from "./fixtures.js"
import {
  createEntity,
  createRelation,
  waitForBackend,
} from "./helpers/api-client.js"

/**
 * 世界库关系分组视角 — 浏览、维护与恢复的浏览器验收。
 *
 * 数据经真实 API 建立（faction + characters + member_of 关系），UI 走
 * Vue 世界库目录的视角入口；断言组列表/成员页、添加/移出确认、URL 恢复
 * 与窄屏可用性。项目由 fixtures 自动清理。
 */

async function seedAffiliationProject(projectId) {
  const group = await createEntity(projectId, {
    name: "晨曦商会",
    entity_type: "faction",
    status: "canonical",
  })
  const memberA = await createEntity(projectId, {
    name: "沈砚",
    entity_type: "character",
    status: "canonical",
  })
  const memberB = await createEntity(projectId, {
    name: "顾青芜",
    entity_type: "character",
    status: "canonical",
  })
  await createEntity(projectId, {
    name: "孤岛渔村",
    entity_type: "location",
    status: "canonical",
  })
  const existing = await createRelation(projectId, {
    source_id: memberA.id,
    target_id: group.id,
    relation_type: "member_of",
    relation_kind: "social",
    description: "商会账房",
    status: "canonical",
  })
  return { group, memberA, memberB, existing }
}

test.describe("世界库 — 关系分组视角", () => {
  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test("按势力浏览成员、添加、返回恢复与移出", async ({ page, projectFactory, openProjectWorkbench }) => {
    const project = await projectFactory({ title: "关系分组验收" })
    const { group, memberA, memberB, existing } = await seedAffiliationProject(project.id)
    await openProjectWorkbench(project, "world", "bible")

    // 资料库首页提供视角入口；进入势力成员视角。
    await page.locator('[data-action="world-home-select-relation-view"][data-relation-view="affiliation"]').first().click()
    await expect(page.locator("[data-relation-view='groups']")).toBeVisible()

    // 组列表显示组名与完整成员数（去重对象数）。
    await expect(page.locator("[data-relation-groups-count]")).toContainText("1 个分组")
    await expect(page.locator("[data-relation-view='groups']")).toContainText("晨曦商会")
    await expect(page.locator("[data-relation-view='groups']")).toContainText("1")

    // 打开组：成员页显示去重成员与关系标签。
    await page.locator("[data-relation-view='groups']").getByText("晨曦商会").first().click()
    await expect(page.locator("[data-relation-view='members']")).toBeVisible()
    await expect(page.locator("[data-relation-view='members']")).toContainText("沈砚")
    // 该成员的匹配关系以可编辑标签展示（relation_refs 装配生效）。
    await expect(page.locator("[data-action='relation-member-edit-relation'][data-relation-id='" + existing.id + "']")).toBeVisible()

    // 打开成员详情后返回：视角、组与结果恢复。
    await page.locator("[data-relation-view='members']")
      .locator("[data-action='open-world-card']", { hasText: "沈砚" }).first().click()
    await page.waitForTimeout(300)
    await page.goBack()
    await expect(page.locator("[data-relation-view='members']")).toBeVisible()
    await expect(page.locator("[data-relation-view='members']")).toContainText("沈砚")

    // 未关联入口：顾青芜尚未加入任何势力。
    await page.locator("[data-action='relation-members-back']").click()
    await expect(page.locator("[data-relation-view='groups']")).toBeVisible()
    await page.locator("[data-relation-view='groups'] .world-relation-groups__main[data-action='relation-group-open-unlinked']").click()
    await expect(page.locator("[data-relation-view='members']")).toContainText("顾青芜")

    // 多选添加到分组（未关联页需先选择目标组）。
    await page.locator("[data-action='relation-member-toggle'][data-id='" + memberB.id + "']").check()
    await expect(page.locator("[data-relation-selected-count]")).toHaveText("1")
    await page.locator("[data-action='relation-members-add']").click()
    const addDialog = page.getByRole("dialog", { name: "添加到分组" })
    await expect(addDialog).toBeVisible()
    await expect(addDialog.locator("[data-field='add-target-group']")).toBeVisible()
    // 组选项异步加载，等待目标组可选。
    await expect(addDialog.locator("[data-field='add-target-group'] option")).toHaveCount(1, { timeout: 15000 })
    await addDialog.locator("[data-field='add-target-group']").selectOption(group.id)
    await page.locator("[data-action='relation-add-confirm']").click()
    await expect(page.getByRole("dialog", { name: "添加到分组" })).toBeHidden({ timeout: 15000 })
    // 添加成功后未关联列表不再包含该成员。
    await expect(page.locator("[data-relation-members-count]")).toContainText("0 名成员", { timeout: 15000 })
    await expect(page.locator("[data-relation-view='members']")).not.toContainText("顾青芜")

    // 组内现在包含两位成员。
    await page.locator("[data-action='relation-members-back']").click()
    await page.locator("[data-relation-view='groups']").getByText("晨曦商会").first().click()
    await expect(page.locator("[data-relation-view='members']")).toContainText("顾青芜")
    await expect(page.locator("[data-relation-members-count]")).toContainText("2")

    // 移出：勾选成员 → 确认清单 → 提交；历史保留（API 层断言）。
    await page.locator("[data-action='relation-member-toggle'][data-id='" + memberA.id + "']").check()
    await page.locator("[data-action='relation-members-remove']").click()
    const removeDialog = page.locator("[data-relation-remove-dialog]")
    await expect(removeDialog).toBeVisible()
    await expect(removeDialog).toContainText("沈砚")
    await expect(removeDialog).toContainText("成员")
    await page.locator("[data-action='relation-remove-confirm']").click()
    await expect(page.locator("[data-relation-remove-dialog]")).toBeHidden({ timeout: 15000 })

    const afterRemove = await page.evaluate(async ({ projectId, relationId }) => {
      const response = await fetch(`/api/world/relations?novel_id=${projectId}&status=deprecated&limit=50`, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      const data = await response.json()
      return (data.items || []).some((relation) => relation.id === relationId)
    }, { projectId: project.id, relationId: existing.id })
    expect(afterRemove).toBe(true)
  })

  test("custom 视角随 URL 刷新恢复；390px 窄屏可用", async ({ page, projectFactory, openProjectWorkbench }) => {
    const project = await projectFactory({ title: "自定义视角验收" })
    const group = await createEntity(project.id, { name: "藏经阁", entity_type: "location", status: "canonical" })
    const item = await createEntity(project.id, { name: "断剑残卷", entity_type: "item", status: "canonical" })
    await createRelation(project.id, {
      source_id: item.id,
      target_id: group.id,
      relation_type: "guarded_by",
      relation_kind: "intentional",
      status: "canonical",
    })

    await page.setViewportSize({ width: 390, height: 844 })
    await openProjectWorkbench(project, "world", "bible")
    await page.evaluate(({ projectId, groupId }) => {
      location.hash = `#workbench/${projectId}/world/bible?group_view=custom&group_type=location&member_type=item&relation_type=guarded_by&group_side=target&group_id=${groupId}`
    }, { projectId: project.id, groupId: group.id })
    await page.reload()
    await expect(page.locator("[data-relation-view='members']")).toBeVisible()
    await expect(page.locator("[data-relation-view='members']")).toContainText("断剑残卷")
    // 窄屏下主要操作仍可操作（按钮存在且可见）。
    await expect(page.locator("[data-action='relation-members-add']")).toBeVisible()
  })
})


test("事件参与视角：participates_in 默认添加与参与关系浏览", async ({ page, projectFactory, openProjectWorkbench }) => {
  const project = await projectFactory({ title: "事件视角验收" })
  const event = await createEntity(project.id, { name: "风暴之夜", entity_type: "event", status: "canonical" })
  const witness = await createEntity(project.id, { name: "风暴目击者", entity_type: "character", status: "canonical" })
  await createRelation(project.id, {
    source_id: witness.id,
    target_id: event.id,
    relation_type: "participates_in",
    relation_kind: "state",
    status: "canonical",
  })
  await openProjectWorkbench(project, "world", "bible")
  await page.locator('[data-action="world-home-select-relation-view"][data-relation-view="event"]').first().click()
  await expect(page.locator("[data-relation-view='groups']")).toContainText("风暴之夜")

  await page.locator("[data-relation-view='groups']").getByText("风暴之夜").first().click()
  await expect(page.locator("[data-relation-view='members']")).toContainText("风暴目击者")
  await expect(page.locator("[data-relation-view='members']")).toContainText("参与")
})
