<template>
  <section ref="panelRoot" class="scene-director" :class="{ 'is-fullscreen': fullscreen }" aria-label="场景导演工作台" :data-director-scene="scene?.id || ''" tabindex="-1" @keydown.esc.stop.prevent="closeFullscreen">
    <header class="scene-director__header">
      <div>
        <p class="scene-director__eyebrow">作者可控的候选排演</p>
        <h2>{{ scene?.title || "请先选择场景" }}</h2>
        <p>每个人物只依据自己的当前资料与观察提出意图；新剧情和表演卡不会写入正史或正文。</p>
      </div>
      <div class="scene-director__header-actions">
        <button type="button" class="btn btn-sm" :aria-pressed="fullscreen" @click="toggleFullscreen">{{ fullscreen ? "收起全屏" : "全屏导演台" }}</button>
        <button type="button" class="btn btn-sm" :disabled="historyLoading || !scene?.id" @click="loadHistory()">{{ historyLoading ? "正在更新…" : "刷新历史" }}</button>
      </div>
    </header>

    <div v-if="!scene?.id" class="scene-director__empty">
      <strong>先从场景工作台选择一个 Scene</strong>
      <p>导演只围绕当前明确选择的场景运行。</p>
    </div>

    <template v-else>
      <section class="scene-director__setup" aria-labelledby="director-start-title">
        <div class="scene-director__section-heading">
          <div><span class="scene-director__step">01</span><h3 id="director-start-title">准备本次排演</h3></div>
          <span class="scene-director__tag">默认一轮</span>
        </div>

        <div v-if="charactersLoading" class="scene-director__notice" role="status">正在读取本场可选人物…</div>
        <div v-else-if="charactersError" class="scene-director__notice scene-director__notice--error" role="alert">
          <span>{{ charactersError }}</span><button type="button" class="btn btn-sm" @click="loadCharacters()">重试</button>
        </div>
        <div v-else-if="!characters.length" class="scene-director__notice">
          <span>本作品还没有可用人物。请先建立或采用人物身份，再回到导演。</span>
        </div>
        <fieldset v-else class="scene-director__participants" :disabled="busy || readOnly">
          <legend>本场参与人物</legend>
          <p class="scene-director__help">主要人物逐个详写；背景人物仍各自隔离提出意图，素材层按群像归纳。</p>
          <div class="scene-director__people">
            <div v-for="actor in characters" :key="actor.id" class="scene-director__person">
              <label class="scene-director__person-select">
                <input v-model="draft.characterIds" type="checkbox" :value="actor.id" @change="onInputsChanged">
                <span>{{ actor.name }}</span>
              </label>
              <label v-if="draft.characterIds.includes(actor.id)" class="scene-director__primary">
                <input v-model="draft.primaryCharacterIds" type="checkbox" :value="actor.id" @change="onInputsChanged">
                <span>主要人物</span>
              </label>
            </div>
          </div>
        </fieldset>

        <div class="scene-director__form-grid">
          <label><span>连续轮数</span><input v-model.number="draft.rounds" type="number" min="1" step="1" required :disabled="busy || readOnly" @input="onInputsChanged"></label>
          <label><span>发散度</span><select v-model="draft.divergence" :disabled="busy || readOnly" @change="onInputsChanged"><option value="conservative">保守</option><option value="balanced">平衡（默认）</option><option value="bold">大胆</option></select></label>
        </div>
        <label class="scene-director__field"><span>角色可共同感知的本轮刺激 <small>可留空</small></span><textarea v-model="draft.publicStimulus" rows="2" maxlength="3000" :disabled="busy || readOnly" placeholder="例如：门外忽然响起三下敲门声" @input="onInputsChanged"></textarea></label>
        <label class="scene-director__field"><span>仅导演可见的作者指示 <small>不会发送给角色意图步骤</small></span><textarea v-model="draft.instructions" rows="3" maxlength="6000" :disabled="busy || readOnly" placeholder="想观察什么、保持哪些作者保留项，或希望导演留意的节奏" @input="onInputsChanged"></textarea></label>

        <div class="scene-director__budget-choice">
          <h4>本次累计预算上限</h4>
          <p>额度由你明确选择。系统到 80%、可能计费结果未知或接近时限时暂停；金额不作估算。</p>
          <div class="scene-director__form-grid scene-director__form-grid--three">
            <label><span>最多请求</span><input v-model.number="draft.requestLimit" type="number" min="1" step="1" required :disabled="busy || readOnly" @input="onInputsChanged"></label>
            <label><span>Token 上限</span><input v-model.number="draft.tokenLimit" type="number" min="1" step="1" required :disabled="busy || readOnly" @input="onInputsChanged"></label>
            <label><span>时限（分钟）</span><input v-model.number="draft.timeBudgetMinutes" type="number" min="1" step="1" required :disabled="busy || readOnly" @input="onInputsChanged"></label>
          </div>
        </div>

        <div class="scene-director__actions">
          <button type="button" class="btn" :disabled="readOnly || busy || !canPreview" @click="previewStart">{{ startPreviewLoading ? "正在预览…" : "预览请求与用量" }}</button>
          <button type="button" class="btn btn-primary" :disabled="readOnly || busy || !startPreview || !canSubmitStart" @click="submitStart">{{ submitting ? "正在提交…" : "确认资料并开始" }}</button>
        </div>
        <div v-if="startPreview" class="scene-director__budget" aria-live="polite">
          <div><strong>{{ startPreview.rounds }} 轮</strong><span>{{ startPreview.participants }} 名人物</span></div>
          <dl>
            <div><dt>模型请求</dt><dd>{{ startPreview.request_count.minimum }}–{{ startPreview.request_count.maximum }}</dd></div>
            <div><dt>Token 区间</dt><dd>{{ number(startPreview.token_count.minimum) }}–{{ number(startPreview.token_count.maximum) }}</dd></div>
            <div><dt>预计耗时</dt><dd>{{ duration(startPreview.time_seconds.minimum) }}–{{ duration(startPreview.time_seconds.maximum) }}</dd></div>
          </dl>
          <p>{{ startPreview.possible_charge }}</p>
          <p v-if="startPreview.omitted?.length" class="scene-director__warning">有 {{ startPreview.omitted.length }} 项来源范围省略；不会写入角色知识范围回执。</p>
          <p v-for="warning in startPreview.warnings || []" :key="warning" class="scene-director__help">{{ warning }}</p>
        </div>
      </section>

      <section v-if="taskProgress" class="scene-director__progress" :aria-busy="!taskProgress.terminal" aria-live="polite">
        <div><strong>{{ taskProgress.message || "正在逐人物推演…" }}</strong><span v-if="taskProgress.percent != null">{{ taskProgress.percent }}%</span></div>
        <progress v-if="!taskProgress.terminal && taskProgress.percent != null" :value="taskProgress.percent" max="100"></progress>
        <p v-if="taskProgress.terminal && taskProgress.status === 'failed'" role="alert">{{ taskProgress.errorMessage || "排演未完成；已保存输入与已完成轮次。请先查看历史再决定是否继续。" }}</p>
        <p v-else-if="taskProgress.terminal && taskProgress.result?.needs_author_resume" class="scene-director__warning">运行已在预算或未知用量边界暂停。请查看累计账本，再明确追加额度后继续。</p>
      </section>

      <section class="scene-director__history" aria-labelledby="director-history-title">
        <div class="scene-director__section-heading">
          <div><span class="scene-director__step">02</span><h3 id="director-history-title">导演历史</h3></div>
          <span v-if="history?.rounds?.length" class="scene-director__tag">{{ history.rounds.length }} 个已保存回合</span>
        </div>
        <div v-if="historyError" class="scene-director__notice scene-director__notice--error" role="alert"><span>{{ historyError }}</span><button type="button" class="btn btn-sm" @click="loadHistory()">重试</button></div>
        <div v-else-if="historyLoading && !history" class="scene-director__empty" role="status">正在读取本场导演历史…</div>
        <div v-else-if="!history?.rounds?.length && !history?.references?.length && !history?.recoverable_references?.length" class="scene-director__empty">
          <strong>这里还没有导演回合</strong><p>预算预览不会发起模型请求；开始后，每轮都会保留输入、来源、结果和累计用量。</p>
        </div>
        <template v-else>
          <div class="scene-director__history-toolbar">
            <label><span>对比第一轮</span><select v-model="compareLeft"><option value="">选择回合</option><option v-for="item in history.rounds" :key="item.id" :value="item.id">{{ roundLabel(item) }}</option></select></label>
            <label><span>对比第二轮</span><select v-model="compareRight"><option value="">选择回合</option><option v-for="item in history.rounds" :key="item.id" :value="item.id">{{ roundLabel(item) }}</option></select></label>
            <button type="button" class="btn btn-sm" :disabled="!comparison" @click="compareOpen = !compareOpen">{{ compareOpen ? "收起对比" : "对比差异" }}</button>
            <button type="button" class="btn btn-sm btn-text" :disabled="readOnly || !unstarredBranchCount" @click="deleteUnstarred">删除未星标分支</button>
          </div>
          <section class="scene-director__branch-list" aria-label="分支管理">
            <h4>排演分支</h4>
            <article v-for="branch in history.branches || []" :key="branch.id">
              <div><strong>{{ branch.name || (branch.branch_kind === "start" ? "初始分支" : "未命名分支") }}</strong><span>{{ branch.round_ids?.length || 0 }} 个回合 · {{ branchStatus(branch.status) }}</span></div>
              <p v-if="branch.note">{{ branch.note }}</p>
              <div class="scene-director__actions">
                <button type="button" class="btn btn-sm" :aria-pressed="branch.starred" :disabled="readOnly || busy" @click="saveBranchMeta(branch, { starred: !branch.starred })">{{ branch.starred ? "★ 已星标" : "☆ 星标" }}</button>
                <button type="button" class="btn btn-sm" :disabled="readOnly || busy" @click="editBranchMeta(branch)">命名 / 备注</button>
                <button type="button" class="btn btn-sm btn-text" :disabled="readOnly || busy || branch.status === 'running' || branch.status === 'queued'" @click="deleteBranch(branch)">删除分支</button>
              </div>
              <div v-if="editingBranchId === branch.id" class="scene-director__metadata-editor">
                <label><span>分支名称</span><input v-model="branchMetadata.name" maxlength="180"></label>
                <label><span>作者备注</span><textarea v-model="branchMetadata.note" rows="2" maxlength="2000"></textarea></label>
                <button type="button" class="btn btn-sm btn-primary" :disabled="busy" @click="saveBranchMeta(branch, branchMetadata)">保存</button>
              </div>
            </article>
          </section>
          <div v-if="compareOpen && comparison" class="scene-director__comparison" aria-label="回合对比">
            <section v-for="item in comparison" :key="item.id"><h4>{{ roundLabel(item) }}</h4><p>{{ item.input?.instructions || "没有导演侧指示" }}</p><ul><li v-for="card in item.performances || []" :key="card.character_id"><strong>{{ actorName(card.character_id) }}：</strong>{{ card.change_from_previous }}</li></ul><p v-for="warning in item.warnings || []" :key="warning">{{ warning }}</p></section>
          </div>

          <div class="scene-director__tree" aria-label="场景导演轮次与分支">
            <article v-for="round in orderedRounds" :key="round.id" class="scene-director__round" :class="{ 'is-selected': continuation.parentRoundId === round.id }" :style="{ '--branch-depth': roundDepth(round) }">
              <header class="scene-director__round-header">
                <div><span class="scene-director__round-marker">{{ round.round_number }}</span><div><h4>{{ roundLabel(round) }}</h4><p>{{ branchLabel(round.branch_id) }} · {{ dateLabel(round.created_at) }}</p></div></div>
                <div class="scene-director__round-actions">
                  <button type="button" class="btn btn-sm" :aria-pressed="round.starred" :disabled="readOnly || busy" @click="saveRoundMeta(round, { starred: !round.starred })">{{ round.starred ? "★ 已星标" : "☆ 星标" }}</button>
                  <button type="button" class="btn btn-sm" :disabled="readOnly || busy" @click="editRoundMeta(round)">命名 / 备注</button>
                </div>
              </header>
              <div v-if="editingRoundId === round.id" class="scene-director__metadata-editor">
                <label><span>回合名称</span><input v-model="roundMetadata.name" maxlength="180"></label>
                <label><span>作者备注</span><textarea v-model="roundMetadata.note" rows="2" maxlength="2000"></textarea></label>
                <button type="button" class="btn btn-sm btn-primary" :disabled="busy" @click="saveRoundMeta(round, roundMetadata)">保存</button>
              </div>
              <div class="scene-director__round-summary">
                <span>依据 {{ round.input?.source_changed || round.basis_status === "changed" ? "已变化" : round.basis_status === "unknown" ? "暂不可核实" : "与当前资料一致" }}</span>
                <span>累计请求 {{ round.usage?.requests_started ?? 0 }} / {{ round.usage?.request_limit ?? "—" }}</span>
                <span>累计 Token {{ number(round.usage?.tokens_used) }} / {{ round.usage?.token_limit ?? "—" }}</span>
              </div>
              <p v-if="round.input?.instructions" class="scene-director__author-note"><b>导演侧指示：</b>{{ round.input.instructions }}</p>
              <p v-if="round.input?.omitted?.length" class="scene-director__warning">本轮披露了 {{ round.input.omitted.length }} 项参考省略。</p>

              <section class="scene-director__cards" aria-label="人物表演卡">
                <article v-for="card in round.performances || []" :key="card.character_id" class="scene-director__performance">
                  <h5>{{ actorName(card.character_id) }}</h5>
                  <dl>
                    <div><dt>动作</dt><dd>{{ card.action }}</dd></div><div><dt>神态</dt><dd>{{ card.expression }}</dd></div>
                    <div><dt>肢体</dt><dd>{{ card.body_language }}</dd></div><div><dt>声音与台词</dt><dd>{{ card.voice_and_dialogue }}</dd></div>
                    <div><dt>潜台词</dt><dd>{{ card.subtext }}</dd></div><div><dt>动机与情绪</dt><dd>{{ card.motive_and_emotion }}</dd></div>
                    <div><dt>触发与防御</dt><dd>{{ card.trigger_and_defense }}</dd></div><div><dt>注意 / 忽略</dt><dd>{{ card.attention }} / {{ card.ignored }}</dd></div>
                    <div><dt>相较上一轮</dt><dd>{{ card.change_from_previous }}</dd></div>
                  </dl>
                  <p class="scene-director__basis"><b>依据：</b>{{ basisLabel(card.basis) }}</p>
                  <button type="button" class="btn btn-sm" :disabled="readOnly || busy" @click="prepareRewrite(round, card)">只重写此人物</button>
                </article>
              </section>

              <section v-if="round.candidate_events?.length" class="scene-director__candidate-events" aria-label="导演新增候选事件">
                <h5>候选事件 <span>未写入模拟状态</span></h5>
                <article v-for="event in round.candidate_events" :key="event.candidate_id"><strong>{{ event.label }}</strong><p>{{ event.description }}</p><small>{{ event.timepoint === "later" ? "后续可能" : "本场候选" }} · 作者确认前不作为事实</small></article>
              </section>

              <section class="scene-director__materials" :aria-label="`第 ${round.round_number} 回合场景素材`">
                <div class="scene-director__subheading"><h5>可选素材与角度</h5><span v-if="round.consistency?.coverage !== 'complete'">一致性覆盖 {{ coverageLabel(round.consistency?.coverage) }}</span></div>
                <div class="scene-director__material-list">
                  <label v-for="material in round.materials || []" :key="material.material_id" class="scene-director__material" :class="{ 'is-disabled': disabledForSelectedAngle(round, material) }">
                    <input v-model="selectedMaterials[round.id]" type="checkbox" :value="material.material_id" :disabled="busy || readOnly || disabledForSelectedAngle(round, material)">
                    <span><strong>{{ categoryLabel(material.category) }}</strong>{{ material.content }}<small>{{ perceiverLabel(material) }} · {{ sourceLabel(material.source_kind) }} · {{ conflictLabel(material.conflict_status) }}</small></span>
                  </label>
                  <p v-if="!round.materials?.length" class="scene-director__empty scene-director__empty--compact">本轮没有可选素材卡。</p>
                </div>
                <div class="scene-director__angle-choice">
                  <label><span>导演推荐角度</span><select v-model="selectedAngles[round.id]" :disabled="busy || readOnly"><option v-for="angle in round.recommended_angles || []" :key="angle.angle_id" :value="angle.angle_id">{{ angle.label }} · {{ angleLabel(angle) }}</option></select></label>
                  <p v-if="selectedAngle(round)?.disabled_material_ids?.length" class="scene-director__warning">该视角无法感知 {{ selectedAngle(round).disabled_material_ids.length }} 张已灰显素材卡；内心只供本人视角或全知角度使用。</p>
                  <details class="scene-director__custom-angle"><summary>自己组合叙述角度</summary>
                    <div class="scene-director__form-grid">
                      <label><span>视角</span><select v-model="customAngles[round.id].viewpoint" :disabled="busy || readOnly" @change="customAngles[round.id].distance = customAngles[round.id].viewpoint === 'omniscient' ? 'omniscient' : 'close'"><option value="omniscient">全知</option><option v-for="actor in selectedCharacters" :key="actor.id" :value="actor.id">{{ actor.name }}</option></select></label>
                      <label><span>叙述距离</span><select v-model="customAngles[round.id].distance" :disabled="busy || readOnly"><option value="interior">贴近内心</option><option value="close">贴近观察</option><option value="external">外部旁观</option><option v-if="customAngles[round.id].viewpoint === 'omniscient'" value="omniscient">全知</option></select></label>
                    </div>
                    <label><span>焦点</span><input v-model="customAngles[round.id].focus" maxlength="600" placeholder="主写人物、冲突或物件" :disabled="busy || readOnly"></label>
                    <label><span>详略与节奏</span><input v-model="customAngles[round.id].detail" maxlength="600" placeholder="哪些详写、哪些带过" :disabled="busy || readOnly"></label>
                  </details>
                  <label class="scene-director__reference-name"><span>参考剧本名称</span><input v-model="referenceNames[round.id]" maxlength="180" :disabled="busy || readOnly"></label>
                  <button type="button" class="btn btn-sm" :disabled="readOnly || busy || !selectedMaterialIds(round).length" @click="saveReference(round)">保存为参考剧本</button>
                </div>
              </section>

              <details class="scene-director__more">
                <summary>其他可能、状态差量与一致性</summary>
                <div class="scene-director__alternatives"><article v-for="alternative in round.alternatives || []" :key="alternative.alternative_id"><strong>{{ alternative.label }}</strong><p>{{ alternative.branch_instruction }}</p><button type="button" class="btn btn-sm" :disabled="readOnly || busy" @click="prepareIntervention(round, alternative)">从此可能继续</button></article></div>
                <ul class="scene-director__findings"><li v-for="(finding, index) in round.consistency?.findings || []" :key="index" :class="`is-${finding.severity}`">{{ finding.statement }}</li></ul>
                <ul class="scene-director__warnings"><li v-for="warning in round.warnings || []" :key="warning">{{ warning }}</li><li v-for="warning in round.consistency?.unavailable_checks || []" :key="warning">未覆盖：{{ warning }}</li></ul>
                <pre v-if="round.state_delta?.length" class="scene-director__delta">{{ round.state_delta.map(item => `${item.kind}：${item.before ?? "—"} → ${item.after}`).join("\n") }}</pre>
              </details>

              <footer class="scene-director__branch-actions">
                <button type="button" class="btn btn-sm" :disabled="readOnly || busy" @click="prepareContinuation(round, 'continue')">从此回合继续</button>
                <button type="button" class="btn btn-sm" :disabled="readOnly || busy" @click="prepareContinuation(round, 'reroll')">重来同级分支</button>
              </footer>
            </article>
          </div>

          <section v-if="continuation.parentRoundId" class="scene-director__continue" aria-labelledby="director-continue-title">
            <div class="scene-director__section-heading"><div><span class="scene-director__step">03</span><h3 id="director-continue-title">从 {{ roundLabel(roundById(continuation.parentRoundId)) }} 继续</h3></div><button type="button" class="btn btn-sm btn-text" @click="clearContinuation">收起</button></div>
            <div class="scene-director__form-grid">
              <label><span>分支方式</span><select v-model="continuation.branchKind" :disabled="busy" @change="onContinuationChanged"><option value="continue">沿此方向推进</option><option value="reroll">重来同级</option><option value="intervene">作者介入后推进</option><option value="rewrite_character">只重写一名人物</option></select></label>
              <label><span>依据选择</span><select v-model="continuation.basisChoice" :disabled="busy" @change="onContinuationChanged"><option value="current">使用当前资料</option><option value="frozen">沿用原回合冻结资料</option></select></label>
              <label><span>连续轮数</span><input v-model.number="continuation.rounds" type="number" min="1" required :disabled="busy" @input="onContinuationChanged"></label>
              <label v-if="continuation.branchKind === 'rewrite_character'"><span>重写人物</span><select v-model="continuation.rewriteCharacterId" :disabled="busy" @change="onContinuationChanged"><option value="">选择人物</option><option v-for="card in roundById(continuation.parentRoundId)?.performances || []" :key="card.character_id" :value="card.character_id">{{ actorName(card.character_id) }}</option></select></label>
              <label v-if="parentAlternatives.length"><span>采用其他可能</span><select v-model="continuation.selectedAlternative" :disabled="busy" @change="onContinuationChanged"><option value="">不选</option><option v-for="item in parentAlternatives" :key="item.alternative_id" :value="item.alternative_id">{{ item.label }}</option></select></label>
            </div>
            <label v-if="continuation.branchKind === 'intervene'" class="scene-director__field"><span>本次介入 <small>只给导演层，不会让角色提前知道</small></span><textarea v-model="continuation.intervention" rows="3" maxlength="3000" :disabled="busy" @input="onContinuationChanged"></textarea></label>
            <label class="scene-director__field"><span>导演侧指示</span><textarea v-model="continuation.instructions" rows="2" maxlength="6000" :disabled="busy" @input="onContinuationChanged"></textarea></label>
            <label class="scene-director__field"><span>共同可感知刺激</span><textarea v-model="continuation.publicStimulus" rows="2" maxlength="3000" :disabled="busy" @input="onContinuationChanged"></textarea></label>
            <div class="scene-director__form-grid scene-director__form-grid--two">
              <label><span>新增请求额度 <small>原预算足够可填 0</small></span><input v-model.number="continuation.additionalRequests" type="number" min="0" :disabled="busy" @input="onContinuationChanged"></label>
              <label><span>新增 Token 额度</span><input v-model.number="continuation.additionalTokens" type="number" min="0" :disabled="busy" @input="onContinuationChanged"></label>
            </div>
            <label v-if="continuationPreview?.current_budget?.unknown_requests" class="scene-director__duplicate-confirm"><input v-model="continuation.allowPossibleDuplicateCharge" type="checkbox" @change="onContinuationChanged"><span>我已核对累计账本，明确确认旧请求可能重复计费后再续算。</span></label>
            <div class="scene-director__actions">
              <button type="button" class="btn" :disabled="busy || !canPreviewContinuation" @click="previewContinue">{{ continuationPreviewLoading ? "正在预览…" : "预览同一累计根预算" }}</button>
              <button type="button" class="btn btn-primary" :disabled="readOnly || busy || !continuationPreview || !canSubmitContinuation" @click="submitContinuation">{{ submitting ? "正在提交…" : Number(continuation.additionalRequests || 0) === 0 && Number(continuation.rounds) === 1 ? "用原预算推进一轮" : "确认续算并创建分支" }}</button>
            </div>
            <div v-if="continuationPreview" class="scene-director__budget" aria-live="polite">
              <div><strong>同一累计根账本</strong><span>已用 {{ continuationPreview.current_budget?.requests_used ?? 0 }} / {{ continuationPreview.current_budget?.requests_authorized ?? "—" }} 请求</span><span>已用 {{ number(continuationPreview.current_budget?.tokens_used) }} / {{ continuationPreview.current_budget?.tokens_authorized ?? "—" }} Token</span></div>
              <dl><div><dt>本分支请求</dt><dd>{{ continuationPreview.request_count.minimum }}–{{ continuationPreview.request_count.maximum }}</dd></div><div><dt>Token 区间</dt><dd>{{ number(continuationPreview.token_count.minimum) }}–{{ number(continuationPreview.token_count.maximum) }}</dd></div><div><dt>预计耗时</dt><dd>{{ duration(continuationPreview.time_seconds.minimum) }}–{{ duration(continuationPreview.time_seconds.maximum) }}</dd></div></dl>
              <p>{{ continuationPreview.possible_charge }}</p>
              <p v-if="continuationPreview.current_budget?.deadline_at" class="scene-director__help">原运行时限：{{ dateLabel(continuationPreview.current_budget.deadline_at) }}；续算不会重置起始时间或时限。</p>
            </div>
          </section>

          <section v-if="history.references?.length || history.recoverable_references?.length" class="scene-director__references" aria-labelledby="director-reference-title">
            <h4 id="director-reference-title">保存的参考剧本 <small>可供作者查看，不是采用剧本</small></h4>
            <article v-for="reference in history.references || []" :key="reference.id" class="scene-director__reference">
              <div><strong>{{ reference.name }}</strong><span v-if="reference.source_deleted">来源回合已删除</span><span v-if="reference.source_changed">依据已变化</span></div>
              <label class="scene-director__reference-use">
                <input
                  type="checkbox"
                  :checked="selectedWritingReferenceIds.includes(reference.id)"
                  :disabled="readOnly || busy"
                  @change="toggleWritingReference(reference.id, $event.target.checked)"
                >
                <span>作为本场 AI 正文建议的可选参考</span>
              </label>
              <label><span>作者批注</span><textarea v-model="referenceAnnotations[reference.id]" rows="2" maxlength="3000"></textarea></label>
              <div class="scene-director__actions"><button type="button" class="btn btn-sm" :disabled="readOnly || busy" @click="saveReferenceNote(reference)">保存批注</button><button type="button" class="btn btn-sm" :disabled="readOnly || busy" @click="deleteReference(reference)">删除参考</button></div>
              <details><summary>查看保存的素材副本</summary><p v-for="(item, index) in reference.content_copy?.materials || []" :key="index">{{ categoryLabel(item.category) }}：{{ item.content }}</p><p>{{ reference.annotation || "尚无作者批注" }}</p></details>
            </article>
            <p v-for="reference in history.recoverable_references || []" :key="reference.id" class="scene-director__recovery">已删除的参考可在 {{ dateLabel(reference.restore_until) }} 前恢复。<button type="button" class="btn btn-sm" :disabled="busy" @click="restoreReference(reference)">恢复</button></p>
          </section>

          <section v-if="history.recoverable_branches?.length" class="scene-director__recoveries" aria-label="可恢复的分支">
            <h4>30 天内可恢复的分支</h4><p v-for="branch in history.recoverable_branches" :key="branch.id">{{ branch.name || "未命名分支" }} · {{ dateLabel(branch.restore_until) }} <button type="button" class="btn btn-sm" :disabled="busy" @click="restoreBranch(branch)">恢复</button></p>
          </section>
        </template>
      </section>
      <p v-if="error" class="scene-director__error" role="alert">{{ error }}</p>
      <p v-if="message" class="scene-director__message" role="status" aria-live="polite">{{ message }}</p>
      <p v-if="readOnly" class="scene-director__notice">当前项目只读；可以查看导演历史。</p>
    </template>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue"
