import { test, expect } from "./fixtures.js"
import { createWorldBiblePage, waitForBackend } from "./helpers/api-client.js"
import { openWorkbench } from "./helpers/workbench.js"
import { SEL } from "./helpers/selectors.js"

function deferred() {
  let resolve
  const promise = new Promise((next) => { resolve = next })
  return { promise, resolve }
}

async function switchWorldProject(page, projectId, pageId) {
  await page.evaluate(({ targetProjectId, targetPageId }) => {
    const query = new URLSearchParams({ page_id: targetPageId })
    window.history.pushState(
      { view: "world", subView: "bible", projectId: targetProjectId },
      "",
      `#workbench/${targetProjectId}/world/bible?${query.toString()}`,
    )
    window.dispatchEvent(new PopStateEvent("popstate"))
  }, {
    targetProjectId: projectId,
    targetPageId: pageId,
  })
}

test.describe("共享项目路由生命周期", () => {
  test.beforeAll(async () => {
    await waitForBackend(60_000)
  })

  test("should remove old World Bible actions before target metadata resolves", async ({
    page,
    projectFactory,
    browserErrors,
  }) => {
    const projectA = await projectFactory({
      title: "路由生命周期项目 A",
      genre: "fantasy",
      language: "zh",
    })
    const projectB = await projectFactory({
      title: "路由生命周期项目 B",
      genre: "fantasy",
      language: "zh",
    })
    const sourcePage = await createWorldBiblePage(projectA.id, {
      title: "只属于项目 A 的世界书",
      page_type: "background",
      free_text: "项目 A 的旧内容不应出现在项目 B 的 URL 下。",
      sections_json: [],
    })

    await openWorkbench(page, projectA, "world", "bible")
    await switchWorldProject(page, projectA.id, sourcePage.id)
    await expect(page.locator(SEL.worldBibleWorkspace)).toContainText(
      "只属于项目 A 的世界书",
    )

    const metadataSeen = deferred()
    const releaseMetadata = deferred()
    const writeRequests = []
    page.on("request", (request) => {
      if (
        request.url().includes("/api/")
        && !["GET", "HEAD", "OPTIONS"].includes(request.method())
      ) {
        writeRequests.push(`${request.method()} ${request.url()}`)
      }
    })
    await page.route(`**/api/projects/${projectB.id}`, async (route) => {
      metadataSeen.resolve()
      await releaseMetadata.promise
      await route.continue()
    })

    await switchWorldProject(page, projectB.id, sourcePage.id)
    await metadataSeen.promise

    await expect(page).toHaveURL(new RegExp(
      `#workbench/${projectB.id}/world/bible\\?page_id=${sourcePage.id}`,
    ))
    await expect(page.locator(SEL.loadingSkeleton)).toBeVisible()
    await expect(page.locator(SEL.workspaceContent)).not.toContainText(
      "只属于项目 A 的世界书",
    )
    await expect(page.locator(SEL.worldBibleWorkspace)).toHaveCount(0)
    await expect(page.locator(SEL.worldBibleSavePage)).toHaveCount(0)
    await expect(page.locator(SEL.worldBiblePublishPage)).toHaveCount(0)
    await expect(page.locator(SEL.worldBibleImproveWithAi)).toHaveCount(0)
    await expect(page.locator(SEL.modalOverlay)).toBeHidden()
    expect(writeRequests).toEqual([])

    releaseMetadata.resolve()
    await expect(page.locator(SEL.worldBibleWorkspace)).toBeVisible({ timeout: 10_000 })
    await expect(page.locator(SEL.worldBibleNewResource)).toBeVisible()
    await expect(page.locator(SEL.worldBibleWorkspace)).not.toContainText(
      "只属于项目 A 的世界书",
    )
    expect(browserErrors).toEqual([])
  })

  test("should roll back a project switch when a dirty modal rejects leaving", async ({
    page,
    projectFactory,
    browserErrors,
  }) => {
    const projectA = await projectFactory({
      title: "弹窗守卫项目 A",
      genre: "fantasy",
      language: "zh",
    })
    const projectB = await projectFactory({
      title: "弹窗守卫项目 B",
      genre: "fantasy",
      language: "zh",
    })
    const sourcePage = await createWorldBiblePage(projectA.id, {
      title: "弹窗守卫来源页",
      page_type: "background",
      free_text: "确认取消时必须完整保留。",
      sections_json: [],
    })
    await openWorkbench(page, projectA, "world", "bible")
    await switchWorldProject(page, projectA.id, sourcePage.id)
    await expect(page.locator(SEL.worldBibleWorkspace)).toContainText("弹窗守卫来源页")

    await page.locator(SEL.worldBibleNewResource).click()
    await page.locator(SEL.worldBibleNewPageChoice).click()
    await expect(page.locator(SEL.modalOverlay)).toBeVisible()
    await page.locator(SEL.worldBibleCreateTitle).fill("尚未保存的新页面")

    let metadataRequestCount = 0
    const metadataSeen = deferred()
    const releaseMetadata = deferred()
    await page.route(`**/api/projects/${projectB.id}`, async (route) => {
      metadataRequestCount += 1
      metadataSeen.resolve()
      await releaseMetadata.promise
      await route.continue()
    })

    const rejectedDialog = deferred()
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("有未保存的更改")
      await dialog.dismiss()
      rejectedDialog.resolve()
    })
    await switchWorldProject(page, projectB.id, sourcePage.id)
    await rejectedDialog.promise

    await expect(page).toHaveURL(new RegExp(
      `#workbench/${projectA.id}/world/bible`,
    ))
    await expect(page.locator(SEL.modalOverlay)).toBeVisible()
    await expect(page.locator(SEL.worldBibleCreateTitle)).toHaveValue("尚未保存的新页面")
    await expect(page.locator(SEL.worldBibleWorkspace)).toContainText("弹窗守卫来源页")
    expect(metadataRequestCount).toBe(0)

    const acceptedDialog = deferred()
    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("有未保存的更改")
      await dialog.accept()
      acceptedDialog.resolve()
    })
    await switchWorldProject(page, projectB.id, sourcePage.id)
    await acceptedDialog.promise
    await metadataSeen.promise

    await expect(page.locator(SEL.modalOverlay)).toBeHidden()
    await expect(page.locator(SEL.loadingSkeleton)).toBeVisible()
    await expect(page.locator(SEL.workspaceContent)).not.toContainText("弹窗守卫来源页")
    expect(metadataRequestCount).toBe(1)

    releaseMetadata.resolve()
    await expect(page.locator(SEL.worldBibleNewResource)).toBeVisible({ timeout: 10_000 })
    expect(browserErrors).toEqual([])
  })
})
