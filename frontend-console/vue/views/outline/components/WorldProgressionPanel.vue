<template>
  <section class="world-progression" aria-labelledby="world-progression-title">
    <header class="world-progression__header">
      <div class="world-progression__heading">
        <p class="world-progression__eyebrow">候选推演 · 不改正史</p>
        <h2 id="world-progression-title">世界推进</h2>
        <p>从最近已写到的场景出发，查看离场人物与群体接下来可能怎样行动。</p>
      </div>
      <button
        type="button"
        class="btn world-progression__toggle"
        :aria-expanded="open"
        @click="toggleOpen"
      >{{ open ? "收起" : "开始探索" }}</button>
    </header>

    <div v-if="open" class="world-progression__body" :aria-busy="loading">
      <p v-if="error" class="world-progression__notice world-progression__notice--error" role="alert">
        {{ error }}
      </p>
      <p v-if="notice" class="world-progression__notice" :role="noticeRole">{{ notice }}</p>

      <div v-if="loading && !participants.length" class="world-progression__empty" role="status">
        正在读取当前作品的人物、群体和故事结构…
      </div>

      <template v-else>
        <section class="world-progression__section" aria-labelledby="progression-participants-title">
          <div class="world-progression__section-heading">
            <div><span class="world-progression__step">01</span><h3 id="progression-participants-title">选择参与者</h3></div>
            <span class="world-progression__tag">默认 {{ defaultParticipantCount }} 位</span>
          </div>
          <p class="world-progression__help">
            默认选择最多 12 位；你可以增减任意数量。资料超过单次上下文时会分组并披露，不会静默省略。
            势力参与仍等待势力路线图前置阶段。
          </p>
          <label class="world-progression__search">
            <span class="sr-only">筛选人物和群体</span>
            <input v-model="participantSearch" type="search" placeholder="筛选姓名" autocomplete="off">
          </label>
          <div v-if="!participants.length && !loading" class="world-progression__empty">
            还没有可证明的人物或群体身份。请先建立并采用对应世界对象。
          </div>
          <fieldset v-else class="world-progression__participants" :disabled="busy">
            <legend class="sr-only">本次推进参与者</legend>
            <label v-for="actor in filteredParticipants" :key="`${actor.kind}:${actor.id}`" class="world-progression__participant">
              <input v-model="form.participantIds" type="checkbox" :value="actor.id" @change="onParticipantsChanged">
              <span class="world-progression__participant-copy">
                <strong>{{ actor.name }}</strong>
                <small>{{ actor.kind === "group" ? "群体" : "人物" }}</small>
              </span>
            </label>
          </fieldset>
          <p class="world-progression__selection-count" aria-live="polite">
            已选择 {{ selectedParticipants.length }} 位
            <span v-if="selectedParticipants.length > 16">· 资料将分为 {{ Math.ceil(selectedParticipants.length / 16) }} 组</span>
          </p>
        </section>

        <section class="world-progression__section" aria-labelledby="progression-direction-title">
          <div class="world-progression__section-heading">
            <div><span class="world-progression__step">02</span><h3 id="progression-direction-title">设定推进方式</h3></div>
          </div>
          <div class="world-progression__field-grid">
            <label>
              <span>推进方式</span>
              <select v-model="form.mode" :disabled="busy" @change="invalidatePreview">
                <option value="free">自由推进</option>
                <option value="directed">导向推进</option>
              </select>
            </label>
            <label>
              <span>每步步长</span>
              <select v-model="form.stepLength" :disabled="busy" @change="invalidatePreview">
                <option value="auto">自动</option>
                <option value="day">一天</option>
                <option value="week">一周</option>
                <option value="month">一个月</option>
                <option value="season">一季</option>
                <option value="year">一年</option>
                <option value="next_beat">下一个关键节拍</option>
              </select>
            </label>
            <label>
              <span>运行方式</span>
              <select v-model="form.runPolicy" :disabled="busy" @change="onRunPolicyChanged">
                <option value="one_step">点击一步（默认）</option>
                <option value="n_steps">连续指定步数</option>
                <option value="until_goal">推进到目标</option>
                <option value="until_budget">推进到预算停止</option>
              </select>
            </label>
            <label v-if="form.runPolicy === 'n_steps'">
              <span>连续步数</span>
              <input v-model.number="form.steps" type="number" min="1" step="1" :disabled="busy" @input="onBudgetInputsChanged">
            </label>
            <label v-if="form.runPolicy === 'n_steps' && form.targets.length" class="world-progression__must-reach">
              <input v-model="form.stopAtGoal" type="checkbox" :disabled="busy" @change="invalidatePreview">
              <span>目标达成后提前停止</span>
            </label>
          </div>

          <label v-if="form.mode === 'directed'" class="world-progression__field">
            <span>作者设定的剧情方向 <small>只进入导演裁决层</small></span>
            <textarea v-model="form.instructions" rows="3" maxlength="6000" :disabled="busy" placeholder="例如：他们逐步接近结盟，但关系变化要有铺垫；如果与既有设定冲突，请保留冲突并说明。" @input="invalidatePreview"></textarea>
          </label>

          <div v-if="form.mode === 'directed'" class="world-progression__targets">
            <div class="world-progression__targets-heading">
              <div><h4>可选目标节点</h4><p>目标默认是软目标；只有你勾选“必达”才会作为保留项。</p></div>
              <span v-if="targetLoading" role="status">正在读取…</span>
            </div>
            <label class="world-progression__search">
              <span class="sr-only">筛选目标节点</span>
              <input v-model="targetSearch" type="search" placeholder="筛选篇章、剧情线或计划场景" autocomplete="off">
            </label>
            <div v-if="targetLoadError" class="world-progression__notice world-progression__notice--error" role="alert">{{ targetLoadError }}</div>
            <div v-else-if="!targetLoading && !targetOptions.length" class="world-progression__empty">当前没有可用的篇章、剧情线或计划场景。也可以只写方向，不选择节点。</div>
            <div v-else class="world-progression__target-list">
              <div v-for="target in filteredTargets" :key="`${target.kind}:${target.id}`" class="world-progression__target">
                <label class="world-progression__target-select">
                  <input type="checkbox" :checked="isTargetSelected(target)" :disabled="busy" @change="toggleTarget(target)">
                  <span><strong>{{ target.name }}</strong><small>{{ target.kindLabel }}<template v-if="target.range"> · {{ target.range }}</template></small></span>
                </label>
                <label v-if="isTargetSelected(target)" class="world-progression__must-reach">
                  <input type="checkbox" :checked="isMustReach(target)" :disabled="busy" @change="toggleMustReach(target)">
                  <span>必达保留项</span>
                </label>
              </div>
            </div>
          </div>

          <label class="world-progression__field">
            <span>保留项 <small>可以不填</small></span>
            <textarea v-model="form.retainedConstraintsText" rows="2" maxlength="4000" :disabled="busy" placeholder="例如：不要让尚未相识的人物突然互相信任。" @input="invalidatePreview"></textarea>
          </label>

          <details class="world-progression__budget-details" open>
            <summary>本次运行预算</summary>
            <p>预算由你明确选择。到 80%、用量未知或接近时限时暂停；只记录计费状态，不估算金额。</p>
            <div class="world-progression__field-grid world-progression__field-grid--three">
              <label><span>最多请求</span><input v-model.number="form.requestLimit" type="number" min="1" step="1" :disabled="busy" @input="onBudgetInputsChanged"></label>
              <label><span>Token 上限</span><input v-model.number="form.tokenLimit" type="number" min="1" step="1" :disabled="busy" @input="onBudgetInputsChanged"></label>
              <label><span>时限（分钟）</span><input v-model.number="form.timeBudgetMinutes" type="number" min="1" step="1" :disabled="busy" @input="onBudgetInputsChanged"></label>
            </div>
          </details>

          <div class="world-progression__actions">
            <button type="button" class="btn" :disabled="busy || !canPreview" @click="previewBudget">
              {{ previewLoading ? "正在预览…" : "预览预算与资料" }}
            </button>
            <button type="button" class="btn btn-primary" :disabled="busy || !budgetPreview || !canStart" @click="startRun">
              {{ submitting ? "正在提交…" : "确认资料并推进" }}
            </button>
          </div>
          <p v-if="!canPreview" class="world-progression__help">请选择参与者；导向推进还需要作者方向或目标节点。连续到目标模式需要至少一个目标。</p>

          <section v-if="budgetPreview" class="world-progression__preview" aria-labelledby="progression-preview-title" aria-live="polite">
            <div class="world-progression__section-heading">
              <div><span class="world-progression__step">03</span><h3 id="progression-preview-title">预算预览</h3></div>
              <span class="world-progression__tag">{{ budgetPreview.model || "当前项目模型" }}</span>
            </div>
            <p>截止场景：{{ budgetPreview.scene_title || sceneTitle(budgetPreview.scene_id) }} · {{ budgetPreview.scene_index != null ? `场景 ${budgetPreview.scene_index + 1}` : "最近已写到的位置" }}</p>
            <div class="world-progression__metrics">
              <div><strong>{{ budgetPreview.participants }}</strong><span>位参与者</span></div>
              <div><strong>{{ budgetPreview.request_budget?.estimate_minimum }}–{{ budgetPreview.request_budget?.estimate_maximum }}</strong><span>{{ budgetPreview.request_budget?.estimate_scope === "authorization_window" ? "首步至授权窗口预计请求" : "完成所选步骤预计请求" }} / 上限 {{ budgetPreview.request_budget?.limit }}</span></div>
              <div><strong>{{ formatNumber(budgetPreview.token_budget?.estimate_minimum) }}–{{ formatNumber(budgetPreview.token_budget?.estimate_maximum) }}</strong><span>预计 Token / 上限 {{ formatNumber(budgetPreview.token_budget?.limit) }}</span></div>
              <div><strong>{{ budgetPreview.time_budget?.estimate_minimum_seconds }}–{{ budgetPreview.time_budget?.estimate_maximum_seconds }} 秒</strong><span>预计耗时 / 上限 {{ budgetPreview.time_budget?.limit_seconds }} 秒</span></div>
            </div>
            <p class="world-progression__fee">{{ budgetPreview.fee_status }}</p>
            <p class="world-progression__help">步长建议：{{ recommendationText(budgetPreview.step_length_recommendation) }}</p>
            <p v-if="budgetPreview.grouping?.group_count > 1" class="world-progression__warning">资料分为 {{ budgetPreview.grouping.group_count }} 组，每组最多 {{ budgetPreview.grouping.entity_group_size }} 项。</p>
            <ul v-if="budgetPreview.warnings?.length" class="world-progression__warnings">
              <li v-for="warning in budgetPreview.warnings" :key="warning">{{ warning }}</li>
            </ul>
          </section>
          <div v-if="flowAvailable" class="world-progression__actions">
            <button type="button" class="btn" :disabled="busy || !budgetPreview" @click="startGuidedFlow">
              {{ flowView ? "重新载入引导流程" : "改用引导流程复核" }}
            </button>
            <span class="world-progression__help">流程会冻结当前选择；预算与钩子采用仍需你逐次确认。</span>
          </div>
          <section v-if="flowView" class="world-progression__flow" aria-labelledby="progression-flow-title" aria-live="polite">
            <div class="world-progression__section-heading">
              <div><span class="world-progression__step">引导</span><h3 id="progression-flow-title">{{ flowView.title }}</h3></div>
              <button type="button" class="btn btn-sm" :disabled="busy" @click="refreshGuidedFlow">刷新流程</button>
            </div>
            <ol class="world-progression__flow-steps">
              <li v-for="step in flowView.steps || []" :key="step.step_id" :data-state="step.state">{{ step.title }}</li>
            </ol>
            <p v-if="flowView.stop" class="world-progression__notice" role="status">{{ flowView.stop.reason }}</p>
            <p v-else-if="flowView.status === 'running'" class="world-progression__help" role="status">{{ flowView.panel?.message || "正在等候推进候选保存…" }}</p>
            <div v-if="(flowView.stop?.step_id === 'review_hooks' || flowView.stop?.actions?.some((item) => item.action === 'choose_another_hook')) && flowView.panel?.hooks?.length" class="world-progression__field-grid">
              <label><span>选择剧情钩子</span><select v-model="flowHookSelection.hookId" :disabled="busy" @change="syncFlowHookWindow"><option value="">请选择</option><option v-for="hook in flowView.panel.hooks" :key="hook.hook_id" :value="hook.hook_id">{{ hook.title }}</option></select></label>
              <label><span>采用为</span><select v-model="flowHookSelection.assetType" :disabled="busy" @change="syncFlowHookWindow"><option value="plot_thread">剧情线</option><option value="outline_arc">篇章</option><option value="planned_scene">计划场景</option></select></label>
              <label><span>开始章节</span><input v-model.number="flowHookSelection.startChapter" type="number" min="1" :disabled="busy"></label>
              <label><span>结束章节</span><input v-model.number="flowHookSelection.endChapter" type="number" min="1" :disabled="busy"></label>
            </div>
            <div v-if="flowView.panel?.selected_hook" class="world-progression__hook-preview">
              <strong>{{ flowView.panel.selected_hook.title }}</strong>
              <p>{{ flowView.panel.selected_hook.summary }}</p>
              <p v-if="flowView.panel.hook_preview">只读窗口预览：{{ chapterRange(flowView.panel.hook_preview.window) }} · {{ flowView.panel.hook_preview.effect }}</p>
            </div>
            <p v-if="flowView.panel?.history" class="world-progression__help">引导流程已读取不可变步骤历史；所有结果仍是候选，不会写入世界或正文。</p>
            <div v-if="flowView.stop?.actions?.length" class="world-progression__actions">
              <button v-for="action in flowView.stop.actions" :key="action.action" type="button" class="btn" :class="{ 'btn-primary': action.action === 'confirm_and_start' || action.action === 'adopt_hook' }" :disabled="busy || (action.action === 'select_hook' && !flowHookSelection.hookId)" @click="runGuidedFlowAction(action.action)">{{ action.label }}</button>
            </div>
            <p v-if="flowError" class="world-progression__notice world-progression__notice--error" role="alert">{{ flowError }}</p>
          </section>
        </section>

        <section class="world-progression__section" aria-labelledby="progression-history-title">
          <div class="world-progression__section-heading">
            <div><span class="world-progression__step">04</span><h3 id="progression-history-title">推进历史</h3></div>
            <button type="button" class="btn btn-sm" :disabled="historyLoading" @click="loadHistory">{{ historyLoading ? "正在更新…" : "刷新历史" }}</button>
          </div>
          <p v-if="historyError" class="world-progression__notice world-progression__notice--error" role="alert">{{ historyError }}</p>
          <div v-else-if="historyLoading && !history.roots.length" class="world-progression__empty" role="status">正在读取不可变步骤…</div>
          <div v-else-if="!history.roots.length" class="world-progression__empty">
            这里还没有推进运行。预算预览不会调用模型；开始后每一步都会保留输入、结果、依据和累计用量。
          </div>
          <div v-else class="world-progression__roots">
            <article v-for="root in history.roots" :key="root.id" class="world-progression__root">
              <header class="world-progression__root-header">
                <div><h4>{{ root.name || "世界推进运行" }}</h4><p>{{ sceneTitle(root.scene_id) }} · {{ dateLabel(root.created_at) }} · {{ statusLabel(root.status) }}</p></div>
                <span class="world-progression__tag">{{ root.request?.mode === "directed" ? "导向推进" : "自由推进" }}</span>
              </header>
              <p class="world-progression__budget-line">
                累计请求 {{ root.budget?.requests_used || 0 }} / {{ root.budget?.requests_authorized || "—" }}
                · Token {{ formatNumber(root.budget?.tokens_used) }} / {{ formatNumber(root.budget?.tokens_authorized) }}
                · {{ root.budget?.fee_status || "计费状态未知" }}
              </p>
              <p v-if="root.basis_status" class="world-progression__basis" :data-state="root.basis_status">{{ basisLabel(root.basis_status, root.basis_note) }}</p>

              <div class="world-progression__branch-list">
                <article v-for="branch in root.branches || []" :key="branch.id" class="world-progression__branch" :class="{ 'is-deleted': branch.deleted_at }">
                  <header class="world-progression__branch-header">
                    <div>
                      <h5>{{ branch.name || branchLabel(branch) }} <span v-if="branch.starred" aria-label="已星标">★</span></h5>
                      <p>{{ branchKindLabel(branch.branch_kind) }} · {{ statusLabel(branch.status) }}<template v-if="branch.restore_until"> · 可恢复至 {{ dateLabel(branch.restore_until) }}</template></p>
                    </div>
                    <div class="world-progression__branch-actions">
                      <button v-if="branch.deleted_at" type="button" class="btn btn-sm" :disabled="busy" @click="restoreBranch(branch)">恢复</button>
                      <template v-else>
                        <button type="button" class="btn btn-sm" :aria-pressed="branch.starred" :disabled="busy" @click="saveBranch(branch, { starred: !branch.starred })">{{ branch.starred ? "★ 已星标" : "☆ 星标" }}</button>
                        <button v-if="branch.resume_hash && branch.pending_step?.pending" type="button" class="btn btn-sm" :disabled="busy" @click="resumeBranch(root, branch)">确认恢复中断步骤</button>
                        <button type="button" class="btn btn-sm btn-text" :disabled="busy" @click="deleteBranch(branch)">移入恢复区</button>
                      </template>
                    </div>
                  </header>
                  <div v-if="!branch.deleted_at" class="world-progression__branch-meta">
                    <label><span>分支名称</span><input v-model="branchDrafts[branch.id].name" maxlength="180" :disabled="busy"></label>
                    <label><span>作者近况备注 <small>只作作者备注，不计作发生事件</small></span><textarea v-model="branchDrafts[branch.id].note" rows="2" maxlength="4000" :disabled="busy"></textarea></label>
                    <button type="button" class="btn btn-sm" :disabled="busy || !branch.updated_at" @click="saveBranch(branch, branchDrafts[branch.id])">保存备注</button>
                  </div>

                  <div v-if="!branch.deleted_at && branch.steps?.length" class="world-progression__step-list">
                    <details v-for="step in branch.steps" :key="step.id" class="world-progression__history-step">
                      <summary>
                        <span>第 {{ step.step_number }} 步 · {{ step.result?.story_time_text || "时间估计待核" }}</span>
                        <small>{{ step.source_current_status === "changed" || step.basis_changed ? "依据已变化" : step.source_current_status === "same" ? "当前依据一致" : "依据未核对" }} · {{ dateLabel(step.created_at) }}</small>
                      </summary>
                      <div class="world-progression__step-content">
                        <p class="world-progression__time-note">故事时间是模型估计，不代表产品日历已实现。</p>
                        <p class="world-progression__hashes">输入 {{ step.input_hash || "—" }} · 输出 {{ step.output_hash || "—" }} · 父输出 {{ step.parent_output_hash || "无（根步骤）" }}</p>
                        <p>{{ step.result?.narrative_summary }}</p>
                        <div class="world-progression__metrics world-progression__metrics--compact">
                          <div><strong>{{ step.metrics?.state_changes || 0 }}</strong><span>结构状态变化</span></div>
                          <div><strong>{{ step.metrics?.intersections || 0 }}</strong><span>结构交汇</span></div>
                          <div><strong>{{ step.metrics?.goals_completed || 0 }}</strong><span>目标完成</span></div>
                          <div><strong>{{ step.metrics?.goals_blocked || 0 }}</strong><span>目标受阻</span></div>
                        </div>
                        <p v-if="step.result?.progress_advice" class="world-progression__warning">连续两步推进较少；可尝试把步长改为“{{ stepLengthLabel(step.result.progress_advice.suggested_step_length) }}”。</p>
                        <section v-if="step.result?.actor_intents?.length" class="world-progression__result-group">
                          <h6>人物意图与结果</h6>
                          <ul><li v-for="(intent, index) in step.result.actor_intents" :key="`${intent.actor_id}:${index}`"><strong>{{ actorName(intent.actor_id) }}：</strong>{{ intent.action }}<small>{{ intentOutcomeLabel(step, intent.intent_id) }}</small><small v-if="intent.reason">因果依据：{{ intent.reason }}</small></li></ul>
                        </section>
                        <section v-if="step.result?.movement_feasibility?.length || step.result?.source_gaps?.length || step.result?.typed_object_validity?.length || step.result?.life_state_checks?.length" class="world-progression__result-group">
                          <h6>可行性与资料边界</h6>
                          <ul v-if="step.result?.movement_feasibility?.length">
                            <li v-for="(check, index) in step.result.movement_feasibility" :key="`move:${index}`">{{ actorName(check.actor_id) }}：{{ movementStatusLabel(check) }}</li>
                          </ul>
                          <ul v-if="step.result?.life_state_checks?.length">
                            <li v-for="check in step.result.life_state_checks" :key="`life:${check.participant_id}`">{{ actorName(check.participant_id) }} · 生死状态：{{ check.status === "verified_typed_fact" ? check.value : "缺少唯一可信的 typed 事实，未核实" }}</li>
                          </ul>
                          <ul v-if="step.result?.typed_object_validity?.length">
                            <li v-for="check in step.result.typed_object_validity" :key="check.notice_key">{{ validityTargetLabel(check.target) }}：{{ validityDecisionLabel(check.validity_decision) }}<small>依据指纹 {{ check.basis_fingerprint?.slice(0, 12) || "不可用" }}</small></li>
                          </ul>
                          <ul v-if="step.result?.source_gaps?.length">
                            <li v-for="gap in step.result.source_gaps" :key="gap">{{ sourceGapLabel(gap) }}</li>
                          </ul>
                        </section>
                        <section v-if="step.result?.state_delta?.length || hasCandidateUpdates(step.result)" class="world-progression__result-group">
                          <h6>结构化候选变化</h6>
                          <ul v-if="step.result?.state_delta?.length">
                            <li v-for="(patch, index) in step.result.state_delta" :key="`${patch.kind}:${patch.key}:${index}`">{{ stateDeltaText(patch) }}</li>
                          </ul>
                          <ul v-if="step.result?.candidate_status_updates?.length">
                            <li v-for="(change, index) in step.result.candidate_status_updates" :key="`status:${index}`">{{ actorName(change.actor_id) }} · {{ statusFieldLabel(change.field) }}：{{ change.value }}</li>
                          </ul>
                          <ul v-if="step.result?.candidate_attitude_updates?.length">
                            <li v-for="(change, index) in step.result.candidate_attitude_updates" :key="`attitude:${index}`">{{ actorName(change.subject_id) }} 对 {{ actorName(change.target_id) }} 的态度：{{ change.stance }}（{{ change.degree }}）</li>
                          </ul>
                          <ul v-if="step.result?.candidate_resource_updates?.length">
                            <li v-for="(change, index) in step.result.candidate_resource_updates" :key="`resource:${index}`">资源持有者变化：{{ actorName(change.holder_id) }}</li>
                          </ul>
                          <ul v-if="step.result?.candidate_knowledge_updates?.length">
                            <li v-for="(change, index) in step.result.candidate_knowledge_updates" :key="`knowledge:${index}`">{{ actorName(change.receiver_id) }}{{ knowledgeModalityLabel(change.modality) }}：{{ change.statement }}</li>
                          </ul>
                          <p class="world-progression__help">这些差量只存在于推进候选历史，不写入 Story 连续性、World 设定或正文。</p>
                        </section>
                        <section v-if="step.result?.intersections?.items?.length" class="world-progression__result-group">
                          <h6>结构交汇</h6>
                          <article v-for="item in step.result.intersections.items" :key="item.intersection_id" class="world-progression__intersection">
                            <p><strong>{{ actorNames(item.actor_ids) }}</strong> · {{ intersectionKinds(item.kinds) }}</p>
                            <p v-if="intersectionOutcome(step, item.intersection_id)">{{ intersectionOutcome(step, item.intersection_id).description }}</p>
                            <p v-if="item.kinds.includes('shared_existing_route')" class="world-progression__help">路线依据来自当前采用地图；未比较范围：{{ step.result.intersections.route_note || "无" }}</p>
                            <button type="button" class="btn btn-sm" :disabled="busy || !characterActors(item.actor_ids).length" @click="openDirectorDraft(root, step, item)">以此交汇准备导演起点</button>
                          </article>
                        </section>
                        <section v-if="step.result?.goal_outcomes?.length" class="world-progression__result-group">
                          <h6>目标路径</h6>
                          <ul><li v-for="outcome in step.result.goal_outcomes" :key="outcome.target_id"><strong>{{ targetName(outcome.target_id) }} · {{ goalStatusLabel(outcome.status) }}</strong><small>{{ outcome.reason }}</small></li></ul>
                          <ul v-if="step.result.target_paths?.length"><li v-for="path in step.result.target_paths" :key="path.target_id"><strong>{{ targetName(path.target_id) }} 的因果路径</strong>：{{ path.rationale }}</li></ul>
                        </section>
                        <section v-if="step.result?.setup_needed?.length || step.result?.unnatural_points?.length || step.result?.subplots?.length" class="world-progression__result-group">
                          <h6>铺垫与副线</h6>
                          <ul><li v-for="item in step.result.setup_needed || []" :key="`setup:${item}`">需要铺垫：{{ item }}</li><li v-for="item in step.result.unnatural_points || []" :key="`unnatural:${item}`">不自然处：{{ item }}</li><li v-for="(item, index) in step.result.subplots || []" :key="`subplot:${index}`">副线：{{ item.summary || item.description || item.title || "候选线索待核" }}</li></ul>
                        </section>
                        <section v-if="step.result?.plot_hooks?.length" class="world-progression__result-group">
                          <h6>可采用的剧情钩子</h6>
                          <article v-for="hook in step.result.plot_hooks" :key="hook.hook_id" class="world-progression__hook">
                            <div><strong>{{ hook.title }}</strong><p>{{ hook.summary }}</p></div>
                            <div class="world-progression__field-grid">
                              <label><span>作为</span><select v-model="hookDrafts[hook.hook_id].assetType" :disabled="busy"><option value="plot_thread">剧情线</option><option value="outline_arc">篇章</option><option value="planned_scene">计划场景</option></select></label>
                              <label><span>开始章节</span><input v-model.number="hookDrafts[hook.hook_id].startChapter" type="number" min="1" :disabled="busy"></label>
                              <label><span>结束章节</span><input v-model.number="hookDrafts[hook.hook_id].endChapter" type="number" min="1" :disabled="busy"></label>
                            </div>
                            <label class="world-progression__field"><span>候选标题</span><input v-model="hookDrafts[hook.hook_id].title" maxlength="255" :disabled="busy"></label>
                            <label class="world-progression__field"><span>候选内容</span><textarea v-model="hookDrafts[hook.hook_id].summary" rows="3" maxlength="4000" :disabled="busy"></textarea></label>
                            <div class="world-progression__actions">
                              <button type="button" class="btn btn-sm" :disabled="busy" @click="previewHook(root, step, hook)">{{ hookLoadingId === hook.hook_id ? "正在检查窗口…" : "预览滚动规划窗口" }}</button>
                              <button v-if="hookPreviews[hook.hook_id]" type="button" class="btn btn-sm btn-primary" :disabled="busy" @click="adoptHook(root, step, hook)">采用为可编辑候选</button>
                            </div>
                            <div v-if="hookPreviews[hook.hook_id]" class="world-progression__hook-preview" role="status">
                              <strong>只读预览 · {{ chapterRange(hookPreviews[hook.hook_id].window) }}</strong>
                              <p>{{ hookPreviews[hook.hook_id].effect }}</p>
                              <small>来源已冻结核验；预览零模型请求、零资产写入。采用时仍会重验来源并经 R3 确认。</small>
                            </div>
                          </article>
                        </section>
                        <div class="world-progression__actions">
                          <label><span>续跑依据</span><select v-model="continuationBasis[step.id]" :disabled="busy"><option value="current">当前资料（会标明变化）</option><option value="frozen">冻结历史资料</option></select></label>
                          <button type="button" class="btn btn-sm btn-primary" :disabled="busy || branch.deleted_at" @click="continueFromStep(root, branch, step)">从这一步继续</button>
                          <button type="button" class="btn btn-sm" :disabled="compareSteps.first && compareSteps.first !== step.id" @click="selectCompareStep(step)">{{ compareSteps.first === step.id ? "已选作对比项 1" : compareSteps.second === step.id ? "已选作对比项 2" : "选择对比" }}</button>
                        </div>
                      </div>
                    </details>
                  </div>

                  <section v-if="!branch.deleted_at && authorizationFor(root)?.branch_id === branch.id" class="world-progression__continuous" aria-labelledby="progression-continuous-title">
                    <div class="world-progression__section-heading"><div><span class="world-progression__step">05</span><h3 id="progression-continuous-title">持续推进提醒</h3></div><span class="world-progression__tag">{{ authorizationFor(root)?.enabled ? "已开启" : "默认关闭" }}</span></div>
                    <p>读入新章达到你设定的门槛后，只在原根剩余额度内为长期离场且目标未完成的人物生成一步自由候选。这里只保存候选并合并提醒，不扩大预算，也不写入正文。</p>
                    <div v-if="authorizationFor(root)?.enabled" class="world-progression__budget-line">原根剩余：{{ formatNumber(authorizationFor(root)?.budget?.requests_authorized - authorizationFor(root)?.budget?.requests_used) }} 请求 · {{ formatNumber(authorizationFor(root)?.budget?.tokens_authorized - authorizationFor(root)?.budget?.tokens_used) }} Token · {{ authorizationFor(root)?.budget?.unknown_requests || 0 }} 个未知结果</div>
                    <fieldset class="world-progression__participants" :disabled="busy || authorizationFor(root)?.enabled">
                      <legend>允许自动候选推进的参与者</legend>
                      <label v-for="actor in participantsForRoot(root)" :key="`continuous:${actor.id}`" class="world-progression__participant"><input v-model="continuousDraft.participantIds" type="checkbox" :value="actor.id"><span class="world-progression__participant-copy"><strong>{{ actor.name }}</strong><small>{{ actor.kind === "group" ? "群体" : "人物" }}</small></span></label>
                    </fieldset>
                    <label class="world-progression__interval"><span>每有多少章新正文时检查</span><input v-model.number="continuousDraft.everyNewChapters" type="number" min="1" :disabled="busy || authorizationFor(root)?.enabled"></label>
                    <div class="world-progression__actions">
                      <button v-if="!authorizationFor(root)?.enabled" type="button" class="btn btn-primary" :disabled="busy || !continuousDraft.participantIds.length" @click="setContinuous(root, branch, true)">确认持续授权</button>
                      <button v-else type="button" class="btn" :disabled="busy" @click="setContinuous(root, branch, false)">关闭持续授权</button>
                    </div>
                  </section>
                </article>
              </div>
            </article>
          </div>

          <section v-if="comparison" class="world-progression__comparison" aria-live="polite">
            <h4>步骤比较</h4>
            <p>{{ comparison.state_equal ? "候选结构状态相同" : "候选结构状态不同" }} · {{ comparison.basis_changed ? "至少一项步骤的依据已变化" : "步骤记录保留各自来源指纹" }}</p>
            <div class="world-progression__compare-columns"><article><strong>{{ comparison.left.result?.story_time_text || "步骤一" }}</strong><p>{{ comparison.left.result?.narrative_summary }}</p></article><article><strong>{{ comparison.right.result?.story_time_text || "步骤二" }}</strong><p>{{ comparison.right.result?.narrative_summary }}</p></article></div>
          </section>
          <section v-if="directorDraft.key" class="world-progression__director-draft" aria-labelledby="progression-director-title">
            <div class="world-progression__section-heading">
              <div><span class="world-progression__step">导演</span><h3 id="progression-director-title">交汇候选起点</h3></div>
              <button type="button" class="btn btn-sm btn-text" :disabled="directorDraft.busy" @click="directorDraft.key = ''; directorDraft.preview = null">收起</button>
            </div>
            <p>以下内容是作者选择的候选假设，未被当作已发生事实；提交前仍须确认资料和独立预算。</p>
            <label class="world-progression__field"><span>导演层起点假设</span><textarea v-model="directorDraft.intervention" rows="4" maxlength="3000" :disabled="directorDraft.busy" @input="directorDraft.preview = null"></textarea></label>
            <div class="world-progression__field-grid world-progression__field-grid--three">
              <label><span>最多请求</span><input v-model.number="directorDraft.requestLimit" type="number" min="1" :disabled="directorDraft.busy" @input="directorDraft.preview = null"></label>
              <label><span>Token 上限</span><input v-model.number="directorDraft.tokenLimit" type="number" min="1" :disabled="directorDraft.busy" @input="directorDraft.preview = null"></label>
              <label><span>时限（分钟）</span><input v-model.number="directorDraft.timeBudgetMinutes" type="number" min="1" :disabled="directorDraft.busy" @input="directorDraft.preview = null"></label>
            </div>
            <div class="world-progression__actions">
              <button type="button" class="btn" :disabled="directorDraft.busy" @click="previewDirectorStart">{{ directorDraft.busy ? "正在预览…" : "预览导演预算" }}</button>
              <button v-if="directorDraft.preview" type="button" class="btn btn-primary" :disabled="directorDraft.busy" @click="startDirectorFromIntersection">确认并开始导演候选</button>
            </div>
            <p v-if="directorDraft.preview" class="world-progression__help" role="status">预算预览：{{ formatNumber(directorDraft.preview.token_budget?.estimate_minimum) }}–{{ formatNumber(directorDraft.preview.token_budget?.estimate_maximum) }} Token · {{ directorDraft.preview.fee_status }} · 无费用金额估计</p>
          </section>
        </section>
      </template>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue"
