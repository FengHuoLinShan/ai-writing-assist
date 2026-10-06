# infrastructure/embedding

向量嵌入的统一出口。两条互斥路径，由 `EMBEDDING_PROVIDER` 选择：

## 路径与适用环境

| 路径 | `EMBEDDING_PROVIDER` | 适用环境 | 实现 |
|---|---|---|---|
| **TEI HTTP（生产唯一路径）** | `openai`（compose.production.yml 默认） | 生产部署 | `client.py` 经 `EMBEDDING_BASE_URL`（默认 `http://embedding:80/v1`）调用 text-embeddings-inference 容器，模型 `BAAI/bge-base-zh-v1.5` |
| **BGE ONNX 子进程** | `bge_onnx`（core/config.py 本地默认） | 本地开发 / 离线环境（无容器、无外网） | `worker.py` 的 `BgeOnnxWorker` 单例子进程 + `client.py` 的 `BgeEmbeddingClient`，批处理与 ONNX 回退 |

两条路径产出同维度（`EMBEDDING_DIM` 默认 768）同模型的向量；生产不启动
BGE ONNX 子进程，本地开发不要求 TEI 容器在线。

## 健康检查的验证对象

`scripts/check_embedding.py`（`deploy/scripts/release.sh` 迁移后、
`runtime_health.sh` 定时探测均调用）验证的是 **HTTP embedding 端点的 wire
契约**：等待端点就绪（有界重试）、发一条真实嵌入请求、断言维度与有限性。
它与生产路径一致；不覆盖 `bge_onnx` 子进程路径（该路径无 HTTP 端点，由其
单测与本地启动冒烟验证）。

## 维护约定

- 新增 provider 只经 `EMBEDDING_PROVIDER` 显式接入，不得在业务模块自建
  embedding 客户端（`novel_id` 隔离与预算记账都在统一出口内）。
- `cache.py` 的向量缓存键含模型与维度；改模型必须评估缓存失效影响。
