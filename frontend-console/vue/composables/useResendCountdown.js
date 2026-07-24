import { computed, onUnmounted, ref } from "vue"

const DEFAULT_RESEND_AFTER_SECONDS = 60

function normalizeSeconds(value) {
  const seconds = Number(value)
  return Number.isFinite(seconds) && seconds > 0
    ? Math.ceil(seconds)
    : DEFAULT_RESEND_AFTER_SECONDS
}

export function useResendCountdown() {
  const secondsRemaining = ref(0)
  let timerId = null

  function stop() {
    if (timerId !== null) {
      clearInterval(timerId)
      timerId = null
    }
  }

  function start(resendAfter = DEFAULT_RESEND_AFTER_SECONDS) {
    stop()
    secondsRemaining.value = normalizeSeconds(resendAfter)
    timerId = setInterval(() => {
      secondsRemaining.value -= 1
      if (secondsRemaining.value <= 0) {
        secondsRemaining.value = 0
        stop()
      }
    }, 1000)
  }

  onUnmounted(stop)

  return {
    canResend: computed(() => secondsRemaining.value === 0),
    resendLabel: computed(() => secondsRemaining.value > 0
      ? `重新发送（${secondsRemaining.value}秒）`
      : "发送验证码"),
    secondsRemaining,
    start,
  }
}