import { getApi, getAppState, getConfirm } from "../../../bridge/index.js"
import { confirmAiReference } from "../../../../shared/aiReferenceModal.js"
import { createOperationId } from "../../../../shared/workflowProgress.js"

const props = defineProps({
  projectId: { type: String, default: null },
  characters: { type: Array, default: () => [] },
  entities: { type: Array, default: () => [] },
})

const open = ref(false)
const loading = ref(false)
const targetLoading = ref(false)
const previewLoading = ref(false)
const submitting = ref(false)
const historyLoading = ref(false)
const busy = ref(false)
const error = ref("")
const historyError = ref("")
const targetLoadError = ref("")
const flowError = ref("")
const notice = ref("")
const noticeRole = ref("status")
const participantSearch = ref("")
const targetSearch = ref("")
const participants = ref([])
const targetOptions = ref([])
const budgetPreview = ref(null)
const history = ref({ roots: [] })
const comparison = ref(null)
const taskProgress = ref(null)
const activeAuthorization = ref(null)
const activeAuthorizationRootId = ref("")
const flowAvailable = ref(false)
const flowView = ref(null)
const flowHookSelection = reactive({
  hookId: "",
  assetType: "plot_thread",
  startChapter: 1,
  endChapter: 3,
})
const hookLoadingId = ref("")
const branchDrafts = reactive({})
const hookDrafts = reactive({})
const hookPreviews = reactive({})
const continuationBasis = reactive({})
const compareSteps = reactive({ first: "", second: "" })
const compareRootId = ref("")
const continuousDraft = reactive({ participantIds: [], everyNewChapters: 3 })
const directorDraft = reactive({
  key: "",
  rootId: "",
  sceneId: "",
  characterIds: [],
  relatedObjectIds: [],
  intervention: "",
  requestLimit: 20,
  tokenLimit: 60000,
  timeBudgetMinutes: 30,
  preview: null,
  busy: false,
})

