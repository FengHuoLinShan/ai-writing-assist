<script>
import { h, mergeProps } from "vue"

function appendText(tokens, value) {
  if (!value) return
  const previous = tokens.at(-1)
  if (previous?.type === "text") {
    previous.value += value
    return
  }
  tokens.push({ type: "text", value })
}

function safeHref(value) {
  const href = String(value || "").trim().replace(/^<|>$/g, "")
  if (
    !href
    || /[\u0000-\u001f\u007f]/.test(href)
    || !/^(https?:\/\/|mailto:)/i.test(href)
  ) return ""
  return href
}

function parseInline(source) {
  const tokens = []
  let remaining = String(source || "")

  while (remaining) {
    let match = remaining.match(/^\\([\\`*_[\]{}()#+\-.!>~])/)
    if (match) {
      appendText(tokens, match[1])
      remaining = remaining.slice(match[0].length)
      continue
    }

    match = remaining.match(/^(`+)([\s\S]*?)\1/)
    if (match) {
      tokens.push({
        type: "code",
        value: match[2].replace(/^ | $/g, ""),
      })
      remaining = remaining.slice(match[0].length)
      continue
    }

    match = remaining.match(/^!\[([^\]\n]*)\]\(\s*(<?[^)\s>]+>?)(?:\s+["'][^"']*["'])?\s*\)/)
    if (match) {
      tokens.push({
        type: "image-alt",
        value: match[1] || "图片",
      })
      remaining = remaining.slice(match[0].length)
      continue
    }

    match = remaining.match(/^\[([^\]\n]+)\]\(\s*(<?[^)\s>]+>?)(?:\s+["'][^"']*["'])?\s*\)/)
    if (match) {
      tokens.push({
        type: "link",
        href: safeHref(match[2]),
        children: parseInline(match[1]),
      })
      remaining = remaining.slice(match[0].length)
      continue
    }

    match = remaining.match(/^<((?:https?:\/\/|mailto:)[^ >]+)>/i)
    if (match) {
      tokens.push({
        type: "link",
        href: safeHref(match[1]),
        children: [{ type: "text", value: match[1] }],
      })
      remaining = remaining.slice(match[0].length)
      continue
    }

    match = remaining.match(/^(\*\*|__)(?=\S)([\s\S]*?\S)\1/)
    if (match) {
      tokens.push({ type: "strong", children: parseInline(match[2]) })
      remaining = remaining.slice(match[0].length)
      continue
    }

    match = remaining.match(/^~~(?=\S)([\s\S]*?\S)~~/)
    if (match) {
      tokens.push({ type: "delete", children: parseInline(match[1]) })
      remaining = remaining.slice(match[0].length)
      continue
    }

    match = remaining.match(/^(\*|_)(?=\S)([\s\S]*?\S)\1/)
    if (match) {
      tokens.push({ type: "emphasis", children: parseInline(match[2]) })
      remaining = remaining.slice(match[0].length)
      continue
    }

    if (remaining.startsWith("\n")) {
      tokens.push({ type: "break" })
      remaining = remaining.slice(1)
      continue
    }

    const nextSpecial = remaining.search(/[\\`*_[\]~!<\n]/)
    const length = nextSpecial > 0
      ? nextSpecial
      : nextSpecial === -1
        ? remaining.length
        : 1
    appendText(tokens, remaining.slice(0, length))
    remaining = remaining.slice(length)
  }

  return tokens
}

function listMatch(line) {
  return line.match(/^ {0,3}([-+*]|\d+[.)])\s+(.+)$/)
}

function startsBlock(line) {
  return (
    /^ {0,3}(`{3,}|~{3,})/.test(line)
    || /^ {0,3}#{1,6}\s+/.test(line)
    || /^ {0,3}>\s?/.test(line)
    || /^ {0,3}((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$/.test(line)
    || Boolean(listMatch(line))
  )
}

function parseBlocks(source) {
  const lines = String(source || "").replace(/\r\n?/g, "\n").split("\n")
  const blocks = []
  let index = 0

  while (index < lines.length) {
    const line = lines[index]
    if (!line.trim()) {
      index += 1
      continue
    }

    const fence = line.match(/^ {0,3}(`{3,}|~{3,})(.*)$/)
    if (fence) {
      const marker = fence[1]
      const language = fence[2].trim().split(/\s+/)[0].replace(/[^\w-]/g, "")
      const content = []
      index += 1
      while (
        index < lines.length
        && !new RegExp(`^ {0,3}${marker[0]}{${marker.length},}\\s*$`).test(lines[index])
      ) {
        content.push(lines[index])
        index += 1
      }
      if (index < lines.length) index += 1
      blocks.push({ type: "code", language, value: content.join("\n") })
      continue
    }

    const heading = line.match(/^ {0,3}(#{1,6})\s+(.+?)\s*$/)
    if (heading) {
      blocks.push({
        type: "heading",
        level: heading[1].length,
        children: parseInline(heading[2].replace(/\s+#+\s*$/, "")),
      })
      index += 1
      continue
    }

    if (/^ {0,3}((\*\s*){3,}|(-\s*){3,}|(_\s*){3,})$/.test(line)) {
      blocks.push({ type: "rule" })
      index += 1
      continue
    }

    if (/^ {0,3}>\s?/.test(line)) {
      const quoteLines = []
      while (index < lines.length && /^ {0,3}>\s?/.test(lines[index])) {
        quoteLines.push(lines[index].replace(/^ {0,3}>\s?/, ""))
        index += 1
      }
      blocks.push({ type: "quote", children: parseBlocks(quoteLines.join("\n")) })
      continue
    }

    const firstListItem = listMatch(line)
    if (firstListItem) {
      const ordered = /^\d/.test(firstListItem[1])
      const items = []
      while (index < lines.length) {
        const item = listMatch(lines[index])
        if (!item || /^\d/.test(item[1]) !== ordered) break
        const itemLines = [item[2]]
        index += 1
        while (
          index < lines.length
          && lines[index].trim()
          && !startsBlock(lines[index])
          && /^\s{2,}/.test(lines[index])
        ) {
          itemLines.push(lines[index].trim())
          index += 1
        }
        items.push(parseInline(itemLines.join("\n")))
      }
      blocks.push({ type: "list", ordered, items })
      continue
    }

    const paragraph = [line]
    index += 1
    while (
      index < lines.length
      && lines[index].trim()
      && !startsBlock(lines[index])
    ) {
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push({
      type: "paragraph",
      children: parseInline(paragraph.join("\n")),
    })
  }

  return blocks
}

function renderInline(tokens, prefix) {
  return tokens.map((token, index) => {
    const key = `${prefix}-${index}`
    if (token.type === "text") return token.value
    if (token.type === "break") return h("br", { key })
    if (token.type === "code") return h("code", { key }, token.value)
    if (token.type === "strong") {
      return h("strong", { key }, renderInline(token.children, key))
    }
    if (token.type === "emphasis") {
      return h("em", { key }, renderInline(token.children, key))
    }
    if (token.type === "delete") {
      return h("del", { key }, renderInline(token.children, key))
    }
    if (token.type === "image-alt") {
      return h(
        "span",
        {
          key,
          class: "rp-markdown-image-alt",
          role: "img",
          "aria-label": token.value,
        },
        `〔图片：${token.value}〕`,
      )
    }
    if (token.type === "link" && token.href) {
      return h(
        "a",
        {
          key,
          href: token.href,
          target: "_blank",
          rel: "noopener noreferrer",
        },
        renderInline(token.children, key),
      )
    }
    if (token.type === "link") {
      return h(
        "span",
        { key, class: "rp-markdown-link--blocked" },
        renderInline(token.children, key),
      )
    }
    return ""
  })
}

function renderBlocks(blocks, prefix = "block") {
  return blocks.map((block, index) => {
    const key = `${prefix}-${index}`
    if (block.type === "paragraph") {
      return h("p", { key }, renderInline(block.children, key))
    }
    if (block.type === "heading") {
      return h(`h${block.level}`, { key }, renderInline(block.children, key))
    }
    if (block.type === "rule") return h("hr", { key })
    if (block.type === "quote") {
      return h("blockquote", { key }, renderBlocks(block.children, key))
    }
    if (block.type === "list") {
      return h(
        block.ordered ? "ol" : "ul",
        { key },
        block.items.map((item, itemIndex) => (
          h("li", { key: `${key}-${itemIndex}` }, renderInline(item, `${key}-${itemIndex}`))
        )),
      )
    }
    if (block.type === "code") {
      const className = block.language ? `language-${block.language}` : undefined
      return h("pre", { key }, [h("code", { class: className }, block.value)])
    }
    return null
  })
}

export default {
  name: "RpMarkdownContent",
  inheritAttrs: false,
  props: {
    source: { type: String, default: "" },
  },
  setup(props, { attrs }) {
    return () => h(
      "div",
      mergeProps(attrs, { class: "rp-markdown-content" }),
      renderBlocks(parseBlocks(props.source)),
    )
  },
}
</script>
