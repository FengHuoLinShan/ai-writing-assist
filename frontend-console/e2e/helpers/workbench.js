/**
 * 共享的工作台导航辅助函数
 *
 * 提供确定性的视图导航与页面刷新后恢复，供 E2E 场景复用。
 */

import { expect } from "@playwright/test"
import { API_HOST } from "./api-client.js"
import { SEL } from "./selectors.js"

async function installApiHost(page) {
  await page.addInitScript((apiHost) => {
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
    writing: "写作台",
    world: "世界对象",
    outline: "大纲",
    scene: "场景",
    rag: "RAG 检索",
    context: "上下文",
    generate: "生成中心",
    project: "项目",
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
  await expect(page.locator(SEL.viewTitle)).toHaveText("项目", { timeout: 10000 })
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
  await expect(page.locator(SEL.viewTitle)).toHaveText("项目", { timeout: 10000 })
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
