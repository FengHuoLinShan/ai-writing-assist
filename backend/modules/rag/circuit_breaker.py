"""
BGE Embedding 熔断降级

状态机：CLOSED → [连续失败 N 次] → OPEN → [冷却 T 秒] → HALF_OPEN → CLOSED

用法:
    cb = get_circuit_breaker()
    if cb.allow_request():
        try:
            embedding = await generate_embedding(...)
            cb.record_success()
        except Exception:
            cb.record_failure()
    else:
        # 降级：跳过 embedding，走纯关键词检索
        embedding = None
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum

logger = logging.getLogger(__name__)


class State(Enum):
    CLOSED = "closed"       # 正常
    OPEN = "open"           # 熔断
    HALF_OPEN = "half_open" # 探测


class CircuitBreaker:
    """BGE Embedding 熔断器（全局单例）"""

    def __init__(
        self,
        failure_threshold: int = 3,
        cooldown_seconds: float = 60.0,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown = cooldown_seconds

        self._state = State.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> State:
        return self._state

    def allow_request(self) -> bool:
        """检查是否允许发起 embedding 请求。"""
        with self._lock:
            if self._state == State.CLOSED:
                return True

            if self._state == State.OPEN:
                if time.monotonic() - self._last_failure_time >= self._cooldown:
                    self._state = State.HALF_OPEN
                    logger.info("Circuit breaker: OPEN -> HALF_OPEN (cooldown expired)")
                    return True
                return False

            # HALF_OPEN: 允许一次探测
            return True

    def record_success(self) -> None:
        with self._lock:
            if self._state == State.HALF_OPEN:
                self._state = State.CLOSED
                self._failure_count = 0
                logger.info("Circuit breaker: HALF_OPEN -> CLOSED (recovered)")

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == State.HALF_OPEN:
                self._state = State.OPEN
                logger.warning("Circuit breaker: HALF_OPEN -> OPEN (probe failed)")
            elif self._state == State.CLOSED and self._failure_count >= self._failure_threshold:
                self._state = State.OPEN
                logger.warning(
                    "Circuit breaker: CLOSED -> OPEN (%d consecutive failures)",
                    self._failure_count,
                )

    def reset(self) -> None:
        with self._lock:
            self._state = State.CLOSED
            self._failure_count = 0
            self._last_failure_time = 0.0

    @property
    def status(self) -> dict:
        with self._lock:
            return {
                "state": self._state.value,
                "failure_count": self._failure_count,
                "failure_threshold": self._failure_threshold,
                "cooldown_seconds": self._cooldown,
            }


# 全局单例
_circuit_breaker = CircuitBreaker()


def get_circuit_breaker() -> CircuitBreaker:
    return _circuit_breaker
