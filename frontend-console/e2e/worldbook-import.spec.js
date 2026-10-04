// 世界书目录导入主链路 E2E（M4）：
// 目录选择 → 预览 → 应用 → 工作稿 → 发布 → 增量 → 冲突。
//
// 目录选择：webkitdirectory 输入只接受真实目录路径，测试在临时目录写入
// 合成 Wiki 后整目录提交——与真实浏览器目录选择同一提交路径
// （webkitRelativePath 含所选根目录名）。
// 结果一律以 API/数据库为准：导入只产生未发布工作稿，发布经既有确认弹窗；
// 冲突不覆盖工作稿内容。
import { mkdtemp, mkdir, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join } from "node:path"

import { test, expect } from "./fixtures.js"
import { openWorkbench } from "./helpers/workbench.js"
import {
  cleanupProject,
  createProject,
  listWorldBibleDrafts,
  listWorldBiblePages,
  updateWorldBibleDraft,
  waitForBackend,
} from "./helpers/api-client.js"
import { SEL } from "./helpers/selectors.js"

const ENTRY_BODY_V1 = "---\ntitle: 理法之环\npage_type: concept\n---\n以理法编织万物的环，参见 [[本体定位]]。"
const ENTRY_BODY_V2 = "---\ntitle: 理法之环\npage_type: concept\n---\n以理法编织万物的环；第二版补充环律细节，参见 [[本体定位]]。"
const ENTRY_BODY_V3 = "---\ntitle: 理法之环\npage_type: concept\n---\n以理法编织万物的环；第三版重写环律，参见 [[本体定位]]。"
const RELATED_BODY = "---\ntitle: 本体定位\npage_type: concept\n---\n本体定位正文。"
const RAW_BODY = "作者原始笔记：尚未整理的真相。"

async function writeWiki(entryBody) {
  // 根目录名不携带「理法之环」，保证入口检测（最短含提示名 rel_path）
  // 唯一命中真正的入口页。
  const root = await mkdtemp(join(tmpdir(), "worldbook-import-e2e-"))
  await mkdir(join(root, "环世界", "concepts", "真名回响"), { recursive: true })
  await mkdir(join(root, "环世界", "raw"), { recursive: true })
  await writeFile(join(root, "环世界", "concepts", "真名回响", "理法之环.md"), entryBody, "utf-8")
  await writeFile(join(root, "环世界", "concepts", "真名回响", "本体定位.md"), RELATED_BODY, "utf-8")
  await writeFile(join(root, "环世界", "raw", "原始笔记.txt"), RAW_BODY, "utf-8")
  return root
}

async function openMoreTools(page) {
  // 桌面：编辑态经资料库工具条，图鉴态经侧栏工具卡；窄屏经工作台抽屉
  if ((page.viewportSize()?.width || 1280) > 760) {
    const toolbar = page.locator(".world-bible-toolbar").getByRole("button", { name: "更多工具", exact: true })
    if (await toolbar.count()) {
      await toolbar.first().click()
      return
    }
    await page.locator("#sidebar-context-slot button", { hasText: "更多工具" }).first().click()
    return
  }
  await page.locator(".workspace-tools-trigger").click()
  await page.locator(".workspace-drawer .workspace-tools")
    .locator("button:visible", { hasText: "更多工具" })
    .first()
    .click()
}

async function openImportPanel(page) {
  await openMoreTools(page)
  await page.getByRole("dialog").getByRole("button", { name: "导入目录", exact: true }).click()
  const panel = page.locator(".worldbook-import-panel")
  await expect(panel).toBeVisible()
  return panel
}

async function selectDirectory(page, wikiRoot) {
  await page.locator(".worldbook-import-panel input[type='file']").setInputFiles(wikiRoot)
}

