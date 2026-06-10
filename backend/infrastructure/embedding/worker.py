"""
BGE Embedding 推理 Worker

独立子进程运行，通过 multiprocessing.Queue 与主进程通信。
优先 ONNX Runtime (需预导出 ONNX 模型)，回退 sentence-transformers。

协议:
  task_queue 输入:
    "__SHUTDOWN__" → 退出循环
    ("__HEALTHCHECK__", request_id) → 返回健康状态
    (texts, is_query, request_id) → 编码文本

  result_queue 输出:
    (request_id, embeddings | Exception)
"""

from __future__ import annotations

import logging
import math
import multiprocessing as mp
import os

logger = logging.getLogger(__name__)

BGE_QUERY_PREFIX = "为这个句子生成表示以用于检索："

_SHUTDOWN = "__SHUTDOWN__"
_HEALTHCHECK = "__HEALTHCHECK__"


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    if norm < 1e-12:
        return vec
    return [v / norm for v in vec]


def _try_load_onnx(model_path: str, wlog) -> tuple | None:
    """尝试加载 ONNX 模型。返回 (session, tokenizer) 或 None。"""
    # 检查是否有导出的 ONNX 文件
    onnx_path = os.path.join(model_path, "model.onnx")
    if not os.path.isfile(onnx_path):
        onnx_path = model_path if model_path.endswith(".onnx") else ""
        if not onnx_path or not os.path.isfile(onnx_path):
            return None

    try:
        import onnxruntime as ort
    except ImportError:
        wlog.info("onnxruntime not installed, skip ONNX backend")
        return None

    try:
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = (
            ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        )
        sess_options.intra_op_num_threads = 2
        sess_options.inter_op_num_threads = 1

        session = ort.InferenceSession(
            onnx_path, sess_options, providers=["CPUExecutionProvider"]
        )

        # 同时加载 tokenizer
        from tokenizers import Tokenizer

        tokenizer_path = os.path.join(
            os.path.dirname(onnx_path), "tokenizer.json"
        )
        if os.path.isfile(tokenizer_path):
            tokenizer = Tokenizer.from_file(tokenizer_path)
        else:
            wlog.warning("No tokenizer.json found alongside ONNX model")
            return None

        wlog.info(
            "ONNX session ready — inputs=%s",
            [i.name for i in session.get_inputs()],
        )
        return (session, tokenizer)
    except Exception:
        wlog.exception("ONNX load failed")
        return None


def _load_st_model(model_id: str, wlog):
    """加载 sentence-transformers 模型。"""
    from sentence_transformers import SentenceTransformer

    wlog.info("Loading SentenceTransformer: %s", model_id)
    st_model = SentenceTransformer(
        model_id, device="cpu", trust_remote_code=True
    )
    wlog.info(
        "SentenceTransformer loaded, dim=%s",
        st_model.get_embedding_dimension(),
    )
    return st_model


def _resolve_model_id(model_path: str) -> str:
    """将本地路径映射到 HuggingFace model_id。"""
    if os.path.isdir(model_path):
        return model_path
    if "/" in model_path and not os.path.exists(model_path):
        return model_path
    name_map = {
        "bge-base-zh-v1.5": "BAAI/bge-base-zh-v1.5",
        "bge-small-zh-v1.5": "BAAI/bge-small-zh-v1.5",
        "bge-large-zh-v1.5": "BAAI/bge-large-zh-v1.5",
    }
    return name_map.get(model_path, model_path)


def _worker_loop(
    model_path: str,
    device: str,
    quantization: str,
    max_batch: int,
    task_queue: mp.Queue,
    result_queue: mp.Queue,
) -> None:
    """子进程主循环：加载模型 → 循环处理任务 → 退出"""
    import logging as _log

    _log.basicConfig(
        level=_log.INFO, format="[BGE-Worker] %(levelname)s %(message)s"
    )
    wlog = _log.getLogger("bge_worker")

    if device == "cpu":
        os.environ.setdefault("OMP_NUM_THREADS", "2")

    model_id = _resolve_model_id(model_path)
    _ = quantization  # 预留：ONNX 量化参数，当前由 sentence-transformers 统一处理

    # 尝试 ONNX Runtime（仅当存在导出的 .onnx 文件时）
    onnx_bundle = _try_load_onnx(model_path, wlog)
    onnx_session = None
    tokenizer = None
    st_model = None
    backend = "none"

    if onnx_bundle is not None:
        onnx_session, tokenizer = onnx_bundle
        backend = "onnx"

    if backend == "none":
        try:
            st_model = _load_st_model(model_id, wlog)
            backend = "st"
        except Exception as exc:
            wlog.exception("Failed to load any embedding backend")
            result_queue.put(
                ("__error__", RuntimeError(f"No embedding backend available: {exc}"))
            )
            return

    # 通知主进程模型已就绪
    result_queue.put(("__ready__", backend))
    wlog.info("Worker ready — backend=%s", backend)

    # ---- 主循环 ----
    while True:
        task = task_queue.get()

        if task == _SHUTDOWN:
            wlog.info("Worker shutting down")
            break

        if (
            isinstance(task, tuple)
            and len(task) == 2
            and task[0] == _HEALTHCHECK
        ):
            result_queue.put((task[1], "ok"))
            continue

        # 此时 task 必为 (texts, is_query, request_id) 三元组
        texts: list[str]
        is_query: bool
        request_id: str
        texts, is_query, request_id = task  # type: ignore[assignment]

        try:
            if is_query:
                texts = [BGE_QUERY_PREFIX + t for t in texts]

            if backend == "onnx":
                # ONNX 推理路径
                assert onnx_session is not None and tokenizer is not None
                batch_embeddings = []
                for i in range(0, len(texts), max_batch):
                    batch_texts = texts[i : i + max_batch]
                    encodings = tokenizer.encode_batch(batch_texts)
                    input_ids = [e.ids for e in encodings]
                    attention_mask = [e.attention_mask for e in encodings]
                    # Pad to same length
                    max_len = max(len(ids) for ids in input_ids)
                    padded_ids = [
                        ids + [0] * (max_len - len(ids))
                        for ids in input_ids
                    ]
                    padded_mask = [
                        mask + [0] * (max_len - len(mask))
                        for mask in attention_mask
                    ]
                    ort_inputs = {
                        "input_ids": padded_ids,
                        "attention_mask": padded_mask,
                    }
                    outputs = onnx_session.run(None, ort_inputs)
                    # 取最后一层 hidden state 的 mean pooling
                    last_hidden = outputs[0]
                    sentence_embeds = (
                        last_hidden.mean(axis=1).tolist()
                    )
                    batch_embeddings.extend(sentence_embeds)
                embeddings_list = batch_embeddings
            else:
                assert st_model is not None  # 保证 backend=="st" 时已加载
                embeddings_list = st_model.encode(
                    texts,
                    normalize_embeddings=False,
                    show_progress_bar=False,
                    batch_size=max_batch,
                ).tolist()

            embeddings_list = [_l2_normalize(e) for e in embeddings_list]
            result_queue.put((request_id, embeddings_list))

        except Exception as exc:
            wlog.exception("Encoding failed for request %s", request_id)
            result_queue.put((request_id, RuntimeError(str(exc))))


