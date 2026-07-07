# Character 模块文档归档说明

旧文档入口 `docs/modules/character/README.md` 已移除；当前权威位置/状态如下。

- Character 不再是活跃独立模块。
- 人物档案、人物知识边界、人物位置等能力并入 `world`。
- 当前权威文档：`docs/modules/02_world.md`。
- 当前稳定入口：`backend/modules/world/facade.py` 与 `/api/world/characters`。
- 决策记录：`docs/adr/character-module-merge-to-world.md`。

注意：本归档说明不表示仓库中不存在历史目录或缓存残留，也不恢复旧 character 模块、旧深度导入流程或旧测试。
