import { expect, test } from "./fixtures.js"
import {
  createProject,
  cleanupProject,
  createWorldBiblePage,
  createWorldBibleDraft,
  waitForBackend,
} from "./helpers/api-client.js"

function json(route, status, body) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  })
}

async function mockPublicAuth(page, { initiallySignedIn = false } = {}) {
  let signedIn = initiallySignedIn
  let logoutRequests = 0
  const account = {
    id: "account-new",
    status: "active",
    identity_type: "email",
    support_code: "U-E2ELOGIN",
  }
  await page.route("**/api/auth/config", (route) => json(route, 200, {
    auth_mode: "public",
    email_enabled: true,
    wechat_enabled: false,
    terms_url: "/legal/terms",
    privacy_url: "/legal/privacy",
    support_email: "support@example.test",
  }))
  await page.route("**/api/auth/me", (route) => (
    signedIn
      ? json(route, 200, account)
      : json(route, 401, { detail: "Authentication required" })
  ))
  await page.route("**/api/auth/email/request-code", (route) => json(route, 200, {
    accepted: true,
    challenge_id: "challenge-e2e",
    expires_in: 300,
    resend_after: 60,
  }))
  await page.route("**/api/auth/email/verify", (route) => {
    signedIn = true
    return json(route, 200, account)
  })
  await page.route("**/api/auth/logout", (route) => {
    logoutRequests += 1
    signedIn = false
    return json(route, 200, { logged_out: true })
  })
  return { account, logoutRequests: () => logoutRequests }
}

function seedPrivateBrowserState({ accountId = null } = {}) {
  const testSeedSentinel = "__e2e_auth_private_state_seeded"
  if (sessionStorage.getItem(testSeedSentinel)) return
  sessionStorage.setItem(testSeedSentinel, "1")

  if (accountId) localStorage.setItem("novel_accountId", accountId)
  localStorage.setItem("novel_currentProjectId", "private-project-old")
  localStorage.setItem(
    "novel_currentProject",
    JSON.stringify({ id: "private-project-old", title: "旧账号项目" }),
  )
  localStorage.setItem("draft_backup_private-project-old_1", JSON.stringify({
    title: "旧账号标题",
    content: "旧账号未保存正文",
  }))
  localStorage.setItem(
    "generate_world_workspace_state_v2_private-project-old_project_core_entity",
    JSON.stringify({ messages: [{ role: "user", content: "旧账号生成会话" }] }),
  )
  localStorage.setItem("novel_active_workflows_v1", JSON.stringify([{
    taskId: "private-task-old",
    projectId: "private-project-old",
  }]))
  sessionStorage.setItem("workspace-rail:private-project-old:writing:assistant", "closed")
  sessionStorage.setItem("workflow-progress-card:private-task-old", "open")
  localStorage.setItem("nc-theme", "dark")
}

async function storedPrivateState(page) {
  return page.evaluate(() => ({
    accountId: localStorage.getItem("novel_accountId"),
    projectId: localStorage.getItem("novel_currentProjectId"),
    project: localStorage.getItem("novel_currentProject"),
    draft: localStorage.getItem("draft_backup_private-project-old_1"),
    generate: localStorage.getItem(
      "generate_world_workspace_state_v2_private-project-old_project_core_entity",
    ),
    workflows: localStorage.getItem("novel_active_workflows_v1"),
    rail: sessionStorage.getItem("workspace-rail:private-project-old:writing:assistant"),
    workflowCard: sessionStorage.getItem("workflow-progress-card:private-task-old"),
    theme: localStorage.getItem("nc-theme"),
  }))
}

test("marker 缺失的公开邮箱登录会清除旧账号数据并写入账号 marker", async ({ page }) => {
  await mockPublicAuth(page)
  await page.addInitScript(seedPrivateBrowserState, { accountId: null })

  await page.goto("/")
  await expect(page.getByRole("heading", { name: "今天想怎样进入故事？" })).toBeVisible()
  await page.getByRole("button", { name: /我是作家/ }).click()
  await expect(page.getByRole("heading", { name: "登录或注册" })).toBeVisible()
  await page.getByLabel("邮箱", { exact: true }).fill("writer@example.com")
  await page.getByLabel("邮箱验证码", { exact: true }).fill("123456")
  await page.getByRole("button", { name: "发送验证码" }).click()
  await page.getByRole("checkbox").check()
  await page.getByRole("button", { name: "邮箱登录" }).click()

  await expect(page.locator("#project-catalog-title")).toBeVisible()
  expect(await storedPrivateState(page)).toEqual({
    accountId: "account-new",
    projectId: null,
    project: null,
    draft: null,
    generate: null,
    workflows: null,
    rail: null,
    workflowCard: null,
    theme: "dark",
  })
})

test("公开模式启动时账号变化会清除旧账号数据", async ({ page }) => {
  await mockPublicAuth(page, { initiallySignedIn: true })
  await page.addInitScript(seedPrivateBrowserState, { accountId: "account-old" })

  await page.goto("/")

  await expect(page.getByRole("heading", { name: "今天想怎样进入故事？" })).toBeVisible()
  expect(await storedPrivateState(page)).toEqual({
    accountId: "account-new",
    projectId: null,
    project: null,
    draft: null,
    generate: null,
    workflows: null,
    rail: null,
    workflowCard: null,
    theme: "dark",
  })
})

