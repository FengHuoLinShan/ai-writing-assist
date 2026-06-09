export const meta = {
  name: 'module-architecture-explorer',
  description: '并行探索每个模块结构，汇总输出总设计架构图',
  phases: [
    { title: '模块扫描', detail: '8个模块并行扫描—project/imports/world/memory/rag/context/writing/tasks' },
    { title: '依赖分析', detail: '分析跨模块引用与数据流' },
    { title: '生成架构图', detail: '合成结果产出设计结构图' },
  ],
}

phase('模块扫描')

var MODULES = [
  { name: 'project', path: 'backend/app/modules/project' },
  { name: 'imports', path: 'backend/app/modules/imports' },
  { name: 'world', path: 'backend/app/modules/world' },
  { name: 'memory', path: 'backend/app/modules/memory' },
  { name: 'rag', path: 'backend/app/modules/rag' },
  { name: 'context', path: 'backend/app/modules/context' },
  { name: 'writing', path: 'backend/app/modules/writing' },
  { name: 'tasks', path: 'backend/app/modules/tasks' },
]

var MODULE_SCHEMA = {
  type: 'object',
  properties: {
    name: { type: 'string' },
    contracts: { type: 'string' },
    models: { type: 'string' },
    repos: { type: 'string' },
    services: { type: 'string' },
    facade: { type: 'string' },
    api: { type: 'string' },
    tasks: { type: 'string' },
    imports_from_other_modules: { type: 'string' },
  },
  required: ['name', 'contracts', 'models', 'repos', 'services', 'facade', 'api', 'tasks', 'imports_from_other_modules'],
}

var moduleResults = await parallel(
  MODULES.map(function(m) {
    return function() {
      return agent(
        '探索模块 ' + m.name + '（路径: ' + m.path + '）。读取每个文件并输出：\n' +
        '1. contracts.py 中的核心类型/协议（dataclass、Protocol、Enum 等）\n' +
        '2. models.py 中的 SQLAlchemy 模型\n' +
        '3. repositories.py 中的 Repository 类\n' +
        '4. services.py 中的 Service/Processor 类\n' +
        '5. facade.py 暴露的公开函数\n' +
        '6. api.py 注册的路由（@router 装饰器）\n' +
        '7. tasks.py 中的任务函数（如果有）\n' +
        '8. 跨模块导入（from modules.xxx 语句）',
        { label: '扫:' + m.name, schema: MODULE_SCHEMA }
      )
    }
  })
)

log('8 个模块扫描完成')

phase('依赖分析')

var serialized = moduleResults.filter(Boolean).map(function(r) { return JSON.stringify(r, null, 2) }).join('\n\n')

var analysisResult = await agent(
  '基于以下 8 个模块的扫描结果，分析模块间依赖关系和数据流：\n\n' +
  serialized +
  '\n\n请分析：\n' +
  '1. 每个模块依赖了哪些其他模块\n' +
  '2. 模块间的依赖方向（谁依赖谁）\n' +
  '3. 核心数据流（哪个模块产生数据，哪个模块消费数据）\n' +
  '4. 是否存在循环依赖风险\n\n' +
  '也读取一下 backend/app/main.py 中模块注册的顺序和相关注释。',
  {
    label: '依赖分析',
    schema: {
      type: 'object',
      properties: {
        dependencies: {
          type: 'array',
          items: {
            type: 'object',
            properties: {
              from_module: { type: 'string' },
              to_module: { type: 'string' },
              reason: { type: 'string' },
            },
            required: ['from_module', 'to_module', 'reason'],
          },
        },
        data_flow: { type: 'string' },
        cycle_risk: { type: 'string' },
        layered_summary: { type: 'string' },
      },
      required: ['dependencies', 'data_flow', 'cycle_risk'],
    },
  }
)

log('依赖分析完成: ' + analysisResult.dependencies.length + ' 条依赖')

phase('生成架构图')

var moduleLines = moduleResults.filter(Boolean).map(function(r) {
  return '- name=' + r.name + ' models=[' + r.models + '] repos=[' + r.repos + '] facade=[' + r.facade + '] deps=[' + r.imports_from_other_modules + ']'
}).join('\n')

await agent(
  '已扫描 8 个模块并完成依赖分析，结果摘要：\n' +
  JSON.stringify(analysisResult, null, 2) + '\n\n' +
  '模块详情：\n' +
  moduleLines +
  '\n\n基于上述数据，创建一个精美的暗色主题架构图 HTML 文件，保存到 /Users/tywww/Desktop/项目/ai-writing-assist/docs/architecture/module-architecture.html\n\n' +
  '要求：\n' +
  '- 自包含 HTML 文件，不需要外部资源\n' +
  '- 暗色主题，现代设计，美观大方\n' +
  '- 展示 8 个模块及它们之间的依赖关系，标注数据流方向\n' +
  '- 分组为三层：核心层（project/tasks）、数据层（world/memory/rag）、应用层（imports/context/writing）\n' +
  '- 中文字体支持（使用系统字体: PingFang SC, Microsoft YaHei, sans-serif）\n' +
  '- 使用 SVG 绘制箭头和模块框，不要用 mermaid\n' +
  '- 注意 docs/architecture/ 目录可能还不存在，需要先创建\n' +
  '- 尽量让图看起来专业、可读性强\n' +
  '- 使用渐变色模块框，每层不同色调',
  { label: '生成架构图HTML', isolation: 'worktree' }
)

log('架构图已生成到 docs/architecture/module-architecture.html')
