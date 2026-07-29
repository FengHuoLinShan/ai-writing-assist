import { test, expect } from "./fixtures.js"
import { waitForBackend } from "./helpers/api-client.js"

const journeyId = "11111111-1111-4111-8111-111111111111"

function storyMessage(id, role, content) {
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
  }
}

async function mockRpApis(page) {
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
      storyMessage("a3", "assistant", "信纸上的墨迹正在重新浮现。"),
    ],
    has_older_messages: false,
    active_attempt: null,
  }
  await page.route("**/api/settings/llm-connections", (route) => route.fulfill({
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
    body: JSON.stringify({ see_sea_notice_acknowledged: true }),
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

test.describe("RP 路由与窄屏故事页", () => {
  test.beforeAll(async () => {
    await waitForBackend(60000)
  })

  test("双入口进入 RP 列表并打开当前旅程", async ({ page, browserErrors }) => {
    await mockRpApis(page)
    await page.goto("/")
    await page.getByRole("button", { name: /我是 RP/ }).click()

    await expect(page.getByRole("heading", { name: "跑团模式" })).toBeVisible()
    await expect(page.getByText("雾港钟楼")).toBeVisible()
    await expect(page.locator("#sidebar")).toHaveCount(0)

    await page.getByRole("button", { name: /雾港钟楼/ }).click()
    await expect(page).toHaveURL(new RegExp(`#interaction/${journeyId}`))
    await expect(page.getByText("信纸上的墨迹正在重新浮现。")).toBeVisible()
    await expect(page.locator(".rp-composer-dock")).toBeVisible()
    expect(browserErrors).toEqual([])
  })

  test("390px 下输入工具保持单行，更多操作使用底部面板且页面不横溢", async ({
    page,
    browserErrors,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await mockRpApis(page)
    await page.goto(`/#interaction/${journeyId}`)

    await expect(page.locator(".rp-story-title")).toHaveJSProperty("tagName", "DIV")
    await expect(page.locator(".rp-locator-rail")).toBeVisible()
    await expect(page.locator(".rp-composer-dock")).toBeVisible()

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
    await expect(page.locator(".rp-more-menu__themes")).toContainText("午夜星河")
    await page.locator(".rp-more-menu__header").getByRole("button", { name: "关闭" }).click()
    await expect(page.locator(".rp-more-menu")).not.toHaveAttribute("open", "")

    await page.locator(".rp-more-menu summary").click()
    await page.locator(".rp-more-menu__themes").getByRole(
      "button",
      { name: /午夜星河/ },
    ).click()
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark")
    await expect(page.locator(".rp-more-menu")).not.toHaveAttribute("open", "")

    const overflow = await page.evaluate(() => (
      document.documentElement.scrollWidth - window.innerWidth
    ))
    expect(overflow).toBeLessThanOrEqual(0)
    expect(browserErrors).toEqual([])
  })
})
