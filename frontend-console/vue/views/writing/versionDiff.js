/**
 * Writing 版本临时 Diff。
 *
 * 先按段落对齐，仅在变化段落中做中文字符 / 标点 / 英文词级比较。
 * 结果只存在于当前页面，不改变草稿或版本状态。
 */

const DEFAULT_PARAGRAPH_LCS_LIMIT = 120_000
const DEFAULT_TOKEN_LCS_LIMIT = 80_000

export function buildVersionDiff(leftText = "", rightText = "", options = {}) {
  const left = String(leftText ?? "").replace(/\r\n?/g, "\n")
  const right = String(rightText ?? "").replace(/\r\n?/g, "\n")
  const leftParagraphs = splitParagraphs(left)
  const rightParagraphs = splitParagraphs(right)
  const paragraphLimit = normalizeLimit(options.paragraphLcsLimit, DEFAULT_PARAGRAPH_LCS_LIMIT)
  const tokenLimit = normalizeLimit(options.tokenLcsLimit, DEFAULT_TOKEN_LCS_LIMIT)
  const paragraphDiff = sequenceDiff(leftParagraphs, rightParagraphs, paragraphLimit)
  const rows = pairChangedParagraphs(paragraphDiff.operations, tokenLimit)
  const movedParagraphs = annotateMovedParagraphs(rows)
  const leftChars = countCodePoints(left)
  const rightChars = countCodePoints(right)
  const counts = rows.reduce((result, row) => {
    result[row.type] = (result[row.type] || 0) + 1
    return result
  }, {})

  return {
    rows,
    identical: left === right,
    fallbackUsed: paragraphDiff.fallbackUsed || rows.some((row) => row.fallbackUsed),
    stats: {
      leftChars,
      rightChars,
      deltaChars: rightChars - leftChars,
      unchangedParagraphs: counts.equal || 0,
      changedParagraphs: counts.replace || 0,
      addedParagraphs: counts.insert || 0,
      removedParagraphs: counts.delete || 0,
      movedParagraphs,
    },
  }
}

export function renderVersionDiff(diff, {
  esc,
  leftLabel = "左侧版本",
  rightLabel = "右侧版本",
} = {}) {
  const escapeHtml = typeof esc === "function" ? esc : defaultEscape
  const stats = diff?.stats || {}
  const rows = Array.isArray(diff?.rows) ? diff.rows : []
  const delta = Number(stats.deltaChars || 0)
  const deltaLabel = `${delta > 0 ? "+" : ""}${delta}`
  return `
    <div class="writing-version-diff">
      <div class="writing-version-diff__stats" aria-label="版本差异统计">
        <span>左侧 ${escapeHtml(stats.leftChars || 0)} 字</span>
        <span>右侧 ${escapeHtml(stats.rightChars || 0)} 字</span>
        <span class="${delta > 0 ? "is-added" : (delta < 0 ? "is-removed" : "")}">字数差 ${escapeHtml(deltaLabel)}</span>
        <span>修改 ${escapeHtml(stats.changedParagraphs || 0)} 段</span>
        <span>新增 ${escapeHtml(stats.addedParagraphs || 0)} 段</span>
        <span>删除 ${escapeHtml(stats.removedParagraphs || 0)} 段</span>
        <span>移动 ${escapeHtml(stats.movedParagraphs || 0)} 段</span>
      </div>
      ${diff?.identical ? '<div class="writing-version-diff__identical">两个版本正文完全一致</div>' : ""}
      ${diff?.fallbackUsed ? '<div class="writing-version-diff__notice">章节较长，已使用安全降级对齐；差异内容保持完整。</div>' : ""}
      <div class="writing-version-diff__grid" role="table" aria-label="正文版本并排差异">
        <div class="writing-version-diff__header" role="columnheader">${escapeHtml(leftLabel)}</div>
        <div class="writing-version-diff__header" role="columnheader">${escapeHtml(rightLabel)}</div>
        ${renderRows(rows, escapeHtml)}
      </div>
    </div>
  `
}

function splitParagraphs(text) {
  if (!text) return []
  return text.split("\n")
}

function sequenceDiff(left, right, productLimit) {
  if (left.length === 0 || right.length === 0) {
    return {
      operations: oneSidedDiff(left, right),
      fallbackUsed: false,
    }
  }
  if (left.length * right.length > productLimit) {
    return {
      operations: prefixSuffixDiff(left, right),
      fallbackUsed: true,
    }
  }
  return {
    operations: lcsDiff(left, right),
    fallbackUsed: false,
  }
}

function lcsDiff(left, right) {
  if (left.length > right.length) {
    return lcsDiffMatrix(right, left).map((operation) => ({
      ...operation,
      type: operation.type === "delete"
        ? "insert"
        : (operation.type === "insert" ? "delete" : operation.type),
    }))
  }
  return lcsDiffMatrix(left, right)
}