async function previewAndApply(page, datasetName, { intent = "new", counts = {}, label = "" } = {}) {
  await page.locator("[data-action='worldbook-import-format']").selectOption("obsidian")
  if (intent !== "new") {
    await page.locator("input[name='worldbook-import-intent'][value='continue']").check()
  }
  await page.locator("[data-action='worldbook-import-dataset-name']").fill(datasetName)
  await page.locator("[data-action='worldbook-import-preview']").click()
  await expect(page.locator(".worldbook-import-counts")).toBeVisible({ timeout: 15000 })
  for (const [countLabel, value] of Object.entries(counts)) {
    await expect(page.locator(".worldbook-import-counts")).toContainText(`${countLabel} ${value}`)
  }
  const dialogAccept = (dialog) => void dialog.accept()
  page.on("dialog", dialogAccept)
  // toast 不自动消失，不能只匹配文案（旧 toast 会残留）；以本次 apply 响应为准
  const applyResponse = page.waitForResponse((response) => (
    response.request().method() === "POST"
    && response.url().includes("/imports/")
    && response.url().includes("/apply")
  )).catch((err) => {
    throw new Error(`[${label}] apply 请求未发出 (url=${page.url()}): ${err.message}`)
  })
  try {
    await page.locator("[data-action='worldbook-import-apply']").click()
  } finally {
    page.off("dialog", dialogAccept)
  }
  const applied = await applyResponse
  if (!applied.ok()) {
    throw new Error(`[${label}] 应用导入失败 (${applied.status()}): ${await applied.text()}`)
  }
  const applyResult = await applied.json()
  await expect(page.locator(SEL.toastContainer)).toContainText(
    `导入完成：${applyResult.draft_ids.length} 个工作稿`,
    { timeout: 15000 },
  )
  return applyResult
}

