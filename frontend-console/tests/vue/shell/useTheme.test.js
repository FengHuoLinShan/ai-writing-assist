import { describe, expect, it, vi } from "vitest"
import { createThemeController, normalizeTheme } from "../../../vue/shell/composables/useTheme.js"

function fakeMatchMedia(matches) {
  return vi.fn(() => ({ matches }))
}

describe("shell theme controller", () => {
  it("normalizes legacy and unknown values without trusting storage text", () => {
    expect(normalizeTheme("light")).toBe("sticky")
    expect(normalizeTheme("minimal")).toBe("sticky")
    expect(normalizeTheme("dark")).toBe("night")
    expect(normalizeTheme("dark-soft")).toBe("night")
    expect(normalizeTheme("paper")).toBe("ink")
    expect(normalizeTheme("warm")).toBe("ink")
    expect(normalizeTheme('<img src=x onerror="boom">')).toBe("sticky")
  })

  it("applies a stored nc-theme value without rewriting it", () => {
    const storage = { getItem: vi.fn(() => "ink"), setItem: vi.fn() }
    const root = { setAttribute: vi.fn() }
    const controller = createThemeController({ storage, root })
    expect(controller.initialize()).toBe("ink")
    expect(root.setAttribute).toHaveBeenCalledWith("data-theme", "ink")
    expect(storage.setItem).not.toHaveBeenCalled()
  })

  it("persists the canonical value when nc-theme holds a legacy alias", () => {
    const storage = { getItem: vi.fn(() => "dark-soft"), setItem: vi.fn() }
    const root = { setAttribute: vi.fn() }
    const controller = createThemeController({ storage, root })
    expect(controller.initialize()).toBe("night")
    expect(root.setAttribute).toHaveBeenCalledWith("data-theme", "night")
    expect(storage.setItem).toHaveBeenCalledWith("nc-theme", "night")
  })

  it("migrates a legacy novel_theme value into nc-theme and removes the old key", () => {
    const storage = {
      getItem: vi.fn((key) => (key === "novel_theme" ? "warm" : null)),
      setItem: vi.fn(),
      removeItem: vi.fn(),
    }
    const root = { setAttribute: vi.fn() }
    const controller = createThemeController({ storage, root })
    expect(controller.initialize()).toBe("ink")
    expect(root.setAttribute).toHaveBeenCalledWith("data-theme", "ink")
    expect(storage.setItem).toHaveBeenCalledWith("nc-theme", "ink")
    expect(storage.removeItem).toHaveBeenCalledWith("novel_theme")
  })

  it("follows the system dark color scheme when nothing is stored", () => {
    const storage = { getItem: vi.fn(() => null), setItem: vi.fn() }
    const root = { setAttribute: vi.fn() }
    const controller = createThemeController({
      storage,
      root,
      matchMedia: fakeMatchMedia(true),
    })
    expect(controller.initialize()).toBe("night")
    expect(root.setAttribute).toHaveBeenCalledWith("data-theme", "night")
    expect(storage.setItem).not.toHaveBeenCalled()
  })

  it("follows the system light color scheme when nothing is stored", () => {
    const storage = { getItem: vi.fn(() => null), setItem: vi.fn() }
    const root = { setAttribute: vi.fn() }
    const controller = createThemeController({
      storage,
      root,
      matchMedia: fakeMatchMedia(false),
    })
    expect(controller.initialize()).toBe("sticky")
    expect(root.setAttribute).toHaveBeenCalledWith("data-theme", "sticky")
  })

  it("falls back to sticky when matchMedia is unavailable", () => {
    const root = { setAttribute: vi.fn() }
    const controller = createThemeController({
      storage: { getItem: vi.fn(() => null), setItem: vi.fn() },
      root,
      matchMedia: undefined,
    })
    expect(controller.initialize()).toBe("sticky")
    expect(root.setAttribute).toHaveBeenCalledWith("data-theme", "sticky")
  })

  it("announces theme switches with the stable toast copy", () => {
    const notify = vi.fn()
    const controller = createThemeController({
      storage: { getItem: vi.fn(() => null), setItem: vi.fn() },
      root: { setAttribute: vi.fn() },
      notify,
    })
    expect(controller.apply("night")).toBe("night")
    expect(notify).toHaveBeenCalledWith("已切换至「暗夜书房」主题", "success")
  })
})
