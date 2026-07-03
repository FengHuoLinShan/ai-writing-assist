import { test, expect } from "@playwright/test"
import { SEL } from "./helpers/selectors.js"
import { openWorkbench } from "./helpers/workbench.js"
import { createProject, cleanupProject, waitForBackend } from "./helpers/api-client.js"

const generatedTaskId = "00000000-0000-0000-0000-0000000000b1"

test.describe("生成中心模块", () => {
  let testProjectId = null

  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test.beforeEach(async ({ page }) => {
    const project = await createProject({
      title: "生成测试项目",
      genre: "fantasy",
      language: "zh",
    })
    testProjectId = project.id

    await openWorkbench(page, project, "generate")

    // Mock 上下文编译 API
    await page.route("**/api/context/compile", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          section_count: 3,
          scope: "arc",
          reveal_mode: "author_safe",
          budgets: [{ category: "core_entities", budget: 100, used: 20 }],
          sections_present: ["project", "world_entities"],
          warnings: [],
        }),
      })
    })

    // Mock AI 参考资料确认 API
    await page.route("**/api/context/confirm", async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify({
          id: "confirm-generate-e2e",
          selected_asset_ids: {},
          warnings: [],
        }),
      })
    })

    await page.route("**/api/tasks/**", async (route) => {
      const url = new URL(route.request().url())
      if (url.pathname === `/api/tasks/${generatedTaskId}`) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            id: generatedTaskId,
            task_id: generatedTaskId,
            task_type: "plot_structure_generate",
            status: "done",
            progress: 100,
            result: { summary: "剧情结构生成完成" },
          }),
        })
        return
      }
      await route.continue()
    })

    // Mock 领域生成任务提交 API
    await page.route("**/api/outline/generate", async (route) => {
      const postBody = route.request().postDataJSON()
      if (postBody?.context_confirmation_id) {
        await route.fulfill({
          status: 200,
          body: JSON.stringify({
            task_id: generatedTaskId,
            status: "pending",
          }),
        })
        return
      }
      await route.continue()
    })
  })

  test.afterEach(async () => {
    if (testProjectId) {
      try { await cleanupProject(testProjectId) } catch {}
      testProjectId = null
    }
  })

  test("生成中心页面加载", async ({ page }) => {
    await expect(page.locator("#workspace-content")).toContainText("生成类型")
    await expect(page.locator("#workspace-content")).toContainText("世界与人物结构")
    await expect(page.locator("#workspace-content")).toContainText("剧情结构")
    await expect(page.locator("#workspace-content")).toContainText("章节与场景结构")
  })

  test("选择生成类型后显示输入区域", async ({ page }) => {
    await page.locator('[data-action="select-type"][data-type="world_character"]').click()
    await expect(page.locator("#generate-input-area")).toBeVisible()
    await expect(page.locator("#generate-intent")).toBeVisible()
  })

  test("提交生成任务并显示结果", async ({ page }) => {
    await page.locator('[data-action="select-type"][data-type="plot"]').click()
    await expect(page.locator("#generate-input-area")).toBeVisible()

    await page.locator("#generate-intent").fill("生成测试剧情结构")
    await page.locator('[data-action="start-generate"]').click()
    await expect(page.locator(SEL.modalTitle)).toHaveText("AI 参考资料")
    await page.getByRole("button", { name: "确认使用" }).click()

    // 验证进度步骤显示
    await expect(page.locator("#generate-result")).toContainText("剧情结构生成完成", { timeout: 15000 })
    await expect(page.locator("#generate-result")).toContainText("查看大纲")
  })

  test("未填写意图时给出警告", async ({ page }) => {
    await page.locator('[data-action="select-type"][data-type="chapter"]').click()
    await page.locator('[data-action="start-generate"]').click()

    await expect(page.locator(SEL.toastContainer)).toContainText("请输入创作意图描述", { timeout: 10000 })
  })
})