const form = reactive({
  participantIds: [],
  mode: "free",
  stepLength: "auto",
  runPolicy: "one_step",
  steps: 2,
  stopAtGoal: false,
  instructions: "",
  retainedConstraintsText: "",
  targets: [],
  requestLimit: 20,
  tokenLimit: 60000,
  timeBudgetMinutes: 30,
})

let generation = 0
let pollTimer = null
let flowPollTimer = null
let activeTaskId = ""
let budgetTouched = false

const selectedParticipants = computed(() => participants.value.filter((item) => form.participantIds.includes(item.id)))
const filteredParticipants = computed(() => {
  const query = participantSearch.value.trim().toLocaleLowerCase()
  return query
    ? participants.value.filter((item) => item.name.toLocaleLowerCase().includes(query))
    : participants.value
})
const filteredTargets = computed(() => {
  const query = targetSearch.value.trim().toLocaleLowerCase()
  return query
    ? targetOptions.value.filter((item) => `${item.name} ${item.kindLabel}`.toLocaleLowerCase().includes(query))
    : targetOptions.value
})
const defaultParticipantCount = computed(() => Math.min(12, participants.value.length))
const canPreview = computed(() => {
  if (!props.projectId || !form.participantIds.length) return false
  if (form.mode === "directed" && !form.instructions.trim() && !form.targets.length) return false
  if (form.runPolicy === "n_steps" && (!Number.isInteger(Number(form.steps)) || Number(form.steps) < 1)) return false
  if (form.runPolicy === "until_goal" && !form.targets.length) return false
  return [form.requestLimit, form.tokenLimit, form.timeBudgetMinutes].every((item) => Number.isInteger(Number(item)) && Number(item) > 0)
})
const canStart = computed(() => canPreview.value && budgetPreview.value && !previewLoading.value)