function lcsDiffMatrix(left, right) {
  const rows = Array.from({ length: left.length + 1 }, () => new Uint32Array(right.length + 1))
  for (let i = left.length - 1; i >= 0; i -= 1) {
    for (let j = right.length - 1; j >= 0; j -= 1) {
      rows[i][j] = left[i] === right[j]
        ? rows[i + 1][j + 1] + 1
        : Math.max(rows[i + 1][j], rows[i][j + 1])
    }
  }

  const operations = []
  let leftIndex = 0
  let rightIndex = 0
  while (leftIndex < left.length && rightIndex < right.length) {
    if (left[leftIndex] === right[rightIndex]) {
      operations.push({ type: "equal", value: left[leftIndex] })
      leftIndex += 1
      rightIndex += 1
    } else if (rows[leftIndex + 1][rightIndex] >= rows[leftIndex][rightIndex + 1]) {
      operations.push({ type: "delete", value: left[leftIndex] })
      leftIndex += 1
    } else {
      operations.push({ type: "insert", value: right[rightIndex] })
      rightIndex += 1
    }
  }
  while (leftIndex < left.length) operations.push({ type: "delete", value: left[leftIndex++] })
  while (rightIndex < right.length) operations.push({ type: "insert", value: right[rightIndex++] })
  return operations
}

function prefixSuffixDiff(left, right) {
  let prefix = 0
  while (prefix < left.length && prefix < right.length && left[prefix] === right[prefix]) prefix += 1
  let suffix = 0
  while (
    suffix < left.length - prefix &&
    suffix < right.length - prefix &&
    left[left.length - 1 - suffix] === right[right.length - 1 - suffix]
  ) suffix += 1

  const operations = []
  for (let index = 0; index < prefix; index += 1) {
    operations.push({ type: "equal", value: left[index] })
  }
  for (let index = prefix; index < left.length - suffix; index += 1) {
    operations.push({ type: "delete", value: left[index] })
  }
  for (let index = prefix; index < right.length - suffix; index += 1) {
    operations.push({ type: "insert", value: right[index] })
  }
  for (let index = left.length - suffix; index < left.length; index += 1) {
    operations.push({ type: "equal", value: left[index] })
  }
  return operations
}

function oneSidedDiff(left, right) {
  const operations = []
  for (const value of left) operations.push({ type: "delete", value })
  for (const value of right) operations.push({ type: "insert", value })
  return operations
}

function pairChangedParagraphs(operations, tokenLimit) {
  const rows = []
  let index = 0
  while (index < operations.length) {
    const operation = operations[index]
    if (operation.type === "equal") {
      rows.push({
        type: "equal",
        leftText: operation.value,
        rightText: operation.value,
        leftSegments: [{ type: "equal", text: operation.value }],
        rightSegments: [{ type: "equal", text: operation.value }],
      })
      index += 1
      continue
    }

    const deleted = []
    const inserted = []
    while (index < operations.length && operations[index].type !== "equal") {
      if (operations[index].type === "delete") deleted.push(operations[index].value)
      if (operations[index].type === "insert") inserted.push(operations[index].value)
      index += 1
    }
    const rowCount = Math.max(deleted.length, inserted.length)
    for (let rowIndex = 0; rowIndex < rowCount; rowIndex += 1) {
      const leftText = deleted[rowIndex]
      const rightText = inserted[rowIndex]
      if (leftText !== undefined && rightText !== undefined) {
        const tokenDiff = diffParagraphTokens(leftText, rightText, tokenLimit)
        rows.push({
          type: "replace",
          leftText,
          rightText,
          leftSegments: tokenDiff.leftSegments,
          rightSegments: tokenDiff.rightSegments,
          fallbackUsed: tokenDiff.fallbackUsed,
        })
      } else if (leftText !== undefined) {
        rows.push({
          type: "delete",
          leftText,
          rightText: null,
          leftSegments: [{ type: "delete", text: leftText }],
          rightSegments: [],
        })
      } else {
        rows.push({
          type: "insert",
          leftText: null,
          rightText,
          leftSegments: [],
          rightSegments: [{ type: "insert", text: rightText }],
        })
      }
    }
  }
  return rows
}

function annotateMovedParagraphs(rows) {
  const deletedByText = new Map()
  const insertedByText = new Map()
  rows.forEach((row, index) => {
    if (row.type === "delete" && row.leftText) {
      const entries = deletedByText.get(row.leftText) || []
      entries.push(index)
      deletedByText.set(row.leftText, entries)
    }
    if (row.type === "insert" && row.rightText) {
      const entries = insertedByText.get(row.rightText) || []
      entries.push(index)
      insertedByText.set(row.rightText, entries)
    }
  })

  let moved = 0
  for (const [text, deletedIndexes] of deletedByText.entries()) {
    const insertedIndexes = insertedByText.get(text) || []
    const pairCount = Math.min(deletedIndexes.length, insertedIndexes.length)
    for (let index = 0; index < pairCount; index += 1) {
      const moveId = `move-${moved + 1}`
      const movedFrom = rows[deletedIndexes[index]]
      const movedTo = rows[insertedIndexes[index]]
      movedFrom.type = "move-from"
      movedFrom.moveId = moveId
      movedFrom.leftSegments = [{ type: "equal", text }]
      movedTo.type = "move-to"
      movedTo.moveId = moveId
      movedTo.rightSegments = [{ type: "equal", text }]
      moved += 1
    }
  }
  return moved
}

