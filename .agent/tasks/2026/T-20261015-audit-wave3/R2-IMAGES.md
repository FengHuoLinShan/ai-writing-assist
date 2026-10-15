# R2：Python 3.14.8 镜像和工具链修复

总记录在R1树 `.worktrees/wave3-r1/.agent/tasks/2026/T-20261015-audit-wave3/TASK.md`。本项树 `.worktrees/wave3-r2`，基于#244原head b567085bb（main d2ab2dbf3）。更新原Dependabot PR，暂不合并。

## 根因与处理

镜像更新3.14.8但 `.python-version`仍3.14.7，build中uv自动下载 `/root/.local/share/uv/python/cpython-3.14.7-...`，`/app/.venv/bin/python`指向该处。runtime仅copy /app，虚拟环境解释器不可达，PATH回退到全局3.14.8，故运行时缺pydantic。diagnostic build实测readlink/pyvenv.cfg/import复现，修复后runtime解析 `/usr/local/bin/python3.14`，Python3.14.8/pydantic2.14.0正确导入。

同步所有CI Python钉版、.python-version和文档为3.14.8；build固定 `UV_PYTHON=/usr/local/bin/python`，`UV_PYTHON_DOWNLOADS=never`，漂移直接失败而非另取解释器。

uv0.12.3的managed downloads不识别3.14.8，不能仅修镜像。官方release核对：uv0.13.1于2026-10-14发布；python-build-standalone20261013有3.14.8的macOS aarch64资产。因此同步Docker/CI/docs的uv钉版至0.13.1，使用独立uv tool环境安装并运行；未替换宿主全局uv。

## 验证与边界

- 最终 `make test-production-images` 通过：后端非root/无uv-pip/只读/实际app import、前端Nginx与静态资产、真实隔离PG恢复均通过。最终日志 /tmp/wave3-production-images-final.log；恢复摘要57d87ec029e76dc33eeb64d43ff7305961bca8bfd1b52fb977b116d54996a1d8。
- 原容器全快测8032通过、21因缺git/make环境失败；补环境后受影响的146项通过。完整原始日志保留，不将分批结果冒称首次全绿。
- 最终本机Python3.14.8/uv0.13.1完整快测：8053 passed、2 optional skipped，106.11秒；lint、repo-gates、docs-check BASE_REF=origin/main、git diff --check通过。
- 未改生产数据、未发布/部署、未调用真实模型；测试自建恢复容器由脚本正常清理。

官方工具链来源：[uv0.13.1](https://github.com/astral-sh/uv/releases/tag/0.13.1)、[python-build-standalone20261013](https://github.com/astral-sh/python-build-standalone/releases/tag/20261013)。
