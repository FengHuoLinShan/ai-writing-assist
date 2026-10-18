import { afterEach, expect, it } from 'vitest'
import { resetBridgeOverrides, setBridgeOverrides } from '../../vue/bridge/index.js'
import { readWritingObjectReturn, rememberWritingObjectReturn, writingContentHash } from '../../vue/shared/writingObjectReturn.js'

afterEach(() => { sessionStorage.clear(); resetBridgeOverrides() })
const location = { entityId: 'person', chapterIndex: 2, draftId: 'draft', contentHash: 'a'.repeat(64), start: 1, end: 3 }

it('isolates return positions by account, work and object, and rejects malformed offsets', () => {
  setBridgeOverrides({ currentAccount: { id: 'first' } })
  rememberWritingObjectReturn('work', location)
  expect(readWritingObjectReturn('work', 'person')).toEqual(location)
  expect(readWritingObjectReturn('other', 'person')).toBeNull()
  expect(readWritingObjectReturn('work', 'other-person')).toBeNull()
  setBridgeOverrides({ currentAccount: { id: 'second' } })
  expect(readWritingObjectReturn('work', 'person')).toBeNull()
  rememberWritingObjectReturn('work', { ...location, end: 0 })
  expect(readWritingObjectReturn('work', 'person')).toBeNull()
})

it('hashes the actual text including emoji and repeated quotes', async () => {
  expect(await writingContentHash('甲😀乙，甲😀乙')).toHaveLength(64)
  expect(await writingContentHash('甲😀乙，甲😀乙')).not.toBe(await writingContentHash('甲😀乙，甲乙'))
})