function diffParagraphTokens(leftText, rightText, tokenLimit) {
  const leftTokens = tokenize(leftText)
  const rightTokens = tokenize(rightText)
  const result = sequenceDiff(leftTokens, rightTokens, tokenLimit)
  const leftSegments = []
  const rightSegments = []
  for (const operation of result.operations) {
    if (operation.type !== "insert") appendSegment(leftSegments, operation.type, operation.value)
    if (operation.type !== "delete") appendSegment(rightSegments, operation.type, operation.value)
  }
  return { leftSegments, rightSegments, fallbackUsed: result.fallbackUsed }
}

function tokenize(text) {
  return String(text || "").match(/[\p{Script=Han}]|[\p{L}\p{N}_]+|\s+|[^\s\p{L}\p{N}_]/gu) || []
}

function appendSegment(segments, type, text) {
  const previous = segments[segments.length - 1]
  if (previous?.type === type) previous.text += text
  else segments.push({ type, text })
}

function renderRows(rows, escapeHtml) {
  if (!rows.length) return '<div class="writing-version-diff__empty">两个版本均无正文</div>'
  let html = ""
  let index = 0
  while (index < rows.length) {
    if (rows[index].type !== "equal") {
      html += renderRow(rows[index], escapeHtml)
      index += 1
      continue
    }
    let end = index
    while (end < rows.length && rows[end].type === "equal") end += 1
    const run = rows.slice(index, end)
    if (run.length <= 5) {
      html += run.map((row) => renderRow(row, escapeHtml)).join("")
    } else {
      html += run.slice(0, 2).map((row) => renderRow(row, escapeHtml)).join("")
      const hidden = run.slice(2, -2)
      html += `
        <details class="writing-version-diff__collapsed">
          <summary>折叠 ${escapeHtml(hidden.length)} 个未变化段落</summary>
          <div class="writing-version-diff__collapsed-rows">
            ${hidden.map((row) => renderRow(row, escapeHtml)).join("")}
          </div>
        </details>
      `
      html += run.slice(-2).map((row) => renderRow(row, escapeHtml)).join("")
    }
    index = end
  }
  return html
}

function renderRow(row, escapeHtml) {
  const rowType = escapeHtml(row.type)
  const moveData = renderMoveData(row, escapeHtml)
  const leftContent = renderMoveLabel(row, "left", escapeHtml)
    + renderSegments(row.leftSegments, "left", escapeHtml, row.leftText)
  const rightContent = renderMoveLabel(row, "right", escapeHtml)
    + renderSegments(row.rightSegments, "right", escapeHtml, row.rightText)
  return `<div class="writing-version-diff__cell writing-version-diff__cell--${rowType}" role="cell" data-side="左"${moveData}>${leftContent}</div>`
    + `<div class="writing-version-diff__cell writing-version-diff__cell--${rowType}" role="cell" data-side="右"${moveData}>${rightContent}</div>`
}

function renderMoveData(row, escapeHtml) {
  return row.moveId ? ` data-move-id="${escapeHtml(row.moveId)}"` : ""
}

function renderMoveLabel(row, side, escapeHtml) {
  const isMovedFrom = row.type === "move-from" && side === "left"
  const isMovedTo = row.type === "move-to" && side === "right"
  if (!isMovedFrom && !isMovedTo) return ""
  const moveNumber = String(row.moveId || "").replace(/^move-/, "")
  const action = isMovedFrom ? "移出" : "移入"
  return `<span class="pill writing-version-diff__move-label">移动 ${escapeHtml(moveNumber)} · ${action}</span>`
}

function renderSegments(segments, side, escapeHtml, paragraphText) {
  if (!segments?.length) {
    return paragraphText === ""
      ? '<span class="writing-version-diff__empty-paragraph">空段落</span>'
      : '<span class="writing-version-diff__placeholder">此侧无对应段落</span>'
  }
  if (segments.length === 1 && segments[0]?.text === "") {
    return '<span class="writing-version-diff__empty-paragraph">空段落</span>'
  }
  const html = segments.map((segment) => {
    if (segment.type === "delete" && side === "left") {
      return `<mark class="writing-version-diff__removed">${escapeHtml(segment.text)}</mark>`
    }
    if (segment.type === "insert" && side === "right") {
      return `<mark class="writing-version-diff__added">${escapeHtml(segment.text)}</mark>`
    }
    return `<span>${escapeHtml(segment.text)}</span>`
  }).join("")
  return html || '<span class="writing-version-diff__empty-paragraph">空段落</span>'
}

function normalizeLimit(value, fallback) {
  if (value == null) return fallback
  const number = Number(value)
  return Number.isFinite(number) && number >= 0 ? number : fallback
}

function countCodePoints(text) {
  let count = 0
  for (const _character of text) count += 1
  return count
}

function defaultEscape(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;")
}
