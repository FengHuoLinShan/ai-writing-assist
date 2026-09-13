export const navigation = [
  { id: 'today', color: 'orange', title: '创作概览', icon: 'home', group: '创作空间' },
  { id: 'writing', color: 'blue', title: '写作', icon: 'writing' },
  { id: 'world', color: 'green', title: '人物与世界', icon: 'world' },
  { id: 'outline', color: 'purple', title: '故事结构', icon: 'outline' },
  { id: 'map', color: 'teal', title: '地图', icon: 'map' },
  { id: 'search', color: 'blue', title: '查找', icon: 'search' },
  { id: 'assistant', color: 'purple', title: '写作伙伴', icon: 'sparkles' },
  { id: 'projects', color: 'blue', title: '作品档案', icon: 'project', group: '我的作品' },
  { id: 'tasks', color: 'orange', title: '创作计划', icon: 'outline' },
  { id: 'import', color: 'blue', title: '导入与审阅', icon: 'project' },
  { id: 'journeys', color: 'purple', title: '互动故事', icon: 'generate', group: '另一种创作' },
]
export const pageTitles = Object.fromEntries([...navigation, ...[
  { id: 'reading', title: '潮汐之间' }, { id: 'identity', title: '选择你的创作方式' },
  { id: 'settings', title: '账户与偏好' }, { id: 'components', title: '组件与状态' },
]].map(item => [item.id, item.title]))
export const chapters = [
  { title: '雾中的灯塔', words: '2,840', state: '已完成', text: '雾从海面升起的时候，灯塔已经熄灭了三年。' },
  { title: '一封迟到的信', words: '3,126', state: '已完成', text: '信封上的邮戳属于一个早已消失的港口。' },
  { title: '潮汐之间', words: '1,862', state: '写作中', text: '林舟抵达白沙港时，最后一班渡船刚刚离岸。' },
  { title: '没有名字的航线', words: '待开始', state: '提纲', text: '沿着旧海图上的虚线，他们决定向北。' },
  { title: '风暴的另一面', words: '待开始', state: '提纲', text: '所有的罗盘，都在同一刻失去了方向。' },
  { title: '灯火归来的夜晚', words: '待开始', state: '提纲', text: '海岸线重新出现在晨光里。' },
]
export const paragraphs = [
  '码头上只剩下几个收网的渔人。湿漉漉的石阶一直伸进海里，潮水缓慢地漫上来，又缓慢地退下去，像一封迟迟没有写完的信。',
  '她把那张折了四次的海图展开，压在膝上。纸的边缘已经起了毛，靠近北方的地方有一圈淡淡的水渍。父亲的字迹穿过那圈水渍，留下一句没有结尾的话。',
  '「如果灯塔再次亮起——」',
  '“你在等船？”',
  '林舟抬起头。一个穿深蓝色外套的年轻人站在石阶上，手里提着一盏没有点亮的风灯。他的袖口沾着盐，目光却落在她膝上的海图上。',
  '“我在找一个地方。”她说。',
  '年轻人没有立刻回答。海风翻过纸页的一角，露出背面那枚小小的银色记号。他的手指收紧了一瞬，像是认出了什么，又决定不说。',
  '远处，雾中的灯塔忽然闪了一下。',
]
export const people = [
  { name: '林舟', role: '追寻真相的人', type: '人物', color: 'blue', initials: '林', note: '带着父亲留下的海图，重返阔别十年的白沙港。她相信每一次离开，都有一个没有说完的理由。' },
  { name: '沈雁', role: '灯塔守望者', type: '人物', color: 'blue', initials: '沈', note: '守着一座不再亮起的灯塔，也守着关于那场海难的最后一个秘密。' },
  { name: '白沙港', role: '故事开始的地方', type: '地点', color: 'teal', initials: '港', note: '三面环山的小港口。每逢大潮，海面会浮出一条通向旧灯塔的石路。' },
  { name: '北境海图', role: '一条不曾存在的航线', type: '物品', color: 'orange', initials: '图', note: '一张会随潮汐改变的海图。银色标记只会在月光下显现。' },
  { name: '潮汐公约', role: '海岸居民的共同约定', type: '规则', color: 'pink', initials: '约', note: '灯塔亮起时，不得有人离开港口。没有人记得这条规矩从何而来。' },
  { name: '引航人协会', role: '航线与秘密的保管者', type: '组织', color: 'green', initials: '航', note: '他们记录每一艘船的来去，却从不记录自己的名字。' },
]
export const statusOptions = [
  { id: 'normal', label: '默认' }, { id: 'empty', label: '空态' }, { id: 'loading', label: '加载' },
  { id: 'error', label: '失败' }, { id: 'conflict', label: '冲突' }, { id: 'success', label: '成功' },
]
export const notices = {
  error: { color: 'orange', icon: '!', title: '这次保存没有完成', body: '连接暂时中断。请保留当前页面，恢复连接后重试。', action: '查看重试状态' },
  conflict: { color: 'red', icon: '!', title: '发现另一个更新版本', body: '继续覆盖可能丢失另一份修改。先比较两个版本，再决定保留哪些内容。', action: '比较版本' },
  success: { color: 'green', icon: '✓', title: '工作稿已保存', body: '这是成功反馈的演示状态，没有写入真实作品。', action: '查看版本' },
}
