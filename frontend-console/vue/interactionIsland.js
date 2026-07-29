import { mountIsland } from "./mountIsland.js"
import {
  getApi,
  getAppState,
  getRouter,
} from "./bridge/index.js"
import HomeChoiceView from "./views/interaction/HomeChoiceView.vue"
import InteractionView from "./views/interaction/InteractionView.vue"
import JourneyListView from "./views/interaction/JourneyListView.vue"

async function loadJourneyList() {
  try {
    const [active, archived] = await Promise.all([
      getApi().interactions.listJourneys({ status: "active", limit: 50 }),
      getApi().interactions.listJourneys({ status: "archived", limit: 50 }),
    ])
    const [connectionsResult, preferencesResult] = await Promise.allSettled([
      getApi().settings.listLLMConnections(),
      getApi().interactions.getPreferences(),
    ])
    return {
      activeJourneys: active.items || [],
      activeTotal: Number(active.total || 0),
      archivedJourneys: archived.items || [],
      archivedTotal: Number(archived.total || 0),
      llmConnections: connectionsResult.status === "fulfilled"
        ? connectionsResult.value
        : null,
      preferences: preferencesResult.status === "fulfilled"
        ? preferencesResult.value
        : null,
      startNew: getAppState()?.currentSubView === "new",
      loadError: null,
    }
  } catch {
    return {
      activeJourneys: [],
      activeTotal: 0,
      archivedJourneys: [],
      archivedTotal: 0,
      llmConnections: null,
      preferences: null,
      startNew: getAppState()?.currentSubView === "new",
      loadError: "旅程列表暂时无法加载，请稍后重试。",
    }
  }
}

async function loadInteraction() {
  const journeyId = getAppState()?.currentSubView || null
  if (!journeyId) {
    return {
      initialJourney: null,
      loadError: "没有指定要打开的旅程。",
    }
  }
  try {
    const journey = await getApi().interactions.getJourney(journeyId)
    const [connectionsResult, preferencesResult, indexResult] = await Promise.allSettled([
      getApi().settings.listLLMConnections(),
      getApi().interactions.getPreferences(),
      getApi().interactions.getPathIndex(journeyId),
    ])
    return {
      initialJourney: journey,
      llmConnections: connectionsResult.status === "fulfilled"
        ? connectionsResult.value
        : null,
      preferences: preferencesResult.status === "fulfilled"
        ? preferencesResult.value
        : null,
      initialPathIndex: indexResult.status === "fulfilled"
        ? indexResult.value
        : { selection_epoch: journey.selection_epoch, items: [] },
      loadError: null,
    }
  } catch {
    return {
      initialJourney: null,
      llmConnections: null,
      preferences: null,
      initialPathIndex: null,
      loadError: "旅程不存在、已归档，或当前账号无法访问。",
    }
  }
}

export function registerInteractionIslands() {
  const router = getRouter()
  if (!router) {
    console.error("interactionIsland: router 尚未就绪，island 注册跳过")
    return
  }

  router.registerView("home", mountIsland({
    viewName: "home",
    component: HomeChoiceView,
  }))
  router.registerView("journeys", mountIsland({
    viewName: "journeys",
    component: JourneyListView,
    load: loadJourneyList,
  }))
  router.registerView("interaction", mountIsland({
    viewName: "interaction",
    component: InteractionView,
    load: loadInteraction,
  }))
}

registerInteractionIslands()