watch(() => props.projectId, () => {
  resetForProject()
  if (open.value) {
    loadInitial()
    loadHistory()
  }
})
watch(() => form.participantIds.length, () => {
  if (!budgetTouched) updateDefaultBudget()
})
watch(() => form.runPolicy, () => {
  if (!budgetTouched) updateDefaultBudget()
})
watch(() => form.steps, () => {
  if (!budgetTouched) updateDefaultBudget()
})

onBeforeUnmount(() => {
  generation += 1
  clearTimeout(pollTimer)
  clearTimeout(flowPollTimer)
})

function currentProject() {
  return String(getAppState()?.currentProjectId || props.projectId || "")
}

function owns(token, projectId) {
  return token === generation && String(props.projectId || "") === projectId && currentProject() === projectId
}

function toggleOpen() {
  open.value = !open.value
  if (open.value && !participants.value.length) loadInitial()
  if (open.value) {
    loadHistory()
    loadGuidedFlowAvailability()
  }
}

async function loadGuidedFlowAvailability() {
  const projectId = String(props.projectId || "")
  if (!projectId) return
  const token = generation
  try {
    const capabilities = await getApi().assistant.capabilities(projectId)
    if (!owns(token, projectId)) return
    flowAvailable.value = capabilities?.guided_flows?.available === true
    if (!flowAvailable.value) return
    const latest = await getApi().assistant.guidedFlowLatest(projectId, "world_progression_review")
    if (!owns(token, projectId)) return
    if (latest?.run_id && !["completed", "cancelled", "failed"].includes(latest.status)) {
      flowView.value = latest
      scheduleFlowPoll(token, projectId)
    }
  } catch (cause) {
    if (owns(token, projectId)) {
      flowAvailable.value = false
      flowError.value = cause?.message || "世界推进引导流程暂不可用。"
    }
  }
}

async function startGuidedFlow() {
  if (!flowAvailable.value || !budgetPreview.value || busy.value) return
  const projectId = String(props.projectId || "")
  const token = generation
  busy.value = true
  flowError.value = ""
  try {
    const input = {
      ...requestPayload(),
      scene_id: budgetPreview.value.scene_id,
      budget_preview_hash: budgetPreview.value.preview_hash,
    }
    const value = await getApi().assistant.guidedFlowStart({
      novel_id: projectId,
      flow_id: "world_progression_review",
      input,
    })
    if (!owns(token, projectId)) return
    flowView.value = value
    notice.value = "引导流程已开始；模型调用仍需独立确认预算。"
    scheduleFlowPoll(token, projectId)
  } catch (cause) {
    if (owns(token, projectId)) {
      flowError.value = Number(cause?.status) === 409
        ? "资料或预算已变化；当前表单仍保留，请重新预览。"
        : cause?.message || "引导流程未能开始；当前选择仍保留。"
    }
  } finally {
    if (owns(token, projectId)) busy.value = false
  }
}

function scheduleFlowPoll(token, projectId) {
  clearTimeout(flowPollTimer)
  if (!flowView.value || flowView.value.status !== "running") return
  flowPollTimer = setTimeout(async () => {
    if (!owns(token, projectId) || !flowView.value?.run_id) return
    await refreshGuidedFlow()
    if (owns(token, projectId)) scheduleFlowPoll(token, projectId)
  }, 1800)
}

async function refreshGuidedFlow() {
  if (!flowView.value?.run_id) return
  const projectId = String(props.projectId || "")
  const token = generation
  try {
    const value = await getApi().assistant.guidedFlow(projectId, flowView.value.run_id)
    if (!owns(token, projectId)) return
    flowView.value = value
  } catch (cause) {
    if (owns(token, projectId)) flowError.value = cause?.message || "引导流程刷新失败；已保存历史仍可查看。"
  }
}

async function runGuidedFlowAction(action) {
  if (!flowView.value?.run_id || busy.value) return
  const projectId = String(props.projectId || "")
  const token = generation
  const stepId = String(flowView.value.stop?.step_id || "")
  busy.value = true
  flowError.value = ""
  try {
    if (stepId === "confirm_reference") {
      const selection = flowView.value.panel?.selection || {}
      const participants = selection.participants || []
      const confirmation = await confirmAiReference({
        novel_id: projectId,
        action: "story.one_click.simulate",
        task: "按已选择的人物和群体资料做世界推进候选推演",
        scope: "scene",
        scene_id: selection.scene_id,
        visible_until_scene_id: selection.scene_id,
        character_ids: participants.filter((item) => item.kind === "character").map((item) => item.id),
        entity_ids: participants.filter((item) => item.kind === "group").map((item) => item.id),
        include_pending_objects: false,
        budget_tokens: 0,
      })
      if (!owns(token, projectId) || !confirmation?.id) return
      const next = await getApi().assistant.guidedFlowAdvance(flowView.value.run_id, {
        novel_id: projectId,
        context_confirmation_id: confirmation.id,
      })
      if (!owns(token, projectId)) return
      flowView.value = next
    } else if (stepId === "confirm_rolling_hook") {
      const selection = flowView.value.panel?.hook_selection || {}
      const confirmation = await confirmAiReference({
        novel_id: projectId,
        action: "outline.generate",
        task: "核对世界推进钩子的滚动规划范围",
        scope: "full",
        chapter_index: selection.start_chapter,
        start_chapter: selection.start_chapter,
        planning_window_end: selection.end_chapter,
        budget_tokens: 0,
        include_pending_objects: false,
      })
      if (!owns(token, projectId) || !confirmation?.id) return
      const next = await getApi().assistant.guidedFlowAdvance(flowView.value.run_id, {
        novel_id: projectId,
        context_confirmation_id: confirmation.id,
      })
      if (!owns(token, projectId)) return
      flowView.value = next
    } else {
      const choice = { step_id: stepId, action }
      if (["select_hook", "choose_another_hook"].includes(action)) {
        const hook = (flowView.value.panel?.hooks || []).find((item) => item.hook_id === flowHookSelection.hookId)
        if (!hook) throw new Error("请选择一条可用的剧情钩子。")
        const startChapter = Number(flowHookSelection.startChapter) || Number(hook.cutoff_chapter || 0) + 1
        const endChapter = Number(flowHookSelection.endChapter) || startChapter + (flowHookSelection.assetType === "planned_scene" ? 0 : 2)
        choice.selection = {
          hook_id: hook.hook_id,
          step_id: hook.step_id,
          asset_type: flowHookSelection.assetType,
          start_chapter: startChapter,
          end_chapter: endChapter,
        }
      }
      const next = await getApi().assistant.guidedFlowAdvance(flowView.value.run_id, {
        novel_id: projectId,
        choice,
      })
      if (!owns(token, projectId)) return
      flowView.value = next
    }
    if (!owns(token, projectId)) return
    if (flowView.value.status === "completed") notice.value = "世界推进复核已完成；已采用的只是可编辑大纲候选。"
    scheduleFlowPoll(token, projectId)
    if (flowView.value.status === "waiting_approval" && flowView.value.stop?.step_id === "review_hooks") {
      const available = flowView.value.panel?.hooks || []
      if (!available.some((item) => item.hook_id === flowHookSelection.hookId)) {
        flowHookSelection.hookId = available[0]?.hook_id || ""
      }
      syncFlowHookWindow()
    }
  } catch (cause) {
    if (owns(token, projectId)) {
      flowError.value = Number(cause?.status) === 409
        ? "流程依据已变化；请刷新后重新确认，当前选择仍保留。"
        : cause?.message || "引导流程操作失败；候选历史不会被覆盖。"
    }
  } finally {
    if (owns(token, projectId)) busy.value = false
  }
}

function syncFlowHookWindow() {
  const hook = (flowView.value?.panel?.hooks || []).find((item) => item.hook_id === flowHookSelection.hookId)
  if (!hook) return
  const start = Math.max(Number(hook.cutoff_chapter || 0) + 1, Number(hook.start_chapter || 0)) || 1
  flowHookSelection.startChapter = start
  flowHookSelection.endChapter = start + (flowHookSelection.assetType === "planned_scene" ? 0 : 2)
}

function resetForProject() {
  generation += 1
  clearTimeout(pollTimer)
  clearTimeout(flowPollTimer)
  activeTaskId = ""
  participants.value = []
  targetOptions.value = []
  budgetPreview.value = null
  history.value = { roots: [] }
  comparison.value = null
  compareSteps.first = ""
  compareSteps.second = ""
  compareRootId.value = ""
  flowView.value = null
  flowAvailable.value = false
  flowError.value = ""
  participantSearch.value = ""
  targetSearch.value = ""
  busy.value = false
  loading.value = false
  targetLoading.value = false
  previewLoading.value = false
  submitting.value = false
  historyLoading.value = false
  activeAuthorization.value = null
  activeAuthorizationRootId.value = ""
  taskProgress.value = null
  error.value = ""
  historyError.value = ""
  targetLoadError.value = ""
  notice.value = ""
  form.participantIds = []
  form.targets = []
  form.mode = "free"
  form.stepLength = "auto"
  form.runPolicy = "one_step"
  form.steps = 2
  form.instructions = ""
  form.retainedConstraintsText = ""
  form.requestLimit = 20
  form.tokenLimit = 60000
  form.timeBudgetMinutes = 30
  budgetTouched = false
  flowHookSelection.hookId = ""
  flowHookSelection.assetType = "plot_thread"
  flowHookSelection.startChapter = 1
  flowHookSelection.endChapter = 3
  for (const key of Object.keys(branchDrafts)) delete branchDrafts[key]
  for (const key of Object.keys(hookDrafts)) delete hookDrafts[key]
  for (const key of Object.keys(hookPreviews)) delete hookPreviews[key]
  for (const key of Object.keys(continuationBasis)) delete continuationBasis[key]
}

async function listAllPages(loader) {
  const items = []
  let skip = 0
  while (true) {
    const page = await loader(skip)
    const rows = Array.isArray(page?.items) ? page.items : Array.isArray(page) ? page : []
    items.push(...rows)
    const total = Number(page?.total)
    if (!rows.length || (Number.isFinite(total) && items.length >= total) || rows.length < 50) break
    skip += rows.length
  }
  return items
}

function identity(item) {
  return String(item?.character_id || item?.entity_id || item?.id || "")
}

function participantLabel(item) {
  return String(item?.name || item?.display_name || item?.title || "未命名对象")
}

function updateDefaultBudget() {
  const count = Math.max(1, form.participantIds.length)
  const steps = form.runPolicy === "n_steps" ? Math.max(1, Number(form.steps) || 1) : 1
  const calls = (count + 1) * steps
  form.requestLimit = Math.max(20, Math.ceil(calls / 0.8) + 3)
  form.tokenLimit = Math.max(60000, count * 5000 * steps)
  form.timeBudgetMinutes = Math.max(30, Math.ceil(calls * 0.5))
}

function onParticipantsChanged() {
  invalidatePreview()
  if (!budgetTouched) updateDefaultBudget()
}

function onBudgetInputsChanged() {
  budgetTouched = true
  invalidatePreview()
}

function onRunPolicyChanged() {
  invalidatePreview()
  if (!budgetTouched) updateDefaultBudget()
}

function invalidatePreview() {
  if (budgetPreview.value) budgetPreview.value = null
}

