import { expect, test } from "./fixtures.js"

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
  localStorage.setItem("novel_theme", "dark")
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
    theme: localStorage.getItem("novel_theme"),
  }))
}

test("marker 缺失的公开邮箱登录会清除旧账号数据并写入账号 marker", async ({ page }) => {
  await mockPublicAuth(page)
  await page.addInitScript(seedPrivateBrowserState, { accountId: null })

  await page.goto("/")
  await expect(page.getByRole("heading", { name: "登录或注册" })).toBeVisible()
  await page.getByLabel("邮箱", { exact: true }).fill("writer@example.com")
  await page.getByLabel("邮箱验证码", { exact: true }).fill("123456")
  await page.getByRole("button", { name: "发送验证码" }).click()
  await page.getByRole("checkbox").check()
  await page.getByRole("button", { name: "邮箱登录" }).click()

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

  await expect(page.getByRole("heading", { name: "登录或注册" })).toBeVisible()
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
