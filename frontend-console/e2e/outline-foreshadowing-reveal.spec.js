import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { expectNoPageOverflow } from "./helpers/responsive.js"
import { openWorkbench, reloadWorkbench } from "./helpers/workbench.js"
import {
  cleanupProject,
  createEntity,
  createForeshadowing,
  createProject,
  createReveal,
  createThread,
  waitForBackend,
} from "./helpers/api-client.js"

test.describe("Outline View — 剧情线信息推进", () => {
  let project = null
  let otherProject = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    project = await createProject({
      title: "剧情线信息推进 E2E",
      genre: "fantasy",
      language: "zh",
    })
    await openWorkbench(page, project, "outline", "threads")
  })

  test.afterEach(async () => {
    if (otherProject?.id) {
      try { await cleanupProject(otherProject.id) } catch {}
      otherProject = null
    }
    if (project?.id) {
      try { await cleanupProject(project.id) } catch {}
      project = null
    }
  })

  for (const legacySubview of ["foreshadowing", "reveals"]) {
    test(`旧 ${legacySubview} 路由重定向到剧情线信息推进区域`, async ({ page }) => {
      await openWorkbench(page, project, "outline", legacySubview)

      await expect(page.locator('[data-action="nav-threads"]')).toHaveClass(/active/)
      const information = page.locator("#outline-thread-information")
      await expect(information).toContainText("信息推进")
      await expect(information).toHaveClass(/is-deep-linked/)
      await expect(information).toBeFocused()
      await expect(page).toHaveURL(new RegExp(`/outline/threads\\?information=${legacySubview}$`))
      await expect(page.locator('[data-action="nav-foreshadowing"]')).toHaveCount(0)
      await expect(page.locator('[data-action="nav-reveals"]')).toHaveCount(0)
    })
  }

  test("同一 movement 合并展示伏笔与揭示，并可分配未归类计划", async ({ page, browserErrors }) => {
    otherProject = await createProject({
      title: "信息推进隔离作品",
      genre: "fantasy",
      language: "zh",
    })
    const thread = await createThread(project.id, {
      name: "潮门调查",
      thread_type: "main",
      summary: "主角追查潮门背后的筛选机制。",
    })
    const entity = await createEntity(project.id, {
      name: "潮门",
      entity_type: "item",
      status: "canonical",
    })
    await createForeshadowing(project.id, {
      name: "潮门发光",
      summary: "潮门只在特定人靠近时发光。",
      planned_seed_chapter: 3,
      related_thread_ids: [thread.id],
      provenance_meta: { information_movement_id: "movement-tide-gate" },
    })
    await createReveal(project.id, {
      target_type: "world_entity",
      target_id: entity.id,
      secret_summary: "潮门正在筛选继承者。",
      reveal_stages: [{
        stage_index: 0,
        chapter_index: 5,
        reveal_content: "主角发现潮门会记录来访者。",
      }],
      related_thread_ids: [thread.id],
      provenance_meta: { information_movement_id: "movement-tide-gate" },
    })
    await createForeshadowing(project.id, {
      name: "无主铃声",
      summary: "无人触碰时铜铃自行鸣响。",
      planned_seed_chapter: 4,
      related_thread_ids: [],
    })

    await reloadWorkbench(page, "outline", "threads")

    const information = page.locator("#outline-thread-information")
    const threadProgress = information.locator(`details[data-thread-id="${thread.id}"]`)
    await expect(threadProgress).toHaveAttribute("open", "")
    await expect(threadProgress.locator(".outline-information-movement")).toHaveCount(1)
    await expect(information).toContainText("潮门只在特定人靠近时发光")
    await expect(information).toContainText("潮门正在筛选继承者")
    await expect(information).toContainText("未归入剧情线（1）")

    await openWorkbench(page, project, "outline", "reveals")
    const linkedProgress = page.locator(`#outline-thread-information details[data-thread-id="${thread.id}"]`)
    await expect(linkedProgress).toHaveAttribute("open", "")
    await expect(linkedProgress).toHaveClass(/is-deep-linked/)
    await expect(linkedProgress.locator("summary")).toBeFocused()
    await page.keyboard.press("Space")
    await expect(linkedProgress).not.toHaveAttribute("open", "")
    await page.keyboard.press("Space")
    await expect(linkedProgress).toHaveAttribute("open", "")

    await page.locator('[data-action="nav-arcs"]').click()
    await expect(page).toHaveURL(/\/outline\/arcs/)
    await page.goBack()
    await expect(linkedProgress.locator("summary")).toBeFocused()
    await page.goForward()
    await expect(page).toHaveURL(/\/outline\/arcs/)
    await page.goBack()
    await page.reload()
    await expect(linkedProgress.locator("summary")).toBeFocused()

    await page.setViewportSize({ width: 390, height: 844 })
    await expectNoPageOverflow(page)
    await expect(linkedProgress.locator("summary")).toBeVisible()

    const unassigned = page.locator("#outline-thread-information .outline-information-unassigned", {
      hasText: "无主铃声",
    })
    await unassigned.locator('[data-role="information-thread-assignment"]').selectOption(thread.id)
    await expect(page.locator(SEL.toastContainer)).toContainText("信息推进计划已归入剧情线")
    await expect(page.locator("#outline-thread-information")).toContainText("未归入剧情线（0）")
    await expect(page.locator("#outline-thread-information")).toContainText("无人触碰时铜铃自行鸣响")

    await page.setViewportSize({ width: 1440, height: 900 })
    await page.locator(".sidebar-project-switcher").click()
    await page.locator(SEL.projectCard(otherProject.id)).click()
    await expect(page.locator(SEL.topbarProject)).toHaveText("信息推进隔离作品")
    await page.evaluate(() => window.router.navigate("outline", "threads"))
    await expect(page.locator("#outline-thread-information")).toContainText("创建剧情线后可设计信息推进")
    await expect(page.locator("#outline-thread-information")).not.toContainText("潮门调查")

    await page.locator(".sidebar-project-switcher").click()
    await page.locator(SEL.projectCard(project.id)).click()
    await expect(page.locator(SEL.topbarProject)).toHaveText("剧情线信息推进 E2E")
    await page.evaluate(() => window.router.navigate("outline", "reveals"))
    await expect(page.locator(`#outline-thread-information details[data-thread-id="${thread.id}"] summary`)).toBeFocused()
    expect(browserErrors).toEqual([])
  })
})