async function loadInitial() {
  const projectId = String(props.projectId || "")
  if (!projectId) return
  const token = ++generation
  loading.value = true
  error.value = ""
  targetLoadError.value = ""
  try {
    const api = getApi()
    const [characters, entities] = await Promise.all([
      listAllPages((skip) => api.world.listCharacters({ novel_id: projectId, skip, limit: 50 })),
      listAllPages((skip) => api.world.listEntities({
        novel_id: projectId,
        display_state: "active",
        view_mode: "normal",
        skip,
        limit: 50,
      })),
    ])
    if (!owns(token, projectId)) return
    const seen = new Set()
    participants.value = [
      ...characters.map((item) => ({ id: identity(item), kind: "character", name: participantLabel(item) })),
      ...entities
        .filter((item) => ["group", "organization"].includes(String(item?.entity_type || item?.type || "").toLowerCase()))
        .map((item) => ({ id: identity(item), kind: "group", name: participantLabel(item) })),
    ].filter((item) => item.id && !seen.has(item.id) && seen.add(item.id))
    form.participantIds = participants.value.slice(0, 12).map((item) => item.id)
    budgetTouched = false
    updateDefaultBudget()
    loadTargets(projectId, token)
  } catch (cause) {
    if (owns(token, projectId)) error.value = cause?.message || "参与者列表读取失败；可以重试。"
  } finally {
    if (owns(token, projectId)) loading.value = false
  }
}

async function loadTargets(projectId, parentToken = generation) {
  targetLoading.value = true
  targetLoadError.value = ""
  try {
    const api = getApi()
    const [arcs, threads, scenes] = await Promise.all([
      listAllPages((skip) => api.outline.listArcs(projectId, { skip, limit: 50, status: "active" })),
      listAllPages((skip) => api.outline.listThreads(projectId, { skip, limit: 50, status: "active" })),
      listAllPages((skip) => api.outline.listScenes(projectId, skip, 50)),
    ])
    if (!owns(parentToken, projectId)) return
    targetOptions.value = [
      ...arcs.filter((item) => item?.status !== "deprecated").map((item) => ({
        id: identity(item),
        kind: "outline_arc",
        kindLabel: "篇章",
        name: participantLabel(item),
        range: chapterRange(item),
      })),
      ...threads.filter((item) => item?.status !== "deprecated").map((item) => ({
        id: identity(item),
        kind: "plot_thread",
        kindLabel: "剧情线",
        name: participantLabel(item),
        range: chapterRange(item),
      })),
      ...scenes.filter((item) => item?.status !== "deprecated" && (item?.structure_meta || {}).planning_state === "planned").map((item) => ({
        id: identity(item),
        kind: "planned_scene",
        kindLabel: "计划场景",
        name: participantLabel(item),
        range: chapterRange(item),
      })),
    ].filter((item) => item.id)
  } catch (cause) {
    if (owns(parentToken, projectId)) targetLoadError.value = cause?.message || "目标节点读取失败。"
  } finally {
    if (owns(parentToken, projectId)) targetLoading.value = false
  }
}

function isTargetSelected(target) {
  return form.targets.some((item) => item.kind === target.kind && item.id === target.id)
}

function isMustReach(target) {
  return Boolean(form.targets.find((item) => item.kind === target.kind && item.id === target.id)?.must_reach)
}

function toggleTarget(target) {
  const existing = form.targets.findIndex((item) => item.kind === target.kind && item.id === target.id)
  if (existing >= 0) form.targets.splice(existing, 1)
  else form.targets.push({ kind: target.kind, id: target.id, must_reach: false })
  invalidatePreview()
}

function toggleMustReach(target) {
  const selected = form.targets.find((item) => item.kind === target.kind && item.id === target.id)
  if (!selected) return
  selected.must_reach = !selected.must_reach
  invalidatePreview()
}

function requestPayload() {
  const payload = {
    scene_id: null,
    participants: selectedParticipants.value.map(({ id, kind }) => ({ id, kind })),
    mode: form.mode,
    step_length: form.stepLength,
    run_policy: form.runPolicy,
    steps: form.runPolicy === "n_steps" ? Number(form.steps) : null,
    stop_at_goal: Boolean(form.stopAtGoal),
    targets: form.targets.map((item) => ({ ...item })),
    instructions: form.instructions.trim(),
    retained_constraints: form.retainedConstraintsText.split(/\n+/).map((item) => item.trim()).filter(Boolean),
    request_limit: Number(form.requestLimit),
    token_limit: Number(form.tokenLimit),
    time_budget_seconds: Number(form.timeBudgetMinutes) * 60,
  }
  return payload
}

async function previewBudget() {
  if (!canPreview.value || previewLoading.value) return
  const projectId = String(props.projectId)
  const token = generation
  previewLoading.value = true
  busy.value = true
  error.value = ""
  notice.value = ""
  try {
    const result = await getApi().story.previewWorldProgressionBudget(projectId, requestPayload())
    if (!owns(token, projectId)) return
    budgetPreview.value = result
    notice.value = "预览只读取当前资料，没有调用模型或写入候选历史。"
  } catch (cause) {
    if (owns(token, projectId)) {
      error.value = Number(cause?.status) === 409
        ? "当前资料或配置已变化。作者输入仍保留，请重新读取资料后重新预览。"
        : cause?.message || "预算预览失败；当前输入仍保留。"
    }
  } finally {
    if (owns(token, projectId)) {
      previewLoading.value = false
      busy.value = false
    }
  }
}

async function startRun() {
  if (!canStart.value || submitting.value) return
  const projectId = String(props.projectId)
  const token = generation
  submitting.value = true
  busy.value = true
  error.value = ""
  notice.value = ""
  try {
    const payload = requestPayload()
    const confirmation = await confirmAiReference({
      novel_id: projectId,
      action: "story.one_click.simulate",
      task: "按人物各自可知的资料进行世界推进候选推演",
      scope: "scene",
      scene_id: budgetPreview.value.scene_id,
      visible_until_scene_id: budgetPreview.value.scene_id,
      character_ids: payload.participants.filter((item) => item.kind === "character").map((item) => item.id),
      entity_ids: payload.participants.filter((item) => item.kind === "group").map((item) => item.id),
      include_pending_objects: false,
      budget_tokens: 0,
      user_note: form.mode === "directed" ? form.instructions : "",
    })
    if (!owns(token, projectId)) return
    const operationId = createOperationId()
    const result = await getApi().story.startWorldProgression(projectId, {
      ...payload,
      scene_id: budgetPreview.value.scene_id,
      context_confirmation_id: confirmation.id,
      budget_preview_hash: budgetPreview.value.preview_hash,
      operation_id: operationId,
    })
    if (!owns(token, projectId)) return
    if (!result?.task_id || !result?.root_id) throw new Error("世界推进任务未能开始；请刷新历史后核对状态。")
    activeTaskId = result.task_id
    notice.value = "世界推进已提交；结果仍是候选，不会写入正史。"
    budgetPreview.value = null
    startPolling(result.task_id, projectId, token)
  } catch (cause) {
    if (owns(token, projectId)) {
      error.value = Number(cause?.status) === 409
        ? "资料、预算或历史依据已变化。输入仍保留，请重新预览后再试。"
        : cause?.message || "提交失败；输入仍保留。若状态不确定，请先刷新历史。"
      if (Number(cause?.status) === 409) budgetPreview.value = null
    }
  } finally {
    if (owns(token, projectId)) {
      submitting.value = false
      busy.value = false
    }
  }
}

function startPolling(taskId, projectId, token) {
  clearTimeout(pollTimer)
  taskProgress.value = { status: "pending", terminal: false, message: "等待世界推进开始…" }
  const poll = async () => {
    if (!owns(token, projectId) || activeTaskId !== taskId) return
    try {
      const task = await getApi().tasks.get(taskId, projectId)
      if (!owns(token, projectId) || activeTaskId !== taskId) return
      const status = String(task?.status || "unknown")
      taskProgress.value = {
        status,
        terminal: !["pending", "running", "queued"].includes(status),
        message: status === "running" ? "正在按角色可知资料推演…" : status === "queued" ? "正在排队…" : status === "done" ? "候选步骤已保存。" : status === "failed" ? task?.error_message || "推演失败；请查看已保存历史。" : "任务状态暂不可用。",
        result: task?.result || null,
      }
      if (["pending", "running", "queued"].includes(status)) {
        pollTimer = setTimeout(poll, 1800)
      } else {
        activeTaskId = ""
        await loadHistory()
      }
    } catch (cause) {
      if (!owns(token, projectId) || activeTaskId !== taskId) return
      taskProgress.value = {
        status: "unknown",
        terminal: false,
        message: cause?.message || "任务状态查询失败；历史仍可刷新核对。",
      }
      pollTimer = setTimeout(poll, 6000)
    }
  }
  poll()
}

async function loadHistory() {
  const projectId = String(props.projectId || "")
  if (!projectId) return
  const token = generation
  historyLoading.value = true
  historyError.value = ""
  try {
    const value = await getApi().story.worldProgressionHistory(projectId, { include_deleted: true })
    if (!owns(token, projectId)) return
    history.value = value || { roots: [] }
    for (const root of history.value.roots || []) {
      for (const branch of root.branches || []) {
        if (!branchDrafts[branch.id]) branchDrafts[branch.id] = { name: branch.name || "", note: branch.note || "" }
        for (const step of branch.steps || []) {
          if (!continuationBasis[step.id]) continuationBasis[step.id] = "current"
          for (const hook of step.result?.plot_hooks || []) {
            if (!hookDrafts[hook.hook_id]) hookDrafts[hook.hook_id] = {
              assetType: "plot_thread",
              startChapter: hook.start_chapter || null,
              endChapter: hook.end_chapter || null,
              title: hook.title || "",
              summary: hook.summary || "",
              operationId: "",
              confirmationId: "",
            }
          }
        }
      }
    }
    await readAuthorizationForLatestRoot(token, projectId)
  } catch (cause) {
    if (owns(token, projectId)) historyError.value = cause?.message || "推进历史读取失败。"
  } finally {
    if (owns(token, projectId)) historyLoading.value = false
  }
}

async function readAuthorizationForLatestRoot(token, projectId) {
  const root = (history.value.roots || []).find((item) => item.branches?.length)
  if (!root) {
    activeAuthorization.value = null
    activeAuthorizationRootId.value = ""
    return
  }
  try {
    const branch = root.branches[0]
    const auth = await getApi().story.readWorldProgressionContinuousAuthorization(projectId, root.id, branch.id)
    if (!owns(token, projectId)) return
    activeAuthorization.value = auth
    activeAuthorizationRootId.value = root.id
    continuousDraft.participantIds = [...(auth?.participant_ids || [])]
    continuousDraft.everyNewChapters = Number(auth?.every_new_chapters || 3)
  } catch (cause) {
    if (owns(token, projectId)) historyError.value = cause?.message || "持续授权状态读取失败。"
  }
}

async function continueFromStep(root, branch, step) {
  if (busy.value || branch.deleted_at) return
  const projectId = String(props.projectId)
  const token = generation
  error.value = ""
  notice.value = ""
  busy.value = true
  try {
    const selection = root.request?.participants || []
    const confirmation = await confirmAiReference({
      novel_id: projectId,
      action: "story.one_click.simulate",
      task: "沿现有世界推进预算继续一步",
      scope: "scene",
      scene_id: root.scene_id,
      visible_until_scene_id: root.scene_id,
      character_ids: selection.filter((item) => item.kind === "character").map((item) => item.id),
      entity_ids: selection.filter((item) => item.kind === "group").map((item) => item.id),
      include_pending_objects: false,
      budget_tokens: 0,
    })
    if (!owns(token, projectId)) return
    const result = await getApi().story.advanceWorldProgression(root.id, {
      novel_id: projectId,
      root_id: root.id,
      branch_id: branch.id,
      parent_step_id: step.id,
      basis_choice: continuationBasis[step.id] || "current",
      context_confirmation_id: confirmation.id,
      operation_id: createOperationId(),
    })
    if (!owns(token, projectId)) return
    if (!result?.task_id) throw new Error("续跑未提交；请先刷新历史核对状态。")
    activeTaskId = result.task_id
    notice.value = "续跑已提交；请求仍计入原预算根。"
    startPolling(result.task_id, projectId, token)
  } catch (cause) {
    if (owns(token, projectId)) {
      error.value = Number(cause?.status) === 409
        ? "原预算、资料依据或分支状态已变化。选择仍保留，请刷新历史后再决定。"
        : cause?.message || "续跑失败；历史不会被覆盖。"
    }
  } finally {
    if (owns(token, projectId)) busy.value = false
  }
}

