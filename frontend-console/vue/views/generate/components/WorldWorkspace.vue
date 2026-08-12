<template>
  <div class="card generate-world-source-bar">
    <div>
      <span class="generate-world-source-label">来源</span>
      <strong>{{ sourceLabel }}</strong>
      <span v-if="sourcePage" class="badge">v{{ sourcePage.version_number || 1 }}</span>
    </div>
    <button v-if="sourcePageId" class="btn btn-sm" data-action="return-world-bible" @click="$emit('return-world-bible')">返回世界书</button>
  </div>
  <div v-if="warning" class="generate-template-warning">{{ warning }}</div>
  <div class="generate-world-targets" role="group" aria-label="生成目标">
    <button class="generate-world-target" :class="{ active: targetKind === 'core_entity' }" type="button" :aria-pressed="targetKind === 'core_entity'" data-action="select-world-target" @click="$emit('select-target', 'core_entity')">世界对象</button>
    <button class="generate-world-target" :class="{ active: targetKind === 'world_bible_page' }" type="button" :aria-pressed="targetKind === 'world_bible_page'" :disabled="!sourcePageId" data-action="select-world-target" @click="$emit('select-target', 'world_bible_page')">完善当前页</button>
    <button class="generate-world-target" :class="{ active: targetKind === 'world_bible_new_page' }" type="button" :aria-pressed="targetKind === 'world_bible_new_page'" data-action="select-world-target" @click="$emit('select-target', 'world_bible_new_page')">新建世界书页</button>
  </div>

  <div v-if="targetKind === 'core_entity'" id="generate-template-row" class="generate-template-row generate-template-row--toolbar">
    <button v-for="template in templates" :key="template.value" class="generate-template-btn" :class="{ active: selectedTemplateId === template.value }"
      type="button" :aria-pressed="selectedTemplateId === template.value" data-action="select-object-template" :title="template.hint || template.prompt || ''" @click="selectedTemplateId = template.value">{{ template.label }}</button>
    <button class="btn btn-sm" data-action="edit-object-templates" @click="$emit('edit-templates')">编辑对象模板</button>
  </div>
  <div v-else-if="targetKind === 'world_bible_page'" class="generate-world-config">将以当前服务器工作稿优先，生成一份完整的整页重构提案。</div>
  <div v-else class="generate-world-config">
    <label>页面类别
      <select id="generate-new-page-type" v-model="newPageType" class="form-select">
        <option v-for="category in categories.filter((item) => item.status !== 'archived')" :key="category.category_key" :value="category.category_key">{{ category.name || "未命名类别" }}</option>
      </select>
    </label>
    <label>页面模板（仅作资料组织参考）
      <select id="generate-new-page-template" v-model="newPageTemplateKey" class="form-select">
        <option value="">不指定</option>
        <option v-for="template in pageTemplates.filter((item) => item.status !== 'archived')" :key="template.template_key" :value="template.template_key">{{ template.name || "未命名模板" }} · 第 {{ template.version_number || 1 }} 版</option>
      </select>
    </label>
  </div>

  <div class="generate-chatbox">
    <div class="generate-chat-main">
      <div class="card generate-chat-panel">
        <div id="generate-chat-messages" class="generate-chat-messages">
          <p v-if="!messages.length" class="generate-empty-copy">可以直接说“帮我设计一个反派”，也可以先粘贴外部聊完的内容。</p>
          <div v-for="(message, index) in messages" v-else :key="index" class="generate-chat-message" :class="[message.role, { pending: message.pending, error: message.error }]">
            <div class="generate-chat-role">{{ message.role === 'assistant' ? 'AI' : '你' }}</div>
            <div class="generate-chat-bubble">{{ message.content }}</div>
          </div>
        </div>
        <div class="generate-convergence-action">
          <div>
            <strong>准备做决定时，可以先收束本轮</strong>
            <span v-if="nearMessageLimit">对话接近 40 条发送边界，收束仍需你主动开始。</span>
            <span v-else>只整理当前可见范围，不会创建建议或采用设定。</span>
          </div>
          <button class="btn btn-sm" data-action="converge-world" type="button" :disabled="busy || !hasAuthorInput" @click="$emit('converge')">{{ convergencePending ? "收束中…" : "收束本轮" }}</button>
        </div>
        <details v-if="sourcePageId && targetKind === 'world_bible_new_page'" class="generate-exploration" data-section="adjacent-exploration">
          <summary>从当前页向旁边探索一步</summary>
          <p>AI 只列最多 3 个有证据的相邻缺口，不生成正文。你选中 1 个后，顶部生成按钮才会创建独立待处理建议；未选项不会入队。</p>
          <button class="btn btn-sm" data-action="explore-world" type="button" :disabled="busy" @click="$emit('explore')">{{ explorationPending ? "寻找中…" : explorationDraft ? "重新寻找" : "寻找相邻缺口" }}</button>
          <div v-if="explorationDraft" class="generate-exploration__results">
            <div v-if="explorationDraft.stale" class="generate-template-warning">来源、对话或已选资料已变化。旧入口仅供回看，不能生成。</div>
            <article v-for="item in explorationDraft.targets" :key="item.item_id" class="generate-convergence-card" :class="{ 'is-selected': explorationSelection?.item_id === item.item_id }">
              <div class="generate-convergence-card__title"><strong>{{ item.title }}</strong><span>一跳探索</span></div>
              <p>{{ item.gap }}</p>
              <p><strong>为什么现在值得处理：</strong>{{ item.why_it_matters }}</p>
              <p><strong>仍由你决定：</strong>{{ item.author_boundary }}</p>
              <p><strong>生成后回查：</strong>{{ item.reverse_check_focus }}</p>
              <div class="generate-convergence-sources"><span>依据</span><button v-for="source in item.evidence" :key="source.key" class="btn btn-sm btn-ghost" type="button" @click="$emit('open-convergence-source', { sourceRef: source.source_ref })">{{ source.label }}</button></div>
              <button class="btn btn-sm" :class="{ 'btn-primary': explorationSelection?.item_id === item.item_id }" type="button" :disabled="explorationDraft.stale || explorationSelection?.item_id === item.item_id" @click="$emit('select-exploration', item)">{{ explorationSelection?.item_id === item.item_id ? "已选择这一条" : "选择这一条" }}</button>
            </article>
            <p class="generate-empty-copy">{{ explorationDraft.stop_reason }}</p>
            <p v-if="explorationSelection" class="generate-template-warning">只会生成所选新页；若它确实要求改写来源页，系统还会创建最多 1 条独立的待处理修订。两者都不会自动采用或继续下一跳。</p>
            <button class="btn btn-sm btn-ghost" type="button" @click="$emit('dismiss-exploration')">关闭探索</button>
          </div>
        </details>
        <section v-if="convergenceDraft" class="generate-convergence" data-section="convergence-preview" aria-label="本轮收束预览">
          <header class="generate-convergence__header">
            <div>
              <strong>本轮收束预览</strong>
              <p>{{ convergenceDraft.coverage.scopeLabel }}；共 {{ convergenceDraft.coverage.sourceCount }} 个来源块<span v-if="convergenceDraft.coverage.excludedMessageCount">，另有 {{ convergenceDraft.coverage.excludedMessageCount }} 条更早对话未纳入</span>。</p>
            </div>
            <span class="badge" :class="{ 'badge-warning': !convergenceUsable }">{{ convergenceUsable ? "范围已覆盖" : convergenceDraft.stale ? "材料已变化" : "范围不完整" }}</span>
          </header>
          <div v-if="!convergenceUsable" class="generate-template-warning">
            <p v-if="convergenceDraft.stale">对话、来源或已选材料已变化。旧选择仍可回看，但不能继续使用。</p>
            <p v-else>{{ convergenceDraft.coverage.issues?.[0] || "部分来源没有通过覆盖校验，不能形成作者决定消息。" }}</p>
            <button v-if="!convergenceDraft.externalPacketHash" class="btn btn-sm" data-action="rerun-convergence" type="button" :disabled="busy" @click="$emit('converge')">重新收束当前范围</button>
            <template v-else>
              <p>这次未形成可用的作者决定；原文仍保留，可修订后或按原文重试。只有已形成作者消息的逐字重复回包才会跳过。</p>
              <button class="btn btn-sm" data-action="rerun-external-packet" type="button" :disabled="busy || !externalPacketDraft.trim()" @click="$emit('preview-external-packet')">重新整理这份回包</button>
            </template>
          </div>
          <div class="generate-convergence__stats">
            <span>归组前 {{ convergenceDraft.detailSummary.before_grouping }}</span>
            <span>去重后 {{ convergenceDraft.detailSummary.after_deduplication }}</span>
            <span>{{ convergenceDraft.detailSummary.retained_in_sources }} 项留在原来源</span>
          </div>
          <article v-for="card in convergenceDraft.cards" :key="card.cardId" class="generate-convergence-card">
            <div class="generate-convergence-card__title"><strong>{{ card.title }}</strong><span>{{ targetLabels(card.affectedTargets) }}</span></div>
            <p>{{ card.whyNow }}</p>
            <ul v-if="card.commonGround.length" class="generate-convergence-list"><li v-for="item in card.commonGround" :key="item">{{ item }}</li></ul>
            <div class="generate-convergence-items">
              <label v-for="item in card.items" :key="item.itemId">
                <span>{{ item.text }} <small v-if="item.externalDisposition" class="badge">{{ externalDispositionLabel(item.externalDisposition) }}</small></span>
                <select class="form-select" :value="item.disposition" :disabled="!convergenceUsable" :aria-label="`${item.text} 的处理方式`" @change="$emit('set-convergence-disposition', card.cardId, item.itemId, $event.target.value)">
                  <option value="include">纳入本次决定</option>
                  <option value="open">继续开放</option>
                  <option value="discard">明确放弃</option>
                </select>
              </label>
            </div>
            <details v-if="card.dependencies.length"><summary>依赖与影响</summary><ul class="generate-convergence-list"><li v-for="item in card.dependencies" :key="item">{{ item }}</li></ul></details>
            <div class="generate-convergence-sources"><span>来源</span><button v-for="source in card.sourceRefs" :key="source.key" class="btn btn-sm btn-ghost" type="button" @click="$emit('open-convergence-source', source)">{{ source.label }}</button></div>
          </article>
          <p v-if="convergenceDraft.nextBoundary" class="generate-convergence-boundary"><strong>继续扩展的边界：</strong>{{ convergenceDraft.nextBoundary }}</p>
          <label class="generate-convergence-message">可编辑的作者决定消息
            <textarea class="form-textarea" rows="9" :value="convergenceDraft.authorMessage" :disabled="!convergenceUsable" @input="$emit('edit-convergence-message', $event.target.value)" />
          </label>
          <div class="generate-convergence-actions">
            <button class="btn btn-sm btn-primary" data-action="apply-convergence-message" type="button" :disabled="!convergenceUsable || !convergenceDraft.authorMessage.trim()" @click="$emit('apply-convergence-message')">放入输入框继续修改</button>
            <button class="btn btn-sm" data-action="copy-world-handoff" type="button" :disabled="!convergenceUsable || !convergenceDraft.manifest?.length" @click="$emit('copy-handoff')">复制交接快照</button>
            <button class="btn btn-sm" data-action="download-world-handoff" type="button" :disabled="!convergenceUsable || !convergenceDraft.manifest?.length" @click="$emit('download-handoff')">下载 Markdown</button>
            <button class="btn btn-sm" data-action="open-story-outline" type="button" :disabled="!convergenceUsable" @click="$emit('open-story-outline')">去故事总览</button>
            <button class="btn btn-sm btn-ghost" type="button" @click="$emit('dismiss-convergence')">关闭预览</button>
          </div>
          <p class="generate-empty-copy">全书或分部的核心前提、叙事读法、基调与读者承诺请放在故事总览；前往只切换工作区，不会改写世界事实。放入输入框仍不会创建建议；只有发送消息并再次点击生成建议，才会进入待处理。</p>
        </section>
        <details v-if="convergenceDraft || visualBrief" class="generate-visual-brief" data-section="visual-brief" :open="Boolean(visualBrief)">
          <summary>准备视觉稿</summary>
          <p>先固定一张图要解决的问题，再决定是否进入结构化地图预览或把文本简报交给外部工具。这里不调用图像模型，也不保存图片。</p>
          <div class="generate-visual-brief__axes">
            <span><strong>来源设定</strong>{{ visualBrief?.sourceLabel || "等待从本轮收束建立简报" }}</span>
            <span><strong>视觉结果</strong>{{ visualBriefStatus }}</span>
          </div>
          <button v-if="!visualBrief" class="btn btn-sm" data-action="create-visual-brief" type="button" :disabled="!convergenceUsable" @click="$emit('create-visual-brief')">从本轮决定准备简报</button>
          <template v-else>
            <div v-if="!visualBriefCurrent" class="generate-template-warning">来源或作者决定已经变化。当前编辑仍保留，但不能确认、导出或应用；请先重新收束，再基于当前来源重做。</div>
            <div class="generate-visual-brief__grid">
              <label>画面用途
                <select class="form-select" :value="visualBrief.purpose" :disabled="!visualBriefCurrent" @change="$emit('edit-visual-brief', 'purpose', $event.target.value)">
                  <option v-for="item in visualPurposeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
                </select>
              </label>
              <label>必须准确的名称或标签
                <textarea class="form-textarea" rows="3" maxlength="20000" :value="visualBrief.exactLabels" :disabled="!visualBriefCurrent" @input="$emit('edit-visual-brief', 'exactLabels', $event.target.value)" />
              </label>
              <label>必须保留
                <textarea class="form-textarea" rows="5" maxlength="20000" :value="visualBrief.mustKeep" :disabled="!visualBriefCurrent" @input="$emit('edit-visual-brief', 'mustKeep', $event.target.value)" />
              </label>
              <label>仍开放
                <textarea class="form-textarea" rows="5" maxlength="20000" :value="visualBrief.openItems" :disabled="!visualBriefCurrent" @input="$emit('edit-visual-brief', 'openItems', $event.target.value)" />
              </label>
              <label class="generate-visual-brief__wide">不要新增
                <textarea class="form-textarea" rows="4" maxlength="20000" :value="visualBrief.avoid" :disabled="!visualBriefCurrent" @input="$emit('edit-visual-brief', 'avoid', $event.target.value)" />
              </label>
            </div>
            <p class="generate-empty-copy">一份简报只服务一种用途；总览、城区和工程剖面请拆成最多 3 份分别准备。确认只固定本会话里的意图，不创建建议、地图、事实或画布版本。</p>
            <div class="generate-convergence-actions">
              <button class="btn btn-sm btn-primary" data-action="confirm-visual-brief" type="button" :disabled="!visualBriefCurrent" @click="$emit('confirm-visual-brief')">{{ visualBrief.confirmedAt ? "重新确认简报" : "确认视觉简报" }}</button>
              <button class="btn btn-sm" data-action="copy-visual-brief" type="button" :disabled="!visualBriefConfirmed" @click="$emit('copy-visual-brief')">复制外部简报</button>
              <button class="btn btn-sm" data-action="download-visual-brief" type="button" :disabled="!visualBriefConfirmed" @click="$emit('download-visual-brief')">下载 Markdown</button>
              <button class="btn btn-sm" data-action="preview-visual-map" type="button" :disabled="!visualBriefConfirmed || busy" @click="$emit('preview-visual-map')">预览地图结构</button>
              <button v-if="!visualBriefCurrent && convergenceUsable" class="btn btn-sm btn-ghost" data-action="rebuild-visual-brief" type="button" @click="$emit('create-visual-brief')">按当前收束重做</button>
            </div>
            <p class="generate-empty-copy">外部候选图由你下载并保管；画面细节不会自动成为地点、距离、设施或世界事实。需要采用时，请在地图预览、观察审查或世界建议中逐项确认。</p>
          </template>
        </details>
        <details class="generate-external-handoff" data-section="external-handoff">
          <summary>与外部模型交接</summary>
          <p>主输入框写清“这次要处理什么”，这里粘贴外部模型按当前目标返回的一份材料。整理只生成上方预览，不会创建建议或采用设定。</p>
          <p v-if="!sourcePageId" class="generate-template-warning">项目级材料只能作为参考；首批无法证明所有项目来源自导出后都没有变化，请重新选择当前真正要处理的来源。</p>
          <label class="generate-external-handoff__input">外部回包
            <textarea id="generate-external-packet" v-model="externalPacketDraft" class="form-textarea" rows="8" placeholder="粘贴一份不超过 55,000 字符的回包；原文不会因超限而被截断。" />
          </label>
          <div class="generate-external-handoff__meta" :class="{ 'is-over-limit': externalPacketOverLimit }">
            <span>{{ externalPacketCount.toLocaleString("zh-CN") }} / 55,000 字符</span>
            <span v-if="externalPacketOverLimit">已超限，请让外部模型按当前目标拆包；当前原文仍保留。</span>
            <span v-else>外部编号和“已检查／已通过”只作为来源声明，本地尚未验证。</span>
          </div>
          <div class="generate-convergence-actions">
            <button class="btn btn-sm btn-primary" data-action="preview-external-packet" type="button" :disabled="busy || !externalPacketDraft.trim()" @click="$emit('preview-external-packet')">整理这份回包</button>
            <button class="btn btn-sm btn-ghost" type="button" :disabled="busy || !externalPacketDraft" @click="$emit('clear-external-packet')">清空输入</button>
          </div>
          <div v-if="externalPackets.length" class="generate-external-packet-history">
            <strong>{{ externalPacketSummary.label }}</strong>
            <article v-for="item in externalPackets" :key="`${item.packetIndex}:${item.hash}:${item.previewedAt}`">
              <span>{{ packetLabel(item) }} · {{ packetStatus(item.status) }} · {{ item.characterCount.toLocaleString("zh-CN") }} 字符</span>
              <span v-if="item.sourceCount != null">本地来源覆盖 {{ item.coveredSourceCount || 0 }}/{{ item.sourceCount }}</span>
              <details><summary>校验详情</summary><code>SHA-256 {{ item.hash }}</code><p>仅校验本地来源清单与覆盖；外部回包自称的检查项目不是本地回执。</p></details>
            </article>
          </div>
        </details>
        <div class="generate-composer">
          <textarea
            id="generate-chat-input"
            v-model="composer"
            class="generate-chat-input"
            rows="4"
            placeholder="说明你想创造、推敲或重构的世界设定。AI 会同时关注创意与逻辑。"
            @compositionstart="composing = true"
            @compositionend="composing = false"
            @keydown="onComposerKeydown"
          />
          <button
            class="btn btn-sm generate-composer-send"
            data-action="send-chat-message"
            type="button"
            :disabled="busy || !composer.trim()"
            @click="$emit('send-chat')"
          >{{ chatPending ? "发送中…" : "发送" }}</button>
        </div>
      </div>
    </div>
    <details class="workspace-rail generate-side-rail workspace-rail--right" :open="railOpen" :data-workspace-rail-key="railKey" @toggle="onRailToggle">
      <summary class="workspace-rail__summary" :aria-label="`${railOpen ? '收起' : '展开'}上下文与结果`">
        <span class="workspace-rail__title">上下文与结果</span>
        <span class="workspace-rail__chevron" aria-hidden="true">⌄</span>
      </summary>
      <div class="workspace-rail__body"><div class="generate-chat-side">
        <div class="card generate-settings-card">
          <div class="generate-card-title-row"><div class="card-title">上下文</div></div>
          <div class="generate-side-options">
            <label class="generate-quality-toggle"><input id="generate-quality-pro" v-model="qualityPro" type="checkbox" /><span>加强复核（会多检查一遍）</span></label>
            <label class="generate-quality-toggle"><input id="generate-include-world-synopsis" v-model="includeWorldSynopsis" type="checkbox" /><span>使用世界观简介</span></label>
            <label class="generate-quality-toggle generate-quality-toggle--stacked"><span>已发布 AI 参考规则（显式启用）</span>
              <select id="generate-activation-profile" v-model="activationProfileId" class="form-select"><option :value="null">不启用</option><option v-for="profile in activationProfiles" :key="profile.id" :value="profile.id">{{ profile.name }} · v{{ profile.version_number }}</option></select>
            </label>
            <div id="generate-chat-context-usage"><button v-if="chatContextUsage" class="btn btn-sm" data-action="view-generation-context" @click="$emit('view-context', 'chat')">查看最近聊天上下文</button></div>
            <button class="btn btn-sm" data-action="select-source-chapters" @click="$emit('select-chapters')">附带正文</button>
          </div>
          <p class="generate-empty-copy">单次最多附带 20 章；长对话只发送最近 40 条消息。</p>
          <div id="generate-selected-chapters" class="generate-attachment-summary">{{ chapterSummary }}</div>
          <details class="generate-world-context-panel"><summary>展开精确上下文</summary>
            <label>当前场景<select id="generate-world-scene" v-model="selectedSceneId" class="form-select"><option value="">不指定</option><option v-for="scene in scenes" :key="scene.id" :value="scene.id">{{ scene.title || scene.name || '未命名场景' }}</option></select></label>
            <label>剧情线<select id="generate-world-threads" v-model="selectedThreadIds" class="form-select" multiple size="4"><option v-for="thread in threads" :key="thread.id" :value="thread.id">{{ thread.title || thread.name || "未命名剧情线" }}</option></select></label>
            <label>人物（不手动选择时，自动参考最相关的最多 6 位）<select id="generate-world-characters" v-model="selectedCharacterIds" class="form-select" multiple size="4"><option v-for="item in characters" :key="characterId(item)" :value="characterId(item)">{{ item.name || item.display_name || "未命名人物" }}</option></select></label>
            <label>物品 / 世界对象（不手动选择时，自动参考最相关的最多 16 个）<select id="generate-world-entities" v-model="selectedEntityIds" class="form-select" multiple size="5"><option v-for="item in entities" :key="item.id" :value="item.id">{{ item.name || "未命名世界对象" }}</option></select></label>
            <label v-if="relatedWorldPages.length">相关世界书页（已选 {{ selectedRelatedWorldPageIds.length }}/16）<select id="generate-world-pages" v-model="selectedWorldPageIds" class="form-select" multiple size="5"><option v-for="item in relatedWorldPages" :key="item.id" :value="item.id" :disabled="selectedRelatedWorldPageIds.length >= 16 && !selectedWorldPageIds.includes(item.id)">{{ item.title || '未命名页面' }} · 已采用</option></select></label>
            <p v-else class="generate-empty-copy">暂无其他已采用的世界书页可作参考。</p>
            <p v-if="relatedWorldPages.length" class="generate-empty-copy">所选页只作本轮聊天、收束与建议的参考；不会合并、修改或自动采用。</p>
          </details>
        </div>
        <div class="card"><div class="card-title">结果</div><div id="generate-result" class="generate-result">
          <div v-if="loadingResult" class="loading">正在{{ generateLabel }}...</div>
          <template v-else>
            <p v-if="resultError" class="generate-error-text">{{ resultError }}</p>
            <WorldResult v-if="result || !resultError" :result="result" :previous-result="previousResult" :baseline="sourceDraft || sourcePage" :categories="categories" :context-usage="entityContextUsage" :proposal-draft="proposalDraft" :proposal-reset-token="proposalResetToken" :recovered="recoveredPageProposal" :busy="busy"
              @apply="$emit('apply-page', $event)" @dirty="$emit('proposal-dirty', $event)" @proposal-edit="$emit('proposal-edit', $event)" @clear="$emit('clear-result')" @continue-chat="focusComposer" @open-review="$emit('open-review')" @view-context="$emit('view-context', 'entity')" />
            <div v-if="sourceRevisionResult" class="generate-template-warning" data-state="source-revision-created">
              <strong>来源页还有 1 条待处理修订</strong>
              <p>相邻新页具体改变了来源页的解释。修订已单独保存，仍需你在世界书中审阅；不会随新页一起采用。</p>
              <button class="btn btn-sm" type="button" @click="$emit('open-source-revision')">返回来源页审阅</button>
            </div>
          </template>
        </div></div>
      </div></div>
    </details>
  </div>