class BgeOnnxWorker:
    """BGE embedding 推理 Worker 管理进程。

    负责启动/停止子进程，提供 encode() 和 healthcheck() 接口。
    """

    def __init__(
        self,
        model_path: str,
        *,
        device: str = "cpu",
        quantization: str = "int8",
        max_batch: int = 64,
        timeout: float = 5.0,
    ) -> None:
        self._model_path = model_path
        self._device = device
        self._quantization = quantization
        self._max_batch = max_batch
        self._timeout = timeout

        self._task_queue: mp.Queue = mp.Queue(maxsize=200)
        self._result_queue: mp.Queue = mp.Queue()
        self._process: mp.Process | None = None
        self._healthy = False
        self._request_counter = 0

    @property
    def healthy(self) -> bool:
        if not self._process or not self._process.is_alive():
            return False
        return self._healthy

    def start(self) -> None:
        if self._process and self._process.is_alive():
            return
        self._process = mp.Process(
            target=_worker_loop,
            args=(
                self._model_path,
                self._device,
                self._quantization,
                self._max_batch,
                self._task_queue,
                self._result_queue,
            ),
            daemon=True,
            name="bge-worker",
        )
        self._process.start()

        # 等待 worker 就绪信号（最多等 60 秒，首次需下载/验证 HF 缓存）
        try:
            ready_id, backend = self._result_queue.get(timeout=60.0)
            if ready_id == "__ready__":
                self._healthy = True
                logger.info(
                    "BGE worker ready — pid=%s, backend=%s, model=%s",
                    self._process.pid,
                    backend,
                    self._model_path,
                )
            elif ready_id == "__error__":
                self._healthy = False
                self.stop()
                raise RuntimeError(
                    f"BGE worker failed to initialize: {backend}"
                ) from (backend if isinstance(backend, BaseException) else None)
            else:
                self._healthy = False
                self.stop()
                raise RuntimeError(
                    f"BGE worker unexpected init message: {ready_id}"
                )
        except RuntimeError:
            raise
        except Exception as exc:
            self._healthy = False
            try:
                self.stop()
            except Exception:
                pass
            raise RuntimeError(
                "BGE worker failed to start within 60s"
            ) from exc

    def stop(self, timeout: float = 5.0) -> None:
        if self._process and self._process.is_alive():
            try:
                self._task_queue.put(_SHUTDOWN, timeout=1.0)
            except Exception:
                pass
            self._process.join(timeout=timeout)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=1.0)
        self._healthy = False
        logger.info("BGE worker stopped")

    def healthcheck(self) -> bool:
        if not self._process or not self._process.is_alive():
            self._healthy = False
            return False
        try:
            self._request_counter += 1
            rid = f"health-{self._request_counter}"
            self._task_queue.put((_HEALTHCHECK, rid), timeout=1.0)
            result_id, status = self._result_queue.get(timeout=2.0)
            ok = result_id == rid and status == "ok"
            self._healthy = ok
            return ok
        except Exception:
            self._healthy = False
            return False

    def encode(
        self,
        texts: list[str],
        *,
        is_query: bool = False,
        timeout: float | None = None,
    ) -> list[list[float]]:
        """编码文本为 embedding 向量（同步阻塞）。"""
        if not self._process or not self._process.is_alive():
            raise RuntimeError("BGE worker process is not running")

        self._request_counter += 1
        request_id = f"emb-{self._request_counter}"

        effective_timeout = timeout or self._timeout
        self._task_queue.put((texts, is_query, request_id), timeout=2.0)

        try:
            result_id, result = self._result_queue.get(
                timeout=effective_timeout
            )
        except Exception:
            raise TimeoutError(
                f"BGE worker timed out after {effective_timeout}s"
            )

        if result_id != request_id:
            raise RuntimeError(
                f"BGE worker response mismatch: "
                f"expected {request_id}, got {result_id}"
            )

        if isinstance(result, Exception):
            raise result

        return result
