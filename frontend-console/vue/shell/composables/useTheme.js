import { ref } from "vue"

export const SHELL_THEMES = Object.freeze([
  { value: "minimal", label: "现代极简", icon: "◇" },
  { value: "warm", label: "黄金时刻", icon: "☼" },
  { value: "dark", label: "午夜星河", icon: "☾" },
])

const LEGACY_THEMES = Object.freeze({ light: "minimal", "dark-soft": "warm", paper: "warm" })
const VALID_THEMES = new Set(SHELL_THEMES.map((item) => item.value))

export function normalizeTheme(value) {
  const normalized = LEGACY_THEMES[value] || value || "minimal"
  return VALID_THEMES.has(normalized) ? normalized : "minimal"
}

export function createThemeController({
  storage = globalThis.localStorage,
  root = globalThis.document?.documentElement,
  notify = () => {},
} = {}) {
  const current = ref("minimal")

  function apply(value, { persist = true, announce = true } = {}) {
    const theme = normalizeTheme(value)
    current.value = theme
    root?.setAttribute?.("data-theme", theme)
    if (persist) {
      try { storage?.setItem("novel_theme", theme) } catch {}
    }
    if (announce) {
      const label = SHELL_THEMES.find((item) => item.value === theme)?.label || theme
      notify(`已切换至「${label}」主题`, "success")
    }
    return theme
  }

  function initialize() {
    let saved = "minimal"
    try { saved = storage?.getItem("novel_theme") || "minimal" } catch {}
    return apply(saved, { persist: saved !== normalizeTheme(saved), announce: false })
  }

  return { current, initialize, apply }
}

export function useTheme(services) {
  const controller = createThemeController({ notify: services.toast })
  controller.initialize()
  return controller
}
