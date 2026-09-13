// Public theme vocabulary. Values become CSS only after validation here.
export const DEFAULT_COLORS = Object.freeze({
  light: Object.freeze({ background: '#F6F7F9', surface: '#FFFFFF', muted: '#F0F2F6', text: '#20242C', body: '#414955', secondary: '#626B78', accent: '#0960D6', onAccent: '#FFFFFF', primary: '#0960D6', onPrimary: '#FFFFFF', border: '#E4E7EC', controlBorder: '#7C8795', success: '#197748', warning: '#986006', danger: '#BE3342' }),
  dark: Object.freeze({ background: '#191C22', surface: '#252932', muted: '#333A47', text: '#F0F1F4', body: '#DEE3EB', secondary: '#A0A8B7', accent: '#87B8FF', onAccent: '#192C47', primary: '#87B8FF', onPrimary: '#20242C', border: '#373D48', controlBorder: '#7F899B', success: '#83D5A5', warning: '#F3C26C', danger: '#FF9DA7' }),
})
export const COLOR_VARIABLES = Object.freeze({ background: '--nc-bg', surface: '--nc-surface', muted: '--nc-surface-muted', text: '--nc-ink', body: '--nc-body', secondary: '--nc-dim', accent: '--nc-accent', onAccent: '--nc-on-accent', primary: '--nc-primary', onPrimary: '--nc-on-primary', border: '--nc-hairline', controlBorder: '--nc-hairline-strong', success: '--nc-success', warning: '--nc-warning', danger: '--nc-error' })
export const THEME_LIMITS = Object.freeze({ compressed: 30 * 1024 ** 2, expanded: 64 * 1024 ** 2, entries: 128, image: 6 * 1024 ** 2, font: 24 * 1024 ** 2, dimension: 4096, manifest: 128 * 1024 })
const identifier = /^[a-z][a-z0-9-]{0,63}$/
const hex = /^#[\da-f]{6}$/i
const variantKeys = ['colors', 'radius', 'shadow', 'density', 'uiFont', 'bodyFont', 'background', 'texture', 'emptyState']
const slots = ['background', 'texture', 'emptyState', 'uiFont', 'bodyFont']

