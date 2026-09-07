import { Unzip, UnzipInflate } from 'fflate'
import { THEME_LIMITS } from './themeTokens.js'

// A same-origin module worker keeps decompression off the UI without blob workers or eval.
self.onmessage = ({ data }) => {
  try {
    if (data.byteLength > THEME_LIMITS.compressed) throw new Error('主题包超过 30MiB')
    const files = Object.create(null)
    let total = 0
    let count = 0
    const unzip = new Unzip(file => {
      if (++count > THEME_LIMITS.entries) throw new Error('主题包文件数量超过上限')
      if (!/^[a-zA-Z0-9_./-]+$/.test(file.name) || file.name.startsWith('/') || file.name.split('/').some(part => part === '..' || part === '.') || Object.hasOwn(files, file.name)) throw new Error('主题包包含无效或重复路径')
      if (file.compression !== 0 && file.compression !== 8) throw new Error('主题包使用了不支持的压缩方式')
      if (file.name.endsWith('/')) return
      if (!['theme.json', 'LICENSE.txt'].includes(file.name) && !/^assets\/.+\.(png|jpe?g|webp|woff2)$/i.test(file.name)) throw new Error('主题包包含不支持的文件')
      const chunks = []
      let size = 0
      files[file.name] = null
      file.ondata = (error, chunk, final) => {
        if (error) throw error
        total += chunk.byteLength
        size += chunk.byteLength
        const limit = ['theme.json', 'LICENSE.txt'].includes(file.name) ? THEME_LIMITS.manifest : /\.woff2$/i.test(file.name) ? THEME_LIMITS.font : THEME_LIMITS.image
        if (total > THEME_LIMITS.expanded || size > limit) throw new Error('主题解压后超过资源大小上限')
        chunks.push(chunk)
        if (final) {
          const bytes = new Uint8Array(size)
          let offset = 0
          for (const part of chunks) { bytes.set(part, offset); offset += part.length }
          files[file.name] = bytes
        }
      }
      file.start()
    })
    unzip.register(UnzipInflate)
    const bytes = new Uint8Array(data)
    for (let i = 0; i < bytes.length; i += 1024) unzip.push(bytes.subarray(i, i + 1024), i + 1024 >= bytes.length)
    if (!files['theme.json'] || Object.values(files).some(value => value === null)) throw new Error('主题包不完整')
    self.postMessage({ files }, Object.values(files).map(bytes => bytes.buffer))
  } catch (error) {
    self.postMessage({ error: error.message || '无法打开主题包' })
  }
}