import { getApi } from "../../bridge/index.js"
import { confirmAiReference } from "../../../shared/aiReferenceModal.js"
import { createOperationId, pollTaskProgress } from "../../../shared/workflowProgress.js"

const props = defineProps({
  projectId: { type: String, default: null },
  scene: { type: Object, default: null },
  characters: { type: Array, default: () => [] },
  readOnly: Boolean,
  visible: { type: Boolean, default: true },
  selectedWritingReferenceIds: { type: Array, default: () => [] },
})
const emit = defineEmits(["update:writing-reference-ids"])

const STORAGE_ACTION = "story.one_click.simulate"
const DRAFT_STORAGE_PREFIX = "novelcraft_scene_director_draft_v1"
const worldCharacters = ref([])
const charactersLoading = ref(false)
const charactersError = ref("")
const history = ref(null)
const historyLoading = ref(false)
const historyError = ref("")
const startPreview = ref(null)
const continuationPreview = ref(null)
const startPreviewLoading = ref(false)
const continuationPreviewLoading = ref(false)
const submitting = ref(false)
const taskProgress = ref(null)
const activeTaskId = ref(null)
const error = ref("")
const message = ref("")
const compareLeft = ref("")
const compareRight = ref("")
const compareOpen = ref(false)
const selectedMaterials = reactive({})
const selectedAngles = reactive({})
const customAngles = reactive({})
const referenceAnnotations = reactive({})
const referenceNames = reactive({})
const fullscreen = ref(false)
const panelRoot = ref(null)
const editingRoundId = ref("")
const editingBranchId = ref("")
const roundMetadata = reactive({ name: "", note: "" })
const branchMetadata = reactive({ name: "", note: "" })
const localDrafts = new Map()
const contextTasks = new Map()
const contextProgress = new Map()
let requestGeneration = 0
let currentContextKey = ""
let loadedContextKey = ""
let poller = null

