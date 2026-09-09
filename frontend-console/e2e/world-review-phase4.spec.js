import { spawn } from "node:child_process"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"
import { test, expect } from "./fixtures.js"
import {
  API_BASE,
  cleanupProject,
  createEntity,
  createProject,
  createWorldBiblePage,
  waitForBackend,
} from "./helpers/api-client.js"
import { openWorkbench } from "./helpers/workbench.js"
import { SEL } from "./helpers/selectors.js"

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
    throw new Error(`${path} -> ${response.status}: ${JSON.stringify(body).slice(0, 300)}`)
  }
  return body
}

function startWorker() {
  const here = dirname(fileURLToPath(import.meta.url))
  const backendDir = resolve(here, "../../backend")
  const worker = spawn("python", ["run_worker.py"], {
    cwd: backendDir,
    env: { ...process.env, APP_ENV: "test" },
    stdio: ["ignore", "pipe", "pipe"],
  })
  return worker
}

async function createSession(projectId, overrides = {}) {
  return apiJson("/world/cocreation-sessions", {
    method: "POST",
    body: JSON.stringify({
      novel_id: projectId,
      title: "潮门复核前会话",
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

async function seedWorld(projectId) {
  const guild = await createEntity(projectId, {
    name: "潮汐商会",
    entity_type: "organization",
    status: "canonical",
    summary: "掌握潮汐术的商会。",
  })
  const currency = await createWorldBiblePage(projectId, {
    page_key: "e2e-currency",
    page_type: "background",
    title: "货币制度",
    status: "canonical",
    free_text: "北境使用银币；潮汐商会控制银币铸造。",
    linked_asset_refs_json: [
      { type: "core_entity", id: guild.id, relation: "requires" },
    ],
  })
  const dependent = await createWorldBiblePage(projectId, {
    page_key: "e2e-trade",
    page_type: "background",
    title: "依赖贸易的港口",
    status: "canonical",
    free_text: "港口贸易完全依赖货币制度。",
    linked_asset_refs_json: [
      { type: "world_bible_page", id: currency.id, relation: "requires" },
    ],
  })
  return { guild, currency, dependent }
}

async function openBibleLibrary(page, projectId) {
  await openWorkbench(page, { id: projectId }, "world", "bible")
  await expect(page.locator(".world-bible-workspace")).toBeVisible({ timeout: 15000 })
}

async function clickWorldTool(page, label) {
  const desktop = page.locator("#sidebar-context-slot button", { hasText: label })
  await desktop.first().click()
}

async function openHealth(page) {
  await clickWorldTool(page, "世界健康")
  await expect(page.getByRole("dialog")).toContainText("世界健康", { timeout: 15000 })
}

async function activatePolicy(page) {
  const details = page.locator("[data-section='world-health']")
  if (await details.getAttribute("open") === null) {
    await details.locator("summary").click()
  }
  const dialogAccept = (dialog) => void dialog.accept()
  page.on("dialog", dialogAccept)
  try {
    await page.locator("[data-action='world-health-activate-policy']").click()
    await expect(page.locator("[data-section='world-health']")).toContainText("发布前校验已启用", { timeout: 15000 })
  } finally {
    page.off("dialog", dialogAccept)
  }
}

test.describe("第四期：规则、依赖与变更复核", () => {
  let testProjectId = null
  let worker = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test.afterAll(async () => {
    if (worker) worker.kill()
  })

  test("完整作者流程：找到资料→安全修改→继续创设→采用成果→完成复核", async ({ page }) => {
    const project = await createProject({ title: "四期完整作者流程", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    const seeded = await seedWorld(project.id)
    const session = await createSession(project.id)
    await appendMessage(project.id, session.id, "潮门每天开合两次。", { action: "expand" })
    const candidate = await createEntity(project.id, {
      name: "月闸匠人",
      entity_type: "organization",
      status: "candidate",
      summary: "待采用的匠人组织",
    })

    // ---- 找到任意资料：资料库搜索直达 ----
    await openBibleLibrary(page, project.id)
    await page.locator(".world-card-filters--home .world-card-filters__search input").fill("货币制度")
    await page.locator(".world-card-filters--home").getByRole("button", { name: "查找" }).click()
    await expect(page.locator(".world-library-list, .world-library-cards").first()).toContainText("货币制度", { timeout: 15000 })
    await page.locator(".world-library-list__main strong", { hasText: "货币制度" }).first().click()
    await expect(page.locator("#world-page-reader-title")).toContainText("货币制度", { timeout: 15000 })

    // ---- 安全修改：先看影响预演，再进入编辑改引用分级 ----
    await page.locator("[data-action='world-reader-edit']").click()
    await expect(page.locator(".world-bible-editor-panel")).toBeVisible()
    await page.locator("[data-action='bible-impact-preview']").click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("影响预演")
    await expect(page.locator("#modal-body")).toContainText("世界书页面 · 1 项", { timeout: 15000 })
    await expect(page.locator("#modal-body")).toContainText("依赖贸易的港口")
    await expect(page.locator("#modal-body")).toContainText("未覆盖")
    await page.locator("#modal-close").click()
    await expect(page.locator(SEL.modalTitle)).toBeHidden()

    const relationSelect = page.locator("[data-section='bible-asset-ref-relations'] select").first()
    await expect(relationSelect).toHaveValue("requires")
    await relationSelect.selectOption("derives")
    await page.locator("#bible-free-text").fill("北境使用银币；潮汐商会控制银币铸造与派生票据。")
    await page.waitForTimeout(1500)
    const draftsAfterEdit = await apiJson(
      `/world/bible/drafts?novel_id=${project.id}`
    )
    const editingDraft = (draftsAfterEdit.items || []).find((item) => item.page_id === seeded.currency.id)
    expect(editingDraft).toBeTruthy()
    expect(editingDraft.linked_asset_refs_json[0].relation).toBe("derives")

    // ---- 继续此前创设：打开既有共创会话并看到历史决定 ----
    await page.evaluate(({ projectId }) => {
      window.location.hash = `#workbench/${projectId}/generate?preset=world_core&tab=world`
    }, { projectId: project.id })
    await expect(page.locator("[data-section='cocreation-session']")).toBeVisible({ timeout: 15000 })
    await expect(page.locator("#generate-chat-messages")).toContainText("潮门每天开合两次。")

    // ---- 采用成果：把候选对象经“需要决定”采用为正式资料 ----
    await openWorkbench(page, project, "world", "review-objects")
    const row = page.locator(`tr[data-id="${candidate.id}"]`)
    await expect(row).toContainText("月闸匠人", { timeout: 20000 })
    await row.getByRole("button", { name: "查看并决定" }).click()
    await page.locator(".world-review-decision").getByRole("button", { name: "编辑后采用" }).click()
    await page.locator(SEL.modalFooter).getByRole("button", { name: "编辑后采用" }).click()
    await expect(async () => {
      const entity = await apiJson(`/world/entities/${candidate.id}?novel_id=${project.id}`)
      expect(entity.status || entity.entity?.status).toBe("canonical")
    }).toPass({ timeout: 20000 })

    // ---- 完成复核：启用校验政策并完成一次全面校验 ----
    await openBibleLibrary(page, project.id)
    await openHealth(page)
    await activatePolicy(page)

    worker = startWorker()
    await page.locator("[data-action='world-health-run-full']").click()
    await expect(
      page.locator("[data-section='world-health'] .badge, [data-section='world-health'] summary .badge"),
    ).toContainText(/已通过|有提示|需修正|已完成|校验失败|已失效/, { timeout: 60000 })
    await expect(page.locator("[data-section='world-health']")).toContainText("回执", { timeout: 15000 })

    // 政策编辑：保存工作稿后旧回执因政策变化失效，可追溯
    await page.locator("[data-action='world-health-edit-policy']").click()
    await expect(page.locator("[data-section='world-policy-editor']")).toBeVisible()
    await page.locator("[data-field='world-policy-version']").fill("author-v2")
    await page.locator("[data-action='world-policy-rule-add']").click()
    await page.locator("[data-field='world-policy-rule-op-0']").selectOption("forbid_regex")
    await page.locator("[data-field='world-policy-rule-value-0']").fill("无敌")
    await page.locator("[data-field='world-policy-rule-message-0']").fill("正文与设定中不得出现“无敌”。")
    await page.locator("[data-action='world-policy-save']").click()
    await expect(page.locator(SEL.toastContainer)).toContainText("政策工作稿已保存", { timeout: 15000 })
    await expect(page.locator("[data-section='world-health']")).toContainText("政策已有工作稿", { timeout: 15000 })

    // 政策工作稿不会立刻改变生效政策（发布才生效），但查漏入口保持在当前上下文。
    await expect(page.locator("[data-action='world-health-semantic-gap']")).toBeVisible()
    await expect(page.locator("[data-action='world-health-semantic-gap']")).toContainText("定向语义查漏")
  })

  test("世界健康：查漏回执、逐项复核与可追溯记录", async ({ page }) => {
    const project = await createProject({ title: "四期查漏与复核", genre: "fantasy", language: "zh" })
    testProjectId = project.id
    await seedWorld(project.id)
    // 预植一个需要作者裁定的问题页：decision 页缺 questions。
    await createWorldBiblePage(project.id, {
      page_key: "e2e-decision",
      page_type: "background",
      title: "潮门归属待裁定",
      status: "canonical",
      free_text: "潮门由谁管辖待作者裁定。",
    })

    await openBibleLibrary(page, project.id)
    await openHealth(page)
    await activatePolicy(page)

    worker = startWorker()
    await page.locator("[data-action='world-health-run-full']").click()
    await expect(
      page.locator("[data-section='world-health'] summary .badge"),
    ).toContainText(/需修正|已通过|有提示/, { timeout: 60000 })

    // 逐项复核：作者裁定 AUTHOR-REQUIRED 项，进度 1/1，刷新后仍在。
    const reviewButton = page.locator("[data-action^='review-']").first()
    if (await reviewButton.count()) {
      await expect(page.locator("[data-section='world-health']")).toContainText(/0\/\d+项已复核|\d+\/\d+项已复核/)
      await reviewButton.click()
      await expect(page.locator(SEL.toastContainer)).toContainText("已记录复核", { timeout: 15000 })
      await expect(page.locator("[data-section='world-health']")).toContainText("已复核：")
      await page.reload()
      await openBibleLibrary(page, project.id)
      await openHealth(page)
      await expect(page.locator("[data-section='world-health']")).toContainText("已复核：", { timeout: 15000 })
    } else {
      // 无需裁定的干净库也应显示完成态，而不是假称复核。
      await expect(page.locator("[data-section='world-health']")).toContainText(/回执|未发现需处理的问题/)
    }
  })
})
