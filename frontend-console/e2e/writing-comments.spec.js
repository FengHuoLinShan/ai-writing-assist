import { test, expect } from "./fixtures.js"
import { waitWritingReady } from "./helpers/workbench.js"

async function savedChapter(page, projectFactory, openProjectWorkbench) {
  const project = await projectFactory({ title: "正文批注 E2E" })
  await openProjectWorkbench(project, "writing")
  await page.getByRole("button", { name: "新建章节", exact: true }).click()
  await waitWritingReady(page, { editor: true })
  const editor = page.locator("#writing-editor")
  await editor.fill("甲😀乙丙\n".repeat(80))
  await page.locator("#btn-autosave").click()
  await expect(page.locator("#writing-save-status")).toHaveText("已保存到工作稿")
  await editor.evaluate((element) => {
    element.focus()
    element.setSelectionRange(1, 4)
    element.dispatchEvent(new Event("select", { bubbles: true }))
  })
  return editor
}

test("桌面批注持久化、高亮滚动和键盘定位", async ({ page, projectFactory, openProjectWorkbench }, testInfo) => {
  const editor = await savedChapter(page, projectFactory, openProjectWorkbench)
  await page.getByRole("button", { name: "批注选中内容" }).click()
  await page.getByLabel("希望怎么修改？").fill("让语气更坚定")
  await page.getByRole("button", { name: "保存批注" }).click()
  const card = page.locator(".writing-comments__focus").first()
  await expect(card).toContainText("让语气更坚定")
  await expect(page.locator(".writing-comment-mirror .is-highlighted")).toContainText("😀乙")
  await editor.evaluate((element) => { element.scrollTop = 100; element.dispatchEvent(new Event("scroll")) })
  await expect.poll(() => page.locator(".writing-comment-mirror").evaluate((element) => element.scrollTop)).toBe(100)
  await card.focus()
  await page.keyboard.press("Enter")
  await expect.poll(() => editor.evaluate((element) => [element.selectionStart, element.selectionEnd])).toEqual([1, 4])
  await expect.poll(() => page.locator(".writing-comment-mirror .is-highlighted").evaluate((element) => {
    const highlight = element.getBoundingClientRect()
    const editor = document.querySelector("#writing-editor").getBoundingClientRect()
    return highlight.top >= editor.top && highlight.bottom <= editor.bottom
  })).toBe(true)
  await page.screenshot({ path: testInfo.outputPath("writing-comments-desktop.png") })
  await page.reload()
  await waitWritingReady(page, { editor: true })
  await expect(page.locator(".writing-comment-mirror .is-highlighted")).toContainText("😀乙")
})

test("离开页面后恢复批注任务结果，不重复轮询已完成任务", async ({ page, projectFactory, openProjectWorkbench }) => {
  const editor = await savedChapter(page, projectFactory, openProjectWorkbench)
  await page.getByRole("button", { name: "批注选中内容" }).click()
  await page.getByLabel("希望怎么修改？").fill("调整这句话")
  await page.getByRole("button", { name: "保存批注" }).click()
  const taskId = "00000000-0000-0000-0000-0000000000c1"
  let phase = "pending"
  let polls = 0
  await page.route("**/api/writing/comment-runs", (route) => route.fulfill({
    status: 201, contentType: "application/json",
    body: JSON.stringify({ task_id: taskId, status: "pending" }),
  }))
  await page.route(`**/api/tasks/${taskId}*`, (route) => {
    polls += 1
    return route.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify({ task_id: taskId, status: phase, progress: phase === "done" ? 1 : 0.3,
        result: phase === "done" ? { candidate_draft_id: "00000000-0000-0000-0000-0000000000c2" } : null }),
    })
  })
  await page.getByRole("button", { name: "执行待处理评论" }).click()
  await expect(page.getByText("Agent 正在处理…", { exact: false })).toBeVisible()
  phase = "done"
  await page.reload()
  await waitWritingReady(page, { editor: true })
  await expect(page.getByRole("button", { name: "比较修订候选" })).toBeVisible()
  expect(await editor.inputValue()).toContain("甲😀乙丙")
  await page.waitForTimeout(300)
  expect(polls).toBeLessThan(5)
})

test.describe("窄屏触摸", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true })

  test("触摸入口与批注卡片可定位原文", async ({ page, projectFactory, openProjectWorkbench }, testInfo) => {
    const editor = await savedChapter(page, projectFactory, openProjectWorkbench)
    await page.getByRole("button", { name: "批注选中内容" }).tap()
    await page.getByLabel("希望怎么修改？").fill("保留这个转折")
    await page.getByRole("button", { name: "保存批注" }).tap()
    const card = page.locator(".writing-comments__focus").first()
    await expect(card).toBeVisible()
    await card.tap()
    await expect(page.getByRole("dialog", { name: "本章资料" })).not.toBeVisible()
    await expect.poll(() => editor.evaluate((element) => [element.selectionStart, element.selectionEnd])).toEqual([1, 4])
    await expect.poll(() => page.locator(".writing-comment-mirror .is-highlighted").evaluate((element) => {
      const highlight = element.getBoundingClientRect()
      const editor = document.querySelector("#writing-editor").getBoundingClientRect()
      return highlight.top >= editor.top && highlight.bottom <= editor.bottom
    })).toBe(true)
    await page.screenshot({ path: testInfo.outputPath("writing-comments-mobile.png") })
  })
})
