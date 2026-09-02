import { test, expect } from "./fixtures.js"
import { waitForBackend } from "./helpers/api-client.js"

const journeyId = "11111111-1111-4111-8111-111111111111"
const sourceProjectId = "22222222-2222-4222-8222-222222222222"
const sourceRevisionId = "33333333-3333-4333-8333-333333333333"
const firstAnchorKey = "a".repeat(64)
const secondAnchorKey = "b".repeat(64)
const characterKey = "c".repeat(64)
const locationKey = "d".repeat(64)

function storyMessage(id, role, content, overrides = {}) {
  return {
    id,
    parent_node_id: null,
    role,
    message_kind: "story",
    content,
    completion_state: "complete",
    end_reason: "stop",
    branch_hint: content.slice(0, 30),
    story_ended: false,
    action_suggestions: [],
    created_at: "2026-07-29T00:00:00Z",
    ...overrides,
  }
}

async function expectFillsViewportWidth(locator) {
  const box = await locator.boundingBox()
  expect(box).not.toBeNull()
  const viewportWidth = await locator.evaluate(() => window.innerWidth)
  expect(Math.abs(box.x)).toBeLessThanOrEqual(1)
  expect(Math.abs(box.width - viewportWidth)).toBeLessThanOrEqual(1)
}

async function textContrast(locator) {
  return locator.evaluate((element) => {
    const channel = (value) => {
      const normalized = value / 255
      return normalized <= 0.04045
        ? normalized / 12.92
        : ((normalized + 0.055) / 1.055) ** 2.4
    }
    const luminance = (color) => {
      const [red, green, blue] = color.match(/[\d.]+/g).slice(0, 3).map(Number)
      return (0.2126 * channel(red)) + (0.7152 * channel(green)) + (0.0722 * channel(blue))
    }
    const style = getComputedStyle(element)
    const values = [luminance(style.color), luminance(style.backgroundColor)]
      .sort((left, right) => right - left)
    return {
      contrast: (values[0] + 0.05) / (values[1] + 0.05),
      opacity: Number(style.opacity),
    }
  })
}

async function mockRpApis(
  page,
  { seeSeaNoticeAcknowledged = true, activeAttempt = null } = {},
) {
  const journey = {
    id: journeyId,
    title: "雾港钟楼",
    title_source: "model",
    opening_text: "我是一名刚到雾港的修表师。",
    status: "active",
    see_sea_enabled: false,
    action_options_enabled: true,
    selection_epoch: 3,
    overview_epoch: 0,
    selected_leaf_node_id: "a3",
    setup_messages: [{
      ...storyMessage("setup-1", "user", "我是一名刚到雾港的修表师。"),
      message_kind: "setup",
    }],
    messages: [
      storyMessage("u1", "user", "我走向钟楼。"),
      storyMessage("a1", "assistant", "钟楼的铜门在海风里缓缓打开。"),
      storyMessage("u2", "user", "我点亮提灯。"),
      storyMessage("a2", "assistant", "提灯照出齿轮间的一封旧信。"),
      storyMessage(
        "a3",
        "assistant",
        "## 墨迹重现\n\n信纸上的**墨迹**正在重新浮现。",
        {
          action_suggestions: [{
            label: "谨慎观察",
            text: "我先完整观察信纸边缘的痕迹，再决定是否触碰正在浮现的文字。",
          }],
        },
      ),
    ],
    has_older_messages: false,
    active_attempt: activeAttempt,
  }
  await page.route("**/api/account/settings/llm-connections", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      active_provider_id: "deepseek",
      providers: [{
        provider_id: "deepseek",
        label: "DeepSeek",
        model: "deepseek-v4-flash",
        connected: true,
        active: true,
      }],
    }),
  }))
  await page.route("**/api/interactions/preferences", (route) => route.fulfill({
    contentType: "application/json",
    body: JSON.stringify({
      see_sea_notice_acknowledged: seeSeaNoticeAcknowledged,
    }),
  }))
  await page.route(`**/api/interactions/journeys/${journeyId}/path-index`, (route) => (
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        selection_epoch: 3,
        items: [
          { id: "a1", ordinal: 1, total: 3, excerpt: "钟楼的铜门" },
          { id: "a2", ordinal: 2, total: 3, excerpt: "提灯照出旧信" },
          { id: "a3", ordinal: 3, total: 3, excerpt: "墨迹重新浮现" },
        ],
      }),
    })
  ))
  await page.route(
    `**/api/interactions/journeys/${journeyId}/nodes/*/branches`,
    (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ parent_node_id: null, variants: [] }),
    }),
  )
  await page.route(`**/api/interactions/journeys/${journeyId}`, (route) => (
    route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(journey),
    })
  ))
  await page.route("**/api/interactions/journeys?*", (route) => {
    const status = new URL(route.request().url()).searchParams.get("status")
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(
        status === "active"
          ? {
              items: [{
                id: journeyId,
                title: "雾港钟楼",
                title_source: "model",
                opening_excerpt: "我是一名刚到雾港的修表师。",
                status: "active",
                see_sea_enabled: false,
                action_options_enabled: true,
                selection_epoch: 3,
                latest_activity_at: "2026-07-29T00:00:00Z",
                current_excerpt: "信纸上的墨迹正在重新浮现。",
                attempt_status: "completed",
                active_attempt_id: null,
              }],
              total: 1,
            }
          : { items: [], total: 0 },
      ),
    })
  })
}

