export const emptyMap = () => ({ schema_version: 1, layout_version: 1, features: [], constraints: [], images: [], annotation_bindings: [] })
export const copyMap = value => JSON.parse(JSON.stringify(value))
export const pointsAttribute = points => points.map(point => `${point.x},${point.y}`).join(" ")
export const mapRelationLabels = { inside: "位于区域内", north: "在北侧", south: "在南侧", east: "在东侧", west: "在西侧", northeast: "在东北", northwest: "在西北", southeast: "在东南", southwest: "在西南", adjacent: "相邻", connects: "有已知道路连接", passes_through: "路线经过", along_street: "位于这条街上", entrance_to: "是此处的入口", faces: "朝向此处" }
export const structureLevels = ['region', 'city', 'district', 'street']

export function mapSourceSelections(features, constraints = []) {
  const refs = new Map()
  for (const item of [...features, ...constraints]) for (const source of item.sources || []) {
    const ref = source.kind === 'source_range' ? { kind: 'source_range', source_ref: source.source_ref }
      : { kind: 'target', target_ref: { target_type: source.kind === 'entity' ? 'core_entity' : 'world_bible_page', target_id: source.id, target_path: '' } }
    refs.set(JSON.stringify(ref), ref)
  }
  return [...refs.values()]
}

const equal = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null)
const featureKinds = { location: '地点', landmark: '地标', road: '道路', river: '河流', area: '区域' }
export const mapFeatureCenter = feature => feature?.points?.length ? feature.points.reduce((sum, p) => ({ x: sum.x + p.x / feature.points.length, y: sum.y + p.y / feature.points.length }), { x: 0, y: 0 }) : null

function positionChange(before, after) {
  if (!before?.points?.length) return '从待定位放入地图'
  if (!after?.points?.length) return '改为待定位'
  if (after.points.length > 1 || before.points.length > 1) return `${after.points.length} 个控制点，形状已调整`
  const a = mapFeatureCenter(before), b = mapFeatureCenter(after)
  return `向${b.x > a.x ? '右' : b.x < a.x ? '左' : ''}${b.y > a.y ? '下' : b.y < a.y ? '上' : ''}调整`
}

/** Review only server-owned candidate/history documents; never builds an adoption payload. */
export function mapChangeDetails(before, after) {
  const names = new Map([...before.features, ...after.features].map(feature => [feature.id, feature.label]))
  const name = id => names.get(id) || '未关联'
  const chapter = value => value ? `第 ${value} 章开始` : '仅作者可见'
  const sources = items => (items || []).map(ref => ref.kind === 'source_range' ? `第 ${ref.source_ref.chapter_index} 章${ref.quote ? '：' + ref.quote : ''}` : ref.quote || '世界资料').join('；') || '没有引用'
  const rows = []
  const groups = [
    ['feature', 'features', 'id', item => item.label, item => [item.id]],
    ['constraint', 'constraints', 'id', item => `${name(item.subject)} · ${mapRelationLabels[item.relation] || '空间关系'} · ${name(item.target)}`, item => [item.subject, ...(item.via || []), item.target]],
    ['image', 'images', 'page_id', item => item.role === 'background' ? '图片底图' : `${name(item.feature_id)}配图`, item => [item.feature_id, ...(item.anchors || []).map(anchor => anchor.feature_id)].filter(Boolean)],
    ['binding', 'annotation_bindings', 'annotation_id', item => `${name(item.feature_id)}的图片标注`, item => [item.feature_id]],
  ]
  for (const [category, property, idKey, label, ids] of groups) {
    const previous = new Map((before[property] || []).map(item => [item[idKey], item]))
    const next = new Map((after[property] || []).map(item => [item[idKey], item]))
    for (const id of new Set([...previous.keys(), ...next.keys()])) {
      const old = previous.get(id), item = next.get(id)
      if (equal(old, item)) continue
      const fields = []
      const add = (key, title, describe) => { if (!equal(old?.[key], item?.[key])) fields.push({ title, before: old ? describe(old[key], old) : '尚未加入', after: item ? describe(item[key], item) : '已移出' }) }
      if (category === 'feature') {
        add('label', '名称', value => value)
        add('kind', '类型', value => featureKinds[value] || '地图内容')
        add('points', '位置 / 轮廓', (value, entry) => entry === item && old ? positionChange(old, item) : value?.length ? `${value.length} 个已定位控制点` : '待定位')
        add('note', '说明', value => value || '没有说明')
        add('locked', '位置锁定', value => value ? '已锁定' : '可调整')
        add('entity_id', '世界地点关联', value => value ? '已关联世界地点' : '独立地图标记')
        add('target_node_id', '子图', value => value ? '已关联子图' : '没有子图')
        add('reader_from_chapter', '阅读展示', chapter)
        add('depends_on', '依赖地点', values => (values || []).map(name).join('、') || '无')
      } else if (category === 'constraint') {
        add('relation', '关系', value => mapRelationLabels[value] || '空间关系')
        add('subject', '起点', name); add('target', '目标', name)
        add('via', '经过顺序', values => (values || []).map(name).join(' → ') || '无中间地点')
        add('path_kind', '线路类型', value => value === 'river' ? '河流' : '道路')
        add('path_label', '线路名称', value => value || '未命名路线')
      } else if (category === 'image') {
        add('role', '用途', value => value === 'background' ? '地图底图' : '地点配图')
        add('feature_id', '关联地点', name)
        add('opacity', '透明度', value => `${Math.round((value ?? 1) * 100)}%`)
        add('anchors', '校准点', value => (value || []).map(anchor => name(anchor.feature_id)).join('、') || '未校准')
        add('reader_from_chapter', '阅读展示', chapter)
      } else add('feature_id', '关联地点', name)
      if (category === 'feature' || category === 'constraint') add('sources', '来源依据', sources)
      if (!fields.length) fields.push({ title: '记录', before: '原记录', after: '依据或展示配置已更新' })
      rows.push({ key: `${category}:${id}`, category, action: !old ? '新增' : !item ? '移出' : '调整', label: label(item || old), featureIds: [...new Set([...(old ? ids(old) : []), ...(item ? ids(item) : [])])], fields })
    }
  }
  return rows
}

