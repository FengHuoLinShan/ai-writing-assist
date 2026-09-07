import sampleManifest from '../themes/sample/theme.json'
import packageSchema from '../themes/theme-package.schema.json'
import { describe, expect, it } from 'vitest'
import { COLOR_VARIABLES, DEFAULT_COLORS, resolveVariant, validateThemeManifest, variantVariables } from '../vue/theme/themeTokens.js'

const valid = () => ({ schemaVersion: 1, id: 'test-pack', name: '测试主题', version: '1.0', variants: { light: {} } })
describe('theme package trust boundary', () => {
  it('accepts the documented resource example and fills absent dark values', () => {
    const example = sampleManifest
    expect(validateThemeManifest(example)).toEqual(example)
    expect(resolveVariant(valid(), 'dark').colors).toEqual(DEFAULT_COLORS.dark)
  })
  it.each([
    pack => { delete pack.id },
    pack => { pack.id = 'modern' },
    pack => { pack.schemaVersion = 2 },
    pack => { pack.variants.light.css = 'body{display:none}' },
    pack => { pack.variants.light.colors = { text: '#FFFFFF' } },
    pack => { pack.variants.light.colors = { accent: 'url(https://example.invalid)' } },
    pack => { pack.variants.light.uiFont = 'missing' },
    pack => { pack.assets = { image: { kind: 'image', path: 'assets/a.png' } }; pack.variants.light.background = ['image'] },
    pack => { pack.variants.light.radius = 400 },
    pack => { pack.assets = { image: { kind: 'image', path: 'assets/../outside.png' } } },
    pack => { pack.assets = { image: { kind: 'image', path: 'assets/vector.svg' } } },
    pack => { pack.assets = { a: { kind: 'image', path: 'assets/a.png' }, b: { kind: 'image', path: 'assets/a.png' } } },
    pack => { pack.assets = null },
    pack => { pack.variants.light = null },
    pack => { pack.variants.light.colors = null },
  ])('rejects invalid configuration without mutating input %#', mutate => {
    const pack = valid()
    mutate(pack)
    const before = JSON.stringify(pack)
    expect(() => validateThemeManifest(pack)).toThrow()
    expect(JSON.stringify(pack)).toBe(before)
  })
  it('rejects prototype keys and exposes only the documented token vocabulary', () => {
    expect(() => validateThemeManifest(JSON.parse('{"schemaVersion":1,"id":"test","name":"test","version":"1","variants":{"light":{}},"__proto__":{}}'))).toThrow()
    const schema = packageSchema
    expect(Object.keys(schema.properties.variants.properties.light.properties.colors.properties)).toEqual(Object.keys(COLOR_VARIABLES))
    expect(variantVariables(resolveVariant(valid(), 'light'))['--control-height']).toBe('40px')
  })
})