const draft = reactive({
  characterIds: [],
  primaryCharacterIds: [],
  rounds: 1,
  divergence: "balanced",
  instructions: "",
  publicStimulus: "",
  requestLimit: "",
  tokenLimit: "",
  timeBudgetMinutes: "",
})
const continuation = reactive({
  parentRoundId: "",
  branchKind: "continue",
  basisChoice: "current",
  rounds: 1,
  additionalRequests: 0,
  additionalTokens: 0,
  allowPossibleDuplicateCharge: false,
  instructions: "",
  intervention: "",
  publicStimulus: "",
  selectedAlternative: "",
  rewriteCharacterId: "",
})

const characters = computed(() => {
  const source = props.characters?.length ? props.characters : worldCharacters.value
  const seen = new Set()
  return source.map((item) => {
    const id = String(item?.character_id || item?.entity_id || item?.id || "")
    if (!id || id.startsWith("character-") || seen.has(id)) return null
    seen.add(id)
    return { id, name: String(item?.name || item?.display_name || item?.title || "未命名人物") }
  }).filter(Boolean)
})
const selectedCharacters = computed(() => characters.value.filter((item) => draft.characterIds.includes(item.id)))
const canPreview = computed(() => Boolean(
  props.projectId && props.scene?.id && draft.characterIds.length && Number.isInteger(Number(draft.rounds)) && Number(draft.rounds) >= 1,
))
const canSubmitStart = computed(() => Number(draft.requestLimit) >= 1 && Number(draft.tokenLimit) >= 1 && Number(draft.timeBudgetMinutes) >= 1)
const busy = computed(() => submitting.value || startPreviewLoading.value || continuationPreviewLoading.value || Boolean(taskProgress.value && !taskProgress.value.terminal))
const orderedRounds = computed(() => [...(history.value?.rounds || [])].sort((a, b) => String(a.created_at || "").localeCompare(String(b.created_at || "")) || Number(a.round_number) - Number(b.round_number)))
const comparison = computed(() => {
  const left = history.value?.rounds?.find((item) => item.id === compareLeft.value)
  const right = history.value?.rounds?.find((item) => item.id === compareRight.value)
  return left && right && left.id !== right.id ? [left, right] : null
})
const unstarredBranchCount = computed(() => (history.value?.branches || []).filter((item) => !item.starred).length)
const parentAlternatives = computed(() => roundById(continuation.parentRoundId)?.alternatives || [])
const canPreviewContinuation = computed(() => Boolean(
  continuation.parentRoundId && Number.isInteger(Number(continuation.rounds)) && Number(continuation.rounds) >= 1,
))
const canSubmitContinuation = computed(() => Number(continuation.additionalRequests) >= 0
  && Number(continuation.additionalTokens) >= 0
  && (!continuationPreview.value?.current_budget?.unknown_requests || Number(continuation.additionalRequests) > 0)
  && (!continuationPreview.value?.current_budget?.unknown_requests || continuation.allowPossibleDuplicateCharge))

