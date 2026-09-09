import { nextTick } from "vue"

/** Open an existing work area without duplicating its form or state. */
export async function focusWorkspaceTool(root, selector) {
  await nextTick()
  const target = root?.querySelector(selector)
  if (!target) return false
  for (let element = target; element && element !== root; element = element.parentElement) {
    if (element.tagName === "DETAILS") element.open = true
  }
  target.scrollIntoView?.({ block: "nearest" })
  const control = target.matches("button, input, select, textarea, summary, [tabindex]")
    ? target : target.querySelector("input:not(:disabled), textarea:not(:disabled), select:not(:disabled), button:not(:disabled), summary")
  if (control) control.focus()
  else { target.setAttribute("tabindex", "-1"); target.focus() }
  return true
}