test.describe("世界书目录导入主链路", () => {
  let testProject = null
  let pageErrors = []

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    pageErrors = []
    page.on("pageerror", (err) => pageErrors.push(err.message))
    testProject = await createProject({
      title: "世界书导入 E2E 项目",
      genre: "fantasy",
      language: "zh",
    })
    await openWorkbench(page, testProject, "world", "bible")
    await page.evaluate(() => window.errorLog?.clear?.())
  })

  test.afterEach(async () => {
    if (testProject?.id) {
      try { await cleanupProject(testProject.id) } catch {}
      testProject = null
    }
  })

  test("目录选择→预览→应用→工作稿→发布→增量→冲突", async ({ page }) => {
    test.setTimeout(300_000)
    const wikiRoot = await writeWiki(ENTRY_BODY_V1)

    // 1. 目录选择：入口页自动纳入，关联页只提示；内容保持在浏览器本地
    const panel = await openImportPanel(page)
    await selectDirectory(page, wikiRoot)
    await expect(panel).toContainText("已选 1 页")
    await expect(panel).toContainText("直接关联中未纳入的页面（1）")
    await expect(panel).toContainText("本体定位")

    // 纳入候选页后再预览（raw 笔记未被作者选择，不进入本次范围）
    await panel.locator("[data-action='worldbook-import-adopt']").click()
    await expect(panel).toContainText("已选 2 页")

    // 2-3. 预览并应用：只产生未发布工作稿；项目内没有任何已发布页（以 API 为准）
    await previewAndApply(page, "理法之环 E2E", { label: "首轮" })
    const drafts = await listWorldBibleDrafts(testProject.id)
    expect(drafts.items).toHaveLength(2)
    for (const draft of drafts.items) {
      expect(draft.page_meta_json?.worldbook_import?.dataset_name).toBe("理法之环 E2E")
      expect(draft.page_meta_json.worldbook_import.source_authority_hint).toBe("candidate")
      expect(draft.page_meta_json.worldbook_import.dataset_key).toBeTruthy()
      // source_path 保留原始提交路径（含所选根目录名）
      expect(draft.page_meta_json.worldbook_import.source_path.includes("环世界/concepts/真名回响/")).toBe(true)
    }
    const pagesAfterImport = await listWorldBiblePages(testProject.id)
    expect(pagesAfterImport.items).toHaveLength(0)

    // 4. 工作稿 → 发布：打开入口页工作稿，经既有发布确认弹窗走 Canon 门禁
    const entryDraft = drafts.items.find((draft) => draft.title === "理法之环")
    await expect(page).toHaveURL(/draft_id=/)
    await page.evaluate(({ projectId, draftId }) => {
      window.location.hash = `#workbench/${projectId}/world/bible?draft_id=${draftId}`
    }, { projectId: testProject.id, draftId: entryDraft.id })
    await expect(page.locator(".world-bible-workspace")).toContainText("理法之环")
    const publishResponse = page.waitForResponse((response) => (
      response.request().method() === "POST"
      && response.url().includes("/api/world/bible/drafts/")
      && response.url().includes("/publish")
      && response.status() === 200
    ))
    await page.locator("[data-action='bible-publish-page']").click()
    await expect(page.getByRole("dialog")).toContainText("发布前影响核对")
    await page.getByRole("button", { name: "确认发布", exact: true }).click()
    const publishedPage = await (await publishResponse).json()
    if (publishedPage.validation_receipt) {
      await expect(page.getByRole("dialog")).toContainText("发布完成 · 检查回执")
      await page.getByRole("button", { name: "知道了", exact: true }).click()
    }
    await expect(page.locator(".world-page-reader")).toBeVisible({ timeout: 15000 })
    await expect(page.locator(".world-page-reader__meta")).toContainText("已采用")
    const pagesAfterPublish = await listWorldBiblePages(testProject.id)
    expect(pagesAfterPublish.items).toHaveLength(1)
    expect(pagesAfterPublish.items[0].page_meta_json?.worldbook_import?.dataset_name).toBe("理法之环 E2E")

    // 5. 增量：同资料集改一页来源重导 → 已发布页的更新生成新工作稿，其余保留
    await writeFile(join(wikiRoot, "环世界", "concepts", "真名回响", "理法之环.md"), ENTRY_BODY_V2, "utf-8")
    const panelForUpdate = await openImportPanel(page)
    await selectDirectory(page, wikiRoot)
    await panelForUpdate.locator("[data-action='worldbook-import-adopt']").click()
    await expect(panelForUpdate).toContainText("已选 2 页")
    await previewAndApply(page, "理法之环 E2E", {
      intent: "continue",
      counts: { "更新": 1, "保留": 1 },
      label: "增量轮",
    })
    const draftsAfterUpdate = await listWorldBibleDrafts(testProject.id)
    const updatedEntryDraft = draftsAfterUpdate.items.find((draft) => draft.title === "理法之环")
    expect(updatedEntryDraft, `更新后工作稿清单: ${JSON.stringify(draftsAfterUpdate.items?.map((d) => d.title))}; 页面错误: ${JSON.stringify(pageErrors)}`).toBeTruthy()
    expect(updatedEntryDraft.free_text).toContain("第二版补充环律细节")

    // 6. 冲突：作者本地编辑 + 来源再变 → 冲突进队列且不覆盖工作稿
    await updateWorldBibleDraft(testProject.id, updatedEntryDraft.id, {
      free_text: "作者本地修改的环律。",
      expected_updated_at: updatedEntryDraft.updated_at,
    })
    await writeFile(join(wikiRoot, "环世界", "concepts", "真名回响", "理法之环.md"), ENTRY_BODY_V3, "utf-8")
    const panelForConflict = await openImportPanel(page)
    await selectDirectory(page, wikiRoot)
    await panelForConflict.locator("[data-action='worldbook-import-adopt']").click()
    await expect(panelForConflict).toContainText("已选 2 页")
    await page.locator("[data-action='worldbook-import-format']").selectOption("obsidian")
    await page.locator("input[name='worldbook-import-intent'][value='continue']").check()
    await page.locator("[data-action='worldbook-import-dataset-name']").fill("理法之环 E2E")
    await previewAndApply(page, "理法之环 E2E", {
      intent: "continue",
      counts: { "冲突": 1, "保留": 1 },
      label: "冲突轮",
    })
    await expect(page.locator(SEL.toastContainer)).toContainText("待核对冲突", { timeout: 15000 })
    // 工作稿内容未被覆盖；无重复工作稿
    const draftsAfterConflict = await listWorldBibleDrafts(testProject.id)
    const conflictDrafts = draftsAfterConflict.items.filter((draft) => draft.title === "理法之环")
    expect(conflictDrafts).toHaveLength(1)
    expect(conflictDrafts[0].free_text).toBe("作者本地修改的环律。")
    expect(pageErrors, `页面错误: ${JSON.stringify(pageErrors)}`).toHaveLength(0)
  })

  test("390px 窄屏下导入面板选项与预览操作保持可用", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    const wikiRoot = await writeWiki(ENTRY_BODY_V1)
    const panel = await openImportPanel(page)
    await selectDirectory(page, wikiRoot)
    await expect(panel).toContainText("已选 1 页")
    await expect(panel.locator("[data-action='worldbook-import-format']")).toBeVisible()
    await expect(panel.locator("[data-action='worldbook-import-commit-mode']")).toBeVisible()
    await expect(panel.locator("[data-action='worldbook-import-dataset-name']")).toBeVisible()
    await panel.locator("[data-action='worldbook-import-dataset-name']").fill("窄屏资料集")
    await panel.locator("[data-action='worldbook-import-preview']").click()
    await expect(panel.locator(".worldbook-import-counts")).toBeVisible({ timeout: 15000 })
    await expect(panel.locator(".worldbook-import-counts")).toContainText("新建 1")
    // 窄屏下无横向溢出
    const overflow = await panel.evaluate((el) => el.scrollWidth - el.clientWidth)
    expect(overflow).toBeLessThanOrEqual(1)
  })
})
