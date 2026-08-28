import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { createDraft, createEntity, createScene, seedEntityArchive, waitForBackend } from "./helpers/api-client.js"
import { openWorkbench } from "./helpers/workbench.js"

test.describe("世界对象与大纲 chaos", () => {
  let project = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page, projectFactory }) => {
    project = await projectFactory({ title: "世界与大纲 chaos 项目", genre: "fantasy", language: "zh" })
    await openWorkbench(page, project, "outline", "scenes")
  })

  test("S5-DNG-001 取消实体合并确认和回滚表单不会改变对象", async ({ page }) => {
    const target = await createEntity(project.id, {
      name: "实体合并目标",
      entity_type: "location",
      status: "canonical",
      summary: "目标实体保持正史",
    })
    const candidate = await createEntity(project.id, {
      name: "待合并候选实体",
      entity_type: "location",
      status: "candidate",
      summary: "候选实体保持待处理",
      content_json: {
        _meta: {
          suggested_action: "merge_with_existing",
          suggested_existing_entity_name: target.name,
        },
      },
    })
    const entity = await createEntity(project.id, {
      name: "待取消回滚实体",
      entity_type: "item",
      status: "canonical",
      summary: "当前摘要不应变化",
    })
    await seedEntityArchive(project.id, entity.id, "归档摘要", { sceneIndex: 5 })

    await openWorkbench(page, project, "world", "candidates")
    const mutationRequests = []
    const onRequest = (request) => {
      const url = new URL(request.url())
      if (
        (request.method() === "POST" && url.pathname.endsWith(`/api/world/entities/${candidate.id}/merge`))
        || (request.method() === "POST" && url.pathname.endsWith("/api/world/entities/fusion-suggestions/apply"))
        || (request.method() === "POST" && url.pathname.endsWith(`/api/world/entities/${entity.id}/rollback`))
      ) mutationRequests.push(`${request.method()} ${url.pathname}`)
    }
    page.on("request", onRequest)
    try {
      const candidateRow = page.locator(`tr[data-id="${candidate.id}"]`)
      await expect(candidateRow).toContainText(candidate.name)
      await candidateRow.getByRole("button", { name: "查看并决定" }).click()
      await page.locator(".world-review-decision").getByRole("button", { name: "合并到" }).click()
      await expect(page.locator(SEL.modalTitle)).toHaveText("合并对象")
      const picker = page.locator("#merge-target-picker")
      await picker.locator("[data-reference-query]").fill(target.name)
      await picker.locator("[data-reference-result]", { hasText: target.name }).click()
      await expect(page.locator("#merge-target-id")).toHaveValue(target.id)
      await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
      await expect(page.locator(SEL.modalTitle)).toHaveText("确认操作")
      await page.getByRole("button", { name: "取消", exact: true }).click()

      await expect(candidateRow).toContainText(candidate.name)
      await expect(page.locator(".data-table tbody tr")).toHaveCount(1)

      await openWorkbench(page, project, "world", "objects")
      await expect(page.locator(SEL.viewTitle)).toHaveText("人物与世界")
      const targetRow = page.locator(`.world-object-table tr[data-id="${target.id}"]`)
      await expect(targetRow).toContainText(target.name)
      await expect(targetRow).toContainText("目标实体保持正史")
      const entityRow = page.locator(`.world-object-table tr[data-id="${entity.id}"]`)
      await expect(entityRow).toContainText("当前摘要不应变化")
      await entityRow.locator(".action-menu-btn").click()
      await entityRow.locator('[data-action="rollback-entity"]').click()
      await expect(page.locator(SEL.modalTitle)).toHaveText("回滚对象")
      await page.locator("#rollback-scene-index").fill("5")
      await page.getByRole("button", { name: "取消", exact: true }).click()

      await expect(entityRow).toContainText("当前摘要不应变化")
      await expect(page.locator(".view-header__count")).toHaveText("共 2 个")
      expect(mutationRequests).toEqual([])
    } finally {
      page.off("request", onRequest)
    }
  })

  test("S6-STA-002 移入历史后写作台不会复活失效 Scene", async ({ page }) => {
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "将归档的当前 Scene",
      goal: "不应留在写作台",
      status: "canonical",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 4 }],
    })
    await createDraft(project.id, 1, "第 1 章", "第一章正文")

    await openWorkbench(page, project, "writing")
    await expect(page.getByRole("button", { name: /^打开第 1 章/ })).toBeVisible()
    await page.getByRole("button", { name: /^打开第 1 章/ }).click()
    await expect(page.locator(".scene-cockpit-switcher__item.active")).toContainText(scene.title)
    await expect(page.locator("#writing-panel-container")).toContainText(scene.title)

    const writingSessionMarker = await page.evaluate(() => {
      window.__phase53WritingSessionMarker = `marker-${Date.now()}`
      return window.__phase53WritingSessionMarker
    })
    await page.getByRole("button", { name: "整理", exact: true }).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("故事结构")
    expect(await page.evaluate(() => window.__phase53WritingSessionMarker)).toBe(writingSessionMarker)

    const row = page.locator(`.scene-workbench-row[data-id="${scene.id}"]`)
    await expect(row).toBeVisible()
    await row.locator('[data-action="select-workbench-scene"]').click()
    await expect(page).toHaveURL(new RegExp(`scene_id=${scene.id}`))
    await row.locator(".action-menu-btn").click()
    await row.locator('[data-action="move-scene-to-history"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("确认操作")
    await page.getByRole("button", { name: "确认移入历史" }).click()
    await expect(page.locator(`.scene-workbench-row[data-id="${scene.id}"]`)).toHaveCount(0)
    await expect(page).not.toHaveURL(new RegExp(`scene_id=${scene.id}`))

    const navigationMarker = await page.evaluate(() => {
      window.__phase53NavigationMarker = `marker-${Date.now()}`
      return window.__phase53NavigationMarker
    })
    await page.locator(SEL.navItem("today")).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作")
    expect(await page.evaluate(() => window.__phase53NavigationMarker)).toBe(navigationMarker)
    await page.getByRole("button", { name: "继续写作" }).click()
    await expect(page.locator("#writing-panel-container")).not.toContainText(scene.title)
    await expect(page.locator(".scene-cockpit-switcher__item", { hasText: scene.title })).toHaveCount(0)
  })

  test("S6-IDM-001 覆盖确认取消后不会强制重试或启动 worker", async ({ page }) => {
    const existing = await createScene(project.id, {
      scene_index: 0,
      title: "既有 Scene 保持不变",
      goal: "不可被静默覆盖",
      status: "canonical",
      chapter_ids: ["1"],
    })
    const submissions = []
    await page.route("**/api/imports/stages/scenes", async (route) => {
      submissions.push(route.request().postDataJSON())
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ requires_confirmation: true, warning: "已有 Scene，确认覆盖才会继续。" }),
      })
    })

    await page.reload()
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })
    await page.locator(".scene-workbench-tools summary").click()
    await page.locator('[data-action="scene-auto-extract"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("从正文整理场景")
    await page.locator("#scene-auto-extract-start").fill("1")
    await page.locator("#scene-auto-extract-end").fill("1")
    await page.getByRole("button", { name: "确认并开始整理" }).click()

    await expect(page.locator(SEL.modalTitle)).toHaveText("确认操作")
    await expect(page.locator(SEL.modalBody)).toContainText("已有场景，确认覆盖才会继续")
    await page.getByRole("button", { name: "取消", exact: true }).click()

    expect(submissions).toHaveLength(1)
    expect(submissions[0]).toMatchObject({ novel_id: project.id, start_chapter: 1, end_chapter: 1, force: false })
    await expect(page.locator(`.scene-workbench-row[data-id="${existing.id}"]`)).toBeVisible()
    await expect(page.locator(".scene-workbench-row")).toHaveCount(1)
    await expect(page.locator('[data-role="scene-auto-extract-progress"]')).toHaveCount(0)
  })
})
