import { randomUUID } from 'node:crypto'

/** Synthetic durable transport: no model request reaches the backend/provider. */
export async function mockCocreationTurns(page, handler) {
  const tasks = new Map(), messages = new Map(), requests = []
  let reply = handler
  await page.route('**/api/world/cocreation-turns/task', async route => {
    const body = route.request().postDataJSON(), id = body.operation_id
    requests.push({ url: route.request().url(), body })
    if (!tasks.has(id)) {
      const task = { task_id: id, task_type: 'world_cocreation_turn', status: 'running', progress: 0.1, meta: body }
      tasks.set(id, task)
      Promise.resolve().then(() => reply(body)).then(result => {
        if (task.status === 'cancelled') return
        task.status = 'done'; task.progress = 1; task.result = { ...result, mode: body.mode, session_id: body.session_id }
        const rows = messages.get(body.session_id) || []
        const author = [...(body.messages || [])].reverse().find(item => item.role === 'user')
        const base = { session_id: body.session_id, kind: 'message', action: body.session_action, task_id: id, created_at: new Date().toISOString() }
        if (author) rows.push({ ...base, id: randomUUID(), role: 'author', content: author.content })
        rows.push({ ...base, id: randomUUID(), role: 'assistant', content: result.reply || result.summary, outcome_kind: body.mode === 'design' ? 'world_design_preview' : null })
        messages.set(body.session_id, rows)
      }).catch(error => { task.status = 'failed'; task.error_message = error.message })
    }
    await route.fulfill({ status: 202, json: { task_id: id, status: tasks.get(id).status } })
  })
  await page.route('**/api/tasks/**', async route => {
    const parts = new URL(route.request().url()).pathname.split('/')
    const id = parts.at(-1) === 'cancel' ? parts.at(-2) : parts.at(-1)
    const task = tasks.get(id)
    if (!task) return route.fallback()
    if (parts.at(-1) === 'cancel') task.status = 'cancelled'
    await route.fulfill({ json: task })
  })
  await page.route('**/api/world/cocreation-sessions/*?*', async route => {
    if (route.request().method() !== 'GET') return route.fallback()
    const id = new URL(route.request().url()).pathname.split('/').at(-1)
    const operations = [...tasks.values()].filter(task => task.meta.session_id === id)
    if (!operations.length && !messages.has(id)) return route.fallback()
    const response = await route.fetch(), body = await response.json()
    const rows = [...(body.messages || []), ...(messages.get(id) || [])]
    const latest = operations.at(-1)
    await route.fulfill({ response, json: { ...body, messages: rows.slice(-40), message_total: rows.length, last_operation: latest ? { task_id: latest.task_id, status: latest.status } : null } })
  })
  return { requests, tasks, setHandler(value) { reply = value },
    recordSuggestion(body, response) {
      if (!body.session_id) return
      const rows = messages.get(body.session_id) || []
      const author = [...(body.messages || [])].reverse().find(item => item.role === 'user')
      if (author) rows.push({ id: randomUUID(), session_id: body.session_id, role: 'author', kind: 'message', content: author.content })
      const suggestion = response.result?.suggestion
      rows.push({ id: randomUUID(), session_id: body.session_id, role: 'assistant', kind: 'message', content: '已生成待审设定', outcome_suggestion_id: suggestion?.id, task_id: body.operation_id })
      messages.set(body.session_id, rows)
    },
  }
}
