import { test, expect } from "./fixtures.js"
import {
  cleanupProject,
  createAuthorTask,
  createDraft,
  createEntity,
  createProject,
  createWorldBiblePage,
  deleteEntity,
  waitForBackend,
} from "./helpers/api-client.js"
import { openWorkbench } from "./helpers/workbench.js"
import { expectNoPageOverflow } from "./helpers/responsive.js"
import { SEL } from "./helpers/selectors.js"

test.describe("作者任务工作台", () => {
  let project = null

  test.beforeAll(async () => {
    await waitForBackend(60_000)
  })

  test.afterEach(async () => {
    if (project?.id) await cleanupProject(project.id)
    project = null
  })

  async function openTaskInbox(page, targetProject) {
    await openWorkbench(page, targetProject, "writing")
    await page.evaluate(async () => {
      await window.router.navigate("writing", null, true, new URLSearchParams({
        home: "1",
        panel: "tasks",
        scope: "inbox",
      }))
    })
    await expect(page.getByRole("heading", { name: "我的任务" })).toBeVisible()
  }

  async function createInBatches(items, create, batchSize = 10) {
    for (let start = 0; start < items.length; start += batchSize) {
      await Promise.all(items.slice(start, start + batchSize).map(create))
    }
  }

  test("返回作者两步内继续最近正文，并在 390px 保留带文字导航", async ({ page }) => {
    project = await createProject({ title: "今日工作续写", genre: "fantasy", language: "zh" })
    await createDraft(project.id, 3, "雾港来信", "潮声越过窗沿。")

    await page.goto("/")
    await page.evaluate((projectData) => {
      localStorage.setItem("novel_currentProjectId", projectData.id)
      localStorage.setItem("novel_currentProject", JSON.stringify(projectData))
    }, project)
    await page.reload()

    await page.getByRole("button", { name: /我是作家/ }).click()
    await expect(page).toHaveURL(new RegExp(`#workbench/${project.id}/writing\\?home=1$`))
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作")
    await expect(page.getByRole("heading", { name: "雾港来信" })).toBeVisible()

    await page.setViewportSize({ width: 390, height: 844 })
    for (const label of ["写作", "世界", "结构", "全部"]) {
      await expect(page.locator(".sidebar-mobile-nav").getByRole("button", { name: label })).toBeVisible()
    }
    await expectNoPageOverflow(page)

    await page.getByRole("button", { name: "继续写作" }).click()
    await expect(page).toHaveURL(new RegExp(`#workbench/${project.id}/writing`))
    await expect(page.locator(SEL.viewTitle)).toHaveText("写作")
  })

  test("失效的上次作品会清除并回到作品档案", async ({ page }) => {
    const staleId = "00000000-0000-4000-8000-000000000099"
    await page.goto("/")
    await page.evaluate((projectId) => {
      localStorage.setItem("novel_currentProjectId", projectId)
      localStorage.setItem("novel_currentProject", JSON.stringify({ id: projectId, title: "已失效作品" }))
    }, staleId)
    await page.reload()

    await page.getByRole("button", { name: /我是作家/ }).click()
    await expect(page.locator(SEL.viewTitle)).toHaveText("作品档案")
    await expect(page).toHaveURL(/#project$/)
    await expect(page.locator(SEL.toastContainer)).toContainText("上次打开的作品已不可用")
    await expect.poll(() => page.evaluate(() => localStorage.getItem("novel_currentProjectId"))).toBeNull()
  })

  for (const width of [1280, 390]) {
    test(`${width}px 资料库与作者任务闭环可恢复`, async ({ page }) => {
      test.setTimeout(60_000)
      project = await createProject({ title: `资料任务闭环 ${width}`, genre: "fantasy", language: "zh" })
      const entities = []
      for (let index = 1; index <= 24; index += 1) {
        entities.push(await createEntity(project.id, {
          name: `港口资料 ${index}`,
          entity_type: "location",
          status: "canonical",
          summary: `港区备忘 ${index}`,
        }))
      }
      const linkedEntity = entities[0]
      await createWorldBiblePage(project.id, {
        title: "港口资料总览",
        page_type: "background",
        free_text: "记录沉钟港的船期和税则。",
        linked_asset_refs_json: [{ type: "core_entity", id: linkedEntity.id }],
      })

      await page.setViewportSize({ width, height: 844 })
      await openWorkbench(page, project, "world", "bible")
      await page.getByRole("group", { name: "资料库显示方式" })
        .getByRole("button", { name: "列表" })
        .click()
      await page.getByRole("search").getByRole("searchbox", { name: "搜索资料" }).fill("港口资料")
      await page.getByRole("search").getByRole("button", { name: "查找" }).click()
      await expect(page).toHaveURL(/world\/bible\?.*q=%E6%B8%AF%E5%8F%A3%E8%B5%84%E6%96%99/)
      await expect(page).toHaveURL(/layout=list/)
      await expect(page.locator(".world-library-list__row")).toHaveCount(25)

      const content = page.locator("#workspace-content")
      await content.evaluate((element) => { element.scrollTop = 260 })
      const savedTop = await content.evaluate((element) => element.scrollTop)
      expect(savedTop).toBeGreaterThan(0)
      await page.locator(".world-library-list__row", { hasText: "港口资料总览" })
        .locator("[data-action='open-world-card']")
        .click()
      await expect(page.locator("#bible-title")).toHaveValue("港口资料总览")
      await page.getByRole("button", { name: `打开 ${linkedEntity.name}` }).click()
      await expect(page).toHaveURL(new RegExp(`world/bible\\?.*q=.*layout=list.*entity_id=${linkedEntity.id}`))
      await expect(page.getByRole("heading", { name: linkedEntity.name })).toBeVisible()
      await page.getByRole("button", { name: /返回资料库/ }).click()
      await expect(page).toHaveURL(/world\/bible\?.*q=.*layout=list/)
      await expect(page.locator(".world-library-list__row", { hasText: "港口资料总览" })).toBeVisible()

      await page.locator(".world-library-list__row", { hasText: "港口资料总览" })
        .locator("[data-action='open-world-card']")
        .click()
      const pageOverview = page.locator("#bible-free-text")
      await pageOverview.fill("未保存的港口补充")
      const leaveDialog = page.waitForEvent("dialog")
      const writingNav = width === 390
        ? page.locator(".sidebar-mobile-nav button", { hasText: "写作" })
        : page.locator('.nav-item[data-view="today"]')
      const leaveClick = writingNav.click()
      const dialog = await leaveDialog
      expect(dialog.message()).toContain("未保存修改")
      await dialog.dismiss()
      await leaveClick
      await expect(pageOverview).toHaveValue("未保存的港口补充")
      await pageOverview.fill("记录沉钟港的船期和税则。")
      await page.getByRole("button", { name: /返回资料库/ }).click()
      await expect.poll(() => content.evaluate((element) => element.scrollTop)).toBeGreaterThan(0)
      await expect(page.locator(".world-library-list__row", { hasText: "港口资料总览" })).toBeVisible()

      const target = entities.at(-1)
      await page.locator(".world-library-list__row", { hasText: target.name })
        .locator("[data-action='open-world-card']")
        .click()
      await expect(page.getByRole("heading", { name: target.name })).toBeVisible()
      await page.getByRole("button", { name: "添加到我的任务" }).click()
      await expect(page).toHaveURL(/writing\?home=1&panel=tasks&scope=inbox/)
      const localDate = await page.evaluate(() => {
        const now = new Date()
        return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
      })
      await page.locator("#author-task-date").fill(localDate)
      await page.getByRole("button", { name: "保存任务" }).click()
      await page.getByRole("button", { name: "写作首页" }).click()

      const taskSection = page.locator(".today-author-tasks")
      await expect(taskSection).toContainText(target.name)
      await taskSection.getByRole("checkbox", { name: `完成任务：${target.name}` }).check()
      await expect(taskSection).not.toContainText(target.name)
      await taskSection.getByRole("button", { name: "查看全部" }).click()
      await page.getByRole("button", { name: /已完成/ }).click()
      await page.getByRole("checkbox", { name: `重开任务：${target.name}` }).uncheck()
      await page.getByRole("button", { name: "写作首页" }).click()
      await expect(page.locator(".today-author-tasks")).toContainText(target.name)

      await page.locator(".today-author-tasks").getByRole("button", { name: `${target.name} →` }).click()
      await expect(page).toHaveURL(new RegExp(`world/bible\\?.*entity_id=${target.id}`))
      await expect(page.getByRole("heading", { name: target.name })).toBeVisible()

      await expectNoPageOverflow(page)
      if (width === 390) {
        const targetHeights = await page.locator(".world-entity-detail__header .btn, .sidebar-mobile-nav button")
          .evaluateAll((elements) => elements.map((element) => element.getBoundingClientRect().height))
        expect(targetHeights.length).toBeGreaterThan(0)
        expect(Math.min(...targetHeights)).toBeGreaterThanOrEqual(44)
      }
    })
  }

  test("双标签任务冲突保留输入，并且只在作者再次保存时重试", async ({ page, context }) => {
    project = await createProject({ title: "双标签任务冲突", genre: "fantasy", language: "zh" })
    const source = await createEntity(project.id, {
      name: "钟港守门人",
      entity_type: "character",
      status: "canonical",
      summary: "负责核对船期。",
    })
    const task = await createAuthorTask(project.id, {
      title: "核对守门人口供",
      source: { kind: "world_entity", id: source.id },
    })
    const second = await context.newPage()
    await Promise.all([openTaskInbox(page, project), openTaskInbox(second, project)])

    for (const current of [page, second]) {
      const row = current.locator(".author-task-row", { hasText: task.title })
      await expect(row.getByRole("button", { name: `${source.name} →` })).toBeVisible()
      await row.getByRole("button", { name: "编辑" }).click()
    }
    await page.locator("#author-task-note").fill("标签 A 已补充")
    await second.locator("#author-task-note").fill("标签 B 需保留")
    await page.getByRole("button", { name: "保存任务" }).click()
    await expect(page.locator(".author-task-form")).toHaveCount(0)

    const patchPayloads = []
    second.on("request", (request) => {
      if (request.method() === "PATCH" && request.url().includes(`/author-tasks/${task.id}`)) {
        patchPayloads.push(request.postDataJSON())
      }
    })
    await second.getByRole("button", { name: "保存任务" }).click()
    await expect(second.getByRole("alert")).toContainText("你的输入已保留")
    await expect(second.locator("#author-task-note")).toHaveValue("标签 B 需保留")
    await expect.poll(() => patchPayloads.length).toBe(1)

    await second.getByRole("button", { name: "保存任务" }).click()
    await expect.poll(() => patchPayloads.length).toBe(2)
    expect(patchPayloads[1].expected_updated_at).not.toBe(patchPayloads[0].expected_updated_at)
    await expect(second.locator(".author-task-form")).toHaveCount(0)
    await second.close()
  })

  test("来源失效不删任务，且可以只清除来源", async ({ page }) => {
    project = await createProject({ title: "任务来源失效", genre: "fantasy", language: "zh" })
    const source = await createEntity(project.id, {
      name: "即将归档的码头",
      entity_type: "location",
      status: "canonical",
      summary: "仅用于来源失效验收。",
    })
    const task = await createAuthorTask(project.id, {
      title: "保留码头核对任务",
      source: { kind: "world_entity", id: source.id },
    })
    await deleteEntity(project.id, source.id)

    await page.setViewportSize({ width: 390, height: 844 })
    await openTaskInbox(page, project)
    const row = page.locator(".author-task-row", { hasText: task.title })
    await expect(row).toContainText("来源已失效")
    await row.getByRole("button", { name: "清除来源" }).click()
    await expect(row).toBeVisible()
    await expect(row).not.toContainText("来源已失效")
    await expectNoPageOverflow(page)
  })

  test("Entity 局部失败不阻断资料页，并可原位重试", async ({ page }) => {
    project = await createProject({ title: "Entity 局部失败", genre: "fantasy", language: "zh" })
    await createWorldBiblePage(project.id, {
      title: "仍可使用的港口页",
      page_type: "background",
      free_text: "对象列表失败时这页仍应出现。",
    })
    await createEntity(project.id, {
      name: "重试后出现的灯塔",
      entity_type: "location",
      status: "canonical",
      summary: "用于局部恢复验收。",
    })
    let failed = false
    await page.route("**/api/world/entities?**", async (route) => {
      const url = new URL(route.request().url())
      if (!failed
        && url.searchParams.get("novel_id") === project.id
        && url.searchParams.get("view_mode") === "normal"
        && url.searchParams.get("limit") === "50") {
        failed = true
        await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "synthetic entity failure" }) })
        return
      }
      await route.continue()
    })

    await openWorkbench(page, project, "world", "bible")
    await expect(page.getByRole("alert")).toContainText("资料页和工作稿仍可使用")
    await expect(page.locator(".world-bible-page-card", { hasText: "仍可使用的港口页" })).toBeVisible()
    await page.getByRole("button", { name: "重新加载" }).click()
    await expect(page.getByRole("alert")).toHaveCount(0)
    await expect(page.locator(".world-card", { hasText: "重试后出现的灯塔" })).toBeVisible()
  })

  test("默认前 50 条之外的对象仍可通过服务端搜索找到", async ({ page }) => {
    test.setTimeout(120_000)
    project = await createProject({ title: "资料库百条搜索", genre: "fantasy", language: "zh" })
    const hiddenTarget = await createEntity(project.id, {
      name: "唯一的默认窗口外灯塔",
      entity_type: "location",
      status: "canonical",
      summary: "应位于默认窗口之外。",
    })
    await createInBatches(Array.from({ length: 99 }, (_, index) => index + 1), (index) => (
      createEntity(project.id, {
        name: `后建资料 ${String(index).padStart(3, "0")}`,
        entity_type: "location",
        status: "canonical",
        summary: `后建资料摘要 ${index}`,
      })
    ))
    await createInBatches(Array.from({ length: 50 }, (_, index) => index + 1), (index) => (
      createWorldBiblePage(project.id, {
        title: `资料页 ${String(index).padStart(2, "0")}`,
        page_type: "background",
        free_text: `合成资料页 ${index}`,
      })
    ))

    await openWorkbench(page, project, "world", "bible")
    await expect(page.getByText("已显示前 50 个人物或设定")).toBeVisible()
    await expect(page.locator(".world-card", { hasText: hiddenTarget.name })).toHaveCount(0)
    const searchRequest = page.waitForRequest((request) => {
      const url = new URL(request.url())
      return url.pathname.endsWith("/api/world/entities")
        && url.searchParams.get("novel_id") === project.id
        && url.searchParams.get("q") === hiddenTarget.name
    })
    await page.getByRole("search").getByRole("searchbox", { name: "搜索资料" }).fill(hiddenTarget.name)
    await page.getByRole("search").getByRole("button", { name: "查找" }).click()
    await searchRequest
    await expect(page.locator(".world-card", { hasText: hiddenTarget.name })).toBeVisible()
    await page.locator(".world-card", { hasText: hiddenTarget.name })
      .locator("[data-action='open-world-card']")
      .click()
    await expect(page).toHaveURL(new RegExp(`entity_id=${hiddenTarget.id}`))
    await expect(page.getByRole("heading", { name: hiddenTarget.name })).toBeVisible()
  })
})
