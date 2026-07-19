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
    project: { title: "项目", subViews: [] },
    world: { title: "世界对象", subViews: ["objects", "bible"], defaultSubView: "objects" },
    writing: { title: "写作台", subViews: [] },
    generate: { title: "生成中心", subViews: [] },
    settings: { title: "全局设置", subViews: [] },
  }
  const services = {
    state,
    subscribeState: vi.fn((listener) => { listeners.add(listener); return () => listeners.delete(listener) }),
    router: {
      getRoute: vi.fn((view) => routes[view] || { title: view, subViews: [] }),
      getSubViewTitle: vi.fn((_view, subview) => ({ objects: "对象库", bible: "世界书" })[subview] || subview || ""),
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
