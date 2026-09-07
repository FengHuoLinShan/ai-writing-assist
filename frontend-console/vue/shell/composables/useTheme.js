import { nextTick, ref } from 'vue'
import { resolveVariant, variantVariables, validateThemeManifest, COLOR_VARIABLES } from '../../theme/themeTokens.js'

export const SHELL_THEMES = Object.freeze([
  { value: 'light', label: '浅色', icon: '○' },
  { value: 'dark', label: '深色', icon: '●' },
  { value: 'system', label: '跟随系统', icon: '◐' },
])
export const THEME_STORAGE_KEY = 'nc-theme'
const PACK_KEY = 'nc-theme-package'
const BOOT_KEY = 'nc-theme-bootstrap'
const legacyThemes = { sticky: 'light', ink: 'light', minimal: 'light', paper: 'light', warm: 'light', night: 'dark', 'dark-soft': 'dark' }
export function normalizeTheme(value) {
  const normalized = Object.hasOwn(legacyThemes, value) ? legacyThemes[value] : value
  return SHELL_THEMES.some(item => item.value === normalized) ? normalized : 'system'
}

export function createThemeController({ storage, root = globalThis.document?.documentElement, notify = () => {}, matchMedia = globalThis.matchMedia?.bind(globalThis) } = {}) {
  if (storage === undefined) { try { storage = globalThis.localStorage } catch { storage = null } }
  const current = ref('system')
  const resolved = ref('light')
  const packageId = ref('modern')
  const packageName = ref('现代简约')
  const error = ref('')
  let media
  try { media = matchMedia?.('(prefers-color-scheme: dark)') } catch { /* System preference is optional. */ }
  let prepared = null
  let bootstrapManifest = null
  let generation = 0
  let initialized = false
  let ready = Promise.resolve()
  let written = new Set()
  function write(key, value) {
    try { storage?.setItem(key, value); return Boolean(storage) } catch { return false }
  }
  function read(key) { try { return storage?.getItem(key) || null } catch { return null } }
  function render() {
    resolved.value = current.value === 'system' ? (media?.matches ? 'dark' : 'light') : current.value
    const variant = resolveVariant(prepared?.manifest || bootstrapManifest, resolved.value)
    const variables = prepared || bootstrapManifest ? variantVariables(variant) : {}
    if (prepared) {
      for (const [slot, css] of [['uiFont', '--font-ui'], ['bodyFont', '--font-body']]) {
        const font = prepared.fonts.get(variant[slot])
        if (font) { document.fonts.add(font); variables[css] = `"${font.family}", system-ui, sans-serif` }
      }
      for (const [slot, css] of [['background', '--theme-background'], ['texture', '--theme-texture'], ['emptyState', '--theme-empty-image']]) {
        const url = prepared.urls.get(variant[slot])
        if (url) variables[css] = `url("${url}")`
      }
    }
    for (const name of new Set([...written, ...Object.values(COLOR_VARIABLES)])) root?.style?.removeProperty(name)
    for (const [name, value] of Object.entries(variables)) root?.style?.setProperty(name, value)
    written = new Set(Object.keys(variables))
    root?.setAttribute?.('data-theme', resolved.value)
    root?.setAttribute?.('data-theme-package', packageId.value)
    if (root?.style) root.style.colorScheme = resolved.value
  }
  function apply(value, { persist = true, announce = true } = {}) {
    current.value = normalizeTheme(value)
    render()
    const saved = !persist || write(THEME_STORAGE_KEY, current.value)
    if (announce) notify(saved ? `已切换至「${SHELL_THEMES.find(item => item.value === current.value).label}」` : '外观已切换；浏览器未能记住选择，本次会话有效', saved ? 'success' : 'warning')
    return current.value
  }
  async function activate(record, { persist = true } = {}) {
    const ticket = ++generation
    let next = null
    if (record) {
      const { prepareThemeResources } = await import('../../theme/themePackages.js')
      next = await prepareThemeResources(record)
    }
    if (ticket !== generation) { next?.dispose(); return false }
    const previous = prepared
    bootstrapManifest = null
    prepared = next
    packageId.value = next?.manifest.id || 'modern'
    packageName.value = next?.manifest.name || '现代简约'
    render()
    previous?.dispose()
    error.value = ''
    if (persist) {
      const cache = Object.fromEntries(['light', 'dark'].map(mode => [mode, resolveVariant(next?.manifest, mode).colors]))
      if (!write(PACK_KEY, packageId.value) || !write(BOOT_KEY, JSON.stringify(cache))) {
        error.value = '主题已应用；浏览器未能记住选择，本次会话有效'
        notify(error.value, 'warning')
      }
    }
    return true
  }
  function initialize() {
    if (initialized) return current.value
    initialized = true
    error.value = ''
    try {
      const cache = JSON.parse(read(BOOT_KEY) || 'null')
      if (cache && read(PACK_KEY) && read(PACK_KEY) !== 'modern') bootstrapManifest = validateThemeManifest({ schemaVersion: 1, id: 'bootstrap', name: '已保存外观', version: '1', variants: { light: { colors: cache.light }, dark: { colors: cache.dark } } })
    } catch { bootstrapManifest = null }
    const saved = read(THEME_STORAGE_KEY)
    const legacy = !saved && read('novel_theme')
    apply(saved || legacy || 'system', { persist: Boolean(saved || legacy), announce: false })
    if (legacy && read(THEME_STORAGE_KEY) === current.value) {
      try { storage?.removeItem('novel_theme') } catch { /* Migration remains safe to repeat. */ }
    }
    media?.addEventListener?.('change', onSystemChange)
    const id = read(PACK_KEY)
    if (id && id !== 'modern') {
      let ticket = generation
      ready = import('../../theme/themePackages.js').then(async ({ getThemePackage }) => {
        const record = await getThemePackage(id)
        if (ticket !== generation) return
        if (!record) throw new Error('此浏览器中的主题资源已不可用')
        ticket = generation + 1
        await activate(record, { persist: false })
      }).catch(cause => {
        if (ticket !== generation || packageId.value !== 'modern') return
        bootstrapManifest = null
        render()
        error.value = `${cause.message}，已恢复现代简约。可在外观设置重新导入。`
        notify(error.value, 'warning')
      })
    }
    return current.value
  }
  function onSystemChange() { if (current.value === 'system') render() }
  function dispose() { generation++; media?.removeEventListener?.('change', onSystemChange); prepared?.dispose(); prepared = null; bootstrapManifest = null; initialized = false }
  return { current, resolved, packageId, packageName, error, initialize, apply, activate, dispose, get ready() { return ready }, setNotify(value) { notify = value } }
}
let sharedController
export function getThemeController() {
  sharedController ||= createThemeController()
  return sharedController
}
export function useTheme(services) {
  const controller = getThemeController()
  controller.setNotify(services.toast)
  controller.initialize()
  void nextTick(() => { if (controller.error.value) services.toast(controller.error.value, 'warning') })
  return controller
}