async function resumeBranch(root, branch) {
  if (busy.value || branch.deleted_at || !branch.resume_hash) return
  const projectId = String(props.projectId)
  const token = generation
  const unknown = Number(root.budget?.unknown_requests || 0)
  const message = `沿原运行和原分支恢复已保存的半步？原根已用 ${root.budget?.requests_used || 0}/${root.budget?.requests_authorized || 0} 次请求、${root.budget?.tokens_used || 0}/${root.budget?.tokens_authorized || 0} Token，原时限至 ${dateLabel(root.budget?.deadline_at)}。${unknown ? `当前有 ${unknown} 个计费结果未知；确认可能重复计费后，仅确认这 ${unknown} 个，后来新增未知仍会暂停。` : "不会增加或重置预算。"}`
  if (!getConfirm()(message)) return
  busy.value = true
  error.value = ""
  notice.value = ""
  try {
    const selection = branch.request?.participants || root.request?.participants || []
    const sceneId = branch.request?.scene_id || root.scene_id
    const confirmation = await confirmAiReference({
      novel_id: projectId,
      action: "story.one_click.simulate",
      task: "确认恢复已保存的世界推进半步与原根预算",
      scope: "scene",
      scene_id: sceneId,
      visible_until_scene_id: sceneId,
      character_ids: selection.filter((item) => item.kind === "character").map((item) => item.id),
      entity_ids: selection.filter((item) => item.kind === "group").map((item) => item.id),
      include_pending_objects: false,
      budget_tokens: 0,
    })
    if (!owns(token, projectId) || !confirmation?.id) return
    const result = await getApi().story.resumeWorldProgression(root.id, branch.id, {
      novel_id: projectId,
      root_id: root.id,
      branch_id: branch.id,
      operation_id: createOperationId(),
      context_confirmation_id: confirmation.id,
      resume_hash: branch.resume_hash,
      acknowledge_unknown_requests: unknown,
      allow_possible_duplicate_charge: unknown > 0,
    })
    if (!owns(token, projectId)) return
    if (!result?.task_id) throw new Error("恢复未提交；请刷新历史核对状态。")
    activeTaskId = result.task_id
    notice.value = "已沿原分支恢复；用量继续计入原预算。"
    startPolling(result.task_id, projectId, token)
  } catch (cause) {
    if (owns(token, projectId)) {
      error.value = Number(cause?.status) === 409
        ? "预算、来源或任务状态已变化。原半步仍保留，请刷新历史后重新确认。"
        : cause?.message || "恢复失败；已保存的半步仍保留。"
    }
  } finally {
    if (owns(token, projectId)) busy.value = false
  }
}

function selectCompareStep(step) {
  const root = findRootForStep(step.id)
  if (!root) return
  if (!compareSteps.first || compareRootId.value !== root.id || compareSteps.first === step.id) {
    compareRootId.value = root.id
    compareSteps.first = step.id
    compareSteps.second = ""
    comparison.value = null
    return
  }
  compareSteps.second = step.id
  compareSelectedSteps()
}

async function compareSelectedSteps() {
  const root = findRootForStep(compareSteps.first)
  if (!root || !compareSteps.second) return
  const projectId = String(props.projectId || "")
  const token = generation
  busy.value = true
  error.value = ""
  try {
    const result = await getApi().story.compareWorldProgressionSteps(
      projectId, compareSteps.first, compareSteps.second,
    )
    if (!owns(token, projectId)) return
    comparison.value = result
  } catch (cause) {
    if (owns(token, projectId)) error.value = cause?.message || "无法比较所选步骤。"
  } finally {
    if (owns(token, projectId)) busy.value = false
  }
}

function findRootForStep(stepId) {
  return (history.value.roots || []).find((root) => (root.branches || []).some((branch) => (branch.steps || []).some((step) => step.id === stepId))) || null
}

async function saveBranch(branch, changes) {
  if (!branch.updated_at) {
    error.value = "历史版本标识不可用，请刷新后再保存。"
    return
  }
  const projectId = String(props.projectId || "")
  const token = generation
  busy.value = true
  error.value = ""
  try {
    await getApi().story.updateWorldProgressionBranch(branch.id, {
      novel_id: projectId,
      ...changes,
      expected_updated_at: branch.updated_at,
    })
    if (!owns(token, projectId)) return
    notice.value = "作者备注已保存；不会写入推演事实。"
    await loadHistory()
  } catch (cause) {
    if (owns(token, projectId)) {
      error.value = Number(cause?.status) === 409
        ? "这条历史已被修改。你的输入仍保留，请刷新后再保存。"
        : cause?.message || "历史备注保存失败。"
    }
  } finally {
    if (owns(token, projectId)) busy.value = false
  }
}

async function deleteBranch(branch) {
  if (!getConfirm()("将此分支移入 30 天恢复区？不可变步骤会保留，AI 不提供删除入口。")) return
  const projectId = String(props.projectId || "")
  const token = generation
  busy.value = true
  error.value = ""
  try {
    await getApi().story.deleteWorldProgressionBranch(branch.id, { novel_id: projectId, confirm: true })
    if (!owns(token, projectId)) return
    notice.value = "分支已移入恢复区，可在 30 天内恢复。"
    await loadHistory()
  } catch (cause) {
    if (owns(token, projectId)) error.value = cause?.message || "分支删除失败。"
  } finally {
    if (owns(token, projectId)) busy.value = false
  }
}

async function restoreBranch(branch) {
  const projectId = String(props.projectId || "")
  const token = generation
  busy.value = true
  error.value = ""
  try {
    await getApi().story.restoreWorldProgressionBranch(branch.id, { novel_id: projectId, confirm: true })
    if (!owns(token, projectId)) return
    notice.value = "分支已恢复。"
    await loadHistory()
  } catch (cause) {
    if (owns(token, projectId)) error.value = cause?.message || "分支恢复失败。"
  } finally {
    if (owns(token, projectId)) busy.value = false
  }
}

function hookRequest(root, step, hook) {
  const draft = hookDrafts[hook.hook_id]
  const content = draft.assetType === "plot_thread"
    ? {
        name: draft.title,
        thread_type: "world_progression",
        summary: draft.summary,
        visible_goal: draft.summary,
        hidden_truth: "",
        start_chapter: draft.startChapter,
        planned_payoff_chapter: draft.endChapter,
      }
    : draft.assetType === "outline_arc"
      ? {
          title: draft.title,
          start_chapter: draft.startChapter,
          end_chapter: draft.endChapter,
          arc_goal: draft.summary,
        }
      : {
          scene_index: 0,
          title: draft.title,
          goal: draft.summary,
          narrative_tag: "hook",
          source: "world_progression",
          chapter_ids: [],
          pov_character_id: null,
          structure_meta: {
            planning_state: "planned",
            planned_chapter_range: {
              start: draft.startChapter,
              end: draft.endChapter,
            },
            progression_related_actor_ids: hook.actor_ids || [],
          },
        }
  return {
    novel_id: String(props.projectId),
    root_id: root.id,
    step_id: step.id,
    hook_id: hook.hook_id,
    asset_type: draft.assetType,
    operation_id: draft.operationId || createOperationId(),
    context_confirmation_id: draft.confirmationId,
    start_chapter: draft.startChapter,
    end_chapter: draft.endChapter,
    draft: content,
  }
}

async function previewHook(root, step, hook) {
  const projectId = String(props.projectId)
  const token = generation
  const draft = hookDrafts[hook.hook_id]
  hookLoadingId.value = hook.hook_id
  busy.value = true
  error.value = ""
  try {
    const confirmation = await confirmAiReference({
      novel_id: projectId,
      action: "outline.generate",
      task: "核对世界推进钩子的滚动规划范围",
      scope: "full",
      start_chapter: draft.startChapter || hook.start_chapter || 1,
      planning_window_end: draft.endChapter || hook.end_chapter || draft.startChapter || 1,
      budget_tokens: 0,
      include_pending_objects: false,
      user_note: "只核对采用来源与计划窗口，不生成内容。",
    })
    if (!owns(token, projectId)) return
    draft.operationId = createOperationId()
    draft.confirmationId = confirmation.id
    const result = await getApi().story.previewWorldProgressionHook(hookRequest(root, step, hook))
    if (!owns(token, projectId)) return
    hookPreviews[hook.hook_id] = result
    notice.value = "钩子预览只读完成；确认采用后才会创建可编辑的大纲候选。"
  } catch (cause) {
    if (owns(token, projectId)) error.value = Number(cause?.status) === 409
      ? "钩子来源已变化。草稿仍保留，请重新核对滚动窗口。"
      : cause?.message || "钩子预览失败；草稿仍保留。"
  } finally {
    if (owns(token, projectId)) {
      hookLoadingId.value = ""
      busy.value = false
    }
  }
}

async function adoptHook(root, step, hook) {
  const preview = hookPreviews[hook.hook_id]
  if (!preview || !getConfirm()("采用这条钩子为可编辑大纲候选？系统会重验滚动来源；不会写入世界设定或正文。")) return
  const projectId = String(props.projectId || "")
  const token = generation
  busy.value = true
  error.value = ""
  try {
    const result = await getApi().story.adoptWorldProgressionHook({
      ...hookRequest(root, step, hook),
      preview_hash: preview.preview_hash,
    })
    if (!owns(token, projectId)) return
    notice.value = `已采用为${assetTypeLabel(result.asset_type)}候选；你可以在对应大纲页继续编辑。`
    delete hookPreviews[hook.hook_id]
    await loadHistory()
  } catch (cause) {
    if (owns(token, projectId)) {
      error.value = Number(cause?.status) === 409
        ? "采用预览已过期，钩子草稿仍保留。请重新预览后再确认。"
        : cause?.message || "采用失败；原推演历史保持不变。"
    }
  } finally {
    if (owns(token, projectId)) busy.value = false
  }
}

function participantsForRoot(root) {
  return (root.request?.participants || []).map((item) => ({
    id: item.id,
    kind: item.kind || "character",
    name: actorName(item.id),
  }))
}

function authorizationFor(root) {
  return activeAuthorizationRootId.value === root.id ? activeAuthorization.value : null
}

async function setContinuous(root, branch, enabled) {
  const projectId = String(props.projectId)
  const token = generation
  busy.value = true
  error.value = ""
  try {
    let contextConfirmationId = null
    if (enabled) {
      const selection = participantsForRoot(root).filter((item) => continuousDraft.participantIds.includes(item.id))
      const confirmation = await confirmAiReference({
        novel_id: projectId,
        action: "story.one_click.simulate",
        task: "授权在原世界推进预算内生成轻量自由候选",
        scope: "scene",
        scene_id: root.scene_id,
        visible_until_scene_id: root.scene_id,
        character_ids: selection.filter((item) => item.kind === "character").map((item) => item.id),
        entity_ids: selection.filter((item) => item.kind === "group").map((item) => item.id),
        include_pending_objects: false,
        budget_tokens: 0,
      })
      if (!owns(token, projectId)) return
      contextConfirmationId = confirmation.id
    }
    const result = await getApi().story.setWorldProgressionContinuousAuthorization(root.id, branch.id, {
      novel_id: projectId,
      enabled,
      participant_ids: enabled ? [...continuousDraft.participantIds] : [],
      every_new_chapters: Number(continuousDraft.everyNewChapters),
      context_confirmation_id: contextConfirmationId,
      expected_revision: authorizationFor(root)?.revision ?? 0,
    })
    if (!owns(token, projectId)) return
    activeAuthorization.value = result
    activeAuthorizationRootId.value = root.id
    continuousDraft.participantIds = [...(result.participant_ids || [])]
    notice.value = enabled ? "持续授权已开启；只使用原根剩余预算。" : "持续授权已关闭。"
  } catch (cause) {
    if (owns(token, projectId)) {
      error.value = Number(cause?.status) === 409
        ? "持续授权状态或原预算已变化。页面仍保留你的选择，请刷新后重新确认。"
        : cause?.message || "持续授权设置失败。"
    }
  } finally {
    if (owns(token, projectId)) busy.value = false
  }
}

