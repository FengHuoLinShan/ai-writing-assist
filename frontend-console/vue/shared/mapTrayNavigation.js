// Navigation carries frozen identities only. Coordinates originate in the canvas.
export function parseMapTrayNavigation(raw) {
  if (!raw || raw.length > 10000) throw new Error('托盘入口无效，请重新准备。')
  let value
  try { value = JSON.parse(raw) } catch { throw new Error('托盘入口无效，请重新准备。') }
  const text = item => typeof item === 'string' && item.length > 0 && item.length <= 128
  if (!value || !['novel_id', 'node_id', 'revision_id', 'batch_id'].every(key => text(value[key])) ||
    !(value.base_revision_id === null || text(value.base_revision_id)) ||
    !Array.isArray(value.items) || value.items.length < 1 || value.items.length > 20 ||
    value.items.some(item => !item || !text(item.item_id) || !text(item.fingerprint)) ||
    new Set(value.items.map(item => item.item_id)).size !== value.items.length) throw new Error('托盘入口无效，请重新准备。')
  return { novel_id: value.novel_id, node_id: value.node_id, revision_id: value.revision_id, batch_id: value.batch_id, base_revision_id: value.base_revision_id, items: value.items.map(item => ({ item_id: item.item_id, fingerprint: item.fingerprint })) }
}
