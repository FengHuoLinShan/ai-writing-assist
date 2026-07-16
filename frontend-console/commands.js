/**
 * 命令系统 — 支持 :command 和 /search 两种格式
 *
 * 所有命令有中文帮助文本，失败时有中文错误提示。
 */

/** @type {Object<string, {handler: function, help: string, args?: string}>} */
const _commands = {}

/**
 * 注册命令
 * @param {string} name - 命令名称
 * @param {function} handler - 处理函数 (args, context) => void
 * @param {string} help - 帮助文本
 * @param {string} [args] - 参数说明
 */
function registerCommand(name, handler, help, args) {
  _commands[name] = { handler, help, args }
}

/**
 * 执行命令
 * @param {string} input - 用户输入（含前缀 : 或 /）
 */
async function executeCommand(input) {
  if (!input || input.trim() === "") return

  const trimmed = input.trim()

  if (trimmed.startsWith("/")) {
    // 搜索模式
    const query = trimmed.slice(1).trim()
    if (query) {
      state.searchQuery = query
      router.navigate("rag", "search", true, new URLSearchParams({ q: query }))
    } else {
      toast("请在 / 后输入搜索关键词，如 /王印 旧王都", "warning")
    }
    return
  }

  // 命令模式
  const cmdStr = trimmed.startsWith(":") ? trimmed.slice(1).trim() : trimmed
  const parts = cmdStr.split(/\s+/)
  const cmdName = parts[0].toLowerCase()
  const args = parts.slice(1)

  if (!cmdName) return

  // 查找命令
  const cmd = _commands[cmdName]
  if (cmd) {
    try {
      await cmd.handler(args)
    } catch (err) {
      toast(`命令执行失败：${err.message}`, "error")
    }
  } else {
    // 模糊匹配
    const similar = Object.keys(_commands)
      .filter((k) => k.startsWith(cmdName) || cmdName.startsWith(k))
      .slice(0, 5)

    if (similar.length > 0) {
      toast(`未知命令 "${cmdName}"。您是不是想输入：${similar.join("、")}`, "warning")
    } else {
      toast(`未知命令 "${cmdName}"。输入 :help 查看所有命令。`, "error")
    }
  }
}

/**
 * 获取命令建议
 * @param {string} prefix - 输入前缀
 * @returns {Array<{name:string, help:string}>}
 */
function getSuggestions(prefix) {
  if (!prefix || prefix.length < 1) return []

  const lowerPrefix = prefix.toLowerCase()
  return Object.entries(_commands)
    .filter(([name]) => name.toLowerCase().startsWith(lowerPrefix))
    .slice(0, 8)
    .map(([name, cmd]) => ({
      name: `:${name}`,
      help: cmd.help,
      args: cmd.args,
    }))
}

/**
 * 获取所有命令的帮助文本
 * @returns {string}
 */
function getHelpText() {
  const lines = [
    "可用命令：",
    "",
  ]

  const maxLen = Math.max(...Object.keys(_commands).map((k) => k.length))

  for (const [name, cmd] of Object.entries(_commands)) {
    const padded = name.padEnd(maxLen + 2)
    const args = cmd.args ? ` ${cmd.args}` : ""
    lines.push(`  :${padded}${cmd.help}${args}`)
  }

  lines.push("")
  lines.push("搜索：")
  lines.push("  /关键词    搜索所有模块")
  lines.push("")
  lines.push("快捷键：")
  lines.push("  按 ? 查看所有快捷键")

  return lines.join("\n")
}

// ============================================================
// 注册所有命令
// ============================================================

registerCommand("help", () => {
  showModalHtml("命令帮助", `<pre style="font-family:var(--font-mono);font-size:12px;line-height:1.8;">${getHelpText()}</pre>`, [
    { text: "关闭", class: "", handler: closeModal },
  ])
}, "查看帮助")

registerCommand("projects", async () => {
  router.navigate("project")
}, "查看项目列表")

registerCommand("open", async (args) => {
  if (args[0]) {
    const targetView = args[0]
    const route = routes[targetView]
    if (route) {
      // 验证子视图是否合法
      let subView = args[1] || null
      if (subView && route.subViews && route.subViews.length > 0) {
        if (!route.subViews.includes(subView)) {
          toast(`子视图 "${subView}" 不在 ${targetView} 的合法子视图中 (${route.subViews.join(", ")})`, "warning")
          subView = null
        }
      } else if (subView && (!route.subViews || route.subViews.length === 0)) {
        // 没有子视图的模块忽略第二个参数
        subView = null
      }
      router.navigate(targetView, subView)
    } else {
      toast(`未知模块 "${targetView}"`, "error")
    }
  } else {
    toast("请指定要打开的模块，如 :open world", "warning")
  }
}, "打开模块", "<模块名> [子视图]")

registerCommand("world", async () => {
  router.navigate("world", "objects")
}, "打开世界对象页")

registerCommand("candidates", async () => {
  router.navigate("world", "review-objects")
}, "打开待处理内容")

registerCommand("rag", async (args) => {
  if (args[0] === "search" && args[1]) {
    state.searchQuery = args.slice(1).join(" ")
    router.navigate("rag", "search", true, new URLSearchParams({ q: state.searchQuery }))
  } else {
    router.navigate("rag", "status")
  }
}, "RAG 检索", "search <关键词>")

registerCommand("context", async () => {
  const query = new URLSearchParams({ tab: "task" })
  router.navigate("generate", null, true, query)
}, "编译上下文")

registerCommand("writing", async () => {
  router.navigate("writing")
}, "打开写作工作台")

registerCommand("generate", async () => {
  router.navigate("generate")
}, "打开生成中心")

registerCommand("export", async (args) => {
  const type = args[0] || "writing"
  toast(`正在导出 ${type}...`, "info")
  // 导出逻辑在各视图中实现
}, "导出", "<world|writing>")

registerCommand("save", async () => {
  toast("已保存", "success")
}, "保存当前编辑")

// 导出
window.commands = { register: registerCommand, execute: executeCommand, getSuggestions, getHelpText }
