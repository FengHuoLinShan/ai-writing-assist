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
    await page.locator('[data-action="select-chapter"][data-chapter="1"]').click()
    await page.locator('[data-action="open-scene-workbench"]').click()

    await expect(page.locator("#topbar-module")).toHaveText("大纲")
    await expect(page).toHaveURL(new RegExp(`scene_id=${scene.id}`))
    await expect(page.locator(`.scene-workbench-row[data-id="${scene.id}"]`)).toHaveClass(/is-selected/)
  })

  test("自动提取与智能去重和子标签同行且不重复", async ({ page }) => {
    const project = await createProject({ title: "Scene 顶部操作布局", genre: "fantasy", language: "zh" })
    testProjectId = project.id

    await openWorkbench(page, project, "outline", "scenes")

    await expect(page.locator('[data-action="set-scene-view-mode"][data-mode="hot"]')).toHaveClass(/btn-primary/)
    await page.locator('[data-action="set-scene-view-mode"][data-mode="normal"]').click()
    await expect(page).toHaveURL(/outline\/scenes\?mode=normal$/)
    await expect(page.locator('[data-action="set-scene-view-mode"][data-mode="normal"]')).toHaveClass(/btn-primary/)
    await expect.poll(() => page.evaluate(
      (projectId) => localStorage.getItem(`novel_view_mode:${projectId}:scene-workbench`),
      project.id,
    )).toBe("normal")
    await expect(page.locator('[data-action="scene-auto-extract"]')).toHaveCount(1)
    await expect(page.locator('[data-action="start-smart-dedup"], [data-action="show-smart-dedup-progress"]')).toHaveCount(1)
    await expect(page.locator("#workspace-header")).toHaveCount(0)

    const positions = await page.locator(".outline-scene-layout > .subnav").evaluate((subnav) => {
      const activeTab = subnav.querySelector('.subnav-item[data-action="nav-scenes"]')
      const actions = subnav.querySelector(".scene-workbench-actions")
      return {
        activeTabTop: activeTab?.getBoundingClientRect().top,
        actionsTop: actions?.getBoundingClientRect().top,
        actionsInsideSubnav: Boolean(actions),
      }
    })
    expect(positions.actionsInsideSubnav).toBe(true)
    expect(Math.abs(positions.activeTabTop - positions.actionsTop)).toBeLessThan(8)
  })

  test("热点进度忽略空白占位章并可筛选当前剧情", async ({ page }) => {
    const project = await createProject({ title: "Scene 热点定位", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const past = await createScene(project.id, {
      scene_index: 0,
      title: "已经写过",
      chapter_ids: ["1"],
    })
    const current = await createScene(project.id, {
      scene_index: 1,
      title: "正在发生",
      chapter_ids: ["2", "4"],
    })
    const upcoming = await createScene(project.id, {
      scene_index: 2,
      title: "未来事件",
      chapter_ids: ["5"],
    })
    await createDraft(project.id, 1, "第一章", "已完成正文")
    await createDraft(project.id, 3, "第三章", "当前正文")
    await createDraft(project.id, 99, "占位章", " \n\t　")

    await openWorkbench(page, project, "outline", "scenes")

    await expect(page.locator(".scene-progress-panel")).toContainText("截至第 3 章")
    await expect(page.locator(`.scene-workbench-row[data-id="${current.id}"]`)).toContainText("当前剧情")
    await page.locator('[data-action="filter-progress-segment"][data-segment="current"]').click()
    await expect(page.locator('[data-action="filter-progress-segment"][data-segment="current"]')).toHaveClass(/active/)
    await expect(page.locator(`.scene-workbench-row[data-id="${current.id}"]`)).toBeVisible()
    await expect(page.locator(`.scene-workbench-row[data-id="${past.id}"]`)).toHaveCount(0)
    await expect(page.locator(`.scene-workbench-row[data-id="${upcoming.id}"]`)).toHaveCount(0)
  })

  test("选择 Scene 写入 URL，浏览器后退恢复未选中列表", async ({ page }) => {
    const project = await createProject({ title: "Scene 历史恢复", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const first = await createScene(project.id, {
      scene_index: 0,
      title: "默认 Scene",
      goal: "建立起点",
      core_conflict: "起点受阻",
      chapter_ids: ["1"],
    })
    const second = await createScene(project.id, {
      scene_index: 1,
      title: "后续 Scene",
      goal: "推进情节",
      core_conflict: "阻力升级",
      chapter_ids: ["2"],
    })

    await openWorkbench(page, project, "outline", "scenes")
    await page.locator(`.scene-workbench-row[data-id="${second.id}"] [data-action="select-workbench-scene"]`).click()

    await expect(page).toHaveURL(new RegExp(`outline/scenes\\?mode=hot&scene_id=${second.id}$`))
    await expect(page.locator(`.scene-workbench-row[data-id="${second.id}"]`)).toHaveClass(/is-selected/)

    await page.goBack()

    await expect(page).toHaveURL(/outline\/scenes$/)
    await expect(page.locator(".scene-workbench-row.is-selected")).toHaveCount(0)
    await expect(page.locator(".scene-detail-empty")).toHaveText("选择一个 Scene 查看详情。")
    await expect(page.locator(`.scene-workbench-row[data-id="${first.id}"]`)).not.toHaveClass(/is-selected/)
  })

  test("旧 Scene 深链接自动打开目标所在分页", async ({ page }) => {
    const project = await createProject({ title: "Scene 深链接分页", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scenes = await Promise.all(Array.from({ length: 21 }, (_, index) => createScene(project.id, {
      scene_index: index,
      title: `深链接 Scene ${index + 1}`,
      goal: `目标 ${index + 1}`,
      core_conflict: `冲突 ${index + 1}`,
      chapter_ids: [String(index + 1)],
    })))
    const target = scenes.at(-1)

    await openWorkbench(page, project, "scene", target.id)

    await expect(page).toHaveURL(new RegExp(`outline/scenes\\?scene_id=${target.id}$`))
    await expect(page.locator(`.scene-workbench-row[data-id="${target.id}"]`)).toHaveClass(/is-selected/)
    await expect(page.locator(".scene-workbench-pagination")).toContainText("第 2 / 2 页")

    await page.locator('[data-action="prev-scene-page"]').click()

    await expect(page).toHaveURL(/outline\/scenes$/)
    await expect(page.locator(".scene-workbench-pagination")).toContainText("第 1 / 2 页")
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
    await page.locator('[data-action="assign-unassigned-chapter"]').click()
    await expect(page.locator("#modal-title")).toHaveText("分配第 3 章")
    await expect(page.locator(`input[name="assign-target-scene"][value="${scene.id}"]`)).toBeChecked()
    await page.getByRole("button", { name: "确认分配" }).click()

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
    await page.locator('.scene-workbench__detail [data-action="start-split-scene"]').click()

    await expect(page.locator("#modal-title")).toHaveText("Scene AI 建议预览")
    await expect(page.locator(".scene-draft-review-grid")).toBeVisible()
    await expect(page.locator(".scene-split-impact-summary")).toContainText("影响摘要")
    await expect(page.locator("#modal-content")).toHaveAttribute("data-modal-size", "large")
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
    const selectedRow = page.locator(".scene-workbench-row.is-selected")
    await expect(selectedRow.locator(".scene-workbench-row__title")).toHaveText("新标题")
    await selectedRow.locator(".action-menu-btn").click()
    const openWriting = selectedRow.locator('[data-action="open-writing-scene"]')
    await expect(openWriting).toBeVisible()
    await openWriting.click()

    await expect(page.locator("#topbar-module")).toHaveText("写作台")
    await expect(page.locator("#writing-panel-container")).toContainText("新标题")
    await expect(page.locator("#writing-panel-container")).toContainText("新目标")
  })

  test("已采用 Scene 可移入历史并通过历史筛选查看", async ({ page }) => {
    const project = await createProject({ title: "Scene 移入历史", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "旧版潜入计划",
      goal: "潜入王宫",
      core_conflict: "守卫巡查",
      chapter_ids: ["1"],
      status: "canonical",
    })

    await openWorkbench(page, project, "outline", "scenes")
    const row = page.locator(`.scene-workbench-row[data-id="${scene.id}"]`)
    await row.locator(".action-menu-btn").click()
    await row.locator('[data-action="move-scene-to-history"]').click()

    await expect(page.locator("#modal-title")).toHaveText("确认操作")
    await expect(page.locator("#modal-body")).toContainText("正文和追踪信息会保留")
    await page.getByRole("button", { name: "确认移入历史" }).click()

    await expect(page.locator("#toast-container")).toContainText("Scene 已移入历史", { timeout: 10000 })
    await expect(page.locator(`.scene-workbench-row[data-id="${scene.id}"]`)).toHaveCount(0)
    await expect(page).toHaveURL(/outline\/scenes$/)

    await page.locator("#scene-filter-status").selectOption("deprecated")
    await page.locator('[data-action="apply-scene-filters"]').click()

    const historyRow = page.locator(`.scene-workbench-row[data-id="${scene.id}"]`)
    await expect(historyRow).toBeVisible()
    await expect(historyRow).toContainText("历史")
    await historyRow.locator(".action-menu-btn").click()
    await expect(historyRow.locator('[data-action="move-scene-to-history"]')).toHaveCount(0)
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
        .find((item) => item.textContent?.includes("生成 AI 融合建议"))
      button?.click()
    })

    await expect(page.locator("#modal-title")).toHaveText("Scene AI 建议预览")
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
        modalSize: content?.dataset.modalSize || "",
        tableDisplay: getComputedStyle(document.querySelector(".scene-draft-review-grid")).display,
        bodyHasHorizontalOverflow: (() => {
          const body = document.querySelector("#modal-body")
          return body ? body.scrollWidth > body.clientWidth + 1 : true
        })(),
        buttonsWithinContent: Boolean(contentRect) && buttons.every((button) => (
          button.left >= contentRect.left - 1 && button.right <= contentRect.right + 1
        )),
      }
    })
    expect(footerLayout.footerWrap).toBe("wrap")
    expect(footerLayout.modalSize).toBe("large")
    expect(footerLayout.tableDisplay).toBe("table")
    expect(footerLayout.bodyHasHorizontalOverflow).toBe(false)
    expect(footerLayout.buttonsWithinContent).toBe(true)
    await page.locator("#scene-fusion-title").fill("旧港与仓库调查")
    await page.evaluate(() => {
      const button = Array.from(document.querySelectorAll("#modal-footer button"))
        .find((item) => item.textContent?.includes("废弃 2 个原 Scene 并保存"))
      button?.click()
    })
    await expect(page.locator('[data-role="fusion-deprecation-confirm"]')).toBeVisible()
    const scenesBeforeConfirm = await listScenesOrdered(project.id)
    expect(scenesBeforeConfirm.filter((scene) => scene.id === first.id || scene.id === second.id)
      .every((scene) => scene.status === "draft")).toBe(true)
    await page.locator('[data-action="confirm-fusion-deprecation"]').click()
    await expect(page.locator("#toast-container")).toContainText("融合 Scene 已保存", { timeout: 10000 })

    const deprecatedScenes = await listScenes(project.id, { status: "deprecated" })
    const deprecatedIds = new Set((deprecatedScenes.items || deprecatedScenes).map((scene) => scene.id))
    expect(deprecatedIds.has(first.id)).toBe(true)
    expect(deprecatedIds.has(second.id)).toBe(true)

    const scenes = await listScenesOrdered(project.id)
    const fused = scenes.find((scene) => scene.id !== first.id && scene.id !== second.id)
    expect(fused?.source).toBe("manual_fusion")
  })

  test("Scene AI 建议表在中窄屏纵向重排且不横向溢出", async ({ page }) => {
    const project = await createProject({ title: "Scene 预览响应式", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const first = await createScene(project.id, {
      scene_index: 0,
      title: "长文本来源一",
      goal: "第一条需要比较的长目标。".repeat(12),
      chapter_ids: ["1"],
    })
    const second = await createScene(project.id, {
      scene_index: 1,
      title: "长文本来源二",
      goal: "第二条需要比较的长目标。".repeat(12),
      chapter_ids: ["2"],
    })

    await page.setViewportSize({ width: 1280, height: 800 })
    await openWorkbench(page, project, "scene")
    await page.locator(`.scene-workbench-row[data-id="${first.id}"] input[data-action="toggle-fusion-selection"]`).check()
    await page.locator(`.scene-workbench-row[data-id="${second.id}"] input[data-action="toggle-fusion-selection"]`).check()
    await page.locator('[data-action="start-ai-fusion-draft"]').click()
    await page.getByRole("button", { name: "生成 AI 融合建议" }).click()
    await expect(page.locator("#modal-title")).toHaveText("Scene AI 建议预览")

    for (const width of [820, 390]) {
      await page.setViewportSize({ width, height: 800 })
      const layout = await page.evaluate(() => {
        const body = document.querySelector("#modal-body")
        const table = document.querySelector(".scene-draft-review-grid")
        const firstCell = table?.querySelector("td")
        const content = document.querySelector("#modal-content")
        const contentRect = content?.getBoundingClientRect()
        const footerButtons = Array.from(document.querySelectorAll("#modal-footer button"))
          .map((button) => button.getBoundingClientRect())
        return {
          tableDisplay: table ? getComputedStyle(table).display : "",
          cellDisplay: firstCell ? getComputedStyle(firstCell).display : "",
          bodyHasHorizontalOverflow: body ? body.scrollWidth > body.clientWidth + 1 : true,
          buttonsWithinContent: Boolean(contentRect) && footerButtons.every((rect) => (
            rect.left >= contentRect.left - 1 && rect.right <= contentRect.right + 1
          )),
        }
      })
      expect(layout.tableDisplay).toBe("block")
      expect(layout.cellDisplay).toBe("block")
      expect(layout.bodyHasHorizontalOverflow).toBe(false)
      expect(layout.buttonsWithinContent).toBe(true)
    }
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
          .find((item) => item.textContent?.includes("生成 AI 融合建议"))
        button?.click()
      })
      await expect(page.locator("#modal-title")).toHaveText("Scene AI 建议预览")
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

  test("Scene 进度轮询只更新进度卡并保持列表滚动位置", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 620 })
    const project = await createProject({ title: "Scene 进度局部刷新", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    await Promise.all(Array.from({ length: 18 }, (_, index) => createScene(project.id, {
      scene_index: index,
      title: `进度浏览 Scene ${index}`,
      goal: `目标 ${index}`,
      core_conflict: `冲突 ${index}`,
      chapter_ids: [String(index + 1)],
    })))

    const taskId = "11111111-1111-4111-8111-111111111111"
    let phase = "phase1a"
    await page.route(`**/api/tasks/${taskId}?*`, async (route) => {
      const phase1a = phase === "phase1a"
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          task_id: taskId,
          task_type: "scene_auto_extraction",
          status: "running",
          progress: phase1a ? 0.295 : 0.79,
          result: {
            current_phase: phase1a ? "phase1a_scene_slicing" : "phase1b_enrichment",
            current_item: phase1a
              ? { kind: "window", completed: 2, total: 4 }
              : { kind: "scene_candidate", completed: 41, total: 82 },
            phase_timeline: phase1a
              ? [
                  { phase: "phase0_plan", status: "completed" },
                  { phase: "phase1a_scene_slicing", status: "running" },
                ]
              : [
                  { phase: "phase0_plan", status: "completed" },
                  { phase: "phase1a_scene_slicing", status: "completed" },
                  { phase: "phase1b_enrichment", status: "running" },
                ],
          },
        }),
      })
    })

    await openWorkbench(page, project, "scene")
    await page.evaluate(({ taskId: id, projectId }) => {
      localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
        id: `${projectId}:scene_auto_extraction:${id}`,
        taskId: id,
        workflowType: "scene_auto_extraction",
        projectId,
        view: "scene",
        meta: { start_chapter: 1, end_chapter: 60 },
      }]))
    }, { taskId, projectId: project.id })
    await page.reload()
    await expect(page.locator('[data-role="scene-auto-extract-progress"]')).toContainText(
      "Phase 1a · Scene 边界切分｜窗口 2/4",
    )

    const organize = page.locator(".scene-workbench__organize")
    await organize.evaluate((el) => { el.scrollTop = el.scrollHeight })
    const before = await organize.evaluate((el) => el.scrollTop)
    expect(before).toBeGreaterThan(50)
    await page.locator("#scene-filter-q").evaluate((input) => {
      input.value = "正在浏览"
    })

    phase = "phase1b"
    await expect(page.locator('[data-role="scene-auto-extract-progress"]')).toContainText(
      "Phase 1b · Scene 字段补全｜Scene 41/82",
      { timeout: 5000 },
    )

    expect(await organize.evaluate((el) => el.scrollTop)).toBe(before)
    await expect(page.locator("#scene-filter-q")).toHaveValue("正在浏览")
  })

  test("Scene 翻页按钮在列表内容底部且不覆盖场景卡片", async ({ page }) => {
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
    await page.locator(".scene-workbench__organize").evaluate((el) => {
      el.scrollTop = el.scrollHeight
    })
    const pagination = page.locator(".scene-workbench-pagination")
    await expect(pagination).toBeVisible()
    await expect(pagination).toContainText("第 1 / 2 页")

    const paginationState = await page.evaluate(() => {
      const list = document.querySelector(".scene-workbench__organize")
      const pager = document.querySelector(".scene-workbench-pagination")
      const listRect = list?.getBoundingClientRect()
      const pagerRect = pager?.getBoundingClientRect()
      const geometryTolerance = 1
      const style = pager ? getComputedStyle(pager) : null
      const rows = Array.from(document.querySelectorAll(".scene-workbench-row"))
      const overlaps = rows.filter((row) => {
        const rect = row.getBoundingClientRect()
        return Boolean(pagerRect)
          && rect.left < pagerRect.right
          && rect.right > pagerRect.left
          && rect.top < pagerRect.bottom
          && rect.bottom > pagerRect.top
      })
      return {
        workspaceHasOuterScroll: (() => {
          const workspace = document.querySelector("#workspace-content")
          return workspace ? workspace.scrollHeight > workspace.clientHeight + 2 : true
        })(),
        position: style?.position || "",
        afterRows: Boolean(pagerRect && rows.length) && pagerRect.top >= rows.at(-1).getBoundingClientRect().bottom,
        insideList: Boolean(listRect && pagerRect)
          && pagerRect.left >= listRect.left
          && pagerRect.right <= listRect.right
          && pagerRect.top >= listRect.top
          // scrollTop/clientHeight use integer CSS pixels while DOMRect may be fractional.
          && pagerRect.bottom <= listRect.bottom + geometryTolerance,
        overlappingRows: overlaps.length,
        nextHitTarget: (() => {
          const nextButton = document.querySelector('[data-action="next-scene-page"]')
          if (!nextButton) return null
          const rect = nextButton.getBoundingClientRect()
          const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)
          return hit?.getAttribute("data-action") || null
        })(),
      }
    })
    expect(paginationState).toEqual({
      workspaceHasOuterScroll: false,
      position: "static",
      afterRows: true,
      insideList: true,
      overlappingRows: 0,
      nextHitTarget: "next-scene-page",
    })
  })

  test("窄屏下详情进入抽屉，列表仍是主操作面", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const project = await createProject({ title: "Scene 移动端", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const scene = await createScene(project.id, {
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
    await expect(page.locator(".scene-workbench-row .scene-context-action")).toBeVisible()
    await expect(page.locator(".scene-workbench-row .scene-secondary-action")).toBeHidden()
    await expect(page.locator(".scene-workbench-row .action-menu-btn")).toBeVisible()
    await expect(page.locator(".scene-workbench-row.is-selected")).toHaveCount(0)
    await expect(page.locator(".scene-workbench-drawer")).toHaveCount(0)
    await expectNoPageOverflow(page)

    await page.locator(`.scene-workbench-row[data-id="${scene.id}"] [data-action="select-workbench-scene"]`).click()
    await expect(page).toHaveURL(new RegExp(`scene_id=${scene.id}`))
    await expectWithinViewport(page.locator(".scene-workbench-drawer"))
    await expectWithinViewport(page.locator('[data-action="close-scene-detail"]'))
    await page.locator('[data-action="close-scene-detail"]').click()
    await expect(page.locator(".scene-workbench-drawer")).toHaveCount(0)
    await expect(page).not.toHaveURL(/scene_id=/)
    await expect(page.locator(".scene-workbench-row.is-selected")).toHaveCount(0)
  })

  test("390px 窄屏长列表可以滚动到分页并翻页", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const project = await createProject({ title: "Scene 窄屏长列表", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    await Promise.all(Array.from({ length: 21 }, (_, index) => createScene(project.id, {
      scene_index: index,
      title: `窄屏 Scene ${index + 1}`,
      goal: `目标 ${index + 1}`,
      core_conflict: `冲突 ${index + 1}`,
      chapter_ids: [String(index + 1)],
    })))

    await openWorkbench(page, project, "outline", "scenes")

    const scroller = page.locator(".scene-workbench")
    const geometry = await scroller.evaluate((element) => ({
      clientHeight: element.clientHeight,
      scrollHeight: element.scrollHeight,
      overflowY: getComputedStyle(element).overflowY,
    }))
    expect(geometry.scrollHeight).toBeGreaterThan(geometry.clientHeight)
    expect(geometry.overflowY).toBe("auto")

    await scroller.evaluate((element) => { element.scrollTop = element.scrollHeight })
    await expectWithinViewport(page.locator(".scene-workbench-pagination"))
    await page.locator('[data-action="next-scene-page"]').click()
    await expect(page.locator(".scene-workbench-pagination")).toContainText("第 2 / 2 页")
    await expectNoPageOverflow(page)
  })

  test("右侧 Scene 详情栏内容溢出时可滚动", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 620 })
    const project = await createProject({ title: "Scene 详情栏滚动", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const longText = "需要滚动才能查看的示例内容。".repeat(80)
    const scene = await createScene(project.id, {
      scene_index: 0,
      title: "长内容 Scene",
      goal: longText,
      core_conflict: longText,
      must_happen: longText,
      must_not_happen: longText,
      chapter_ids: ["1"],
    })

    await openWorkbench(page, project, "scene", scene.id)

    const body = page.locator(".scene-detail-rail > .workspace-rail__body")
    await expect(body).toBeVisible()
    const canScroll = await body.evaluate((el) => el.scrollHeight > el.clientHeight + 2)
    expect(canScroll).toBe(true)

    const saveButton = page.locator('.scene-detail-rail [data-action="save-scene-detail"]')
    await body.evaluate((el) => { el.scrollTop = el.scrollHeight })
    await expect(saveButton).toBeInViewport()

    const scrollState = await body.evaluate((el) => ({
      scrollTop: el.scrollTop,
      scrollHeight: el.scrollHeight,
      clientHeight: el.clientHeight,
    }))
    expect(scrollState.scrollTop).toBeGreaterThan(50)
    expect(scrollState.scrollTop + scrollState.clientHeight).toBeGreaterThan(scrollState.scrollHeight - 10)
  })
})
