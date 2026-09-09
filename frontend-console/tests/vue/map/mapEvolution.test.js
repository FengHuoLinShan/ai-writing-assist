import { describe, expect, it } from 'vitest'
import { emptyMap, mapChangeDetails, mapImageChanges, mapSourceSelections, rehearseMapRoute } from '../../../vue/views/map/mapStructureEditor.js'

const point = (id, x = 0, y = 0) => ({ id, label: id, kind: 'location', points: [{ x, y }], sources: [] })
const route = (id, from, to, extra = {}) => ({ id, subject: from, target: to, relation: 'connects', path_kind: 'road', via: [], sources: [{ quote: '明确的道路连接' }], ...extra })
const map = () => ({ ...emptyMap(), features: [point('旅馆'), point('石桥', 100), point('码头', 200)] })

describe('可解释地图修改', () => {
  it('字段变化保留可定位的review key，展示方向而非内部坐标', () => {
    const before = map(), after = structuredClone(before)
    after.features[0].label = '旧旅馆'; after.features[0].points[0].x = 80
    const [change] = mapChangeDetails(before, after)
    expect(change.key).toBe('feature:旅馆')
    expect(change.featureIds).toEqual(['旅馆'])
    expect(change.fields).toContainEqual({ title: '名称', before: '旅馆', after: '旧旅馆' })
    expect(change.fields).toContainEqual({ title: '位置 / 轮廓', before: '1 个已定位控制点', after: '向右调整' })
  })

  it('图片复核区分校准点移动与其他空间内容变化', () => {
    const before = map(), after = structuredClone(before)
    after.features[2].points[0].y = 50
    const placement = { anchors: [{ feature_id: '旅馆' }] }
    expect(mapImageChanges(placement, before, after)).toEqual({ anchors: [], content: ['调整：码头'] })
    after.features[0].points[0].y = 10
    expect(mapImageChanges(placement, before, after).anchors).toEqual(['旅馆'])
  })

  it('原文选择去重且保留章首0及精确来源边界', () => {
    const ref = { draft_id: 'draft', chapter_index: 30, start_offset: 0, end_offset: 45, source_hash: 'a'.repeat(64) }
    const source = { kind: 'source_range', source_ref: ref }
    expect(mapSourceSelections([{ sources: [source] }, { sources: [source] }])).toEqual([{ kind: 'source_range', source_ref: ref }])
    expect(mapSourceSelections([{ sources: [{ kind: 'entity', id: 'entity' }] }])[0]).toEqual({ kind: 'target', target_ref: { target_type: 'core_entity', target_id: 'entity', target_path: '' } })
  })
})

describe('只基于明确道路的临时排演', () => {
  it('按选定经过顺序找到道路，不修改地图文档', () => {
    const document = map(); document.constraints = [route('r1', '旅馆', '石桥'), route('r2', '石桥', '码头')]
    const before = JSON.stringify(document), result = rehearseMapRoute(document, ['旅馆', '码头'])
    expect(result.legs.map(leg => leg.label)).toEqual(['旅馆 → 石桥', '石桥 → 码头'])
    expect(result.featureIds).toEqual(['旅馆', '石桥', '码头'])
    expect(result.message).toContain('不代表距离')
    expect(JSON.stringify(document)).toBe(before)
  })

  it.each(['adjacent', 'river', 'stale'])('不把%s当作通行依据', mode => {
    const document = map(); document.constraints = [route('r', '旅馆', '码头', mode === 'adjacent' ? { relation: 'adjacent' } : mode === 'river' ? { path_kind: 'river' } : {})]
    const result = rehearseMapRoute(document, ['旅馆', '码头'], mode === 'stale' ? ['码头'] : [])
    expect(result.legs).toEqual([])
    expect(result.message).toContain('没有足够的明确道路资料')
  })

  it('地图删除排演地点后给出提示而非猜测替代地点', () => {
    expect(rehearseMapRoute(map(), ['旅馆', '另一个码头']).message).toContain('重新选择')
  })
})
