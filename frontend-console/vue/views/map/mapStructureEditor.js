export const emptyMap = () => ({ schema_version: 1, layout_version: 1, features: [], constraints: [], images: [], annotation_bindings: [] })
export const copyMap = value => JSON.parse(JSON.stringify(value))
export const pointsAttribute = points => points.map(point => `${point.x},${point.y}`).join(" ")

export function geometrySignature(document) {
  return JSON.stringify({
    features: [...document.features].sort((a, b) => a.id.localeCompare(b.id)).map(({ id, kind, entity_id, target_node_id, points }) => ({ id, kind, entity_id, target_node_id, points })),
    constraints: [...document.constraints].sort((a, b) => a.id.localeCompare(b.id)).map(({ sources: _sources, ...constraint }) => constraint),
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
  ]
}