function sourceRevision(overrides = {}) {
  return {
    id: sourceRevisionId,
    project_id: sourceProjectId,
    title: "雾都之夜",
    version_number: 1,
    status: "ready",
    chapter_count: 2,
    progress_message: "作品资料已完整整理，可以开始旅程",
    recovery_required: false,
    ambiguities: [],
    anchors: [
      {
        anchor_key: firstAnchorKey,
        chapter_index: 1,
        chapter_title: "第一章 抵达",
        label: "火车进站",
        excerpt: "雾中的火车停靠站台",
        end_offset: 80,
      },
      {
        anchor_key: secondAnchorKey,
        chapter_index: 2,
        chapter_title: "第二章 钟楼",
        label: "进入钟楼之后",
        excerpt: "铜门在身后合拢",
        end_offset: 160,
      },
    ],
    objects: [
      {
        reference_key: characterKey,
        label: "林默",
        entity_type: "character",
        summary: "钟表匠",
        aliases: ["小林"],
        first_chapter_index: 1,
        first_end_offset: 40,
      },
      {
        reference_key: locationKey,
        label: "雾港钟楼",
        entity_type: "location",
        summary: "海边钟楼",
        aliases: [],
        first_chapter_index: 2,
        first_end_offset: 120,
      },
    ],
    ready_at: "2026-09-01T00:00:00Z",
    update_available: false,
    ...overrides,
  }
}

async function mockJourneyCreation(page, capture) {
  await page.route("**/api/interactions/journeys", async (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    capture.payload = route.request().postDataJSON()
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({ journey: { id: journeyId } }),
    })
  })
}