</template>

<script setup>
import { computed, nextTick, ref } from "vue"
import {
  EXTERNAL_HANDOFF_PACKET_CHAR_LIMIT,
  VISUAL_BRIEF_PURPOSE_OPTIONS,
  characterId,
  externalDispositionLabel,
  externalPacketBatchSummary,
  externalPacketCharacterCount,
} from "../logic/generateLogic.js"
import WorldResult from "./WorldResult.vue"

const props = defineProps({
  projectId: String, sourcePageId: String, targetKind: String, sourcePage: Object, sourceDraft: Object,
  warning: String, templates: Array, activationProfiles: Array, categories: Array, pageTemplates: Array, pages: Array,
  scenes: Array, threads: Array, characters: Array, entities: Array, result: Object, previousResult: Object,
  chatContextUsage: Object, entityContextUsage: Object, proposalDraft: Object, proposalResetToken: Number, recoveredPageProposal: Boolean, busy: Boolean, chatPending: Boolean, loadingResult: Boolean, resultError: String,
  convergenceDraft: Object, convergencePending: Boolean, visualBrief: Object, externalPackets: { type: Array, default: () => [] },
  explorationDraft: Object, explorationPending: Boolean, explorationSelection: Object, sourceRevisionResult: Object,
})
const emit = defineEmits(["send-chat", "select-target", "edit-templates", "return-world-bible", "select-chapters", "apply-page", "proposal-dirty", "proposal-edit", "clear-result", "open-review", "view-context", "converge", "set-convergence-disposition", "edit-convergence-message", "apply-convergence-message", "dismiss-convergence", "open-convergence-source", "copy-handoff", "download-handoff", "open-story-outline", "create-visual-brief", "edit-visual-brief", "confirm-visual-brief", "copy-visual-brief", "download-visual-brief", "preview-visual-map", "preview-external-packet", "clear-external-packet", "explore", "select-exploration", "dismiss-exploration", "open-source-revision"])
const selectedTemplateId = defineModel("selectedTemplateId", { type: String, required: true })
const messages = defineModel("messages", { type: Array, required: true })
const composer = defineModel("composer", { type: String, required: true })
const externalPacketDraft = defineModel("externalPacketDraft", { type: String, required: true })
const qualityMode = defineModel("qualityMode", { type: String, required: true })
const includeWorldSynopsis = defineModel("includeWorldSynopsis", { type: Boolean, required: true })
const activationProfileId = defineModel("activationProfileId", { default: null })
const selectedChapters = defineModel("selectedChapters", { type: Array, required: true })
const selectedSceneId = defineModel("selectedSceneId", { type: String, required: true })
const selectedThreadIds = defineModel("selectedThreadIds", { type: Array, required: true })
const selectedCharacterIds = defineModel("selectedCharacterIds", { type: Array, required: true })
const selectedEntityIds = defineModel("selectedEntityIds", { type: Array, required: true })
const selectedWorldPageIds = defineModel("selectedWorldPageIds", { type: Array, required: true })
const newPageType = defineModel("newPageType", { type: String, required: true })
const newPageTemplateKey = defineModel("newPageTemplateKey", { type: String, required: true })
const qualityPro = computed({ get: () => qualityMode.value === "pro", set: (value) => { qualityMode.value = value ? "pro" : "fast" } })
const sourceLabel = computed(() => {
  const source = props.sourceDraft || props.sourcePage
  return source ? `${source.title || "未命名页面"}${props.sourceDraft ? " · 工作稿" : " · 已发布"}` : "整个项目"
})
const chapterSummary = computed(() => selectedChapters.value.length ? `已附带 ${selectedChapters.value.length} 章：${selectedChapters.value.map((item) => `第${item.chapter_index}章`).join("、")}` : "未附带正文")
const relatedWorldPages = computed(() => (props.pages || []).filter((item) => item.id !== props.sourcePageId))
const selectedRelatedWorldPageIds = computed(() => selectedWorldPageIds.value.filter((id) => relatedWorldPages.value.some((item) => item.id === id)))
const generateLabel = computed(() => props.explorationSelection ? "生成所选探索建议" : ({ core_entity: "生成世界对象建议", world_bible_page: "生成整页提案", world_bible_new_page: "生成新页提案" })[props.targetKind] || "生成建议")
const hasAuthorInput = computed(() => composer.value.trim() || messages.value.some((item) => item.role === "user" && !item.pending && !item.error))
const nearMessageLimit = computed(() => messages.value.filter((item) => !item.pending && !item.error).length >= 36)
const convergenceUsable = computed(() => Boolean(props.convergenceDraft?.coverage?.complete && !props.convergenceDraft?.stale))
const visualPurposeOptions = VISUAL_BRIEF_PURPOSE_OPTIONS
const visualBriefCurrent = computed(() => Boolean(props.visualBrief && convergenceUsable.value && !props.visualBrief.stale && props.visualBrief.manifestHash === props.convergenceDraft?.manifestHash))
const visualBriefConfirmed = computed(() => Boolean(visualBriefCurrent.value && props.visualBrief?.confirmedAt))
const visualBriefStatus = computed(() => !props.visualBrief ? "尚未生成图片" : !visualBriefCurrent.value ? "来源已变化，需复核" : props.visualBrief.confirmedAt ? "简报已确认；尚未生成图片" : "简报草稿；尚未生成图片")
const externalPacketCount = computed(() => externalPacketCharacterCount(externalPacketDraft.value))
const externalPacketOverLimit = computed(() => externalPacketCount.value > EXTERNAL_HANDOFF_PACKET_CHAR_LIMIT)
const externalPacketSummary = computed(() => externalPacketBatchSummary(props.externalPackets))
const TARGET_LABELS = { current_world_target: "当前世界目标", world_bible_page: "世界笔记", outline: "故事结构", map: "地图", writing: "正文", other: "其他入口" }
function targetLabels(targets = []) { return [...new Set(targets.map((item) => TARGET_LABELS[item] || TARGET_LABELS.other))].join("、") || TARGET_LABELS.current_world_target }
function packetLabel(item) { return item.packetTotal ? `第 ${item.packetIndex}/${item.packetTotal} 包` : `第 ${item.packetIndex} 份` }
function packetStatus(status) { return ({ previewed: "已形成预览", incomplete: "需要重新准备", decision_ready: "已形成作者消息", exact_duplicate: "完全重复，未重复处理" })[status] || "已记录" }
const railKey = computed(() => `workspace-rail:${props.projectId || "global"}:generate:assistant`)
const railOpen = ref(readRail())
const composing = ref(false)
function readRail() { try { return sessionStorage.getItem(`workspace-rail:${props.projectId || "global"}:generate:assistant`) !== "closed" } catch { return true } }
function onRailToggle(event) { railOpen.value = event.target.open; try { sessionStorage.setItem(railKey.value, railOpen.value ? "open" : "closed") } catch {} }
async function focusComposer() { await nextTick(); document.getElementById("generate-chat-input")?.focus() }
function onComposerKeydown(event) {
  if (composing.value || event.isComposing) return
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault()
    if (!props.busy && composer.value.trim()) emit("send-chat")
  }
}
defineExpose({ focusComposer })
</script>