function currentKey() { return `${props.projectId || ""}:${props.scene?.id || ""}` }
function owns(token, key = currentKey()) { return token === requestGeneration && key === currentContextKey }
function jsonClone(value) { return JSON.parse(JSON.stringify(value)) }
function storedDraft(key) {
  try {
    const raw = window.sessionStorage.getItem(`${DRAFT_STORAGE_PREFIX}:${encodeURIComponent(key)}`)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}
function saveCurrentDraft() {
  if (!currentContextKey) return
  const saved = {
    draft: jsonClone(draft),
    continuation: jsonClone(continuation),
  }
  localDrafts.set(currentContextKey, saved)
  try {
    window.sessionStorage.setItem(
      `${DRAFT_STORAGE_PREFIX}:${encodeURIComponent(currentContextKey)}`,
      JSON.stringify(saved),
    )
  } catch {
    // Keep the in-memory draft when session storage is unavailable.
  }
}
function restoreDraft(key) {
  const saved = localDrafts.get(key) || storedDraft(key)
  Object.assign(draft, saved?.draft || {
    characterIds: [], primaryCharacterIds: [], rounds: 1, divergence: "balanced",
    instructions: "", publicStimulus: "", requestLimit: "", tokenLimit: "", timeBudgetMinutes: "",
  })
  Object.assign(continuation, saved?.continuation || {
    parentRoundId: "", branchKind: "continue", basisChoice: "current", rounds: 1,
    additionalRequests: 0, additionalTokens: 0, allowPossibleDuplicateCharge: false,
    instructions: "", intervention: "", publicStimulus: "", selectedAlternative: "", rewriteCharacterId: "",
  })
  startPreview.value = null
  continuationPreview.value = null
  error.value = ""
  message.value = ""
  taskProgress.value = contextProgress.get(key) || null
  activeTaskId.value = contextTasks.get(key) || null
}

async function loadCharacters() {
  if (props.characters?.length || !props.projectId) return
  const token = requestGeneration
  const key = currentContextKey
  charactersLoading.value = true
  charactersError.value = ""
  try {
    const api = getApi()
    const all = []
    let skip = 0
    let total = null
    let hasMore = true
    while (hasMore) {
      const response = await api.world.listEntities({
        novel_id: props.projectId,
        display_state: "active",
        entity_type: "character",
        skip,
        limit: 50,
      })
      if (!owns(token, key)) return
      const items = Array.isArray(response) ? response : response?.items || []
      all.push(...items)
      total = Number(response?.total ?? (items.length < 50 ? all.length : NaN))
      skip += items.length
      hasMore = items.length > 0 && (!Number.isFinite(total) || skip < total)
    }
    if (owns(token, key)) worldCharacters.value = all
  } catch (cause) {
    if (owns(token, key)) charactersError.value = cause?.message || "人物列表暂不可用。"
  } finally {
    if (owns(token, key)) charactersLoading.value = false
  }
}

async function loadHistory() {
  if (!props.projectId || !props.scene?.id) return
  const token = requestGeneration
  const key = currentContextKey
  historyLoading.value = true
  historyError.value = ""
  try {
    const result = await getApi().story.sceneDirectorHistory(props.projectId, props.scene.id)
    if (!owns(token, key)) return
    history.value = result
    for (const round of result.rounds || []) {
      if (!(round.id in selectedMaterials)) selectedMaterials[round.id] = []
      if (!(round.id in selectedAngles)) selectedAngles[round.id] = round.recommended_angles?.[0]?.angle_id || ""
      if (!(round.id in customAngles)) customAngles[round.id] = { viewpoint: "omniscient", distance: "close", focus: "", detail: "" }
      referenceNames[round.id] ??= round.name || `场景参考 · ${round.round_number}`
    }
    for (const reference of result.references || []) referenceAnnotations[reference.id] ??= reference.annotation || ""
  } catch (cause) {
    if (owns(token, key)) historyError.value = cause?.message || "导演历史暂不可用。"
  } finally {
    if (owns(token, key)) historyLoading.value = false
  }
}

function toggleWritingReference(referenceId, checked) {
  const selected = new Set(props.selectedWritingReferenceIds.map(String))
  if (checked && !selected.has(String(referenceId)) && selected.size >= 20) {
    error.value = "一次最多选择 20 份导演参考副本。"
    return
  }
  if (checked) selected.add(String(referenceId))
  else selected.delete(String(referenceId))
  emit("update:writing-reference-ids", [...selected])
}

async function loadVisibleContext() {
  if (!props.projectId || !props.scene?.id || !props.visible || loadedContextKey === currentContextKey) return
  loadedContextKey = currentContextKey
  await Promise.all([loadCharacters(), loadHistory()])
  const token = requestGeneration
  if (owns(token)) {
    const taskId = contextTasks.get(currentContextKey)
    if (taskId && !contextProgress.get(currentContextKey)?.terminal) startPolling(taskId, currentContextKey)
  }
}

function onInputsChanged() {
  draft.primaryCharacterIds = draft.primaryCharacterIds.filter((id) => draft.characterIds.includes(id))
  startPreview.value = null
  message.value = ""
  saveCurrentDraft()
}
function onContinuationChanged() {
  continuationPreview.value = null
  message.value = ""
  saveCurrentDraft()
}

function startPayload(operationId, confirmationId) {
  return {
    operation_id: operationId,
    scene_id: props.scene.id,
    character_ids: [...draft.characterIds],
    primary_character_ids: [...draft.primaryCharacterIds],
    related_object_ids: [],
    rounds: Number(draft.rounds),
    request_limit: Number(draft.requestLimit),
    token_limit: Number(draft.tokenLimit),
    time_budget_seconds: Number(draft.timeBudgetMinutes) * 60,
    instructions: draft.instructions,
    public_stimulus: draft.publicStimulus,
    divergence: draft.divergence,
    context_confirmation_id: confirmationId,
    budget_preview_hash: startPreview.value.preview_hash,
  }
}

async function previewStart() {
  if (!canPreview.value || busy.value) return
  const token = requestGeneration
  const key = currentContextKey
  startPreviewLoading.value = true
  error.value = ""
  try {
    const operationId = createOperationId()
    const result = await getApi().story.previewSceneDirectorBudget(props.projectId, {
      operation_id: operationId,
      scene_id: props.scene.id,
      character_ids: [...draft.characterIds],
      primary_character_ids: [...draft.primaryCharacterIds],
      related_object_ids: [],
      rounds: Number(draft.rounds),
      instructions: draft.instructions,
      public_stimulus: draft.publicStimulus,
    })
    if (!owns(token, key)) return
    startPreview.value = { ...result, operationId }
    message.value = "预算按当前场景与人物资料指纹计算；还没有发起模型请求。"
  } catch (cause) {
    if (owns(token, key)) error.value = cause?.message || "预算预览失败；输入已保留。"
  } finally {
    if (owns(token, key)) startPreviewLoading.value = false
  }
}

async function confirmScope(characterIds) {
  return confirmAiReference({
    novel_id: props.projectId,
    action: STORAGE_ACTION,
    task: "逐人物隔离推演当前场景",
    scope: "scene",
    scene_id: props.scene.id,
    visible_until_scene_id: props.scene.id,
    character_ids: [...characterIds],
    include_pending_objects: false,
    budget_tokens: 0,
  })
}

async function submitStart() {
  if (!startPreview.value || !canSubmitStart.value || busy.value || props.readOnly) return
  const token = requestGeneration
  const key = currentContextKey
  submitting.value = true
  error.value = ""
  message.value = ""
  try {
    const confirmation = await confirmScope(draft.characterIds)
    if (!owns(token, key)) return
    const result = await getApi().story.startSceneDirector(props.projectId, props.scene.id, startPayload(startPreview.value.operationId, confirmation.id))
    if (!owns(token, key)) return
    startPreview.value = null
    message.value = "排演已提交；已保存结果会逐轮出现在本场历史中。"
    startPolling(result.task_id, key)
  } catch (cause) {
    if (owns(token, key)) {
      error.value = Number(cause?.status) === 409
        ? "资料或运行状态已变化。输入仍保留，请重新预览后再提交。"
        : cause?.message || "提交失败；输入已保留。若请求状态不确定，请先刷新历史。"
      if (Number(cause?.status) === 409) startPreview.value = null
    }
  } finally {
    if (owns(token, key)) submitting.value = false
  }
}

function startPolling(taskId, key) {
  poller?.stop?.()
  activeTaskId.value = taskId
  contextTasks.set(key, taskId)
  taskProgress.value = { status: "pending", terminal: false, message: "等待场景导演开始…", percent: null }
  poller = pollTaskProgress({
    taskId,
    workflowType: "story_scene_director",
    novelId: props.projectId,
    apiClient: getApi(),
    receiptStorage: null,
    onUpdate: (progress, task) => {
      if (key !== currentContextKey) { poller?.stop?.(); return }
      taskProgress.value = { ...progress, status: task?.status || progress.status, result: task?.result || null }
      contextProgress.set(key, taskProgress.value)
    },
    onDone: (progress, task) => {
      if (key !== currentContextKey) return
      taskProgress.value = { ...progress, status: "done", terminal: true, result: task?.result || null }
      contextProgress.set(key, taskProgress.value)
      contextTasks.delete(key)
      activeTaskId.value = null
      message.value = "本次排演已结束；查看每轮结果或明确追加预算后继续。"
      void loadHistory()
    },
    onFailed: (progress) => {
      if (key !== currentContextKey) return
      taskProgress.value = { ...progress, status: "failed", terminal: true }
      contextProgress.set(key, taskProgress.value)
      contextTasks.delete(key)
      activeTaskId.value = null
      error.value = progress.errorMessage || "排演失败；已保存的输入和完成回合仍可查看。"
      void loadHistory()
    },
  })
}

function prepareContinuation(round, branchKind = "continue") {
  Object.assign(continuation, {
    parentRoundId: round.id,
    branchKind,
    basisChoice: "current",
    rounds: 1,
    additionalRequests: 0,
    additionalTokens: 0,
    allowPossibleDuplicateCharge: false,
    instructions: "",
    intervention: "",
    publicStimulus: "",
    selectedAlternative: "",
    rewriteCharacterId: "",
  })
  continuationPreview.value = null
  saveCurrentDraft()
}

function prepareIntervention(round, alternative) {
  prepareContinuation(round, "intervene")
  continuation.selectedAlternative = alternative.alternative_id
  continuation.intervention = alternative.branch_instruction
  onContinuationChanged()
}

function prepareRewrite(round, card) {
  prepareContinuation(round, "rewrite_character")
  continuation.rewriteCharacterId = card.character_id
  onContinuationChanged()
}

function clearContinuation() {
  continuation.parentRoundId = ""
  continuationPreview.value = null
  saveCurrentDraft()
}

function continuationPayload(operationId) {
  return {
    operation_id: operationId,
    novel_id: props.projectId,
    parent_round_id: continuation.parentRoundId,
    rounds: Number(continuation.rounds),
    basis_choice: continuation.basisChoice,
    branch_kind: continuation.branchKind,
    rewrite_character_id: continuation.rewriteCharacterId || null,
    selected_alternative: continuation.selectedAlternative || null,
    instructions: continuation.instructions,
    intervention: continuation.intervention,
    public_stimulus: continuation.publicStimulus,
  }
}

async function previewContinue() {
  if (!canPreviewContinuation.value || busy.value) return
  const parent = roundById(continuation.parentRoundId)
  const branch = history.value?.branches?.find((item) => item.id === parent?.branch_id)
  const token = requestGeneration
  const key = currentContextKey
  continuationPreviewLoading.value = true
  error.value = ""
  try {
    const operationId = createOperationId()
    const result = await getApi().story.previewSceneDirectorContinuation(branch.root_id, continuationPayload(operationId))
    if (!owns(token, key)) return
    continuationPreview.value = { ...result, operationId, rootId: branch.root_id }
    if (Number(result.current_budget?.unknown_requests || 0)) message.value = "累计账本存在结果未知的旧请求；确认可能重复计费后才能续算。"
  } catch (cause) {
    if (owns(token, key)) error.value = cause?.message || "续算预算预览失败；分支输入已保留。"
  } finally {
    if (owns(token, key)) continuationPreviewLoading.value = false
  }
}

async function submitContinuation() {
  if (!continuationPreview.value || !canSubmitContinuation.value || busy.value || props.readOnly) return
  const token = requestGeneration
  const key = currentContextKey
  const operationId = continuationPreview.value.operationId
  submitting.value = true
  error.value = ""
  try {
    const rootId = continuationPreview.value.rootId
    const root = history.value.roots?.find((item) => item.id === rootId)
    const confirmation = await confirmScope(root?.character_ids?.length ? root.character_ids : draft.characterIds)
    if (!owns(token, key)) return
    const payload = {
      ...continuationPayload(operationId),
      context_confirmation_id: confirmation.id,
      additional_requests: Number(continuation.additionalRequests),
      additional_tokens: Number(continuation.additionalTokens || 0),
      allow_possible_duplicate_charge: continuation.allowPossibleDuplicateCharge,
      budget_preview_hash: continuationPreview.value.preview_hash,
    }
    const useExistingBudget = Number(continuation.additionalRequests || 0) === 0 && Number(continuation.rounds) === 1
    const result = useExistingBudget
      ? await getApi().story.advanceSceneDirector(rootId, payload)
      : await getApi().story.continueSceneDirector(rootId, payload)
    if (!owns(token, key)) return
    continuationPreview.value = null
    message.value = "分支已提交；它继续使用同一个累计预算根。"
    startPolling(result.task_id, key)
  } catch (cause) {
    if (owns(token, key)) {
      error.value = Number(cause?.status) === 409
        ? "资料或累计账本已变化；额度与输入已保留，请重新预览。"
        : cause?.message || "续算提交失败；请先刷新历史确认任务状态。"
      if (Number(cause?.status) === 409) continuationPreview.value = null
    }
  } finally {
    if (owns(token, key)) submitting.value = false
  }
}

function roundById(id) { return history.value?.rounds?.find((item) => item.id === id) || null }
function branchLabel(id) { const branch = history.value?.branches?.find((item) => item.id === id); return branch?.name || (branch?.branch_kind === "start" ? "初始分支" : "导演分支") }
function roundLabel(round) { return round ? `${round.name || `第 ${round.round_number} 回合`} · ${branchLabel(round.branch_id)}` : "所选回合" }
function actorName(id) { return characters.value.find((item) => item.id === id)?.name || "人物" }
function selectedAngle(round) { return round?.recommended_angles?.find((item) => item.angle_id === selectedAngles[round.id]) || null }
function disabledForSelectedAngle(round, material) {
  if (!material) return true
  const custom = customAngles[round.id]
  if ((custom?.focus || custom?.detail) && custom.viewpoint !== "omniscient") {
    return Boolean(material.disabled_for_character_ids?.includes(custom.viewpoint))
  }
  const angle = selectedAngle(round)
  return Boolean(angle?.disabled_material_ids?.includes(material.material_id))
}
function selectedMaterialIds(round) { return selectedMaterials[round.id] || [] }
function angleForReference(round) {
  const selected = selectedAngle(round)
  const currentSelected = selectedMaterialIds(round)
  if (customAngles[round.id]?.focus || customAngles[round.id]?.detail) {
    const custom = customAngles[round.id]
    const omniscient = custom.viewpoint === "omniscient"
    return {
      angle_id: `author-${round.id.slice(0, 8)}`,
      label: "作者组合角度",
      viewpoint_kind: omniscient ? "omniscient" : "character",
      viewpoint_character_id: omniscient ? null : custom.viewpoint,
      narrative_distance: omniscient ? "omniscient" : custom.distance,
      focus: custom.focus || "作者自定焦点",
      detail_and_pacing: custom.detail || "作者自定详略与节奏",
      material_ids: currentSelected.filter((id) => !disabledForSelectedAngle(round, round.materials.find((item) => item.material_id === id))),
      disabled_material_ids: currentSelected.filter((id) => disabledForSelectedAngle(round, round.materials.find((item) => item.material_id === id))),
    }
  }
  if (!selected) return null
  return {
    ...selected,
      material_ids: currentSelected.filter((id) => !selected.disabled_material_ids.includes(id)),
  }
}

async function saveReference(round) {
  const materialIds = selectedMaterialIds(round).filter((id) => !disabledForSelectedAngle(round, round.materials.find((item) => item.material_id === id)))
  const angle = angleForReference(round)
  if (!materialIds.length || !angle?.material_ids?.length) {
    error.value = "请至少选择一张该角度可感知的素材卡。"
    return
  }
  const name = String(referenceNames[round.id] || "").trim()
  if (!name) { error.value = "请给参考剧本起个名字。"; return }
  try {
    await getApi().story.saveSceneDirectorReference(round.id, {
      novel_id: props.projectId,
      name,
      material_ids: materialIds,
      angle,
      annotation: "",
    })
    message.value = "参考剧本已保存为独立内容副本，不会进入采用剧本或正史。"
    await loadHistory()
  } catch (cause) { error.value = cause?.message || "参考剧本保存失败。" }
}

async function saveReferenceNote(reference) {
  try {
    await getApi().story.updateSceneDirectorReference(reference.id, { novel_id: props.projectId, annotation: referenceAnnotations[reference.id] || "" })
    message.value = "作者批注已保存。"
    await loadHistory()
  } catch (cause) { error.value = cause?.message || "批注保存失败。" }
}

async function deleteReference(reference) {
  if (!window.confirm(`删除“${reference.name}”？30 天内可以恢复。`)) return
  try { await getApi().story.deleteSceneDirectorReference(reference.id, { novel_id: props.projectId }); await loadHistory() }
  catch (cause) { error.value = cause?.message || "参考删除失败。" }
}

async function restoreReference(reference) {
  try { await getApi().story.restoreSceneDirectorReference(reference.id, { novel_id: props.projectId }); await loadHistory() }
  catch (cause) { error.value = cause?.message || "参考恢复失败。" }
}

async function saveRoundMeta(round, changes) {
  try {
    await getApi().story.updateSceneDirectorRound(round.id, { novel_id: props.projectId, ...changes })
    editingRoundId.value = ""
    message.value = "回合标记已保存。"
    await loadHistory()
  } catch (cause) { error.value = cause?.message || "回合标记保存失败。" }
}

function editRoundMeta(round) {
  editingRoundId.value = round.id
  roundMetadata.name = round.name || ""
  roundMetadata.note = round.note || ""
}

async function saveBranchMeta(branch, changes) {
  try { await getApi().story.updateSceneDirectorBranch(branch.id, { novel_id: props.projectId, ...changes }); await loadHistory() }
  catch (cause) { error.value = cause?.message || "分支标记保存失败。" }
}

async function deleteBranch(branch) {
  const affected = (branch.round_ids || []).map((id) => roundById(id)).filter(Boolean)
  const refs = (history.value?.references || []).filter((item) => affected.some((round) => round.id === item.source_round_id))
  if (!window.confirm(`删除“${branch.name || "未命名分支"}”？将影响 ${affected.length} 个回合、${refs.length} 份引用；30 天内可以恢复。`)) return
  try { await getApi().story.deleteSceneDirectorBranch(branch.id, { novel_id: props.projectId, confirm: true }); await loadHistory() }
  catch (cause) { error.value = cause?.message || "分支删除失败。" }
}

async function restoreBranch(branch) {
  try { await getApi().story.restoreSceneDirectorBranch(branch.id, { novel_id: props.projectId }); await loadHistory() }
  catch (cause) { error.value = cause?.message || "分支恢复失败。" }
}

async function deleteUnstarred() {
  const affected = (history.value?.branches || []).filter((item) => !item.starred)
  const rounds = affected.reduce((sum, branch) => sum + (branch.round_ids || []).length, 0)
  const refs = (history.value?.references || []).filter((item) => affected.some((branch) => branch.round_ids?.includes(item.source_round_id)))
  if (!window.confirm(`删除本场 ${affected.length} 个未星标分支、${rounds} 个回合及其 ${refs.length} 份历史引用？30 天内可以恢复；已保存的参考剧本副本仍可用。`)) return
  try { await getApi().story.deleteUnstarredSceneDirectorBranches(props.scene.id, { novel_id: props.projectId, confirm: true }); await loadHistory() }
  catch (cause) { error.value = cause?.message || "批量删除失败。" }
}

function basisLabel(items = []) {
  if (!items.length) return "缺少可核验依据，按导演发挥处理"
  return items.map((item) => `${sourceLabel(item.source_kind)}${item.source_fingerprint ? "（当前来源已校验）" : "（导演发挥）"}`).join("；")
}
function sourceLabel(value) { return ({ world_dossier: "人物 / 世界档案", continuity: "本场时点状态", character_pattern: "表达倾向", story_character_card: "人物卡来源", observed_event: "本轮可观察事件", director_inference: "导演发挥", candidate: "导演候选" })[value] || "来源待核实" }
function categoryLabel(value) { return ({ environment: "环境", object: "物件", crowd: "群像", mood: "氛围", pacing: "节奏", time: "时间" })[value] || "素材" }
function angleLabel(angle) { return `${angle.viewpoint_kind === "omniscient" ? "全知" : actorName(angle.viewpoint_character_id)} · ${angle.narrative_distance}` }
function perceiverLabel(material) { return material.perceiver_ids?.length ? `可感知：${material.perceiver_ids.map(actorName).join("、")}` : material.perception_status === "impossible" ? "角色不可感知" : "感知范围未知" }
function conflictLabel(value) { return value === "conflict" ? "与精确来源冲突" : value === "clear" ? "来源无冲突" : "冲突未知" }
function coverageLabel(value) { return value === "unknown" ? "未知" : value === "partial" ? "部分" : "完整" }
function number(value) { return Number(value || 0).toLocaleString("zh-CN") }
function duration(seconds) { const value = Number(seconds || 0); return value < 60 ? `${value} 秒` : `${Math.ceil(value / 60)} 分钟` }
function dateLabel(value) { if (!value) return "时间未知"; const date = new Date(value); return Number.isNaN(date.getTime()) ? "时间未知" : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) }
function branchStatus(value) { return ({ queued: "等待执行", running: "运行中", paused_budget: "预算暂停", paused_unknown: "用量待确认", complete: "已完成", ready: "可继续", failed: "失败", deleted: "已删除" })[value] || "已保存" }
function roundDepth(round, seen = new Set()) {
  if (!round || seen.has(round.id)) return 0
  seen.add(round.id)
  const branch = history.value?.branches?.find((item) => item.id === round.branch_id)
  return branch?.parent_round_id ? Math.min(5, 1 + roundDepth(roundById(branch.parent_round_id), seen)) : 0
}
function editBranchMeta(branch) {
  editingBranchId.value = branch.id
  branchMetadata.name = branch.name || ""
  branchMetadata.note = branch.note || ""
}

