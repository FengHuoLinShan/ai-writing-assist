import { ref } from "vue"

export const SHELL_THEMES = Object.freeze([
  { value: "sticky", label: "晨光便签", icon: "○" },
  { value: "night", label: "暗夜书房", icon: "●" },
  { value: "ink", label: "水墨写意", icon: "◉" },
])

export const THEME_STORAGE_KEY = "nc-theme"
const LEGACY_STORAGE_KEY = "novel_theme"

const LEGACY_THEMES = Object.freeze({
  light: "sticky",
  minimal: "sticky",
  dark: "night",
  "dark-soft": "night",
  paper: "ink",
  warm: "ink",
})
const VALID_THEMES = new Set(SHELL_THEMES.map((item) => item.value))

export function normalizeTheme(value) {
  const normalized = LEGACY_THEMES[value] || value || "sticky"
  return VALID_THEMES.has(normalized) ? normalized : "sticky"
}

function systemDefaultTheme(matchMedia) {
  try {
    return matchMedia?.("(prefers-color-scheme: dark)")?.matches ? "night" : "sticky"
  } catch {
    return "sticky"
  }
}

export function createThemeController({
  storage = globalThis.localStorage,
  root = globalThis.document?.documentElement,
  notify = () => {},
  matchMedia = globalThis.matchMedia?.bind(globalThis),
} = {}) {
  const current = ref("sticky")

  function apply(value, { persist = true, announce = true } = {}) {
    const theme = normalizeTheme(value)
    current.value = theme
    root?.setAttribute?.("data-theme", theme)
    if (persist) {
      try { storage?.setItem(THEME_STORAGE_KEY, theme) } catch {}
    }
    if (announce) {
      const label = SHELL_THEMES.find((item) => item.value === theme)?.label || theme
      notify(`已切换至「${label}」主题`, "success")
    }
    return theme
  }

  function initialize() {
    let saved = null
    try { saved = storage?.getItem(THEME_STORAGE_KEY) || null } catch {}
    if (saved) {
      return apply(saved, { persist: saved !== normalizeTheme(saved), announce: false })
    }
    let legacy = null
    try { legacy = storage?.getItem(LEGACY_STORAGE_KEY) || null } catch {}
    if (legacy) {
      const theme = apply(legacy, { persist: true, announce: false })
      try { storage?.removeItem(LEGACY_STORAGE_KEY) } catch {}
      return theme
    }
    return apply(systemDefaultTheme(matchMedia), { persist: false, announce: false })
  }

  return { current, initialize, apply }
}

export function useTheme(services) {
  const controller = createThemeController({ notify: services.toast })
  controller.initialize()
  return controller
}