function characterActors(actorIds) {
  const characterIds = new Set(participants.value.filter((item) => item.kind === "character").map((item) => item.id))
  return actorIds.filter((id) => characterIds.has(id))
}

function openDirectorDraft(root, step, intersection) {
  const actorIds = characterActors(intersection.actor_ids || [])
  if (!actorIds.length) {
    error.value = "这次交汇只有群体参与者；场景导演目前需要至少一位人物。"
    return
  }
  const assumptions = (step.result?.intersection_outcomes || []).find((item) => item.intersection_id === intersection.intersection_id)?.description || step.result?.narrative_summary || ""
  const candidate = `作者选择的世界推进交汇起点（候选假设，不代表已发生事实）：${assumptions}\n\n保留参考路径：${(step.result?.target_paths || []).map((item) => item.rationale).join("；") || "暂无目标路径"}`
  directorDraft.key = `${root.id}:${step.id}:${intersection.intersection_id}`
  directorDraft.rootId = root.id
  directorDraft.sceneId = root.scene_id
  directorDraft.characterIds = actorIds
  directorDraft.relatedObjectIds = (intersection.actor_ids || []).filter((id) => !actorIds.includes(id))
  directorDraft.intervention = candidate.slice(0, 3000)
  directorDraft.preview = null
  notice.value = "已准备显式导演起点假设。它会作为导演层 intervention 传入，不会写成场景事实。"
}

async function previewDirectorStart() {
  if (!directorDraft.sceneId || !directorDraft.characterIds.length || directorDraft.busy) return
  const projectId = String(props.projectId)
  const token = generation
  directorDraft.busy = true
  error.value = ""
  try {
    const operationId = createOperationId()
    const preview = await getApi().story.previewSceneDirectorBudget(projectId, {
      operation_id: operationId,
      scene_id: directorDraft.sceneId,
      character_ids: [...directorDraft.characterIds],
      primary_character_ids: [...directorDraft.characterIds],
      related_object_ids: [...directorDraft.relatedObjectIds],
      rounds: 1,
      instructions: "从作者选择的世界推进交汇候选开始一轮场景导演排演。",
      intervention: directorDraft.intervention,
      public_stimulus: "",
    })
    if (!owns(token, projectId)) return
    directorDraft.preview = { ...preview, operationId }
  } catch (cause) {
    if (owns(token, projectId)) error.value = cause?.message || "场景导演预算预览失败。"
  } finally {
    if (owns(token, projectId)) directorDraft.busy = false
  }
}

async function startDirectorFromIntersection() {
  if (!directorDraft.preview || directorDraft.busy) return
  const projectId = String(props.projectId)
  const token = generation
  directorDraft.busy = true
  error.value = ""
  try {
    const confirmation = await confirmAiReference({
      novel_id: projectId,
      action: "story.one_click.simulate",
      task: "将作者选定的世界推进交汇作为场景导演候选起点",
      scope: "scene",
      scene_id: directorDraft.sceneId,
      visible_until_scene_id: directorDraft.sceneId,
      character_ids: [...directorDraft.characterIds],
      entity_ids: [...directorDraft.relatedObjectIds],
      include_pending_objects: false,
      budget_tokens: 0,
      user_note: directorDraft.intervention,
    })
    if (!owns(token, projectId)) return
    const result = await getApi().story.startSceneDirector(projectId, directorDraft.sceneId, {
      operation_id: directorDraft.preview.operationId,
      scene_id: directorDraft.sceneId,
      character_ids: [...directorDraft.characterIds],
      primary_character_ids: [...directorDraft.characterIds],
      related_object_ids: [...directorDraft.relatedObjectIds],
      rounds: 1,
      request_limit: Number(directorDraft.requestLimit),
      token_limit: Number(directorDraft.tokenLimit),
      time_budget_seconds: Number(directorDraft.timeBudgetMinutes) * 60,
      instructions: "从作者明确选择的世界推进候选交汇起点进行排演。",
      divergence: "balanced",
      intervention: directorDraft.intervention,
      context_confirmation_id: confirmation.id,
      budget_preview_hash: directorDraft.preview.preview_hash,
      public_stimulus: "",
    })
    if (!owns(token, projectId)) return
    activeTaskId = result.task_id
    taskProgress.value = { status: "pending", terminal: false, message: "场景导演候选已提交…" }
    startPolling(result.task_id, projectId, token)
    directorDraft.preview = null
    notice.value = "场景导演已收到显式候选假设；推演结果仍需作者审阅。"
  } catch (cause) {
    if (owns(token, projectId)) error.value = Number(cause?.status) === 409
      ? "导演资料或预算依据已变化；候选假设仍保留，请重新预览。"
      : cause?.message || "场景导演提交失败；请刷新导演历史核对。"
  } finally {
    if (owns(token, projectId)) directorDraft.busy = false
  }
}

function actorName(id) {
  return participants.value.find((item) => item.id === String(id))?.name || "未命名参与者"
}

function actorNames(ids) {
  return (ids || []).map(actorName).join("、")
}

function targetName(id) {
  return targetOptions.value.find((item) => item.id === String(id))?.name || "已选目标节点"
}

function sceneTitle(id) {
  const scene = targetOptions.value.find((item) => item.id === String(id) && item.kind === "planned_scene")
  return scene?.name || "最近已写到的场景"
}

function intersectionKinds(kinds) {
  const labels = {
    same_location_target: "同一地点目标",
    same_target_object: "同一目标对象",
    same_resource_key: "争用同一资源",
    shared_existing_route: "引用同一条既有路线",
    information_recipient: "信息接收者交汇",
  }
  return (kinds || []).map((item) => labels[item] || "结构交汇").join("、")
}

function intersectionOutcome(step, intersectionId) {
  return (step.result?.intersection_outcomes || []).find((item) => item.intersection_id === intersectionId) || null
}

function hasCandidateUpdates(result) {
  return [
    "candidate_status_updates",
    "candidate_attitude_updates",
    "candidate_resource_updates",
    "candidate_knowledge_updates",
  ].some((key) => result?.[key]?.length)
}

function statusFieldLabel(value) {
  return ({ condition: "状态", goal: "目标", commitment: "承诺", presence: "在场" })[value] || "状态"
}

function intentOutcomeLabel(step, intentId) {
  const outcome = (step.result?.intent_outcomes || []).find((item) => item.intent_id === intentId)?.outcome
  return "结算：" + (({ succeeded: "成功", failed: "未成功", uncertain: "未定" })[outcome] || "未定")
}

function movementStatusLabel(check) {
  if (check.status === "already_at_destination") return "已由精确当前位置核对为目的地。"
  if (check.status === "route_evidence_available") {
    return "存在角色可见的 typed 路线、时长与截止时间依据；结果仍由模型按时间和条件裁决，不代表已成功。"
  }
  return "移动可行性未能核实，结算保持未定。"
}

function validityTargetLabel(target = {}) {
  if (target.map_item_id) return "当前地图声明"
  if (target.relation_id) return "World 关系声明"
  if (target.entity_id) return "World 对象档案"
  return "结构化对象声明"
}

function validityDecisionLabel(value) {
  return ({
    author_priority: "按作者声明有效期处理",
    story_override: "按同一声明的精确 Story 状态处理",
    gap: "精确对应关系待核，不当作已验证",
  })[value] || "决定不可用，保留为未核实"
}

function sourceGapLabel(value) {
  const gap = String(value || "")
  if (gap === "exact_cutoff_time_fact_missing") return "没有精确的作者时间事实；涉及行程的结果不能确认。"
  if (gap === "author_evidence_coverage_incomplete") return "作者资料覆盖不完整，裁决只把当前证据作为有限依据。"
  if (gap.startsWith("object_validity_notice_limit_reached")) return "有效期核对达到读取上限，仍可能有对象没有核对。"
  if (gap.startsWith("map_validity_gap") || gap.startsWith("map_validity_override_unreadable")) return "一项地图声明缺少精确 Story 对应事实，路线保持未核实。"
  if (gap.startsWith("spatial_validity")) return "一项地图有效期锚点不可解析，相关路线未计入可用路线。"
  if (gap.startsWith("journey_type_unavailable")) return "一项路线的类型依据不可用，未作为可行路线提供。"
  if (gap.startsWith("journey_source") || gap.startsWith("journey_endpoint")) return "一项路线的来源或端点核验不完整，未作为可行路线提供。"
  if (gap.startsWith("life_state_unknown")) return "至少一位参与者没有唯一精确的生死状态事实，未作判断。"
  if (gap.startsWith("map_document")) return "一份当前地图结构无法读取，路线比较不完整。"
  return "部分结构化资料缺口已披露；对应判断保留为未核实。"
}

function knowledgeModalityLabel(value) {
  return ({ reported_claim: "听到一条说法", direct_observation: "观察到", uncertain: "不确定地得知" })[value] || "得知"
}

function referenceLabel(value) {
  const raw = String(value || "")
  if (!raw) return "未记录"
  const id = raw.includes(":") ? raw.slice(raw.lastIndexOf(":") + 1) : raw
  const name = actorName(id)
  if (name !== "未命名参与者") return name
  const target = targetName(id)
  if (target !== "已选目标节点") return target
  return raw.startsWith("map_node:") ? "已核验地图节点" : "相关对象"
}

function stateDeltaText(patch) {
  const subject = referenceLabel(patch.key)
  if (patch.kind === "location") return `${subject} 的位置：${referenceLabel(patch.before)} → ${referenceLabel(patch.after)}`
  if (patch.kind === "departed") return `${subject} 的离场状态：${patch.before ? "离场" : "未记录离场"} → ${patch.after ? "离场" : "在场"}`
  if (patch.kind === "resource_holder") return `结构化资源持有者：${referenceLabel(patch.before)} → ${referenceLabel(patch.after)}`
  if (patch.kind === "observation") return `${subject} 新增一条可见观察记录`
  if (patch.kind === "belief") return `${subject} 的候选信念更新`
  return "一项结构化候选状态已变化"
}

function branchLabel(branch) {
  return branch.branch_kind === "start" ? "初始分支" : branchKindLabel(branch.branch_kind)
}

function branchKindLabel(kind) {
  return ({ start: "初始运行", continue: "作者续跑", continuous_light_step: "持续授权轻量一步" })[kind] || "历史分支"
}

function statusLabel(value) {
  return ({ queued: "排队中", running: "运行中", ready: "可继续", complete: "已完成", paused_budget: "预算暂停", paused_unknown: "用量未知，已暂停", failed: "失败", deleted: "已删除" })[value] || "待核对"
}

function basisLabel(value, note) {
  const label = ({ unchanged: "当前依据一致", same: "当前依据一致", changed: "依据已变化", unknown: "依据暂不可核实", not_checked: "尚未核对当前依据" })[value] || "依据状态待核对"
  return note ? `${label} · ${note}` : label
}

function goalStatusLabel(value) {
  return ({ completed: "已完成", blocked: "受阻", in_progress: "进行中", uncertain: "未定" })[value] || "待核对"
}

function recommendationText(value) {
  if (!value || value.status === "insufficient_data") return value?.message || "该模型的持久化步数不足，暂不推荐。"
  return `根据 ${value.sample_count} 个已保存步数，当前建议“${stepLengthLabel(value.step_length)}”。`
}

function stepLengthLabel(value) {
  return ({ auto: "自动", day: "一天", week: "一周", month: "一个月", season: "一季", year: "一年", next_beat: "下一个关键节拍" })[value] || "自动"
}

function assetTypeLabel(value) {
  return ({ plot_thread: "剧情线", outline_arc: "篇章", scene: "计划场景", planned_scene: "计划场景" })[value] || "大纲"
}

function chapterRange(value) {
  if (value?.start_chapter == null && value?.start == null) return ""
  const start = value.start_chapter ?? value.start
  const end = value.end_chapter ?? value.end ?? start
  return `第 ${start}–${end} 章`
}

function dateLabel(value) {
  if (!value) return "时间待定"
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? "时间待定" : date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })
}

