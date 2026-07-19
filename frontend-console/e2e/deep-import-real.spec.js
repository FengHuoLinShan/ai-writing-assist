/**
 * 深度导入真实 E2E 测试 — 走 POST /api/imports/deep/sync 同步路径
 *
 * 此测试不覆盖浏览器关闭恢复、后台任务轮询等异步场景。
 * 异步深度导入的浏览器恢复/轮询覆盖在 deep-import.spec.js 中。
 *
 * 默认跳过，避免本地/CI 默认 E2E 调用真实 LLM：
 *   ENABLE_REAL_LLM=1 npx playwright test deep-import-real.spec.js
 *
 * 流程：创建项目 → 上传 6 章 → 深度导入 1-6 章（同步模式 sync）→
 *       大纲界面验证 Scene 卡 → 写作工作台验证 Scene 树
 */
import { test, expect } from "./fixtures.js"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import {
  API_BASE,
  createProject, cleanupProject, waitForBackend,
  listScenesOrdered,
} from "./helpers/api-client.js"
import path from "path"
import { fileURLToPath } from "url"

const __dirname = path.dirname(fileURLToPath(import.meta.url))
// 深度导入同步执行需要时间（LLM 调用），给充足的超时
const SYNC_DEEP_TIMEOUT = 240_000
const IMPORT_TIMEOUT = 30_000
const ENABLED = process.env.ENABLE_REAL_LLM === "1"

test.describe("深度导入真实流水线 (无 Mock)", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    if (!ENABLED) {
      test.skip(true, "未设置 ENABLE_REAL_LLM=1，跳过真实 LLM 深度导入验收")
    }
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "深度导入真实验证",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openWorkbench(page, project, "writing")
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("完整深度导入流程：上传 6 章 → 深度导入 → 验证 Scene 卡", async ({ page }) => {
    // Navigate to project view for file upload
    await page.evaluate(() => window.router.navigate("project"))
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })
    // ============================================================
    // Step 1: 在项目视图上传 6 章小说文件
    // ============================================================
    await page.locator('[data-action="toggle-import"]').click()
    await expect(page.locator("#pv-import-file")).toBeVisible()

    const filePath = path.join(
      __dirname, "helpers", "fixtures", "six-chapter-novel.txt",
    )
    await page.locator("#pv-import-file").setInputFiles(filePath)
    await page.locator('[data-action="upload-file"]').click()

    await expect(page.locator(SEL.toastContainer)).toContainText(
      "导入完成", { timeout: IMPORT_TIMEOUT },
    )
    console.log("[E2E] File import completed")

    // ============================================================
    // Step 2: 通过同步 API 直接执行深度导入
    // ============================================================
    console.log("[E2E] Starting synchronous deep import via API...")

    // 直接用 fetch 调用同步端点，等待完整返回
    const deepResult = await page.evaluate(async ({ projectId, apiBase }) => {
      const resp = await fetch(`${apiBase}/imports/deep/sync`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          novel_id: projectId,
          start_chapter: 1,
          end_chapter: 6,
        }),
      })
      if (!resp.ok) {
        const text = await resp.text()
        throw new Error(`Deep import failed (${resp.status}): ${text}`)
      }
      return resp.json()
    }, { projectId: testProjectId, apiBase: API_BASE })

    console.log("[E2E] Deep import result:", JSON.stringify(deepResult))

    expect(deepResult.phase).toBe("done")
    expect(deepResult.completed_steps).toContain("scene_segmentation")
    expect(deepResult.completed_steps).toContain("entity_extraction")
    expect(deepResult.completed_steps).toContain("structure_analysis")
    console.log("[E2E] Deep import completed with message:", deepResult.message)

    // ============================================================
    // Step 3: 后端 API 双重验证
    // ============================================================
    const scenes = await listScenesOrdered(testProjectId)
    console.log(`[E2E] API returned ${scenes.length} scenes`)
    expect(scenes.length).toBeGreaterThan(0)

    const deepImportScenes = scenes.filter((s) => s.source === "deep_import")
    console.log(`[E2E] Deep import scenes: ${deepImportScenes.length}/${scenes.length}`)
    expect(deepImportScenes.length).toBeGreaterThan(0)

    for (const s of scenes) {
      console.log(
        `[E2E] Scene #${s.scene_index}: "${s.title}" | tag=${s.narrative_tag} | source=${s.source} | goal=${s.goal ? "✓" : "✗"}`,
      )
    }

    // ============================================================
    // Step 4: 导航到大纲 → 验证 Scene 卡列表
    // ============================================================
    await page.evaluate(() => {
      const pid = localStorage.getItem("novel_currentProjectId")
      if (pid) state.currentProjectId = pid
      window.router.navigate("outline", "scenes")
    })
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })

    // 子标签应为场景卡（默认激活）
    const scenesTab = page.locator('[data-action="nav-scenes"]')
    await expect(scenesTab).toHaveClass(/active/)

    // Scene 卡以 .scene-card 类渲染
    const sceneCards = page.locator(".scene-card")
    await expect(sceneCards.first()).toBeVisible({ timeout: 10000 })
    const cardCount = await sceneCards.count()
    console.log(`[E2E] Found ${cardCount} scene cards in outline view`)
    expect(cardCount).toBeGreaterThan(0)

    // 验证卡片来源标签为 "AI导入"
    const firstCardSource = sceneCards.first().locator(".scene-source")
    await expect(firstCardSource).toBeVisible()
    const sourceText = await firstCardSource.textContent()
    expect(sourceText).toContain("AI导入")

    // 验证卡片有标题
    const firstCardTitle = sceneCards.first().locator(".scene-card-title")
    await expect(firstCardTitle).toBeVisible()
    const titleText = await firstCardTitle.textContent()
    expect(titleText).toBeTruthy()
    console.log(`[E2E] First scene card title: "${titleText}"`)

    // ============================================================
    // Step 5: 返回写作台 → 验证 Scene 树
    // ============================================================
    await page.evaluate(() => {
      const pid = localStorage.getItem("novel_currentProjectId")
      if (pid) state.currentProjectId = pid
      window.router.navigate("writing")
    })
    await page.waitForFunction(() => !state.loading, { timeout: 10000 })

    // 左侧章节树应该有 Scene 节点
    const treeText = await page.locator("#writing-tree-container").textContent()
    console.log("[E2E] Writing tree content:", treeText?.substring(0, 200))

    // Scene 卡应该在树中以 Scene 或章节标题形式出现
    expect(treeText).toBeTruthy()
    const hasContent =
      treeText.includes("Scene") ||
      treeText.includes("第") ||
      treeText.includes("觉醒") ||
      treeText.includes("灰色雾气") ||
      treeText.includes("灰雾")
    expect(hasContent).toBeTruthy()
    console.log("[E2E] ALL CHECKS PASSED")
  })
})