test("真实退出入口会清除账号数据并保留主题", async ({ page }) => {
  const auth = await mockPublicAuth(page, { initiallySignedIn: true })
  await page.addInitScript(seedPrivateBrowserState, { accountId: "account-new" })

  await page.goto("/")
  await expect(page.getByRole("heading", { name: "今天想怎样进入故事？" })).toBeVisible()
  await page.getByRole("button", { name: /我是作家/ }).click()
  await expect(page.locator("#topbar")).toBeVisible()
  await page.getByRole("button", { name: "账户菜单", exact: true }).click()
  await page.getByRole("button", { name: /账户信息/ }).click()
  const dialog = page.getByRole("dialog", { name: "账号" })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole("button", { name: "关闭账号设置", exact: true })).toBeVisible()
  await dialog.getByText("删除账号", { exact: true }).click()
  await expect(dialog.getByLabel("账号删除验证码", { exact: true })).toBeVisible()
  await dialog.getByRole("button", { name: "退出登录" }).click()

  await expect(page.getByRole("heading", { name: "今天想怎样进入故事？" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "登录或注册" })).toHaveCount(0)
  expect(auth.logoutRequests()).toBe(1)
  expect(await storedPrivateState(page)).toEqual({
    accountId: null,
    projectId: null,
    project: null,
    draft: null,
    generate: null,
    workflows: null,
    rail: null,
    workflowCard: null,
    theme: "dark",
  })
})

test("账号切换后世界资料编辑从服务器恢复，旧账号本地状态不泄漏", async ({ page }) => {
  test.setTimeout(90000)
  await waitForBackend(60000)
  await mockPublicAuth(page, { initiallySignedIn: true })
  await page.addInitScript(seedPrivateBrowserState, { accountId: "account-old" })

  const project = await createProject({ title: "账号切换世界资料", language: "zh" })
  try {
    const worldPage = await createWorldBiblePage(project.id, {
      title: "潮门志",
      page_type: "background",
      free_text: "旧正文第一段。",
    })
    await createWorldBibleDraft(project.id, {
      page_id: worldPage.id,
      title: "潮门志",
      page_type: "background",
      free_text: "旧正文第一段。\n\n新增：潮门每日开合两次。",
    })

    // 账号 A：进入资料页编辑，产生一次服务器工作稿修改。
    await page.goto("/")
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })
    await openBibleEditor(page, project, worldPage.id)
    const editor = page.locator("#bible-free-text")
    await expect(editor).toHaveValue(/潮门每日开合两次/, { timeout: 10000 })
    await editor.fill("旧正文第一段。\n\n潮门每日开合两次。\n\n切换前新增的段落。")
    await expect(page.locator("#bible-autosave-status")).toHaveAttribute("data-autosave-status", "idle", { timeout: 15000 })

    // 退出账号：旧账号的本地数据被清空。
    await page.goto("/")
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })
    await page.getByRole("button", { name: /我是作家/ }).click()
    await page.getByRole("button", { name: "账户菜单", exact: true }).click()
    await page.getByRole("button", { name: /账户信息/ }).click()
    const dialog = page.getByRole("dialog", { name: "账号" })
    await expect(dialog).toBeVisible()
    await dialog.getByRole("button", { name: "退出登录" }).click()
    await expect(page.getByRole("heading", { name: "今天想怎样进入故事？" })).toBeVisible()
    const cleared = await storedPrivateState(page)
    expect(cleared.accountId).toBeNull()
    expect(cleared.projectId).toBeNull()
    expect(cleared.draft).toBeNull()
    expect(cleared.generate).toBeNull()

    // 重新登录同一账号：从服务器工作稿恢复，切换前的编辑没有丢失。
    await expect(page.getByRole("heading", { name: "今天想怎样进入故事？" })).toBeVisible()
    await page.getByRole("button", { name: /我是作家/ }).click()
    await page.getByLabel("邮箱", { exact: true }).fill("writer@example.com")
    await page.getByLabel("邮箱验证码", { exact: true }).fill("123456")
    await page.getByRole("button", { name: "发送验证码" }).click()
    await page.getByRole("checkbox").check()
    await page.getByRole("button", { name: "邮箱登录" }).click()
    await expect(page.locator("#project-catalog-title")).toBeVisible()

    await openBibleEditor(page, project, worldPage.id)
    await expect(page.locator("#bible-free-text")).toHaveValue(/切换前新增的段落/, { timeout: 10000 })
  } finally {
    try { await cleanupProject(project.id) } catch {}
  }
})

async function openBibleEditor(page, project, pageId) {
  await page.evaluate(async ({ projectData, pageId: pid }) => {
    localStorage.setItem("novel_currentProjectId", projectData.id)
    localStorage.setItem("novel_currentProject", JSON.stringify(projectData))
    state.currentProjectId = projectData.id
    state.currentProject = projectData
    await window.router.navigate("world", "bible", true, new URLSearchParams({ page_id: pid }))
  }, { projectData: project, pageId })
  await expect(page.locator(".world-page-reader")).toBeVisible({ timeout: 15000 })
  await page.locator("[data-action='world-reader-edit']").click()
  await expect(page.locator("#bible-free-text")).toBeVisible({ timeout: 10000 })
}