export function mapImageChanges(placement, before, after) {
  const changes = mapChangeDetails(before, after)
  const anchorIds = new Set((placement.anchors || []).map(anchor => anchor.feature_id))
  const anchors = changes.filter(change => change.category === 'feature' && change.featureIds.some(id => anchorIds.has(id)) && change.fields.some(field => field.title === '位置 / 轮廓' || field.title === '类型'))
  const spatial = changes.filter(change => change.category === 'constraint' || (change.category === 'feature' && change.fields.some(field => ['位置 / 轮廓', '类型', '世界地点关联', '子图'].includes(field.title))))
  return { anchors: anchors.map(change => change.label), content: spatial.map(change => `${change.action}：${change.label}`) }
}

/** Find one explicitly documented road route, never shortest distance or inferred intersections. */
export function rehearseMapRoute(document, stops, blocked = []) {
  const features = new Map(document.features.map(feature => [feature.id, feature]))
  if (stops.some(id => !features.has(id))) return { message: '选中的地点已不在当前地图，请重新选择。', legs: [], featureIds: [] }
  if (stops.length < 2) return { message: '选择起点和终点，可继续添加经过地点。', legs: [], featureIds: [] }
  const excluded = new Set(blocked), graph = new Map(document.features.map(feature => [feature.id, []]))
  for (const relation of document.constraints || []) {
    if (!['connects', 'passes_through'].includes(relation.relation) || relation.path_kind === 'river') continue
    const route = [relation.subject, ...(relation.via || []), relation.target]
    if (route.some(id => excluded.has(id) || !features.get(id)?.points.length)) continue
    for (let i = 1; i < route.length; i++) {
      graph.get(route[i - 1])?.push({ target: route[i], relation })
      graph.get(route[i])?.push({ target: route[i - 1], relation })
    }
  }
  const legs = [], featureIds = new Set()
  for (let i = 1; i < stops.length; i++) {
    const from = stops[i - 1], to = stops[i], queue = [from], previous = new Map([[from, null]])
    for (let cursor = 0; cursor < queue.length && !previous.has(to); cursor++) {
      for (const edge of graph.get(queue[cursor]) || []) if (!previous.has(edge.target)) {
        previous.set(edge.target, { from: queue[cursor], relation: edge.relation }); queue.push(edge.target)
      }
    }
    if (!previous.has(to)) return { message: `“${features.get(from).label}”到“${features.get(to).label}”之间没有足够的明确道路资料。相邻、河流或线条相交不代表可以通行。`, legs: [], featureIds: stops }
    const path = []
    for (let at = to; at !== from;) { const entry = previous.get(at); path.unshift({ from: entry.from, to: at, relation: entry.relation }); at = entry.from }
    for (const edge of path) {
      featureIds.add(edge.from); featureIds.add(edge.to)
      legs.push({ label: `${features.get(edge.from).label} → ${features.get(edge.to).label}`, points: [mapFeatureCenter(features.get(edge.from)), mapFeatureCenter(features.get(edge.to))], sources: edge.relation.sources || [], relationId: edge.relation.id })
    }
  }
  return { message: '已突出一条有明确道路关系支持的通路；连线仅示意顺序，不代表距离、耗时或已发生的行程。', legs, featureIds: [...featureIds] }
}

