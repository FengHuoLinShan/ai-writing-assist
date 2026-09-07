import { describe, expect, it, vi } from 'vitest'
import { createThemeController, normalizeTheme } from '../../../vue/shell/composables/useTheme.js'

function controller(saved = null, dark = false) {
  const values = new Map(saved ? Object.entries(saved) : [])
  const storage = { getItem: key => values.get(key), setItem: vi.fn((key, value) => values.set(key, value)), removeItem: vi.fn(key => values.delete(key)) }
  const media = { matches: dark, addEventListener: vi.fn(), removeEventListener: vi.fn() }
  const root = document.createElement('div')
  const notify = vi.fn()
  return { theme: createThemeController({ storage, root, notify, matchMedia: () => media }), root, storage, media, notify }
}
describe('modern theme controller', () => {
  it.each([['sticky', 'light'], ['ink', 'light'], ['paper', 'light'], ['night', 'dark'], ['dark-soft', 'dark'], ['<img>', 'system'], ['constructor', 'system']])('migrates %s to %s', (old, next) => expect(normalizeTheme(old)).toBe(next))
  it('migrates the legacy key after the new value has been saved', () => {
    const { theme, root, storage } = controller({ novel_theme: 'warm' })
    expect(theme.initialize()).toBe('light')
    expect(root.dataset.theme).toBe('light')
    expect(storage.setItem).toHaveBeenCalledWith('nc-theme', 'light')
    expect(storage.removeItem).toHaveBeenCalledWith('novel_theme')
    theme.dispose()
  })
  it('retains legacy preferences when persistence fails and reports temporary switches', () => {
    const { theme, storage, notify } = controller({ novel_theme: 'warm' })
    storage.setItem.mockImplementation(() => { throw new Error('quota') })
    theme.initialize()
    expect(storage.removeItem).not.toHaveBeenCalled()
    theme.apply('dark')
    expect(notify).toHaveBeenCalledWith(expect.stringContaining('本次会话有效'), 'warning')
    theme.dispose()
  })
  it('tracks system changes only while system mode is selected and releases the listener', () => {
    const { theme, root, media } = controller(null, true)
    expect(theme.initialize()).toBe('system')
    expect(root.dataset.theme).toBe('dark')
    media.matches = false
    media.addEventListener.mock.calls[0][1]()
    expect(root.dataset.theme).toBe('light')
    theme.apply('dark')
    media.addEventListener.mock.calls[0][1]()
    expect(root.dataset.theme).toBe('dark')
    theme.dispose()
    expect(media.removeEventListener).toHaveBeenCalledTimes(1)
  })
  it('does not duplicate system listeners on repeated initialization', () => {
    const { theme, media } = controller()
    theme.initialize(); theme.initialize()
    expect(media.addEventListener).toHaveBeenCalledTimes(1)
    theme.dispose()
  })
})
