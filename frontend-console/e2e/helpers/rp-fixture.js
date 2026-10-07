export const journeyId = "11111111-1111-4111-8111-111111111111"

export function storyMessage(id, role, content, overrides = {}) {
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

export async function mockRpApis(
  page,
  {
    seeSeaNoticeAcknowledged = true,
    activeAttempt = null,
    partialMessage = false,
    archivedJourney = false,
  } = {},
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
          completion_state: partialMessage ? "partial" : "complete",
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
  await page.route(`**/api/interactions/journeys/${journeyId}/care/policy`, route => route.fulfill({ json: {
    available: false, policy: { enabled: false, categories: [], allow_web: false, web_backend: "none", daily_limit: 1 },
    pending_count: 0, overflow: false, active_run_id: null,
  } }))
  await page.route(`**/api/interactions/journeys/${journeyId}/forecasts/capabilities`, route => route.fulfill({ json: {
    enabled: false, semantic_enabled: false,
  } }))
  await page.route(`**/api/interactions/journeys/${journeyId}`, (route) => {
    if (route.request().method() === "DELETE") {
      archivedJourney = false
      return route.fulfill({ status: 204, body: "" })
    }
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify(journey),
    })
  })
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
          : archivedJourney
            ? {
                items: [{
                  id: journeyId,
                  title: "雾港钟楼",
                  opening_excerpt: "我是一名刚到雾港的修表师。",
                  status: "archived",
                  latest_activity_at: "2026-07-29T00:00:00Z",
                  current_excerpt: "信纸上的墨迹正在重新浮现。",
                  attempt_status: "completed",
                }],
                total: 1,
              }
            : { items: [], total: 0 },
      ),
    })
  })
  return journey
}
