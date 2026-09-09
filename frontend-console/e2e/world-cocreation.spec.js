import { test, expect } from "./fixtures.js"
import { API_BASE, API_HOST, createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"
import { openWorkbench } from "./helpers/workbench.js"

async function apiJson(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      "X-Requested-With": "XMLHttpRequest",
    },
    ...options,
  })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(`${path} -> ${response.status}: ${JSON.stringify(body).slice(0, 200)}`)
  }
  return body
}

async function createSession(projectId, overrides = {}) {
  return apiJson("/world/cocreation-sessions", {
    method: "POST",
    body: JSON.stringify({
      novel_id: projectId,
      title: "北境潮门共创",
      source: { kind: "project" },
      workflow_preset: "world_core",
      target_kind: "core_entity",
      ...overrides,
    }),
  })
}

async function appendMessage(projectId, sessionId, content, overrides = {}) {
  return apiJson(`/world/cocreation-sessions/${sessionId}/messages`, {
    method: "POST",
    body: JSON.stringify({ novel_id: projectId, content, ...overrides }),
  })
}

async function openWorldCoreWorkspace(page, project) {
  await openWorkbench(page, project, "generate")
  await page.evaluate(({ projectId }) => {
    window.location.hash = `#workbench/${projectId}/generate?preset=world_core&tab=world`
  }, { projectId: project.id })
  await expect(page.locator("[data-section='cocreation-session']")).toBeVisible({ timeout: 10000 })
}

async function approveContext(page) {
  const modal = page.locator("#modal-title")
  await expect(modal).toContainText("AI 参考资料", { timeout: 10000 })
  const start = page.getByRole("button", { name: "按这份资料开始" })
  await expect(start).toBeEnabled()
  await start.click()
}

test.describe("共创会话持久化", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("服务端会话在另一台设备上恢复，历史会话可列出", async ({ page }) => {
    const project = await createProject({ title: "共创跨设备项目", language: "zh" })
    testProjectId = project.id
    const session = await createSession(project.id)
    await appendMessage(project.id, session.id, "潮门每天开合两次。", { action: "expand" })
    await appendMessage(project.id, session.id, "决定：税率保持开放。", { kind: "decision" })

    await openWorldCoreWorkspace(page, project)
    await expect(page.locator("#generate-chat-messages")).toContainText("潮门每天开合两次。")
    await expect(page.locator("#generate-chat-messages")).toContainText("决定：税率保持开放。")
    await expect(page.locator("[data-section='cocreation-session']")).toContainText("已存服务器")
    await expect(page.locator(".generate-chat-action-badge").first()).toContainText("完善体系")

    await page.locator("[data-action='open-session-history']").click()
    await expect(page.locator("#modal-title")).toContainText("共创会话历史")
    await expect(page.locator("#modal-body")).toContainText("北境潮门共创")
    await expect(page.locator("#modal-body").locator(".badge").first()).toContainText("当前")

    // 模拟换设备：清空本机全部会话缓存后重开，内容仍从服务器恢复。
    const device2 = await page.context().newPage()
    try {
      await device2.addInitScript((host) => { window.API_HOST = host }, API_HOST)
      await device2.goto("/")
      await device2.evaluate(() => {
        localStorage.clear()
        sessionStorage.clear()
      })
      await openWorldCoreWorkspace(device2, project)
      await expect(device2.locator("#generate-chat-messages")).toContainText("潮门每天开合两次。")
      await expect(device2.locator("#generate-chat-messages")).toContainText("决定：税率保持开放。")
    } finally {
      await device2.close()
    }
  })

  test("会话聊天绑定会话与动作，刷新后不自动重复提交", async ({ page }) => {
    const project = await createProject({ title: "共创回合项目", language: "zh" })
    testProjectId = project.id
    const chatRequests = []
    await page.route("**/api/evidence/compilation/compile", async (route) => {
      const body = route.request().postDataJSON()
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          novel_id: body.novel_id,
          task: body.task,
          scope: body.scope,
          total_tokens: 120,
          budget_tokens: body.budget_tokens || 4000,
          context_fingerprint: "a".repeat(64),
          selection_state: { status: "ready", counts: {}, effective_range: {}, excluded_items: [], omitted_items: [] },
          blockers: [],
          sections: [],
          evicted: [],
          truncated: [],
          warnings: [],
        }),
      })
    })
    await page.route("**/api/evidence/compilation/confirm", async (route) => {
      const body = route.request().postDataJSON()
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({
          id: "confirmation-e2e",
          novel_id: body.novel_id,
          action: body.action,
          result_refs: [],
          result_status: "confirmed",
          stale_reasons: [],
          context_fingerprint: "a".repeat(64),
          selection_state: { status: "ready", counts: {}, effective_range: {}, excluded_items: [], omitted_items: [] },
          blockers: [],
          warnings: [],
        }),
      })
    })
    await page.route("**/api/world/cocreation-sessions/*/chat", async (route) => {
      chatRequests.push({
        url: route.request().url(),
        body: route.request().postDataJSON(),
      })
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          reply: "潮门规则需要一条维护代价。",
          model: "account-model",
          provider: "fake",
          source_snapshot: { kind: "project" },
        }),
      })
    })

    await openWorldCoreWorkspace(page, project)
    await page.locator("[data-action='world-core-pressure']").click()
    await expect(page.locator("#generate-chat-input")).toHaveValue(/压力测试/)
    await page.locator("[data-action='send-chat-message']").click()
    await approveContext(page)
    await expect(page.locator("#generate-chat-messages")).toContainText("潮门规则需要一条维护代价。", { timeout: 15000 })

    expect(chatRequests).toHaveLength(1)
    expect(chatRequests[0].url).toContain("/api/world/cocreation-sessions/")
    expect(chatRequests[0].url).not.toContain("/generation-center/chat")
    expect(chatRequests[0].body).toMatchObject({ novel_id: project.id, session_action: "pressure" })
    expect(page.locator("[data-section='cocreation-session']")).toContainText("已存服务器")

    await page.reload()
    await expect(page.locator("[data-section='cocreation-session']")).toBeVisible({ timeout: 10000 })
    await page.waitForTimeout(1500)
    expect(chatRequests).toHaveLength(1)
    await expect(page.locator("#generate-chat-messages .generate-chat-message.pending")).toHaveCount(0)
  })
})
