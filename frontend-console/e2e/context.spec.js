import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

test.describe("上下文模块", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "上下文测试项目",
      genre: "mystery",
      language: "zh",
    })
    testProjectId = project.id

    await openWorkbench(page, project, "context")
    // 等待 DOM 实际更新为 contextView 内容（防御 renderCurrentView 偶发竞态）
    try {
      await page.waitForFunction(() => {
        const content = document.getElementById("workspace-content")
        return content && content.querySelector("#ctx-task") !== null
      }, { timeout: 8000 })
    } catch {
      // 若渲染竞态导致 DOM 未更新，通过 reload 从 URL hash 恢复 context 视图
      await page.reload()
      await page.waitForFunction(() => {
        const content = document.getElementById("workspace-content")
        return content && content.querySelector("#ctx-task") !== null
      }, { timeout: 10000 })
    }
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("上下文编译页面加载", async ({ page }) => {
    await expect(page.locator("#ctx-task")).toBeVisible()
    await expect(page.locator("#ctx-scope")).toBeVisible()
    await expect(page.locator("#ctx-reveal")).toBeVisible()
    await expect(page.locator('[data-action="compile"]')).toBeVisible()
  })

  test("未选择项目时编译给出警告", async ({ page }) => {
    // 清除 localStorage 中的项目选择后导航到上下文视图
    await page.evaluate(() => {
      localStorage.removeItem("novel_currentProjectId")
      localStorage.removeItem("novel_currentProject")
    })
    await page.reload()
    await page.evaluate(() => {
      state.currentProjectId = null
      state.currentProject = null
      window.router.navigate("context")
    })
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })

    await page.locator("#ctx-task").fill("测试任务")
    await page.locator('[data-action="compile"]').click()

    await expect(page.locator(SEL.toastContainer)).toContainText("请先选择项目", { timeout: 10000 })
  })

  test("编译上下文并显示结果", async ({ page }) => {
    await page.locator("#ctx-task").fill("为测试项目生成上下文")
    await page.locator('[data-action="compile"]').click()

    // 编译可能成功也可能因为没有数据而返回空结果
    await expect(page.locator("#ctx-output")).not.toContainText("填写左侧参数后点击编译", { timeout: 15000 })
  })

  test("角色揭示模式缺少视角人物时不提交编译", async ({ page }) => {
    let compileCalled = false
    await page.route("**/api/context/compile", async (route) => {
      compileCalled = true
      await route.fulfill({ status: 500, body: JSON.stringify({ detail: "should not call" }) })
    })

    await page.locator("#ctx-reveal").selectOption("character")
    await page.locator("#ctx-task").fill("写角色视角场景")
    await page.locator('[data-action="compile"]').click()

    await expect(page.locator(SEL.toastContainer)).toContainText("请输入视角人物 ID", { timeout: 10000 })
    expect(compileCalled).toBeFalsy()
  })

  test("选择角色揭示模式时提交 reveal_mode=character", async ({ page }) => {
    const requests = []
    await page.route("**/api/context/compile", async (route) => {
      const body = route.request().postDataJSON()
      requests.push(body)
      const warnings = body.reveal_mode === "character"
        ? ["POV Knowledge: 角色误以为铜铃只是普通遗物"]
        : ["Author Notes: 隐藏真相：铜铃属于旧王密探"]

      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          novel_id: body.novel_id,
          task: body.task,
          scope: body.scope,
          reveal_mode: body.reveal_mode,
          budgets: [],
          warnings,
          section_count: 1,
          sections_present: ["characters"],
        }),
      })
    })

    await page.locator("#ctx-reveal").selectOption("character")
    await page.locator("#ctx-characters").fill("00000000-0000-0000-0000-000000000123")
    await page.locator("#ctx-task").fill("写角色视角场景")
    await page.locator('[data-action="compile"]').click()

    await expect(page.locator("#ctx-output")).toContainText("误以为", { timeout: 10000 })
    await expect(page.locator("#ctx-output")).not.toContainText("隐藏真相")
    expect(requests.at(-1).reveal_mode).toBe("character")
    expect(requests.at(-1).character_ids).toEqual(["00000000-0000-0000-0000-000000000123"])
    expect(requests.at(-1).viewpoint_character_id).toBe("00000000-0000-0000-0000-000000000123")
  })
})
