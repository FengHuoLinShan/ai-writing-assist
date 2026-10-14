import { test, expect } from "./fixtures.js"
import { createEntity } from "./helpers/api-client.js"
import { mockAtlas } from "./helpers/atlas-fixture.js"
import { openWorkbench } from "./helpers/workbench.js"
import { journeyId, mockRpApis } from "./helpers/rp-fixture.js"

async function mockApproval(page, projectId, label) {
  let pending = true
  const approvals = []
  await page.route("**/api/local-agent/tasks/pending?*", route => route.fulfill({
    json: { items: pending ? [{ task_id: "image-task", label }] : [] },
  }))
  await page.route("**/api/local-agent/tasks/image-task/approve", route => {
    approvals.push(route.request().postDataJSON())
    if (approvals.length === 1) return route.fulfill({
      status: 409, json: { error: "conflict", detail: "设备暂时无法确认，请重试" },
    })
    pending = false
    return route.fulfill({ json: { approved: true, waiting_device: true } })
  })
  return async () => {
    const group = page.getByRole("group", { name: `本机生成待确认：${label}` })
    await expect(group).toBeVisible()
    const approve = group.getByRole("button", { name: "允许本次生成" })
    await expect(approve).toBeDisabled()
    await group.getByRole("checkbox").check()
    await approve.click()
    await expect(group).toContainText("设备暂时无法确认，请重试")
    await expect(group.getByRole("checkbox")).toBeChecked()
    await approve.click()
    await expect(group).toHaveCount(0)
    expect(approvals).toHaveLength(2)
    expect(approvals[1]).toEqual({ novel_id: projectId, acknowledge_full_host_access: true })
  }
}

for (const width of [1280, 390]) {
  test(`${width}px 地图册图片批准失败可重试`, async ({ page, projectFactory }) => {
    await page.setViewportSize({ width, height: 844 })
    const project = await projectFactory()
    await mockAtlas(page, { candidate: null, runOverrides: {
      status: "generating", task_id: "image-task", completed_page_count: 0,
    } })
    const approve = await mockApproval(page, project.id, "地图册生成")
    await openWorkbench(page, project, "map")
    await approve()
  })

  test(`${width}px 对象图片批准失败可重试`, async ({ page, projectFactory }) => {
    await page.setViewportSize({ width, height: 844 })
    const project = await projectFactory()
    const entity = await createEntity(project.id, {
      name: "合成守门人", entity_type: "character", status: "canonical", summary: "批准夹具",
    })
    const candidate = {
      id: "candidate-image", entity_id: entity.id, status: "queued", task_id: "image-task",
      awaiting_approval: true, prompt: "合成守门人", error: null,
    }
    await page.route(`**/api/world/entities/${entity.id}/image-generation?*`, route => route.fulfill({
      json: { available: true, executor_kind: "codex", default_prompt: "合成守门人", candidates: [] },
    }))
    await page.route(`**/api/world/entities/${entity.id}/image-candidates`, route => route.fulfill({ json: candidate }))
    await page.route("**/api/world/image-candidates/candidate-image?*", route => route.fulfill({ json: candidate }))
    const approve = await mockApproval(page, project.id, "对象图片生成")
    await openWorkbench(page, project, "world", "objects")
    await page.evaluate(id => window.router.navigate(
      "world", "bible", true, new URLSearchParams({ kind: "entity", entity_id: id }),
    ), entity.id)
    await page.getByRole("button", { name: "用本机 CLI 生成", exact: true }).click()
    await page.getByRole("button", { name: "开始生成", exact: true }).click()
    await approve()
  })

  test(`${width}px RP 图片执行器不替代文字连接且刷新保留草稿`, async ({ page }) => {
    await page.setViewportSize({ width, height: 844 })
    const journey = await mockRpApis(page)
    journey.novel_id = "image-only-project"
    await page.route("**/api/account/settings/llm-connections", route => route.fulfill({
      json: { providers: [{ provider_id: "deepseek", active: true, connected: false }] },
    }))
    await page.route("**/api/local-agent/executor?*", route => route.fulfill({ json: { kind: "codex" } }))
    await page.goto(`/#interaction/${journeyId}`)
    await expect(page.getByText("当前模型尚未连接", { exact: false })).toBeVisible()
    const draft = page.getByRole("textbox", { name: "继续旅程" })
    await draft.fill("离开后仍保留的想法")
    await expect(page.locator(".rp-send-button")).toBeDisabled()
    await page.reload()
    await expect(draft).toHaveValue("离开后仍保留的想法")
    await expect(page.locator(".rp-send-button")).toBeDisabled()
  })
}
