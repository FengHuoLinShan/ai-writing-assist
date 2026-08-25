import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"
import { expectNoPageOverflow, expectWithinViewport } from "./helpers/responsive.js"

async function enterAuthorProjects(page) {
  await page.getByRole("button", { name: /我是作家/ }).click()
  await expect(page.locator(SEL.viewTitle)).toHaveText("作品档案")
}

test.describe("项目模块", () => {
  let testProjectIds = new Set()

  function trackProject(project) {
    const projectId = typeof project === "string" ? project : project.id
    testProjectIds.add(projectId)
    return project
  }

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.reload()
    await enterAuthorProjects(page)
  })

  test.afterEach(async () => {
    for (const projectId of testProjectIds) {
      try {
        await cleanupProject(projectId)
      } catch {}
    }
    testProjectIds = new Set()
  })

  test("空项目状态显示新建按钮", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "开始你的第一部小说" })).toBeVisible()
    await expect(page.getByRole("button", { name: "新建空白作品", exact: true })).toBeVisible()
    const importButton = page.getByRole("button", { name: "导入已有作品", exact: true })
    await expect(importButton).toBeVisible()
    const fileChooserPromise = page.waitForEvent("filechooser")
    await importButton.click()
    const fileChooser = await fileChooserPromise
    expect(await fileChooser.element().getAttribute("accept")).toBe(".txt,.epub,.html,.htm,.mobi,.azw3")
    await expect(page.locator('[data-action="manage-projects"]')).toBeVisible()
    await expect(page.locator('[data-action="recycle-bin"]')).toHaveCount(0)
  })

  test("单键新建项目不会把触发字符写入项目名称", async ({ page }) => {
    await expect(page.getByRole("button", { name: "新建空白作品", exact: true })).toBeVisible()
    await page.keyboard.press("n")
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建项目")
    const title = page.locator(SEL.projectCreateTitle)
    await expect(title).toBeFocused()
    await expect(title).toHaveValue("")
    await page.keyboard.press("Escape")
    await expect(page.locator(SEL.modalOverlay)).toHaveClass(/hidden/)
  })

  test("创建项目并自动切换到写作视图", async ({ page }) => {
    await page.locator('[data-action="new"]').first().click()
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建项目")

    await page.locator("#create-title").fill("E2E 测试小说")
    await page.locator("#create-genre").selectOption("fantasy")
    await page.locator("#create-tone").fill("黑暗史诗")

    const modalFooter = page.locator(SEL.modalFooter)
    await modalFooter.locator(SEL.btnPrimary).click()

    let projectId = null
    await expect.poll(async () => {
      projectId = await page.evaluate(() => localStorage.getItem("novel_currentProjectId"))
      return projectId
    }).toBeTruthy()
    trackProject(projectId)

    // 创建成功后应切换到写作视图
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作", { timeout: 10000 })
    await expect(page).toHaveURL(/#workbench\/[^/]+\/writing/)
    await expect(page.locator(SEL.topbarProject)).toContainText("E2E 测试小说")
  })

  test("空白创建保留 modal、提示必填且可继续输入", async ({ page }) => {
    await page.locator('[data-action="new"]').first().click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建项目")

    await expect(page.getByLabel(/项目名称/)).toBeVisible()
    await expect(page.getByLabel("题材")).toBeVisible()
    await expect(page.getByLabel("语言")).toBeVisible()
    await expect(page.getByLabel("基调")).toBeVisible()
    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.toastContainer)).toContainText("请输入项目标题")
    await page.getByLabel(/项目名称/).fill("仍可继续输入")
    await expect(page.getByLabel(/项目名称/)).toHaveValue("仍可继续输入")

    await page.setViewportSize({ width: 390, height: 844 })
    await expectNoPageOverflow(page)
  })

  test("创建的项目出现在列表中", async ({ page }) => {
    const project = await createProject({
      title: "列表测试项目",
      genre: "scifi",
      tone: "赛博朋克",
      language: "zh",
    })
    trackProject(project)

    await page.reload()
    await expect(page.locator(SEL.projectGrid)).toBeVisible()
    await expect(page.locator(SEL.projectCard(project.id))).toContainText("列表测试项目")
    await expect(page.locator(SEL.projectCard(project.id))).toContainText("科幻")
  })

  test("创建占位卡可用键盘打开新建项目并保持窄屏可见", async ({ page }) => {
    const project = await createProject({
      title: "键盘创建入口测试",
      genre: "scifi",
      language: "zh",
    })
    trackProject(project)

    await page.reload()
    await page.locator('[data-action="manage-projects"]').click()
    const placeholder = page.locator(SEL.projectCreatePlaceholder)
    await expect(placeholder).toHaveAttribute("role", "button")
    await expect(placeholder).toHaveAttribute("tabindex", "0")
    await expect(page.locator(SEL.projectSelectVisible)).toHaveText("全选当前可见项目")
    await page.setViewportSize({ width: 390, height: 844 })
    await expectWithinViewport(page.locator("#project-search-input"))
    await placeholder.focus()
    await expect(placeholder).toBeFocused()
    await expectWithinViewport(placeholder)
    await expectNoPageOverflow(page)
    await placeholder.press("Enter")
    await expect(page.locator(SEL.modalTitle)).toHaveText("新建项目")
  })

  test("编辑项目信息并同步面包屑", async ({ page }) => {
    const project = await createProject({
      title: "编辑前标题",
      genre: "mystery",
      language: "zh",
    })
    trackProject(project)

    await page.reload()
    await expect(page.locator(SEL.projectGrid)).toBeVisible({ timeout: 10000 })
    await page.locator('[data-action="manage-projects"]').click()
    const card = page.locator(SEL.projectCard(project.id))
    await expect(card).toBeVisible()

    // hover 显示操作按钮
    await card.hover()
    const editBtn = card.locator('[data-action="edit-project"]')
    await editBtn.click()

    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑项目")

    await page.locator("#edit-title").fill("编辑后标题")
    await page.locator("#edit-genre").fill("武侠")
    await page.locator("#edit-tone").fill("热血")
    await page.locator("#edit-target-length").selectOption("epic")

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()

    // 等待模态框关闭并提示更新成功
    await expect(page.locator(SEL.modalOverlay)).toHaveClass(/hidden/)
    await expect(page.locator(SEL.toastContainer)).toContainText("项目已更新", { timeout: 10000 })

    // 进入工作台验证面包屑同步刷新
    await card.click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作", { timeout: 10000 })
    await expect(page.locator(SEL.topbarProject)).toHaveText("编辑后标题", { timeout: 10000 })
  })

  test("编辑保存 API 失败后保留表单内容并可取消", async ({ page }) => {
    const project = await createProject({
      title: "编辑失败前标题",
      genre: "mystery",
      tone: "原始基调",
      language: "zh",
    })
    trackProject(project)

    await page.reload()
    await page.locator('[data-action="manage-projects"]').click()
    const card = page.locator(SEL.projectCard(project.id))
    await expect(card).toBeVisible({ timeout: 10000 })
    await card.hover()
    await card.locator('[data-action="edit-project"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("编辑项目")

    await page.getByLabel("项目标题").fill("失败后保留标题")
    await page.getByLabel("题材").fill("武侠")
    await page.getByLabel("风格基调").fill("热血")
    await page.route(`**/api/projects/${project.id}`, async (route) => {
      if (route.request().method() === "PUT") {
        await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "暂时无法保存项目" }) })
        return
      }
      await route.fallback()
    })

    await page.locator(SEL.modalFooter).locator(SEL.btnPrimary).click()
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.getByLabel("项目标题")).toHaveValue("失败后保留标题")
    await expect(page.getByLabel("题材")).toHaveValue("武侠")
    await expect(page.getByLabel("风格基调")).toHaveValue("热血")

    page.once("dialog", (dialog) => dialog.accept())
    await page.getByRole("button", { name: "取消" }).click()
    await expect(page.locator(SEL.modalOverlay)).toHaveClass(/hidden/)
  })

  test("删除项目", async ({ page }) => {
    const project = await createProject({
      title: "待删除项目",
      genre: "romance",
      language: "zh",
    })
    trackProject(project)

    await page.reload()
    await expect(page.locator(SEL.projectGrid)).toBeVisible({ timeout: 10000 })
    await page.locator('[data-action="manage-projects"]').click()
    const card = page.locator(SEL.projectCard(project.id))
    await expect(card).toBeVisible()

    // hover 显示操作按钮
    await card.hover()
    const deleteBtn = card.locator('[data-action="delete-project"]')
    await deleteBtn.click()

    // 确认删除弹窗
    await expect(page.locator(SEL.modalOverlay)).not.toHaveClass(/hidden/)
    await expect(page.locator(SEL.modalBody)).toContainText("确定要删除")

    // 确认弹窗的确定按钮是 btn-danger（来自 confirmAction）
    const confirmBtn = page.locator(SEL.modalFooter).locator(SEL.btnDanger)
    await confirmBtn.click()

    // 等待删除成功 toast（软删除 → 回收站）
    await expect(page.locator(SEL.toastContainer)).toContainText("已移至回收站", { timeout: 15000 })

    // 刷新页面验证项目已消失
    await page.reload()
    await expect(page.locator(SEL.projectCard(project.id))).toHaveCount(0, { timeout: 15000 })
  })

  test("点击项目行切换到项目并显示在写作视图", async ({ page }) => {
    const project = await createProject({
      title: "点击切换项目",
      genre: "wuxia",
      language: "zh",
    })
    trackProject(project)

    await page.reload()
    await expect(page.locator(SEL.projectGrid)).toBeVisible({ timeout: 10000 })
    const card = page.locator(SEL.projectCard(project.id))
    await expect(card).toBeVisible()

    // 点击项目卡片
    await card.click()

    // 应切换到写作首页
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作", { timeout: 10000 })
    await expect(page).toHaveURL(/#workbench\/[^/]+\/writing\?home=1/)
    await expect(page.locator(SEL.topbarProject)).toContainText("点击切换项目")
  })

  test("跨项目切换后面包屑显示正确项目名", async ({ page }) => {
    const projectA = await createProject({
      title: "项目A-面包屑",
      genre: "fantasy",
      language: "zh",
    })
    const projectB = await createProject({
      title: "项目B-面包屑",
      genre: "scifi",
      language: "zh",
    })
    trackProject(projectA)
    trackProject(projectB)

    await page.goto("/")
    await page.evaluate(() => localStorage.clear())
    await page.reload()
    await enterAuthorProjects(page)

    await page.locator(SEL.projectCard(projectA.id)).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作", { timeout: 10000 })
    await expect(page.locator(SEL.topbarProject)).toHaveText("项目A-面包屑")

    await page.locator(".sidebar-project-switcher").click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("作品档案", { timeout: 10000 })

    await page.locator(SEL.projectCard(projectB.id)).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作", { timeout: 10000 })
    await expect(page.locator(SEL.topbarProject)).toHaveText("项目B-面包屑", { timeout: 10000 })
  })

  test("从 URL 直接进入工作台加载项目信息", async ({ page }) => {
    const project = await createProject({
      title: "URL 进入项目",
      genre: "mystery",
      language: "zh",
    })
    trackProject(project)

    await page.goto("/")
    await page.evaluate(() => localStorage.clear())

    await page.goto(`/#workbench/${project.id}/writing`)
    await expect(page.locator(SEL.workspace)).not.toContainText("加载中", { timeout: 10000 })
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作", { timeout: 10000 })
    await expect(page.locator(SEL.topbarProject)).toHaveText("URL 进入项目", { timeout: 10000 })
  })
})
