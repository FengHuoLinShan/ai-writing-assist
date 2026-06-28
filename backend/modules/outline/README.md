# Module: outline / 大纲与结构管理模块

## 定位

outline 模块把事实层资产组织成剧情结构资产，服务写作、地图、RAG 和 AI 结构生成。

## 负责

- 剧情线 `plot_threads`
- 篇章纲 `outline_arcs`
- 章节卡 `chapter_cards`
- Scene `scenes`
- 伏笔计划 `foreshadowing_plans`
- 揭示计划 `reveal_plans`

## 关键服务

- `PlotThreadService`
- `OutlineArcService`
- `SceneService`
- `ForeshadowingPlanService`
- `RevealPlanService`
- `PlotStructureGenerator`

## API

```http
POST/GET/PATCH/DELETE /api/outline/threads...
POST/GET/PATCH/DELETE /api/outline/arcs...
POST/GET/PATCH/DELETE /api/outline/scenes...
POST/GET/PATCH/DELETE /api/outline/foreshadowing...
POST/GET/PATCH/DELETE /api/outline/reveals...
POST /api/outline/generate
```

## Facade

跨模块调用优先走 `facade.py`，当前主要提供 Scene 读取能力：

```python
async def get_scene(...)
async def get_scene_contract(...)
async def get_scenes_by_novel(...)
async def get_scenes_by_chapter(...)
```

## 测试

```bash
cd backend
pytest modules/outline/tests/ -v
```
