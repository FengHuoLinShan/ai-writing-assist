import { test, expect } from "@playwright/test"
import { openWorkbench } from "./helpers/workbench.js"
import { expectNoPageOverflow, expectWithinViewport } from "./helpers/responsive.js"
import {
  cleanupProject,
  createDraft,
  createProject,
  createScene,
  listScenes,
  listScenesOrdered,
  waitForBackend,
} from "./helpers/api-client.js"

test.describe("Scene 工作台", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("从写作页整理按钮进入场景工作台并定位当前 Scene", async ({ page }) => {
    const project = await createProject({ title: "Scene 工作台跳转", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "写作联动 Scene",
      goal: "进入宫门",
      core_conflict: "守卫阻拦",
      must_happen: "交出令牌",
      must_not_happen: "身份暴露",
      chapter_ids: ["1"],
    })
    await createDraft(project.id, 1, "第一章", "正文")

    await openWorkbench(page, project, "writing")
    await page.locator('[data-action="open-scene-workbench"]').click()

    await expect(page.locator("#view-title")).toHaveText("场景")
    await expect(page.locator(`.scene-workbench-row[data-id="${scene.id}"]`)).toHaveClass(/is-selected/)
  })

  test("未归类章节可以分配到 Scene", async ({ page }) => {
    const project = await createProject({ title: "Scene 分配", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "目标 Scene",
      goal: "整理章节",
      core_conflict: "结构混乱",
      must_happen: "章节归位",
      must_not_happen: "误删正文",
      chapter_ids: ["1"],
    })
    await createDraft(project.id, 1, "第一章", "正文")
    await createDraft(project.id, 3, "第三章", "未归类正文")

    await openWorkbench(page, project, "scene")
    await expect(page.locator(".scene-workbench-row--unassigned")).toContainText("第 3 章")
    page.once("dialog", (dialog) => dialog.accept(scene.id))
    await page.locator('[data-action="assign-unassigned-chapter"]').click()

    await expect(page.locator(".scene-workbench-row--unassigned")).toHaveCount(0, { timeout: 10000 })
    const scenes = await listScenesOrdered(project.id)
    expect(scenes[0].chapter_ids).toEqual(["1", "3"])
  })

  test("拆分必须先展示影响预览，确认后才执行", async ({ page }) => {
    const project = await createProject({ title: "Scene 拆分", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "长 Scene",
      goal: "潜入",
      core_conflict: "守卫阻拦",
      must_happen: "拿到文书",
      must_not_happen: "身份暴露",
      chapter_ids: ["1", "2"],
    })

    await openWorkbench(page, project, "scene", scene.id)
    page.once("dialog", (dialog) => dialog.accept("2"))
    await page.locator('[data-action="start-split-scene"]').click()

    await expect(page.locator("#modal-title")).toHaveText("Scene AI 草稿审稿")
    let scenes = await listScenesOrdered(project.id)
    expect(scenes).toHaveLength(1)

    await page.getByRole("button", { name: "确认拆分" }).click()
    await expect(page.locator("#toast-container")).toContainText("Scene 已拆分", { timeout: 10000 })
    scenes = await listScenesOrdered(project.id)
    expect(scenes).toHaveLength(2)
    expect(scenes[0].chapter_ids).toEqual(["1"])
    expect(scenes[1].chapter_ids).toEqual(["2"])
  })

  test("编辑 Scene 字段后写作页驾驶舱刷新", async ({ page }) => {
    const project = await createProject({ title: "Scene 编辑联动", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "旧标题",
      goal: "旧目标",
      core_conflict: "冲突",
      must_happen: "必须",
      must_not_happen: "禁止",
      chapter_ids: ["1"],
    })
    await createDraft(project.id, 1, "第一章", "正文")

    await openWorkbench(page, project, "scene", scene.id)
    await page.locator("#scene-detail-title").fill("新标题")
    await page.locator("#scene-detail-goal").fill("新目标")
    await page.locator('[data-action="save-scene-detail"]').click()
    await expect(page.locator("#toast-container")).toContainText("Scene 已保存", { timeout: 10000 })
    await page.locator(".scene-workbench-row.is-selected .action-menu-btn").click()
    await page.locator(".scene-workbench-row.is-selected [data-action=\"open-writing-scene\"]").click()

    await expect(page.locator("#view-title")).toHaveText("写作台")
    await expect(page.locator("#writing-panel-container")).toContainText("新标题")
    await expect(page.locator("#writing-panel-container")).toContainText("新目标")
  })

  test("手动融合可保存新 Scene 并废弃原 Scene", async ({ page }) => {
    const project = await createProject({ title: "Scene 手动融合", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const first = await createScene(project.id, {
      scene_index: 0,
      title: "调查旧港",
      goal: "找到线索",
      core_conflict: "守卫阻拦",
      must_happen: "发现暗号",
      must_not_happen: "暴露身份",
      chapter_ids: ["1"],
    })
    const second = await createScene(project.id, {
      scene_index: 1,
      title: "潜入仓库",
      goal: "确认走私路线",
      core_conflict: "巡逻靠近",
      must_happen: "拿到账册",
      must_not_happen: "惊动敌人",
      chapter_ids: ["2"],
    })

    await openWorkbench(page, project, "scene")
    await page.locator(`.scene-workbench-row[data-id="${first.id}"] input[data-action="toggle-fusion-selection"]`).check()
    await page.locator(`.scene-workbench-row[data-id="${second.id}"] input[data-action="toggle-fusion-selection"]`).check()
    await page.locator('[data-action="start-ai-fusion-draft"]').click()
    await expect(page.locator("#modal-title")).toHaveText("选择主 Scene")
    await page.evaluate(() => {
      const button = Array.from(document.querySelectorAll("#modal-footer button"))
        .find((item) => item.textContent?.includes("生成 AI 融合草稿"))
      button?.click()
    })

    await expect(page.locator("#modal-title")).toHaveText("Scene AI 草稿审稿")
    await expect(page.locator("#modal-body")).toContainText("找到线索")
    await expect(page.locator("#modal-body")).toContainText("确认走私路线")
    const footerLayout = await page.evaluate(() => {
      const footer = document.querySelector("#modal-footer")
      const content = document.querySelector("#modal-content")
      const footerRect = footer?.getBoundingClientRect()
      const contentRect = content?.getBoundingClientRect()
      const buttons = Array.from(document.querySelectorAll("#modal-footer button"))
        .map((button) => {
          const rect = button.getBoundingClientRect()
          return {
            text: button.textContent || "",
            left: rect.left,
            right: rect.right,
          }
        })
      return {
        footerWrap: footer ? getComputedStyle(footer).flexWrap : "",
        buttonsWithinContent: Boolean(contentRect) && buttons.every((button) => (
          button.left >= contentRect.left - 1 && button.right <= contentRect.right + 1
        )),
      }
    })
    expect(footerLayout.footerWrap).toBe("wrap")
    expect(footerLayout.buttonsWithinContent).toBe(true)
    await page.locator("#scene-fusion-title").fill("旧港与仓库调查")
    await page.evaluate(() => {
      const button = Array.from(document.querySelectorAll("#modal-footer button"))
        .find((item) => item.textContent?.includes("保存融合 Scene，并废弃原 Scene"))
      button?.click()
    })
    await expect(page.locator("#toast-container")).toContainText("融合 Scene 已保存", { timeout: 10000 })

    const deprecatedScenes = await listScenes(project.id, { status: "deprecated" })
    const deprecatedIds = new Set((deprecatedScenes.items || deprecatedScenes).map((scene) => scene.id))
    expect(deprecatedIds.has(first.id)).toBe(true)
    expect(deprecatedIds.has(second.id)).toBe(true)

    const scenes = await listScenesOrdered(project.id)
    const fused = scenes.find((scene) => scene.id !== first.id && scene.id !== second.id)
    expect(fused?.source).toBe("manual_fusion")
  })

  test("手动融合可放弃后继续编辑结果再保存", async ({ page }) => {
    const project = await createProject({ title: "Scene 融合编辑保存", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const first = await createScene(project.id, {
      scene_index: 0,
      title: "追踪线索",
      goal: "锁定嫌疑人",
      core_conflict: "线索被销毁",
      chapter_ids: ["1"],
    })
    const second = await createScene(project.id, {
      scene_index: 1,
      title: "夜审证人",
      goal: "获得证词",
      core_conflict: "证人恐惧",
      chapter_ids: ["2"],
    })

    const selectScenes = async () => {
      await page.locator(`.scene-workbench-row[data-id="${first.id}"] input[data-action="toggle-fusion-selection"]`).check()
      await page.locator(`.scene-workbench-row[data-id="${second.id}"] input[data-action="toggle-fusion-selection"]`).check()
      await page.locator('[data-action="start-ai-fusion-draft"]').click()
      await expect(page.locator("#modal-title")).toHaveText("选择主 Scene")
      await page.evaluate(() => {
        const button = Array.from(document.querySelectorAll("#modal-footer button"))
          .find((item) => item.textContent?.includes("生成 AI 融合草稿"))
        button?.click()
      })
      await expect(page.locator("#modal-title")).toHaveText("Scene AI 草稿审稿")
    }
    const clickFusionButton = async (text) => {
      await page.evaluate((label) => {
        const button = Array.from(document.querySelectorAll("#modal-footer button"))
          .find((item) => item.textContent?.includes(label))
        button?.click()
      }, text)
    }

    await openWorkbench(page, project, "scene")
    await selectScenes()
    await clickFusionButton("放弃融合结果")
    await expect(page.locator("#toast-container")).toContainText("融合结果已放弃", { timeout: 10000 })
    let scenes = await listScenesOrdered(project.id)
    expect(scenes).toHaveLength(2)

    await openWorkbench(page, project, "scene")
    await selectScenes()
    await page.locator("#scene-fusion-title").fill("线索与证词合流")
    await page.locator("#scene-fusion-goal").fill("锁定真正嫌疑人")
    await clickFusionButton("继续编辑融合结果后再保存")
    await expect(page.locator("#toast-container")).toContainText("融合 Scene 已保存", { timeout: 10000 })

    scenes = await listScenesOrdered(project.id)
    expect(scenes.some((scene) => scene.title === "线索与证词合流" && scene.goal === "锁定真正嫌疑人")).toBe(true)
    const sourceScenes = scenes.filter((scene) => scene.id === first.id || scene.id === second.id)
    expect(sourceScenes.every((scene) => scene.status === "draft")).toBe(true)
  })

  test("多选 Scene 不会重绘页面或把列表滚回顶部", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 620 })
    const project = await createProject({ title: "Scene 多选滚动保持", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scenes = await Promise.all(Array.from({ length: 18 }, (_, index) => createScene(project.id, {
      scene_index: index,
      title: `滚动 Scene ${index}`,
      goal: `目标 ${index}`,
      core_conflict: `冲突 ${index}`,
      chapter_ids: [String(index + 1)],
    })))

    await openWorkbench(page, project, "scene")
    const organize = page.locator(".scene-workbench__organize")
    await organize.evaluate((el) => { el.scrollTop = el.scrollHeight })
    const before = await organize.evaluate((el) => el.scrollTop)
    expect(before).toBeGreaterThan(50)

    await page.locator(`.scene-workbench-row[data-id="${scenes.at(-1).id}"] input[data-action="toggle-fusion-selection"]`).check()

    const after = await organize.evaluate((el) => el.scrollTop)
    expect(after).toBeGreaterThan(50)
    await expect(page.locator(".scene-fusion-toolbar")).toContainText("1")
  })

  test("Scene 翻页按钮在列表底部悬浮", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 620 })
    const project = await createProject({ title: "Scene 分页底部悬浮", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    await Promise.all(Array.from({ length: 22 }, (_, index) => createScene(project.id, {
      scene_index: index,
      title: `分页 Scene ${index}`,
      goal: `目标 ${index}`,
      core_conflict: `冲突 ${index}`,
      chapter_ids: [String(index + 1)],
    })))

    await openWorkbench(page, project, "scene")
    const pagination = page.locator(".scene-workbench-pagination")
    await expect(pagination).toBeVisible()
    await expect(pagination).toContainText("第 1 / 2 页")

    const stickyState = await page.evaluate(() => {
      const list = document.querySelector(".scene-workbench__organize")
      const pager = document.querySelector(".scene-workbench-pagination")
      const listRect = list?.getBoundingClientRect()
      const pagerRect = pager?.getBoundingClientRect()
      const style = pager ? getComputedStyle(pager) : null
      return {
        position: style?.position || "",
        bottom: style?.bottom || "",
        nearBottom: Boolean(listRect && pagerRect) && Math.abs(pagerRect.bottom - listRect.bottom) < 4,
      }
    })
    expect(stickyState).toEqual({
      position: "sticky",
      bottom: "0px",
      nearBottom: true,
    })
  })

  test("窄屏下详情进入抽屉，列表仍是主操作面", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 760 })
    const project = await createProject({ title: "Scene 移动端", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    await createScene(project.id, {
      scene_index: 0,
      title: "移动端 Scene",
      goal: "目标",
      core_conflict: "冲突",
      must_happen: "必须",
      must_not_happen: "禁止",
      chapter_ids: ["1"],
    })

    await openWorkbench(page, project, "scene")

    await expect(page.locator(".scene-workbench__organize")).toBeVisible()
    await expectNoPageOverflow(page)
    await expectWithinViewport(page.locator(".scene-workbench-drawer"))
    await expectWithinViewport(page.locator('[data-action="close-scene-detail"]'))
  })
})