export function geometrySignature(document) {
  return JSON.stringify({
    features: [...document.features].sort((a, b) => a.id.localeCompare(b.id)).map(({ id, kind, entity_id, target_node_id, points }) => ({ id, kind, entity_id, target_node_id, points })),
    constraints: [...document.constraints].sort((a, b) => a.id.localeCompare(b.id)).map(({ sources: _sources, generated_by_task_id: _task, ...constraint }) => constraint),
  })
}

export function mapBounds(features) {
  const points = features.flatMap(feature => feature.points || [])
  if (!points.length) return { x: 0, y: 0, width: 900, height: 600 }
  const x = Math.min(...points.map(point => point.x)) - 70
  const y = Math.min(...points.map(point => point.y)) - 70
  return { x, y, width: Math.max(500, Math.max(...points.map(point => point.x)) - x + 100), height: Math.max(350, Math.max(...points.map(point => point.y)) - y + 80) }
}

export function removeMapFeature(document, id) {
  document.features = document.features.filter(feature => feature.id !== id)
  document.constraints = document.constraints.filter(c => ![c.subject, c.target, ...c.via].includes(id))
  document.annotation_bindings = document.annotation_bindings.filter(binding => binding.feature_id !== id)
  for (const feature of document.features) {
    if (feature.depends_on.includes(id)) { feature.points = []; feature.reader_from_chapter = null }
    feature.depends_on = feature.depends_on.filter(key => key !== id)
  }
  document.images = document.images.map(image => image.feature_id === id || image.anchors.some(anchor => anchor.feature_id === id)
    ? { ...image, role: "illustration", feature_id: null, anchors: [], geometry_hash: null, reader_from_chapter: null, reader_image_hash: null }
    : image)
}

export function mapChanges(before, after) {
  const previous = new Map(before.features.map(feature => [feature.id, feature]))
  const next = new Map(after.features.map(feature => [feature.id, feature]))
  return [
    ...after.features.filter(feature => !previous.has(feature.id)).map(feature => `新增：${feature.label}`),
    ...before.features.filter(feature => !next.has(feature.id)).map(feature => `移出：${feature.label}`),
    ...after.features.filter(feature => previous.has(feature.id) && JSON.stringify(feature) !== JSON.stringify(previous.get(feature.id))).map(feature => `调整：${feature.label}`),
    ...collectionChanges(before.constraints || [], after.constraints || [], 'id', item => {
      const names = new Map([...before.features, ...after.features].map(feature => [feature.id, feature.label]))
      return `空间关系：${names.get(item.subject) || '地点'} → ${names.get(item.target) || '地点'}`
    }),
    ...collectionChanges(before.images || [], after.images || [], 'page_id', item => item.role === 'background' ? '图片底图设置' : '地点配图设置'),
    ...collectionChanges(before.annotation_bindings || [], after.annotation_bindings || [], 'annotation_id', () => '图片标注绑定'),
  ]
}

function collectionChanges(before, after, key, label) {
  const previous = new Map(before.map(item => [item[key], item]))
  const next = new Map(after.map(item => [item[key], item]))
  return [
    ...after.filter(item => !previous.has(item[key])).map(item => `新增：${label(item)}`),
    ...before.filter(item => !next.has(item[key])).map(item => `移出：${label(item)}`),
    ...after.filter(item => previous.has(item[key]) && JSON.stringify(item) !== JSON.stringify(previous.get(item[key]))).map(item => `调整：${label(item)}`),
  ]
}