test.describe("RP 路由与窄屏故事页", () => {
  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test("双入口进入 RP 列表并打开当前旅程", async ({ page, browserErrors }) => {
    await page.addInitScript(() => localStorage.setItem("nc-theme", "sticky"))
    await mockRpApis(page)
    await page.goto("/")
    await page.getByRole("button", { name: /进入互动故事/ }).click()

    await expect(page.getByRole("heading", { name: "互动故事" })).toBeVisible()
    await expect(page.getByText("雾港钟楼")).toBeVisible()
    await expect(page.getByRole("button", { name: "归档旅程：雾港钟楼", exact: true }))
      .toBeVisible()
    await expect(page.locator("#sidebar")).toHaveCount(0)
    await expectFillsViewportWidth(page.locator(".rp-list-page"))

    await page.getByRole("button", { name: /^雾港钟楼/ }).click()
    await expect(page).toHaveURL(new RegExp(`#interaction/${journeyId}`))
    await expect(page.getByRole("heading", { name: "墨迹重现" })).toBeVisible()
    await expect(page.locator(".rp-message__text strong")).toHaveText("墨迹")
    const actionCard = page.getByRole("button", { name: /谨慎观察/ })
    await expect(actionCard).toContainText(
      "我先完整观察信纸边缘的痕迹，再决定是否触碰正在浮现的文字。",
    )
    const actionCardStyle = await actionCard.evaluate((element) => ({
      overflow: getComputedStyle(element).overflow,
      textOverflow: getComputedStyle(element).textOverflow,
      whiteSpace: getComputedStyle(element).whiteSpace,
    }))
    expect(actionCardStyle).toEqual({
      overflow: "visible",
      textOverflow: "clip",
      whiteSpace: "normal",
    })

    const messageActions = page.locator(
      '[data-rp-message-id="a3"] .rp-message__actions button',
    )
    await expect(messageActions.nth(0)).toHaveText("复制")
    await expect(messageActions.nth(1)).toHaveText("重新生成")
    await expect(messageActions.nth(0)).toHaveClass(/rp-message-action-button/)
    await expect(messageActions.nth(1)).toHaveClass(/rp-message-action-button/)

    const readingWidth = await page.locator(".rp-story-scroll").evaluate((element) => {
      const style = getComputedStyle(element)
      return element.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight)
    })
    expect(readingWidth).toBeGreaterThanOrEqual(638)
    expect(readingWidth).toBeLessThanOrEqual(642)

    for (const theme of [
      { value: "sticky", label: /晨光便签/ },
      { value: "night", label: /暗夜书房/ },
      { value: "ink", label: /水墨写意/ },
    ]) {
      if (theme.value !== "sticky") {
        await page.locator(".rp-more-menu summary").click()
        await page.locator(".rp-more-menu__themes")
          .getByRole("button", { name: theme.label })
          .click()
      }
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme.value)
      const metrics = await textContrast(messageActions.nth(0))
      expect(metrics.opacity).toBe(1)
      expect(metrics.contrast).toBeGreaterThanOrEqual(4.5)
    }

    await actionCard.click()
    await expect(page.getByRole("textbox", { name: "继续旅程" })).toHaveValue(
      "我先完整观察信纸边缘的痕迹，再决定是否触碰正在浮现的文字。",
    )
    await expect(page.locator(".rp-composer-dock")).toBeVisible()
    expect(browserErrors).toEqual([])
  })

  test("作品资料变化导致的失败给出明确原因与重试入口", async ({
    page,
    browserErrors,
  }) => {
    await mockRpApis(page, {
      activeAttempt: {
        id: "attempt-source-stale",
        journey_id: journeyId,
        response_to_node_id: "a2",
        status: "failed",
        error_kind: "source_context_stale",
        error_message: "作品资料已变化，请重新生成",
        visible_text: "",
        visible_offset: 0,
      },
    })
    await page.goto(`/#interaction/${journeyId}`)

    await expect(page.locator(".rp-story-title")).toContainText("雾港钟楼")
    const banner = page.locator(".rp-attempt-actions--error")
    await expect(banner).toContainText("作品资料已变化，请重新生成")
    await expect(banner.getByRole("button", { name: "重新生成" })).toBeVisible()
    expect(browserErrors).toEqual([])
  })

  test("390px 下输入工具保持单行，更多操作使用底部面板且页面不横溢", async ({
    page,
    browserErrors,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.emulateMedia({ reducedMotion: "reduce" })
    await mockRpApis(page)
    await page.goto(`/#interaction/${journeyId}`)

    await expect(page.locator(".rp-story-title")).toHaveJSProperty("tagName", "DIV")
    await expect(page.locator(".rp-locator-rail")).toBeVisible()
    await expect(page.locator(".rp-composer-dock")).toBeVisible()
    await expect(page.locator("#sidebar")).toHaveCount(0)
    await expectFillsViewportWidth(page.locator(".rp-story-page"))
    const actionBox = await page.locator(
      '[data-rp-message-id="a3"] .rp-message__actions button',
    ).first().boundingBox()
    expect(actionBox.height).toBeGreaterThanOrEqual(42)
    await expect(page.locator(".rp-message__actions").first())
      .toHaveCSS("transition-duration", "0s")

    const toolStyle = await page.locator(".rp-composer-tools").evaluate((element) => ({
      flexWrap: getComputedStyle(element).flexWrap,
      overflowX: getComputedStyle(element).overflowX,
    }))
    expect(toolStyle.flexWrap).toBe("nowrap")
    expect(["auto", "scroll"]).toContain(toolStyle.overflowX)

    await page.locator(".rp-more-menu summary").click()
    const menuBox = await page.locator(".rp-more-menu > div").boundingBox()
    expect(menuBox).not.toBeNull()
    expect(Math.abs((menuBox.y + menuBox.height) - 844)).toBeLessThanOrEqual(2)
    await expect(page.locator(".rp-sheet-backdrop")).toBeVisible()
    await expect(page.locator(".rp-more-menu__themes")).toContainText("暗夜书房")
    await page.locator(".rp-more-menu__header")
      .getByRole("button", { name: "关闭更多操作", exact: true })
      .click()
    await expect(page.locator(".rp-more-menu")).not.toHaveAttribute("open", "")

    await page.locator(".rp-more-menu summary").click()
    await page.locator(".rp-more-menu__themes").getByRole(
      "button",
      { name: /暗夜书房/ },
    ).click()
    await expect(page.locator("html")).toHaveAttribute("data-theme", "night")
    await expect(page.locator(".rp-more-menu")).not.toHaveAttribute("open", "")

    const overflow = await page.evaluate(() => (
      document.documentElement.scrollWidth - window.innerWidth
    ))
    expect(overflow).toBeLessThanOrEqual(0)
    expect(browserErrors).toEqual([])
  })

  test("保留未完整片段时明确显示未完成状态", async ({ page, browserErrors }) => {
    await mockRpApis(page, {
      activeAttempt: {
        id: "attempt-partial",
        journey_id: journeyId,
        response_to_node_id: "a3",
        status: "awaiting_continue",
        error_kind: null,
        error_message: null,
        visible_text: "潮声压住了尚未说完的话。",
        visible_offset: 12,
      },
    })
    await page.goto(`/#interaction/${journeyId}`)

    await expect(page.locator(".rp-message--streaming .rp-message__label"))
      .toContainText("故事 · 未完成")
    await expect(page.locator(".rp-message--streaming")).toContainText("潮声压住了尚未说完的话。")
    expect(browserErrors).toEqual([])
  })

  test("底部看海确认按可视视口自动向上弹出且不被裁剪", async ({
    page,
    browserErrors,
  }) => {
    await page.setViewportSize({ width: 390, height: 520 })
    await mockRpApis(page, { seeSeaNoticeAcknowledged: false })
    await page.goto(`/#interaction/${journeyId}`)

    const seaButton = page.getByRole("button", { name: "故事自主发展" })
    await seaButton.click()
    const confirmation = page.locator(".rp-adaptive-confirm")
    await expect(confirmation).toBeVisible()
    await expect(confirmation).toHaveAttribute("data-placement", "top")
    await expect(confirmation.getByRole("alertdialog")).toContainText(
      "使用你的模型额度",
    )
    await expect(seaButton).toHaveAttribute("aria-expanded", "true")

    const box = await confirmation.boundingBox()
    expect(box).not.toBeNull()
    expect(box.x).toBeGreaterThanOrEqual(0)
    expect(box.y).toBeGreaterThanOrEqual(0)
    expect(box.x + box.width).toBeLessThanOrEqual(390)
    expect(box.y + box.height).toBeLessThanOrEqual(520)
    expect(await confirmation.evaluate((element) => element.parentElement === document.body))
      .toBe(true)
    expect(browserErrors).toEqual([])
  })

  test("已有作品完成关键指代、自然语言剧情点和原创身份后才可开始", async ({
    page,
    browserErrors,
  }) => {
    await mockRpApis(page)
    const capture = {}
    await mockJourneyCreation(page, capture)
    let revision = sourceRevision({
      status: "needs_confirmation",
      progress_message: "还需确认 1 项关键指代",
      ambiguities: [{
        ambiguity_key: "lin-mo",
        label: "林默",
        reason: "同名人物会影响引用正确性",
        choices: [
          { choice_key: characterKey, label: "林默", entity_type: "character" },
          { choice_key: locationKey, label: "林默旧居", entity_type: "location" },
        ],
      }],
    })
    await page.route("**/api/interactions/sources", (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: [revision],
        projects: [{
          project_id: sourceProjectId,
          title: "雾都之夜",
          latest_revision: revision,
        }],
      }),
    }))
    await page.route(`**/api/interactions/sources/${sourceRevisionId}`, (route) => (
      route.fulfill({ contentType: "application/json", body: JSON.stringify(revision) })
    ))
    await page.route(
      `**/api/interactions/sources/${sourceRevisionId}/ambiguities/*`,
      (route) => {
        revision = sourceRevision()
        return route.fulfill({
          contentType: "application/json",
          body: JSON.stringify(revision),
        })
      },
    )
    await page.route(
      `**/api/interactions/sources/${sourceRevisionId}/anchors/match`,
      (route) => route.fulfill({
        contentType: "application/json",
        body: JSON.stringify({ items: [revision.anchors[1]] }),
      }),
    )

    await page.goto("/#journeys/new")
    await page.getByLabel("使用已有作品资料").check()
    await page.getByRole("button", { name: /雾都之夜.*资料版本 1/ }).click()
    await expect(page.getByRole("heading", { name: "确认关键指代" })).toBeVisible()
    await page.getByRole("button", { name: "林默 · 人物" }).click()

    await page.getByLabel("先选章节").selectOption("2")
    await page.getByPlaceholder(/也可以描述/).fill("进入钟楼之后")
    await page.getByRole("button", { name: "匹配剧情点" }).click()
    await page.getByRole("button", { name: /进入钟楼之后 · 铜门在身后合拢/ }).click()
    await expect(page.getByLabel("进入钟楼之后")).toBeChecked()
    await page.getByLabel("原创角色").check()
    await page.getByLabel("角色名称").fill("季遥")
    await page.getByLabel("身份说明").fill("刚抵达雾港的外乡调查员")
    await page.getByText("预先固定重要人物或地点").click()
    await page.getByLabel(/雾港钟楼 · 地点/).check()
    await page.getByLabel("旅程开场").fill("我推开钟楼最深处的门。")
    await page.getByRole("button", { name: "开始旅程" }).click()

    await expect.poll(() => capture.payload?.source_setup).toEqual({
      source_revision_id: sourceRevisionId,
      progress_anchor_key: secondAnchorKey,
      player_identity: {
        kind: "original",
        name: "季遥",
        description: "刚抵达雾港的外乡调查员",
      },
      pinned_reference_keys: [locationKey],
    })
    expect(browserErrors).toEqual([])
  })

  test("新作品导入可刷新恢复，390px 错误聚焦并支持原作角色", async ({
    page,
    browserErrors,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await mockRpApis(page)
    const capture = {}
    await mockJourneyCreation(page, capture)
    let imported = false
    let recovered = false
    const organizing = sourceRevision({
      status: "organizing",
      progress_message: "正在完整整理当前导入版本，可以离开后再回来",
      anchors: [],
      objects: [],
      ready_at: null,
    })
    await page.route("**/api/interactions/sources", (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        items: imported ? [organizing] : [],
        projects: imported
          ? [{ project_id: sourceProjectId, title: "雾都之夜", latest_revision: organizing }]
          : [],
      }),
    }))
    await page.route("**/api/interactions/sources/import-preview", (route) => route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        preview_hash: "e".repeat(64),
        title: "雾都之夜",
        mode: "full",
        chapter_count: 2,
        changes: [
          { chapter_index: 1, title: "第一章", change: "added" },
          { chapter_index: 2, title: "第二章", change: "added" },
        ],
        requires_destructive_confirmation: false,
      }),
    }))
    await page.route("**/api/interactions/sources/import", (route) => {
      imported = true
      return route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify(organizing),
      })
    })
    await page.route(`**/api/interactions/sources/${sourceRevisionId}`, (route) => {
      recovered = true
      return route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(sourceRevision()),
      })
    })

    await page.goto("/#journeys/new")
    await page.getByLabel("使用已有作品资料").check()
    await page.getByRole("button", { name: "导入新作品" }).click()
    await page.getByLabel("作品名称").fill("雾都之夜")
    const fileInput = page.getByLabel("作品文件")
    await fileInput.setInputFiles({ name: "draft.mobi", mimeType: "application/octet-stream", buffer: Buffer.from("x") })
    await page.getByRole("button", { name: "预览章节变化" }).click()
    await expect(page.getByRole("alert")).toBeFocused()
    await expect(page.getByRole("alert")).toContainText("不支持")

    await fileInput.setInputFiles({ name: "draft.txt", mimeType: "text/plain", buffer: Buffer.from("第一章\n未完结正文") })
    await page.getByRole("button", { name: "预览章节变化" }).click()
    await page.getByLabel(/导入后完整整理/).check()
    await page.getByRole("button", { name: "应用版本并开始整理" }).click()
    await expect(page.getByText(/可以离开后再回来/)).toBeVisible()

    await page.reload()
    await expect.poll(() => recovered).toBe(true)
    await expect(page.getByText("作品资料已完整整理，可以选择进入位置")).toBeVisible()
    await page.getByLabel("火车进站").check()
    await page.getByLabel("选择角色").selectOption(characterKey)
    await page.getByLabel("旅程开场").fill("我沿着站台走进雾里。")
    await page.getByRole("button", { name: "开始旅程" }).click()

    await expect.poll(() => capture.payload?.source_setup?.player_identity).toEqual({
      kind: "source_character",
      reference_key: characterKey,
    })
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)
    expect(overflow).toBeLessThanOrEqual(0)
    expect(browserErrors).toEqual([])
  })
})
