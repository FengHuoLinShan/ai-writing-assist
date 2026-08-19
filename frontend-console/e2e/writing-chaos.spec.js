import { test, expect } from "./fixtures.js"
import { API_BASE, createDraft, createScene, waitForBackend } from "./helpers/api-client.js"
import { openWorkbench, reloadWorkbench, waitWritingReady } from "./helpers/workbench.js"

function writingChapter(page, chapter) {
  return page.getByRole("button", { name: new RegExp(`^打开第 ${Number(chapter)} 章`) })
}

async function selectWritingChapter(page, chapter) {
  const rail = page.locator(".writing-tree-rail")
  if (await rail.count() && await rail.evaluate((element) => element.classList.contains("is-collapsed"))) {
    await page.getByLabel("展开章节").click()
  }
  await writingChapter(page, chapter).click()
}

test.describe("写作路径 chaos", () => {
  let project = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page, projectFactory }) => {
    project = await projectFactory({ title: "写作 chaos 项目", genre: "fantasy", language: "zh" })
    await openWorkbench(page, project, "writing")
    await waitWritingReady(page)
  })

  test("S4-REC-001 localStorage 恢复会保留未保存正文", async ({ page }) => {
    const backupContent = "本地暂存的离线内容"
    const backupTitle = "离线标题"

    const created = await createDraft(project.id, 1, "第 1 章", "")
    await page.evaluate(({ projectId, draftId }) => {
      localStorage.setItem(`draft_backup_${projectId}_1_${encodeURIComponent(draftId)}`, JSON.stringify({
        project_id: projectId,
        draft_id: draftId,
        content: "本地暂存的离线内容",
        title: "离线标题",
        chapter_index: 1,
        timestamp: Date.now(),
      }))
    }, { projectId: project.id, draftId: created.draft.id })

    page.once("dialog", async (dialog) => {
      expect(dialog.message()).toContain("检测到本地暂存")
      await dialog.accept()
    })
    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)

    await expect(page.locator("#writing-editor")).toHaveValue(backupContent, { timeout: 5000 })
    await expect(page.locator("#writing-title-input")).toHaveValue(backupTitle, { timeout: 5000 })
  })

  test("S4-STA-001 切换章节与 Scene 后只显示新 Scene 上下文", async ({ page }) => {
    const firstScene = await createScene(project.id, {
      scene_index: 0,
      title: "第一章旧 Scene",
      goal: "守住旧线索",
      status: "canonical",
      chapter_ids: ["1"],
      scene_chunks: [{ chapter_index: 1, start_pos: 0, end_pos: 4 }],
    })
    const secondScene = await createScene(project.id, {
      scene_index: 1,
      title: "第二章新 Scene",
      goal: "推进新线索",
      status: "canonical",
      chapter_ids: ["2"],
      scene_chunks: [{ chapter_index: 2, start_pos: 0, end_pos: 4 }],
    })
    await createDraft(project.id, 1, "第 1 章", "第一章正文")
    await createDraft(project.id, 2, "第 2 章", "第二章正文")

    await reloadWorkbench(page, "writing")
    await waitWritingReady(page, { chapter: 1 })
    await selectWritingChapter(page, 1)
    await expect(page.locator(".scene-cockpit-switcher__item.active")).toContainText(firstScene.title)
    await expect(page.locator("#writing-panel-container")).toContainText(firstScene.title)

    await selectWritingChapter(page, 2)
    const secondSceneLabel = page.locator(".scene-cockpit-switcher__item", { hasText: secondScene.title })
    await secondSceneLabel.click()

    await expect(page.locator(".scene-cockpit-switcher__item.active")).toContainText(secondScene.title)
    await expect(page.locator(".scene-cockpit-switcher__item.active")).not.toContainText(firstScene.title)
    await expect(page.locator("#writing-panel-container")).toContainText(secondScene.title)
    await expect(page.locator("#writing-panel-container")).not.toContainText(firstScene.title)
  })

  test("S4-VAL-001 恢复空白正文后仍禁止发布", async ({ page }) => {
    const publishRequests = []
    const onRequest = (request) => {
      const url = new URL(request.url())
      if (request.method() === "POST" && url.pathname.startsWith(`${new URL(API_BASE).pathname}/writing/`) && url.pathname.includes("publish")) {
        publishRequests.push(url.pathname)
      }
    }
    page.on("request", onRequest)
    try {
      const created = await createDraft(project.id, 1, "第 1 章", "")
      await page.evaluate(({ projectId, draftId }) => {
        localStorage.setItem(`draft_backup_${projectId}_1_${encodeURIComponent(draftId)}`, JSON.stringify({
          project_id: projectId,
          draft_id: draftId,
          content: " \n\t ",
          title: "恢复的空白正文",
          chapter_index: 1,
          timestamp: Date.now(),
        }))
      }, { projectId: project.id, draftId: created.draft.id })

      page.once("dialog", async (dialog) => {
        expect(dialog.message()).toContain("检测到本地暂存")
        await dialog.accept()
      })
      await reloadWorkbench(page, "writing")
      await waitWritingReady(page, { chapter: 1 })
      await selectWritingChapter(page, 1)

      await expect(page.locator("#writing-title-input")).toHaveValue("恢复的空白正文")
      await expect(page.locator("#writing-editor")).toHaveValue(" \n\t ")
      await expect(page.locator("#btn-publish")).toBeDisabled()
      expect(publishRequests).toEqual([])
    } finally {
      page.off("request", onRequest)
    }
  })
})
