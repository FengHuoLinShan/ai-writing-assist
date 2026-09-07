import { THEME_LIMITS, validateThemeManifest } from './themeTokens.js'
let resourceSequence = 0

function unpack(buffer, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) return reject(new DOMException('已取消', 'AbortError'))
    const worker = new Worker(new URL('./themeArchive.worker.js', import.meta.url), { type: 'module' })
    const finish = (error, value) => {
      clearTimeout(timer)
      signal?.removeEventListener('abort', abort)
      worker.terminate()
      if (error) reject(error)
      else resolve(value)
    }
    const abort = () => finish(new DOMException('已取消', 'AbortError'))
    const timer = setTimeout(() => finish(new Error('解压超时，请缩小主题包后重试')), 15000)
    signal?.addEventListener('abort', abort, { once: true })
    worker.onmessage = ({ data }) => finish(data.error ? new Error(data.error) : null, data.files)
    worker.onerror = () => finish(new Error('无法解压主题，请检查文件是否完整'))
    worker.postMessage(buffer, [buffer])
  })
}

function imageType(bytes) {
  if (bytes[0] === 137 && String.fromCharCode(...bytes.slice(1, 4)) === 'PNG') return 'image/png'
  if (bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255) return 'image/jpeg'
  if (String.fromCharCode(...bytes.slice(0, 4)) === 'RIFF' && String.fromCharCode(...bytes.slice(8, 12)) === 'WEBP') return 'image/webp'
  throw new Error('图片内容与支持格式不符')
}

export async function prepareThemeResources(record, { signal } = {}) {
  const manifest = validateThemeManifest(record.manifest)
  const namespace = ++resourceSequence
  const urls = new Map()
  const fonts = new Map()
  const dispose = () => {
    for (const url of urls.values()) URL.revokeObjectURL(url)
    for (const font of fonts.values()) document.fonts.delete(font)
    urls.clear()
    fonts.clear()
  }
  try {
    let total = 0
    for (const [id, asset] of Object.entries(manifest.assets || {})) {
      signal?.throwIfAborted()
      const bytes = record.files?.[asset.path]
      if (!(bytes instanceof Uint8Array) || !bytes.length) throw new Error(`缺少资源：${asset.path}`)
      total += bytes.length
      if (total > THEME_LIMITS.expanded) throw new Error('主题资源超过大小上限')
      if (asset.kind === 'font') {
        if (bytes.length > THEME_LIMITS.font || String.fromCharCode(...bytes.slice(0, 4)) !== 'wOF2') throw new Error('字体文件无效或过大')
        const font = new FontFace(`nc-${manifest.id}-${namespace}-${id}`, bytes, { weight: String(asset.weight || 400), style: asset.style || 'normal', display: 'swap' })
        await font.load()
        fonts.set(id, font)
      } else {
        if (bytes.length > THEME_LIMITS.image) throw new Error('主题图片超过 6MiB')
        const blob = new Blob([bytes], { type: imageType(bytes) })
        const bitmap = await createImageBitmap(blob)
        const valid = bitmap.width > 0 && bitmap.height > 0 && bitmap.width <= THEME_LIMITS.dimension && bitmap.height <= THEME_LIMITS.dimension
        if (!valid) { bitmap.close(); throw new Error('主题图片边长不能超过 4096 像素') }
        const canvas = document.createElement('canvas')
        canvas.width = bitmap.width
        canvas.height = bitmap.height
        canvas.getContext('2d').drawImage(bitmap, 0, 0)
        bitmap.close()
        const still = await new Promise(resolve => canvas.toBlob(resolve, 'image/webp'))
        if (!still) throw new Error('图片无法转换为静态主题资源')
        urls.set(id, URL.createObjectURL(still))
      }
    }
    signal?.throwIfAborted()
    return { manifest, urls, fonts, dispose }
  } catch (error) {
    dispose()
    throw error
  }
}

export async function readThemePackage(file, { signal } = {}) {
  if (!file || !/\.zip$/i.test(file.name) || !file.size || file.size > THEME_LIMITS.compressed) throw new Error('请选择不超过 30MiB 的 .nctheme.zip 主题包')
  const files = await unpack(await file.arrayBuffer(), signal)
  signal?.throwIfAborted()
  const manifest = validateThemeManifest(JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(files['theme.json'])))
  const expected = new Set(['theme.json', 'LICENSE.txt', ...Object.values(manifest.assets || {}).map(asset => asset.path)])
  if (Object.keys(files).some(path => !expected.has(path))) throw new Error('主题包包含未声明的资源')
  const record = { id: manifest.id, manifest, files, archive: file }
  const prepared = await prepareThemeResources(record, { signal })
  prepared.dispose()
  return record
}

function database() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('nc-theme-packages', 1)
    request.onupgradeneeded = () => request.result.createObjectStore('packages', { keyPath: 'id' })
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(new Error('无法打开本地主题存储；现用主题保持不变'))
    request.onblocked = () => reject(new Error('主题存储正在被其他页面使用，请关闭旧页面后重试'))
  })
}
async function transact(mode, action) {
  const db = await database()
  try {
    return await new Promise((resolve, reject) => {
      const tx = db.transaction('packages', mode)
      const request = action(tx.objectStore('packages'))
      tx.oncomplete = () => resolve(request.result)
      tx.onerror = tx.onabort = () => reject(new Error('主题未能保存到此浏览器，请检查可用存储空间后重试'))
    })
  } catch (cause) {
    throw new Error(mode === 'readwrite' ? '主题未能保存到此浏览器，请检查可用存储空间后重试' : '无法读取此浏览器的主题，请重试', { cause })
  } finally { db.close() }
}
export async function listThemePackages() {
  const db = await database()
  try {
    return await new Promise((resolve, reject) => {
      const items = []
      const tx = db.transaction('packages', 'readonly')
      const cursor = tx.objectStore('packages').openCursor()
      cursor.onsuccess = () => {
        if (!cursor.result) return
        const { id, manifest } = cursor.result.value
        items.push({ id, name: manifest?.name || '无法识别的主题', version: manifest?.version || '未知版本', author: manifest?.author })
        cursor.result.continue()
      }
      tx.oncomplete = () => resolve(items)
      tx.onerror = tx.onabort = () => reject(new Error('无法读取此浏览器的主题，请重试'))
    })
  } finally { db.close() }
}
export const getThemePackage = id => transact('readonly', store => store.get(id))
export const saveThemePackage = record => transact('readwrite', store => store.put(record))
export const deleteThemePackage = id => transact('readwrite', store => store.delete(id))

export function exportThemePackage(record) {
  const url = URL.createObjectURL(record.archive)
  const link = document.createElement('a')
  link.href = url
  link.download = `${record.id}.nctheme.zip`
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