function formatNumber(value) {
  const number = Number(value)
  return Number.isFinite(number) ? new Intl.NumberFormat("zh-CN").format(number) : "—"
}
</script>

<style scoped>
.world-progression { max-width: 1120px; margin: 20px auto 26px; border: 1px solid var(--border); border-radius: 14px; background: var(--bg-panel); box-shadow: 0 8px 28px color-mix(in srgb, var(--text-primary) 5%, transparent); }
.world-progression__header { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 20px clamp(16px, 2.4vw, 28px); }
.world-progression__heading { min-width: 0; }
.world-progression__eyebrow { margin: 0 0 4px; color: var(--accent); font-size: var(--text-xs); font-weight: 750; letter-spacing: .08em; text-transform: uppercase; }
.world-progression__heading h2 { margin: 0; font-size: clamp(20px, 2vw, 26px); letter-spacing: -.025em; }
.world-progression__heading p { margin: 6px 0 0; color: var(--text-secondary); }
.world-progression__body { padding: 0 clamp(16px, 2.4vw, 28px) 24px; }
.world-progression__section { margin-top: 18px; padding-top: 18px; border-top: 1px solid var(--border); }
.world-progression__section-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.world-progression__section-heading > div { display: flex; align-items: center; gap: 9px; min-width: 0; }
.world-progression__section-heading h3 { margin: 0; font-size: 17px; }
.world-progression__step { display: inline-grid; width: 26px; height: 26px; place-items: center; border-radius: 50%; background: var(--accent-soft); color: var(--accent); font-size: 12px; font-weight: 800; }
.world-progression__tag { flex: 0 0 auto; padding: 4px 9px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); font-size: 12px; font-weight: 700; }
.world-progression__help, .world-progression__selection-count { color: var(--text-secondary); font-size: var(--text-sm); }
.world-progression__search { display: block; max-width: 360px; margin: 10px 0; }
.world-progression__search input, .world-progression input:not([type="checkbox"]), .world-progression select, .world-progression textarea { width: 100%; min-height: 40px; padding: 9px 11px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg); color: var(--text-primary); font: inherit; }
.world-progression textarea { min-height: 72px; resize: vertical; }
.world-progression input:focus-visible, .world-progression select:focus-visible, .world-progression textarea:focus-visible, .world-progression button:focus-visible, .world-progression summary:focus-visible { outline: 3px solid color-mix(in srgb, var(--accent) 45%, transparent); outline-offset: 2px; }
.world-progression__participants { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 210px), 1fr)); gap: 8px; margin: 12px 0 0; padding: 0; border: 0; }
.world-progression__participant { display: flex; align-items: center; gap: 10px; min-height: 48px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 9px; cursor: pointer; }
.world-progression__participant:has(input:checked) { border-color: var(--accent); background: var(--accent-soft); }
.world-progression__participant input, .world-progression__target input { width: 18px; height: 18px; flex: 0 0 auto; accent-color: var(--accent); }
.world-progression__participant-copy { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; width: 100%; min-width: 0; }
.world-progression__participant-copy strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.world-progression__participant-copy small, .world-progression__target small { color: var(--text-tertiary); }
.world-progression__selection-count { margin: 8px 0 0; }
.world-progression__field-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 12px 0; }
.world-progression__field-grid--three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.world-progression__field-grid label, .world-progression__field, .world-progression__branch-meta label, .world-progression__interval { display: grid; gap: 6px; min-width: 0; color: var(--text-secondary); font-size: var(--text-sm); }
.world-progression__field small, .world-progression__branch-meta small { color: var(--text-tertiary); font-weight: 400; }
.world-progression__field { margin: 12px 0; }
.world-progression__targets { margin: 14px 0; padding: 14px; border: 1px solid var(--border); border-radius: 10px; background: color-mix(in srgb, var(--bg) 62%, var(--bg-panel)); }
.world-progression__targets-heading { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.world-progression__targets-heading h4 { margin: 0; }
.world-progression__targets-heading p { margin: 5px 0; color: var(--text-secondary); font-size: var(--text-sm); }
.world-progression__target-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 250px), 1fr)); gap: 8px; margin-top: 10px; }
.world-progression__target { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-width: 0; padding: 9px; border: 1px solid var(--border); border-radius: 8px; }
.world-progression__target-select { display: flex; align-items: center; gap: 9px; min-width: 0; cursor: pointer; }
.world-progression__target-select > span { display: grid; min-width: 0; }
.world-progression__target-select strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.world-progression__target small { font-size: 12px; }
.world-progression__must-reach { display: flex; flex: 0 0 auto; align-items: center; gap: 5px; color: var(--text-secondary); font-size: 12px; cursor: pointer; }
.world-progression__must-reach input { width: 16px; height: 16px; accent-color: var(--accent); }
.world-progression__budget-details { margin-top: 14px; padding: 12px 14px; border: 1px solid var(--border); border-radius: 10px; }
.world-progression__budget-details summary { font-weight: 750; cursor: pointer; }
.world-progression__budget-details > p { color: var(--text-secondary); font-size: var(--text-sm); }
.world-progression__actions { display: flex; flex-wrap: wrap; align-items: end; gap: 8px; margin-top: 12px; }
.world-progression__actions label { display: grid; width: min(100%, 220px); gap: 5px; color: var(--text-secondary); font-size: var(--text-sm); }
.world-progression__preview { margin-top: 16px; padding: 16px; border: 1px solid color-mix(in srgb, var(--accent) 35%, var(--border)); border-radius: 10px; background: color-mix(in srgb, var(--accent-soft) 35%, var(--bg-panel)); }
.world-progression__preview > p { margin: 8px 0; }
.world-progression__metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; margin: 12px 0; }
.world-progression__metrics > div { display: grid; gap: 3px; padding: 10px; border-radius: 8px; background: var(--bg-panel); }
.world-progression__metrics strong { overflow-wrap: anywhere; font-size: 18px; }
.world-progression__metrics span { color: var(--text-secondary); font-size: 12px; }
.world-progression__metrics--compact { grid-template-columns: repeat(4, minmax(0, 1fr)); }
.world-progression__metrics--compact strong { font-size: 16px; }
.world-progression__fee { color: var(--text-secondary); font-size: var(--text-sm); }
.world-progression__warnings { display: grid; gap: 4px; padding-left: 20px; color: var(--text-secondary); font-size: var(--text-sm); }
.world-progression__warning { padding: 9px 11px; border-left: 3px solid var(--warning, #b7791f); border-radius: 5px; background: color-mix(in srgb, var(--warning, #b7791f) 10%, var(--bg-panel)); }
.world-progression__notice { padding: 10px 12px; border-radius: 8px; background: var(--accent-soft); color: var(--text-primary); }
.world-progression__notice--error { background: color-mix(in srgb, var(--danger, #b42318) 10%, var(--bg-panel)); color: var(--danger, #b42318); }
.world-progression__empty { padding: 16px; border: 1px dashed var(--border); border-radius: 9px; color: var(--text-secondary); }
.world-progression__roots { display: grid; gap: 14px; }
.world-progression__root { min-width: 0; padding: 15px; border: 1px solid var(--border); border-radius: 11px; }
.world-progression__root-header, .world-progression__branch-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.world-progression__root-header h4, .world-progression__branch-header h5 { margin: 0; }
.world-progression__root-header p, .world-progression__branch-header p { margin: 5px 0 0; color: var(--text-secondary); font-size: var(--text-sm); }
.world-progression__budget-line, .world-progression__basis { color: var(--text-secondary); font-size: var(--text-sm); }
.world-progression__basis[data-state="changed"] { color: var(--warning, #9a6700); font-weight: 700; }
.world-progression__basis[data-state="unknown"] { color: var(--text-tertiary); }
.world-progression__branch-list { display: grid; gap: 10px; margin-top: 12px; }
.world-progression__branch { min-width: 0; padding: 12px; border: 1px solid var(--border); border-radius: 9px; background: color-mix(in srgb, var(--bg) 58%, var(--bg-panel)); }
.world-progression__branch.is-deleted { opacity: .78; }
.world-progression__branch-actions { display: flex; flex-wrap: wrap; justify-content: end; gap: 5px; }
.world-progression__branch-meta { display: grid; grid-template-columns: minmax(130px, .7fr) minmax(0, 1.7fr) auto; align-items: end; gap: 8px; margin: 10px 0; }
.world-progression__history-step { margin-top: 8px; border: 1px solid var(--border); border-radius: 8px; background: var(--bg-panel); }
.world-progression__history-step > summary { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 6px 14px; padding: 10px 12px; cursor: pointer; font-weight: 700; }
.world-progression__history-step > summary small { color: var(--text-secondary); font-weight: 500; }
.world-progression__step-content { padding: 2px 12px 14px; }
.world-progression__time-note, .world-progression__step-content > p { color: var(--text-secondary); }
.world-progression__time-note { font-size: 12px; }
.world-progression__result-group { margin-top: 14px; padding-top: 11px; border-top: 1px solid var(--border); }
.world-progression__result-group h6 { margin: 0 0 7px; font-size: 14px; }
.world-progression__result-group ul { display: grid; gap: 7px; padding-left: 20px; }
.world-progression__result-group li small { display: block; margin-top: 2px; color: var(--text-secondary); }
.world-progression__intersection, .world-progression__hook-preview { margin: 8px 0; padding: 10px; border-radius: 8px; background: var(--bg); }
.world-progression__intersection p { margin: 4px 0 8px; }
.world-progression__hook { display: grid; gap: 7px; margin-top: 10px; padding: 12px; border: 1px solid var(--border); border-radius: 9px; }
.world-progression__hook p { margin: 5px 0; color: var(--text-secondary); }
.world-progression__hook-preview { border: 1px solid color-mix(in srgb, var(--accent) 30%, var(--border)); }
.world-progression__hook-preview small { color: var(--text-secondary); }
.world-progression__continuous { margin-top: 14px; padding: 13px; border: 1px solid var(--border); border-radius: 9px; }
.world-progression__continuous > p { color: var(--text-secondary); font-size: var(--text-sm); }
.world-progression__continuous .world-progression__participants { grid-template-columns: repeat(auto-fit, minmax(min(100%, 175px), 1fr)); }
.world-progression__interval { max-width: 220px; margin-top: 12px; }
.world-progression__comparison { margin-top: 14px; padding: 13px; border: 1px solid var(--border); border-radius: 9px; }
.world-progression__flow { margin-top: 12px; padding: 13px; border: 1px solid color-mix(in srgb, var(--accent) 28%, var(--border)); border-radius: 9px; background: color-mix(in srgb, var(--accent) 4%, var(--bg-panel)); }
.world-progression__flow-steps { display: flex; flex-wrap: wrap; gap: 6px 16px; padding-left: 22px; }
.world-progression__flow-steps li[data-state="done"] { color: var(--success, #1a7f37); }
.world-progression__flow-steps li[data-state="active"] { color: var(--accent); font-weight: 700; }
.world-progression__hashes { overflow-wrap: anywhere; color: var(--text-tertiary); font: 11px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }
.world-progression__compare-columns { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.world-progression__compare-columns article { padding: 10px; border-radius: 8px; background: var(--bg); }
.world-progression__compare-columns p { color: var(--text-secondary); }
.sr-only { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; }
@media (max-width: 760px) {
  .world-progression { margin: 14px 0 20px; border-radius: 11px; }
  .world-progression__header { align-items: flex-start; padding: 16px; }
  .world-progression__body { padding: 0 14px 18px; }
  .world-progression__field-grid, .world-progression__field-grid--three { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .world-progression__metrics, .world-progression__metrics--compact { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .world-progression__branch-meta { grid-template-columns: 1fr; }
  .world-progression__branch-meta .btn { justify-self: start; }
  .world-progression__root-header, .world-progression__branch-header { flex-direction: column; }
  .world-progression__branch-actions { justify-content: start; }
  .world-progression__compare-columns { grid-template-columns: 1fr; }
}
@media (max-width: 420px) {
  .world-progression__header { flex-direction: column; }
  .world-progression__toggle { width: 100%; }
  .world-progression__field-grid, .world-progression__field-grid--three { grid-template-columns: 1fr; }
  .world-progression__targets { padding: 10px; }
  .world-progression__target { align-items: flex-start; flex-direction: column; }
}
</style>