function object(value, keys, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label}须为对象`)
  for (const key of Object.keys(value)) if (!keys.includes(key)) throw new Error(`${label}包含不支持的项目：${key}`)
}
function shortText(value, label, max = 120) {
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw new Error(`${label}无效`)
}
export function contrastRatio(a, b) {
  const luminance = value => {
    const rgb = value.slice(1).match(/../g).map(part => parseInt(part, 16) / 255).map(n => n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4)
    return rgb[0] * 0.2126 + rgb[1] * 0.7152 + rgb[2] * 0.0722
  }
  const [x, y] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (x + 0.05) / (y + 0.05)
}
export function resolveVariant(manifest, mode) {
  const variant = manifest?.variants?.[mode] || {}
  return { radius: 8, shadow: 'soft', density: 'comfortable', ...variant, colors: { ...DEFAULT_COLORS[mode], ...variant.colors } }
}
export function validateThemeManifest(input) {
  object(input, ['schemaVersion', 'id', 'name', 'version', 'author', 'variants', 'assets'], '主题配置')
  if (input.schemaVersion !== 1) throw new Error('此主题版本暂不支持，请使用第 1 版主题包')
  if (typeof input.id !== 'string' || !identifier.test(input.id) || input.id === 'modern') throw new Error('主题标识无效或与内置主题重复')
  shortText(input.name, '主题名称', 60)
  shortText(input.version, '版本', 40)
  if (input.author !== undefined) shortText(input.author, '作者')
  object(input.variants, ['light', 'dark'], '明暗模式')
  if (!Object.keys(input.variants).length) throw new Error('主题至少需要一种明暗模式')
  if (input.assets !== undefined && (!input.assets || typeof input.assets !== 'object' || Array.isArray(input.assets))) throw new Error('主题资源无效')
  const assets = input.assets || {}
  const paths = new Set()
  for (const [id, asset] of Object.entries(assets)) {
    if (!identifier.test(id) || ['constructor', 'prototype'].includes(id)) throw new Error('资源名称无效')
    object(asset, ['path', 'kind', 'weight', 'style'], '资源')
    if (typeof asset.path !== 'string' || !/^assets\/[a-zA-Z0-9_./-]+$/.test(asset.path) || asset.path.split('/').some(part => !part || part === '.' || part === '..') || paths.has(asset.path)) throw new Error('资源路径无效或重复')
    paths.add(asset.path)
    if (asset.kind === 'font') {
      if (!/\.woff2$/i.test(asset.path) || (asset.weight !== undefined && (!Number.isInteger(asset.weight) || asset.weight < 100 || asset.weight > 900)) || (asset.style !== undefined && !['normal', 'italic'].includes(asset.style))) throw new Error('仅支持有效的 WOFF2 字体声明')
    } else if (asset.kind !== 'image' || !/\.(png|jpe?g|webp)$/i.test(asset.path) || asset.weight !== undefined || asset.style !== undefined) throw new Error('图片仅支持 PNG、JPEG 或 WebP')
  }
  if (paths.size + 1 > THEME_LIMITS.entries) throw new Error('主题资源数量超过上限')
  for (const mode of ['light', 'dark']) {
    const variant = input.variants[mode] === undefined ? {} : input.variants[mode]
    object(variant, variantKeys, '模式配置')
    object(variant.colors === undefined ? {} : variant.colors, Object.keys(COLOR_VARIABLES), '颜色')
    for (const color of Object.values(variant.colors || {})) if (typeof color !== 'string' || !hex.test(color)) throw new Error('颜色须为六位十六进制色值')
    if (variant.radius !== undefined && (!Number.isInteger(variant.radius) || variant.radius < 0 || variant.radius > 16)) throw new Error('圆角须在 0–16 之间')
    if (variant.shadow !== undefined && !['none', 'soft'].includes(variant.shadow)) throw new Error('阴影档位无效')
    if (variant.density !== undefined && !['comfortable', 'compact'].includes(variant.density)) throw new Error('密度档位无效')
    for (const slot of slots) {
      if (variant[slot] !== undefined && (typeof variant[slot] !== 'string' || !Object.hasOwn(assets, variant[slot]) || assets[variant[slot]].kind !== (slot.endsWith('Font') ? 'font' : 'image'))) throw new Error(`${slot}引用的资源不存在或类型不符`)
    }
    const colors = resolveVariant(input, mode).colors
    for (const bg of ['background', 'surface', 'muted']) {
      for (const fg of ['text', 'body', 'secondary', 'accent', 'success', 'warning', 'danger']) {
        if (contrastRatio(colors[fg], colors[bg]) < 4.5) throw new Error(`${mode} 的 ${fg} 与 ${bg} 对比度不足，需至少 4.5:1`)
      }
      if (contrastRatio(colors.controlBorder, colors[bg]) < 3) throw new Error(`${mode} 的控件边界对比度不足，需至少 3:1`)
    }
    for (const [fg, bg] of [['onAccent', 'accent'], ['onPrimary', 'primary']]) if (contrastRatio(colors[fg], colors[bg]) < 4.5) throw new Error(`${mode} 的按钮文字对比度不足`)
  }
  return JSON.parse(JSON.stringify(input))
}

export function variantVariables(variant) {
  const vars = Object.fromEntries(Object.entries(COLOR_VARIABLES).map(([key, css]) => [css, variant.colors[key]]))
  for (const [key, offset] of [['sm', -2], ['md', 0], ['lg', 4], ['xl', 4], ['2xl', 8]]) vars[`--radius-${key}`] = `${Math.max(0, variant.radius + offset)}px`
  vars['--control-height'] = variant.density === 'compact' ? '36px' : '40px'
  vars['--theme-float-shadow'] = variant.shadow === 'none' ? 'none' : '0 16px 48px rgb(0 0 0 / 0.18)'
  return vars
}
