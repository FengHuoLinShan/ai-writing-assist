import { describe, expect, it } from 'vitest'
import { emptyMap, mapChangeDetails, mapChangedPinnedTypeRefs, mapImageChanges, mapSourceSelections, rehearseMapRoute } from '../../../vue/views/map/mapStructureEditor.js'

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

describe('空间 v2 的本地排演边界', () => {
  it.each(['character_statement', 'effective', 'relation_type', 'feature_type', 'feature_modality', 'cross_space'])('不能把%s当成已核实的全书通路', mode => {
    const document = map()
    document.schema_version = 2
    document.constraints = [route('r', '旅馆', '码头')]
    if (mode === 'character_statement') document.constraints[0].modality = 'character_statement'
    if (mode === 'effective') document.constraints[0].effective = { start: { kind: 'scene', id: 'scene' } }
    if (mode === 'relation_type') document.constraints[0].type_ref = 'typed-relation'
    if (mode === 'feature_type') document.features[0].type_ref = 'typed-feature'
    if (mode === 'feature_modality') document.features[0].modality = 'author_plan'
    if (mode === 'cross_space') document.features[2].space_id = 'dream'
    expect(rehearseMapRoute(document, ['旅馆', '码头']).legs).toEqual([])
  })
})

it('v2空间、行程、模态、范围与固定词表修订均可逐项比较采用', () => {
  const before = map(), after = structuredClone(before)
  after.schema_version = 2
  after.spaces = [...before.spaces, { id: 'dream', label: '梦境' }]
  after.features[0].modality = 'author_plan'
  after.features[0].type_ref = 'type-a'; after.features[0].type_revision_id = 'revision-a'
  after.features[0].effective = { start: { kind: 'scene', id: 'scene-a', title: '开城前夜' } }
  after.journeys = [{ id: 'j1', origin: '旅馆', destination: '码头', transport_label: '步行', duration: { minimum: 0, maximum: 20, unit: '分钟' }, access_conditions: [{ label: '凭通行牌' }], sources: [{ quote: '沿桥步行二十分钟到码头。' }], modality: 'character_statement' }]
  const changes = mapChangeDetails(before, after)
  expect(changes.map(item => item.key)).toEqual(['space:dream', 'feature:旅馆', 'journey:j1'])
  expect(changes[1].fields).toContainEqual({ title: '可信度', before: '已观察事件', after: '作者计划' })
  expect(changes[1].fields.find(item => item.title === '固定项目类型').after).toBe('项目类型（修订已固定）')
  expect(mapChangeDetails(before, after, { 'type-a@revision-a': { name: '特殊能力', revision_number: 2 } })[1].fields.find(item => item.title === '固定项目类型').after).toBe('特殊能力（第 2 版）')
  expect(changes[1].fields.find(item => item.title === '生效范围').after).toContain('开城前夜')
  expect(JSON.stringify(changes)).not.toContain('type-a')
  expect(JSON.stringify(changes)).not.toContain('revision-a')
  expect(JSON.stringify(changes)).not.toContain('scene-a')
  expect(changes[2].fields).toContainEqual({ title: '声明耗时', before: '尚未加入', after: '0—20 分钟' })
  expect(changes[2].fields.find(item => item.title === '通行条件').after).toBe('凭通行牌')
  expect(changes[2].featureIds).toEqual(['旅馆', '码头'])
})

it('只为变化的固定引用收集词条与精确修订', () => {
  const before = map(), after = structuredClone(before)
  after.features[0].type_ref = 'feature-type'; after.features[0].type_revision_id = 'feature-revision'
  after.constraints = [{ id: 'c', type_ref: 'relation-type', type_revision_id: 'relation-revision', path_type_ref: 'path-type', path_type_revision_id: 'path-revision' }]
  after.journeys = [{ id: 'j', transport_type_ref: 'transport-type', transport_type_revision_id: 'transport-revision', access_conditions: [{ type_ref: 'condition-type', type_revision_id: 'condition-revision' }] }]
  expect(mapChangedPinnedTypeRefs(before, after)).toEqual([
    { typeRef: 'feature-type', revisionId: 'feature-revision' },
    { typeRef: 'relation-type', revisionId: 'relation-revision' },
    { typeRef: 'path-type', revisionId: 'path-revision' },
    { typeRef: 'transport-type', revisionId: 'transport-revision' },
    { typeRef: 'condition-type', revisionId: 'condition-revision' },
  ])
})

it('地图差异缺少词条、场景和空间名称时给出说明且不泄漏内部ID', () => {
  const before = map(), after = structuredClone(before)
  after.features[0].type_ref = 'term-private-id'
  after.features[0].type_revision_id = 'revision-private-id'
  after.features[0].effective = { start: { kind: 'scene', id: 'scene-private-id' } }
  after.features[0].space_id = 'space-private-id'
  const text = JSON.stringify(mapChangeDetails(before, after))

  expect(text).toContain('项目类型（修订已固定）')
  expect(text).toContain('从该场景（名称暂不可用）开始')
  expect(text).toContain('未命名空间')
  expect(text).not.toContain('term-private-id')
  expect(text).not.toContain('revision-private-id')
  expect(text).not.toContain('scene-private-id')
  expect(text).not.toContain('space-private-id')
})

it('空白v2与服务端默认主空间相同，JSON字段顺序和空类型不产生虚假审核项', () => {
  const before = emptyMap(), after = structuredClone(before)
  after.spaces = [{ type_ref: null, type_revision_id: null, id: 'main', label: '主空间' }]
  expect(mapChangeDetails(before, after)).toEqual([])
})
