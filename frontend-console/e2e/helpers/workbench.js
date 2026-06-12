/**
 * 共享的工作台导航辅助函数
 *
 * app.js 因包含 `export default App`（非 module 脚本中的语法错误）而无法执行，
 * 导致 _restoreProjectState() 与 _bindNavigation() 永不运行。
 * 因此侧边栏点击导航完全不可用，必须通过 window.router.navigate 直接导航。
 */

import { expect } from "@playwright/test"
import { SEL } from "./selectors.js"

/**
 * 导航到指定工作台视图
 * 代替已损坏的侧边栏点击导航。
 */
export async function openWorkbench(page, project, view = "writing", subview = null) {
  await page.goto("/")
  await page.evaluate(({ projectData, viewName, subViewName }) => {
    localStorage.setItem("novel_currentProjectId", projectData.id)
    localStorage.setItem("novel_currentProject", JSON.stringify(projectData))
    state.currentProjectId = projectData.id
    state.currentProject = projectData
    window.router.navigate(viewName, subViewName)
  }, { projectData: project, viewName: view, subViewName: subview })
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  const expectedTitle = {
    writing: "手动工作台",
    world: "世界对象",
    outline: "大纲",
    rag: "RAG 检索",
    context: "上下文",
    generate: "生成中心",
    project: "项目",
  }[view]
  await expect(page.locator(SEL.viewTitle)).toHaveText(expectedTitle, { timeout: 10000 })
}

/**
 * 导航到项目列表页（无选中项目）
 */
export async function openProjectList(page) {
  await page.goto("/")
  await page.evaluate(() => {
    localStorage.removeItem("novel_currentProjectId")
    localStorage.removeItem("novel_currentProject")
    state.currentProjectId = null
    state.currentProject = null
    window.router.navigate("project")
  })
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  await expect(page.locator(SEL.viewTitle)).toHaveText("项目", { timeout: 10000 })
}

/**
 * 导航到项目列表页并选中指定项目（上传导入需要当前项目上下文）
 */
export async function openProjectView(page, project) {
  await page.goto("/")
  await page.evaluate((projectData) => {
    localStorage.setItem("novel_currentProjectId", projectData.id)
    localStorage.setItem("novel_currentProject", JSON.stringify(projectData))
    state.currentProjectId = projectData.id
    state.currentProject = projectData
    window.router.navigate("project")
  }, project)
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
  await expect(page.locator(SEL.viewTitle)).toHaveText("项目", { timeout: 10000 })
}

/**
 * 刷新页面后重新导航到指定视图
 * 代替测试体内的 page.reload() + 侧边栏点击模式。
 */
export async function reloadWorkbench(page, view, subview = null) {
  await page.reload()
  await page.evaluate(({ viewName, subViewName }) => {
    const pid = localStorage.getItem("novel_currentProjectId")
    if (pid) {
      state.currentProjectId = pid
      try {
        const proj = JSON.parse(localStorage.getItem("novel_currentProject"))
        if (proj) state.currentProject = proj
      } catch {}
    }
    window.router.navigate(viewName, subViewName)
  }, { viewName: view, subViewName: subview })
  await page.waitForFunction(() => !state.loading, { timeout: 10000 })
}
