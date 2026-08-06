import { vi } from "vitest"

export function createShellTestServices(overrides = {}) {
  const { state: stateOverrides = {}, ...serviceOverrides } = overrides
  const listeners = new Set()
  const state = {
    currentProjectId: "p1",
    currentProject: { id: "p1", title: "测试项目" },
    currentView: "project",
    currentSubView: null,
    backendConnected: false,
    mode: "NORMAL",
    selectedItem: null,
    ...stateOverrides,
  }
  const routes = {
    today: { title: "今日工作", subViews: [] },
    project: { title: "作品档案", subViews: [] },
    world: { title: "人物与世界", subViews: ["objects", "bible"], defaultSubView: "objects" },
    writing: { title: "写作", subViews: [] },
    outline: { title: "故事结构", subViews: ["story-outline"], defaultSubView: "story-outline" },
    map: { title: "地图", subViews: [] },
    rag: { title: "查找", subViews: ["search", "status"], defaultSubView: "search" },
    generate: { title: "高级生成工具", subViews: [] },
    settings: { title: "账户与模型连接", subViews: [] },
    "project-settings": { title: "项目偏好", subViews: [] },
  }
  const services = {
    state,
    subscribeState: vi.fn((listener) => { listeners.add(listener); return () => listeners.delete(listener) }),
    router: {
      getRoute: vi.fn((view) => routes[view] || { title: view, subViews: [] }),
      getSubViewTitle: vi.fn((_view, subview) => ({ objects: "人物与设定", bible: "世界笔记", "story-outline": "故事总览" })[subview] || subview || ""),
      getLastSubView: vi.fn(() => null),
      navigate: vi.fn(async () => true),
      init: vi.fn(async () => true),
    },
    commands: {
      execute: vi.fn(async () => true),
      getSuggestions: vi.fn(() => []),
    },
    modal: { close: vi.fn(() => true), isOpen: vi.fn(() => false) },
    health: { check: vi.fn(async () => true) },
    workspace: {
      triggerAction: vi.fn((action, host) => { const button = host?.querySelector(`[data-action="${action}"]`); button?.click(); return Boolean(button) }),
      moveSelection: vi.fn(),
      autosave: vi.fn(() => false),
      toggleOutlineFloat: vi.fn(() => false),
    },
    toast: vi.fn(),
    ...serviceOverrides,
  }
  services.updateState = (key, value) => {
    state[key] = value
    for (const listener of listeners) listener(key, value)
  }
  return services
}
