import { describe, expect, it, vi } from "vitest"
import { createThemeController, normalizeTheme } from "../../../vue/shell/composables/useTheme.js"

describe("shell theme controller", () => {
  it("normalizes legacy and unknown values without trusting storage text", () => {
    expect(normalizeTheme("light")).toBe("minimal")
    expect(normalizeTheme("paper")).toBe("warm")
    expect(normalizeTheme('<img src=x onerror="boom">')).toBe("minimal")
  })

  it("applies a legacy stored theme and persists its canonical value", () => {
    const storage = { getItem: vi.fn(() => "dark-soft"), setItem: vi.fn() }
    const root = { setAttribute: vi.fn() }
    const controller = createThemeController({ storage, root })
    expect(controller.initialize()).toBe("warm")
    expect(root.setAttribute).toHaveBeenCalledWith("data-theme", "warm")
    expect(storage.setItem).toHaveBeenCalledWith("novel_theme", "warm")
  })
})
