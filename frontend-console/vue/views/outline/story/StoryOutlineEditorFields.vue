<template>
  <div class="story-outline-editor-fields">
    <div class="form-group">
      <label :for="`${prefix}-title-input`">标题</label>
      <input v-model="content.title" class="form-input" :id="`${prefix}-title-input`" autocomplete="off" />
    </div>

    <section class="story-outline-editor-section" :aria-labelledby="`${prefix}-core-title`">
      <div class="section-header">
        <div>
          <h3 :id="`${prefix}-core-title`">故事核心</h3>
          <p class="form-hint">先锁定这个故事最基本的吸引力和持续推进力。</p>
        </div>
      </div>
      <div class="form-grid form-grid--2">
        <label class="form-group" :for="`${prefix}-premise`">
          <span>核心前提</span>
          <textarea v-model="content.creative_core.premise" class="form-textarea" :id="`${prefix}-premise`" rows="5" />
        </label>
        <label class="form-group" :for="`${prefix}-tone`">
          <span>基调与读者承诺</span>
          <textarea v-model="content.creative_core.tone_and_reader_promise" class="form-textarea" :id="`${prefix}-tone`" rows="5" />
        </label>
        <label class="form-group" :for="`${prefix}-engine`">
          <span>故事引擎</span>
          <textarea v-model="content.creative_core.story_engine" class="form-textarea" :id="`${prefix}-engine`" rows="5" />
        </label>
        <label class="form-group" :for="`${prefix}-ending`">
          <span>结局方向（可留空）</span>
          <textarea v-model="content.creative_core.ending_direction" class="form-textarea" :id="`${prefix}-ending`" rows="5" />
        </label>
      </div>
    </section>

    <section class="story-outline-editor-section" :aria-labelledby="`${prefix}-body-title`">
      <div class="section-header">
        <div>
          <h3 :id="`${prefix}-body-title`">总览正文</h3>
          <p class="form-hint">用你习惯的方式记录全书起点、转折和收束方向。</p>
        </div>
      </div>
      <label class="form-group" :for="`${prefix}-markdown`">
        <span class="sr-only">总览正文</span>
        <textarea v-model="content.outline_markdown" class="form-textarea story-outline-editor__body" :id="`${prefix}-markdown`" rows="16" />
      </label>
    </section>

    <section class="story-outline-list-editor" :aria-labelledby="`${prefix}-storylines-title`">
      <div class="section-header">
        <div><h3 :id="`${prefix}-storylines-title`">主要剧情线</h3><p class="form-hint">把故事中最重要的发展方向拆成可排序的项目。</p></div>
        <button class="btn btn-sm" type="button" @click="addItem('major_storylines')">新增剧情线</button>
      </div>
      <article v-for="(item, index) in content.major_storylines" :key="`storyline-${index}`" class="story-outline-list-item">
        <div class="story-outline-list-item__header"><strong>剧情线 {{ index + 1 }}</strong><ListActions :index="index" :length="content.major_storylines.length" :item-label="`剧情线 ${index + 1}`" @move="moveItem('major_storylines', index, $event)" @remove="removeItem('major_storylines', index)" /></div>
        <div class="form-grid form-grid--2">
          <label class="form-group">名称<input v-model="item.name" class="form-input" /></label>
          <label class="form-group">作用<input v-model="item.narrative_function" class="form-input" placeholder="它在故事中解决什么" /></label>
          <label class="form-group">发展轨迹<textarea v-model="item.trajectory" class="form-textarea" rows="3" /></label>
          <label class="form-group">收束方向<textarea v-model="item.resolution_direction" class="form-textarea" rows="3" /></label>
        </div>
        <label class="form-group">交汇点<input class="form-input" :value="listText(item.intersections)" placeholder="多个内容用换行或顿号分开" @input="setList(item, 'intersections', $event.target.value)" /></label>
      </article>
      <p v-if="!content.major_storylines.length" class="form-hint story-outline-list-empty">还没有主要剧情线，可以稍后再补充。</p>
    </section>

    <section class="story-outline-list-editor" :aria-labelledby="`${prefix}-movements-title`">
      <div class="section-header">
        <div><h3 :id="`${prefix}-movements-title`">故事推进</h3><p class="form-hint">记录每个阶段结束后，故事状态发生了什么变化。</p></div>
        <button class="btn btn-sm" type="button" @click="addItem('macro_movements')">新增推进</button>
      </div>
      <article v-for="(item, index) in content.macro_movements" :key="`movement-${index}`" class="story-outline-list-item">
        <div class="story-outline-list-item__header"><strong>推进 {{ index + 1 }}</strong><ListActions :index="index" :length="content.macro_movements.length" :item-label="`推进 ${index + 1}`" @move="moveItem('macro_movements', index, $event)" @remove="removeItem('macro_movements', index)" /></div>
        <div class="form-grid form-grid--2">
          <label class="form-group">名称<input v-model="item.name" class="form-input" /></label>
          <label class="form-group">状态变化<textarea v-model="item.story_state_change" class="form-textarea" rows="3" /></label>
        </div>
        <label class="form-group">关联剧情线<input class="form-input" :value="listText(item.advanced_storylines)" placeholder="多个名称用换行或顿号分开" @input="setList(item, 'advanced_storylines', $event.target.value)" /></label>
      </article>
      <p v-if="!content.macro_movements.length" class="form-hint story-outline-list-empty">还没有故事推进。</p>
    </section>

    <section class="story-outline-list-editor" :aria-labelledby="`${prefix}-decisions-title`">
      <div class="section-header">
        <div><h3 :id="`${prefix}-decisions-title`">待决定问题</h3><p class="form-hint">保留尚未确定、但会影响后续写作的选择。</p></div>
        <button class="btn btn-sm" type="button" @click="addItem('open_decisions')">新增问题</button>
      </div>
      <article v-for="(item, index) in content.open_decisions" :key="`decision-${index}`" class="story-outline-list-item">
        <div class="story-outline-list-item__header"><strong>问题 {{ index + 1 }}</strong><ListActions :index="index" :length="content.open_decisions.length" :item-label="`待决定问题 ${index + 1}`" @move="moveItem('open_decisions', index, $event)" @remove="removeItem('open_decisions', index)" /></div>
        <div class="form-grid form-grid--2">
          <label class="form-group">问题<input v-model="item.question" class="form-input" /></label>
          <label class="form-group">影响<textarea v-model="item.why_it_matters" class="form-textarea" rows="3" /></label>
        </div>
        <label class="form-group">可选方向<input class="form-input" :value="listText(item.options)" placeholder="多个方向用换行或顿号分开" @input="setList(item, 'options', $event.target.value)" /></label>
      </article>
      <p v-if="!content.open_decisions.length" class="form-hint story-outline-list-empty">暂时没有待决定问题。</p>
    </section>

  </div>
</template>

<script setup>
import ListActions from "./StoryListActions.vue"

const content = defineModel({ type: Object, required: true })
defineProps({ prefix: { type: String, required: true } })

const NEW_ITEM = {
  major_storylines: () => ({ name: "", narrative_function: "", trajectory: "", intersections: [], resolution_direction: "" }),
  macro_movements: () => ({ name: "", story_state_change: "", advanced_storylines: [] }),
  open_decisions: () => ({ question: "", why_it_matters: "", options: [] }),
}

function addItem(field) {
  content.value[field].push(NEW_ITEM[field]())
}

function removeItem(field, index) {
  content.value[field].splice(index, 1)
}

function moveItem(field, index, direction) {
  const target = index + Number(direction)
  if (target < 0 || target >= content.value[field].length) return
  const [item] = content.value[field].splice(index, 1)
  content.value[field].splice(target, 0, item)
}

function listText(value) {
  return Array.isArray(value) ? value.join("、") : ""
}

function setList(item, field, value) {
  item[field] = String(value || "").split(/[\n、；;]+/u).map((part) => part.trim()).filter(Boolean)
}
</script>
