/**
 * 共享的工作台导航辅助函数
 *
 * 提供确定性的视图导航与页面刷新后恢复，供 E2E 场景复用。
 */

import { expect } from "@playwright/test"
import { API_HOST } from "./api-client.js"
import { SEL } from "./selectors.js"

async function installApiHost(page) {
  await page.context().addInitScript((apiHost) => {
    window.API_HOST = apiHost
  }, API_HOST)
}

/**
 * 导航到指定工作台视图
 */
export async function openWorkbench(page, project, view = "writing", subview = null) {
  await installApiHost(page)
  await page.goto("/")
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  await page.evaluate(async ({ projectData, viewName, subViewName }) => {
    localStorage.setItem("novel_currentProjectId", projectData.id)
    localStorage.setItem("novel_currentProject", JSON.stringify(projectData))
    state.currentProjectId = projectData.id
    state.currentProject = projectData
    await window.router.navigate(viewName, subViewName)
  }, { projectData: project, viewName: view, subViewName: subview })
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  const expectedTitle = {
    today: "写作",
    writing: "写作",
    world: "人物与世界",
    outline: "故事结构",
    scene: "故事结构",
    rag: "查找",
    context: "写作",
    generate: "人物与世界",
    project: "作品档案",
    map: "地图",
  }[view]
  await expect(page.locator(SEL.viewTitle)).toHaveText(expectedTitle, { timeout: 10000 })
}

/**
 * 导航到项目列表页（无选中项目）
 */
export async function openProjectList(page) {
  await installApiHost(page)
  await page.goto("/")
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  await page.evaluate(async () => {
    localStorage.removeItem("novel_currentProjectId")
    localStorage.removeItem("novel_currentProject")
    state.currentProjectId = null
    state.currentProject = null
    await window.router.navigate("project")
  })
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  await expect(page.locator(SEL.viewTitle)).toHaveText("作品档案", { timeout: 10000 })
}

/**
 * 刷新页面后等待项目列表渲染完成
 */
export async function reloadProjectList(page) {
  await installApiHost(page)
  await page.reload()
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  await expect(page.locator(SEL.projectGrid).or(page.locator(SEL.emptyState))).toBeVisible({ timeout: 10000 })
}

/**
 * 导航到项目列表页并选中指定项目（上传导入需要当前项目上下文）
 */
export async function openProjectView(page, project) {
  await installApiHost(page)
  await page.goto("/")
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  await page.evaluate(async (projectData) => {
    localStorage.setItem("novel_currentProjectId", projectData.id)
    localStorage.setItem("novel_currentProject", JSON.stringify(projectData))
    state.currentProjectId = projectData.id
    state.currentProject = projectData
    await window.router.navigate("project")
  }, project)
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  await expect(page.locator(SEL.viewTitle)).toHaveText("作品档案", { timeout: 10000 })
}

/** 打开写作页唯一 AI 入口；移动速记使用页头，完整编辑器使用页内菜单。 */
export async function openWritingAiDrawer(page) {
  const quickNoteEntry = page.locator('[data-action="open-owner-ai-drawer"]')
  if (await quickNoteEntry.isVisible()) {
    await quickNoteEntry.click()
    return
  }
  await clickWritingTool(page, '[data-action="writing-open-owner-ai"]')
}

/**
 * 刷新页面后重新导航到指定视图
 */
export async function reloadWorkbench(page, view, subview = null) {
  await installApiHost(page)
  await page.reload()
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  await page.evaluate(async ({ viewName, subViewName }) => {
    const pid = localStorage.getItem("novel_currentProjectId")
    if (pid) {
      state.currentProjectId = pid
      try {
        const proj = JSON.parse(localStorage.getItem("novel_currentProject"))
        if (proj) state.currentProject = proj
      } catch {}
    }
    await window.router.navigate(viewName, subViewName)
  }, { viewName: view, subViewName: subview })
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
}

/**
 * Wait for the public Writing island surface instead of a renderer singleton.
 * Optional chapter/editor checks let specs wait for fixture-backed UI state
 * without reading Vue internals.
 */
export async function waitWritingReady(page, { chapter = null, editor = false } = {}) {
  await expect(page.locator(".writing-toolbar")).toBeVisible({ timeout: 10000 })
  if (chapter != null) {
    const opener = page.getByRole('button', { name: '章节', exact: true })
    if (await opener.isVisible() && await opener.getAttribute('aria-expanded') === 'false') await opener.click()
    await expect(
      page.getByRole("button", { name: new RegExp(`^打开第 ${Number(chapter)} 章`) }),
    ).toBeVisible({ timeout: 10000 })
  }
  if (editor) await expect(page.locator("#writing-editor")).toBeVisible({ timeout: 10000 })
}

/** Opens collapsed tools through the currently visible entry, regardless of breakpoint. */
export async function openWorkspaceTools(page) {
  const trigger = page.locator(".workspace-tools-trigger")
  await expect(page.locator(".workspace-tools:visible, .workspace-tools-trigger:visible").first()).toBeVisible()
  if (await trigger.isVisible() && await trigger.getAttribute("aria-expanded") !== "true") {
    await trigger.click()
  }
  await expect(page.locator(".workspace-tools")).toBeVisible()
}

/** 当前可见操作可直接点击；折叠菜单只是定位适配，不冻结布局。 */
export async function openWritingToolMenu(page, selector) {
  const tool = page.locator(selector)
  if (await tool.isVisible()) return
  const menu = page.locator("details.writing-tools-menu").filter({ has: tool })
  if (await menu.getAttribute("open") === null) {
    await menu.locator(":scope > summary").click()
  }
}

export async function clickWritingTool(page, selector) {
  await openWritingToolMenu(page, selector)
  await page.locator(selector).click()
}
