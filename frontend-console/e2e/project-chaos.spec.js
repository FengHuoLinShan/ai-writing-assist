import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { openProjectList, reloadProjectList } from "./helpers/workbench.js"
import { cleanupProject, createProject, waitForBackend } from "./helpers/api-client.js"

async function enterManageMode(page) {
  if (!await page.locator('[data-action="recycle-bin"]').isVisible()) {
    await page.locator('[data-action="manage-projects"]').click()
  }
}

test.describe("项目路径 chaos recovery", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    await openProjectList(page)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("S1-DNG-002 cancel permanent delete should keep project in recycle bin", async ({ page }) => {
    const project = await createProject({
      title: "取消永久删除 chaos",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await reloadProjectList(page)
    await enterManageMode(page)
    const card = page.locator(SEL.projectCard(project.id))
    await card.hover()
    await card.locator('[data-action="delete-project"]').click()
    await page.locator(SEL.modalFooter).locator(SEL.btnDanger).click()
    await expect(page.locator(SEL.toastContainer)).toContainText("已移至回收站", { timeout: 15000 })

    await reloadProjectList(page)
    await enterManageMode(page)
    await page.locator('[data-action="recycle-bin"]').click()
    await expect(page.locator(SEL.modalBody)).toContainText("取消永久删除 chaos")

    await page.locator(`.perm-delete-project-btn[data-id="${project.id}"]`).click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("确认操作")
    await expect(page.locator(SEL.modalBody)).toContainText("不可恢复")

    await page.locator(SEL.modalFooter).getByRole("button", { name: "取消" }).click()
    await expect(page.locator(SEL.modalOverlay)).toHaveClass(/hidden/)

    await page.locator('[data-action="recycle-bin"]').click()
    await expect(page.locator(SEL.modalBody)).toContainText("取消永久删除 chaos")
  })
})