function toggleFullscreen() {
  fullscreen.value = !fullscreen.value
  if (fullscreen.value) requestAnimationFrame(() => panelRoot.value?.focus())
}
function closeFullscreen() { fullscreen.value = false }

watch(() => [props.projectId, props.scene?.id], async ([projectId, sceneId]) => {
  saveCurrentDraft()
  requestGeneration += 1
  poller?.stop?.()
  poller = null
  currentContextKey = `${projectId || ""}:${sceneId || ""}`
  loadedContextKey = ""
  restoreDraft(currentContextKey)
  if (!props.characters?.length) worldCharacters.value = []
  charactersError.value = ""
  history.value = null
  historyError.value = ""
  historyLoading.value = false
  startPreview.value = null
  continuationPreview.value = null
  if (!projectId || !sceneId || !props.visible) return
  await loadVisibleContext()
}, { immediate: true })

watch(() => props.visible, (visible) => {
  if (!visible) { fullscreen.value = false; return }
  if (typeof window !== "undefined" && window.matchMedia?.("(max-width: 560px)").matches) toggleFullscreen()
  void loadVisibleContext()
}, { immediate: true })

watch(() => props.characters, () => {
  if (!props.characters?.length) return
  const eligible = new Set(characters.value.map((item) => item.id))
  draft.characterIds = draft.characterIds.filter((id) => eligible.has(id))
  draft.primaryCharacterIds = draft.primaryCharacterIds.filter((id) => eligible.has(id))
  saveCurrentDraft()
}, { deep: true })

