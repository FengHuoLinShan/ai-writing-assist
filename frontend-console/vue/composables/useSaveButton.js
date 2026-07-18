/**
 * 保存按钮状态组合式函数 — 复刻 vanilla setSettingsButtonLoading /
 * setSettingsButtonError 的类名契约：saving 时挂 settings-btn-loading 并禁用；
 * 出错时挂 settings-btn-error 500ms。
 */
import { ref } from "vue"

export function useSaveButton() {
  const saving = ref(false)
  const error = ref(false)
  let timer = null

  function flashError() {
    error.value = true
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      error.value = false
      timer = null
    }, 500)
  }

  return { saving, error, flashError }
}
