// Runs before styles and authentication. Never interpolate stored text as CSS.
(() => {
  try {
    const storage = globalThis.localStorage
    const value = storage.getItem('nc-theme') || storage.getItem('novel_theme')
    const dark = ['dark', 'night', 'dark-soft'].includes(value) || (!['light', 'sticky', 'ink', 'paper', 'warm', 'minimal'].includes(value) && matchMedia('(prefers-color-scheme: dark)').matches)
    const mode = dark ? 'dark' : 'light'
    document.documentElement.dataset.theme = mode
    document.documentElement.style.colorScheme = mode
    const cache = JSON.parse(storage.getItem('nc-theme-bootstrap') || 'null')?.[mode]
    if (storage.getItem('nc-theme-package') === 'modern' || !cache) return
    const names = { background: 'bg', surface: 'surface', muted: 'surface-muted', text: 'ink', body: 'body', secondary: 'dim', accent: 'accent', onAccent: 'on-accent', primary: 'primary', onPrimary: 'on-primary', border: 'hairline', controlBorder: 'hairline-strong', success: 'success', warning: 'warning', danger: 'error' }
    for (const [key, name] of Object.entries(names)) if (typeof cache[key] === 'string' && /^#[\da-f]{6}$/i.test(cache[key])) document.documentElement.style.setProperty(`--nc-${name}`, cache[key])
  } catch { /* The built-in palette is always usable without browser storage. */ }
})()