onBeforeUnmount(() => {
  saveCurrentDraft()
  requestGeneration += 1
  poller?.stop?.()
})
</script>

<style scoped>
.scene-director{display:grid;gap:16px;color:var(--text,#26323b);font-size:14px;line-height:1.55;min-width:0}.scene-director button,.scene-director input,.scene-director select,.scene-director textarea{font:inherit}.scene-director button,.scene-director select,.scene-director input:not([type=checkbox]){min-height:40px}.scene-director__header{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:16px;border:1px solid var(--border,#d9e0e4);border-radius:14px;background:linear-gradient(135deg,rgba(233,241,239,.7),rgba(255,255,255,.94))}.scene-director__header h2{margin:2px 0 4px;font-size:1.25rem}.scene-director__header p{margin:0;max-width:52rem;color:var(--muted,#64727b)}.scene-director__eyebrow{font-size:.72rem;letter-spacing:.1em;text-transform:uppercase;color:var(--accent,#52766d)!important}.scene-director__setup,.scene-director__history,.scene-director__continue{border:1px solid var(--border,#d9e0e4);border-radius:14px;padding:16px;background:var(--surface,#fff);min-width:0}.scene-director__section-heading{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}.scene-director__section-heading>div,.scene-director__round-header>div:first-child{display:flex;align-items:center;gap:10px}.scene-director__section-heading h3{margin:0;font-size:1.05rem}.scene-director__step,.scene-director__round-marker{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:50%;background:#e6efeb;color:#36594e;font-weight:700;font-size:.78rem}.scene-director__tag{padding:4px 9px;border-radius:999px;background:#f2f4f3;color:#52635d;font-size:.75rem}.scene-director__participants{border:0;padding:0;margin:0 0 14px;min-width:0}.scene-director__participants legend{font-weight:700;margin-bottom:4px}.scene-director__help,.scene-director__budget-choice p{color:var(--muted,#64727b);font-size:.83rem;margin:4px 0 10px}.scene-director__people{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:8px}.scene-director__person{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:9px 10px;border:1px solid var(--border,#d9e0e4);border-radius:10px}.scene-director__person-select,.scene-director__primary,.scene-director__duplicate-confirm{display:flex;align-items:center;gap:8px}.scene-director__person-select{font-weight:600}.scene-director__primary{font-size:.75rem;color:#597169;white-space:nowrap}.scene-director__form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:12px 0}.scene-director__form-grid--three{grid-template-columns:repeat(3,minmax(0,1fr))}.scene-director__form-grid--two{grid-template-columns:repeat(2,minmax(0,1fr))}.scene-director label>span:first-child{display:block;font-weight:600;margin-bottom:5px}.scene-director label small{font-weight:400;color:var(--muted,#64727b)}.scene-director input:not([type=checkbox]),.scene-director select,.scene-director textarea{box-sizing:border-box;width:100%;border:1px solid var(--border,#cfd8dd);border-radius:9px;background:#fff;padding:8px 10px;color:inherit}.scene-director textarea{resize:vertical;min-height:44px}.scene-director__field{display:block;margin:12px 0}.scene-director__budget-choice{margin-top:16px;padding:12px;border-radius:12px;background:#f6f8f7}.scene-director__budget-choice h4,.scene-director__references h4,.scene-director__recoveries h4{margin:0 0 4px}.scene-director__actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}.scene-director__budget{margin-top:12px;padding:13px;border-radius:12px;background:#edf4f1;border:1px solid #d3e2dc}.scene-director__budget>div{display:flex;flex-wrap:wrap;gap:12px;align-items:center}.scene-director__budget dl{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:12px 0}.scene-director__budget dl>div{padding:8px;border-radius:9px;background:rgba(255,255,255,.75)}.scene-director__budget dt{font-size:.72rem;color:var(--muted,#64727b)}.scene-director__budget dd{margin:3px 0 0;font-weight:700}.scene-director__budget p{margin:6px 0 0}.scene-director__warning{color:#845b16!important;font-size:.82rem}.scene-director__progress{padding:12px 14px;border:1px solid #bdd8ce;border-radius:12px;background:#eff7f3}.scene-director__progress>div{display:flex;justify-content:space-between;gap:10px}.scene-director__progress progress{display:block;width:100%;height:8px;margin-top:8px;accent-color:#4b7767}.scene-director__empty{padding:18px;border:1px dashed var(--border,#cfd8dd);border-radius:12px;text-align:center;color:var(--muted,#64727b)}.scene-director__empty strong{color:var(--text,#26323b)}.scene-director__empty p{margin:4px 0 0}.scene-director__empty--compact{padding:8px;text-align:left}.scene-director__notice{display:flex;justify-content:space-between;align-items:center;gap:10px;padding:10px 12px;margin:8px 0;border-radius:10px;background:#f4f6f5}.scene-director__notice--error,.scene-director__error{color:#8b342d;background:#fff1ef}.scene-director__message{color:#35604f}.scene-director__history-toolbar{display:flex;align-items:end;gap:8px;flex-wrap:wrap;padding:10px 0}.scene-director__history-toolbar label{min-width:150px;flex:1}.scene-director__comparison{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:8px 0 14px}.scene-director__comparison section{padding:12px;border-radius:10px;background:#f6f8f7;overflow-wrap:anywhere}.scene-director__comparison h4{margin:0 0 7px}.scene-director__tree{display:grid;gap:12px}.scene-director__round{min-width:0;padding:14px;border:1px solid var(--border,#d9e0e4);border-radius:13px;background:#fff;scroll-margin-top:18px}.scene-director__round.is-selected{border-color:#689181;box-shadow:0 0 0 2px rgba(93,139,119,.12)}.scene-director__round-header{display:flex;align-items:center;justify-content:space-between;gap:10px}.scene-director__round-header h4{margin:0;font-size:.95rem}.scene-director__round-header p{margin:1px 0 0;color:var(--muted,#64727b);font-size:.75rem}.scene-director__round-actions{display:flex;gap:6px;flex-wrap:wrap}.scene-director__round-summary{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.scene-director__round-summary span{padding:4px 8px;border-radius:999px;background:#f2f5f4;font-size:.74rem;color:#52635d}.scene-director__metadata-editor{display:grid;gap:8px;padding:10px;margin-top:10px;border-radius:10px;background:#f6f8f7}.scene-director__author-note{padding:9px 10px;border-left:3px solid #7c9c8f;background:#f6f8f7}.scene-director__cards{display:grid;gap:10px}.scene-director__performance{padding:12px;border:1px solid #e1e7e4;border-radius:11px;background:#fcfdfc}.scene-director__performance h5,.scene-director__materials h5,.scene-director__candidate-events h5{margin:0 0 8px}.scene-director__performance dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:0}.scene-director__performance dl>div{min-width:0}.scene-director__performance dt{font-size:.72rem;color:var(--muted,#64727b)}.scene-director__performance dd{margin:2px 0 0;overflow-wrap:anywhere}.scene-director__basis{font-size:.78rem;color:#52635d}.scene-director__candidate-events{margin-top:12px;padding:12px;border-radius:11px;background:#fff8e9}.scene-director__candidate-events h5 span{font-weight:400;color:#886823;font-size:.74rem}.scene-director__candidate-events article{padding:8px 0;border-top:1px solid #efe3c7}.scene-director__candidate-events p{margin:3px 0}.scene-director__candidate-events small{color:#886823}.scene-director__materials{margin-top:14px}.scene-director__subheading{display:flex;justify-content:space-between;align-items:center;gap:8px}.scene-director__subheading>span{font-size:.75rem;color:var(--muted,#64727b)}.scene-director__material-list{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.scene-director__material{display:flex;gap:8px;align-items:flex-start;padding:9px;border:1px solid #dfe6e2;border-radius:9px;background:#fbfcfb;min-width:0}.scene-director__material input{margin-top:4px;flex:none}.scene-director__material span{min-width:0;overflow-wrap:anywhere}.scene-director__material strong{display:block;color:#426657;font-size:.72rem}.scene-director__material small{display:block;margin-top:4px;color:var(--muted,#64727b);font-size:.7rem}.scene-director__material.is-disabled{opacity:.48;background:#f3f4f4}.scene-director__angle-choice{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:end;gap:8px;margin-top:10px}.scene-director__angle-choice>label{min-width:0}.scene-director__custom-angle{grid-column:1/-1;padding:9px 10px;border-radius:9px;background:#f6f8f7}.scene-director__custom-angle summary,.scene-director__more summary{cursor:pointer;font-weight:600}.scene-director__more{margin-top:13px;padding-top:10px;border-top:1px solid #e6ebe8}.scene-director__alternatives{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin:9px 0}.scene-director__alternatives article{padding:10px;border-radius:9px;background:#f6f8f7}.scene-director__alternatives p{margin:4px 0 8px}.scene-director__findings,.scene-director__warnings{padding-left:20px}.scene-director__findings .is-conflict{color:#9a322c}.scene-director__findings .is-unknown{color:#86621e}.scene-director__delta{white-space:pre-wrap;overflow-wrap:anywhere;padding:10px;border-radius:9px;background:#f6f8f7;font: .75rem/1.5 ui-monospace,monospace}.scene-director__branch-actions{display:flex;flex-wrap:wrap;gap:7px;margin-top:12px}.scene-director__continue{border-color:#93b1a4;background:#fbfdfc}.scene-director__duplicate-confirm{padding:10px;border-radius:9px;background:#fff2dc;color:#795513}.scene-director__references,.scene-director__recoveries{margin-top:14px;padding-top:12px;border-top:1px solid #e2e8e5}.scene-director__references h4 small{display:block;color:var(--muted,#64727b);font-size:.74rem;font-weight:400}.scene-director__reference{padding:10px 0;border-bottom:1px solid #e6ebe8}.scene-director__reference>div:first-child{display:flex;flex-wrap:wrap;gap:9px}.scene-director__reference>div:first-child span{font-size:.75rem;color:#946e25}.scene-director__recovery{display:flex;align-items:center;gap:8px}.scene-director__error{padding:10px;border-radius:9px}.scene-director__message{padding:8px 0}.scene-director__custom-angle label{display:block;margin:8px 0}.scene-director__branch-actions button:focus-visible,.scene-director button:focus-visible,.scene-director input:focus-visible,.scene-director select:focus-visible,.scene-director textarea:focus-visible{outline:3px solid rgba(81,127,111,.35);outline-offset:2px}
.scene-director__branch-list{display:grid;gap:8px;padding:12px;border-radius:11px;background:#f7f9f8}.scene-director__branch-list>h4{margin:0 0 2px}.scene-director__branch-list>article{padding:9px;border:1px solid #e0e6e3;border-radius:10px;background:#fff}.scene-director__branch-list>article>div:first-child{display:flex;flex-wrap:wrap;gap:10px;align-items:center}.scene-director__branch-list>article>div:first-child span{font-size:.75rem;color:var(--muted,#64727b)}.scene-director__round{margin-left:calc(min(72px, var(--branch-depth, 0) * 14px))}.scene-director__header-actions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}.scene-director.is-fullscreen{position:fixed;inset:0;z-index:1500;overflow:auto;overscroll-behavior:contain;padding:20px max(20px,calc((100vw - 1120px)/2));background:#f4f7f5;box-shadow:0 0 0 100vmax rgba(19,31,27,.48)}
@media(max-width:560px){.scene-director__header{display:grid}.scene-director__form-grid,.scene-director__form-grid--three,.scene-director__form-grid--two,.scene-director__budget dl,.scene-director__comparison,.scene-director__performance dl,.scene-director__material-list,.scene-director__alternatives{grid-template-columns:1fr}.scene-director__round-header{align-items:flex-start;flex-direction:column}.scene-director__angle-choice{grid-template-columns:1fr}.scene-director__history-toolbar label{flex-basis:100%}.scene-director__setup,.scene-director__history,.scene-director__continue{padding:12px}.scene-director__round{padding:11px;margin-left:calc(min(42px, var(--branch-depth, 0) * 8px))}}
.scene-director{container-type:inline-size}
@container(max-width:560px){.scene-director__angle-choice,.scene-director__form-grid,.scene-director__form-grid--three,.scene-director__form-grid--two,.scene-director__budget dl,.scene-director__performance dl,.scene-director__material-list,.scene-director__alternatives{grid-template-columns:minmax(0,1fr)}.scene-director__header{display:grid}.scene-director__round-header{align-items:flex-start;flex-direction:column}.scene-director__history-toolbar label{flex-basis:100%}}
</style>
<style scoped>
.scene-director__reference-use{display:flex;align-items:center;gap:8px;margin:8px 0;color:#456458;font-size:.84rem}
.scene-director__reference-use input{flex:none}
</style>
