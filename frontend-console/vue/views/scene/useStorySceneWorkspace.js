import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
  watch,
} from "vue"
import {
  getApi,
  getAppState,
  getRouter,
  getToast,
} from "../../bridge/index.js"
import { confirmAiReference } from "../../../shared/aiReferenceModal.js"
import { sceneRuntimeManager } from "./sceneRuntimeManager.js"
import {
  commitSceneRuntimeTab,
  normalizeSceneRuntimeTab,
  persistSceneRuntimeDraft,
  runtimeTabFromQuery,
  sceneRuntimeSession,
} from "./sceneRuntimeSession.js"

const MAX_SCRIPT_LENGTH = 200000

function listItems(value) {
  if (Array.isArray(value)) return value
  if (Array.isArray(value?.items)) return value.items
  return []
}

function contentOf(card) {
  return card?.revision?.content || card?.content || card?.current_revision?.content || {}
}

function normalizeCharacter(item, index, worldById = new Map()) {
  const characterId = String(item?.character_id || item?.character?.id || item?.entity_id || item?.id || "")
  const cardId = item?.character_id && item?.id ? String(item.id) : (item?.card_id ? String(item.card_id) : null)
  const world = worldById.get(characterId) || {}
  const content = contentOf(item)
  const name = item?.name || item?.character_name || item?.character?.name || world.name || `本场人物 ${index + 1}`
  return {
    id: characterId || `character-${index + 1}`,
    cardId,
    name: String(name),
    status: item?.status || world.status || content.current_state || "当前状态待补充",
    personality: content.personality || item?.personality || world.personality || world.description || "尚未填写人物卡",
    currentGoal: content.current_goal || item?.current_goal || "",
    currentEmotion: content.current_emotion || item?.current_emotion || "",
    relationship: content.relationship_state || item?.relationship || "",
    authorNotes: content.author_notes || item?.author_notes || "",
    currentRevisionId: item?.current_revision_id || item?.revision?.id || item?.current_revision?.id || null,
    versionNumber: Number(item?.current_version_number || item?.revision?.version_number || 0) || 0,
    source: item?.revision ? "人物卡" : "世界资料",
  }
}

function normalizeScriptFile(item) {
  const revision = item?.revision || item?.current_revision || {}
  return {
    id: item?.id || item?.file_id || null,
    fileId: item?.file_id || item?.id || null,
    fileKey: item?.file_key || "draft",
    title: item?.title || "场景剧本",
    content: String(revision?.content || item?.content || ""),
    revisionId: revision?.id || item?.current_revision_id || null,
    currentRevisionId: item?.current_revision_id || revision?.id || null,
    adoptedRevisionId: item?.adopted_revision_id || null,
    adoptedVersionNumber: Number(item?.adopted_version_number || 0) || 0,
    versionNumber: Number(item?.current_version_number || revision?.version_number || 0) || 0,
  }
}

function normalizeScriptRevision(item) {
  return {
    id: item?.id || null,
    fileId: item?.file_id || null,
    versionNumber: Number(item?.version_number || 0) || 0,
    content: String(item?.content || ""),
    status: item?.status || "历史版本",
    isCurrent: Boolean(item?.is_current),
    isAdopted: Boolean(item?.is_adopted),
    createdAt: item?.created_at || null,
  }
}

function normalizeSimulation(result, scene, characters = [], provenance = {}) {
  const source = result?.preview || result?.result?.preview || result?.result || result || {}
  const scriptSource = source?.script || source
  const proposals = Array.isArray(source?.reactions)
    ? source.reactions
    : Array.isArray(source?.proposals)
      ? source.proposals
      : []
  const reactions = proposals.map((item, index) => {
    const characterId = item?.character_id || item?.characterId || null
    const id = String(item?.id || characterId || `reaction-${index + 1}`)
    const character = characters.find((candidate) => candidate.id === String(characterId))
    return {
      id,
      characterId: characterId || character?.id || null,
      name: item?.name || character?.name || `本场人物 ${index + 1}`,
      stance: item?.stance || item?.internal_pressure || item?.internalPressure || item?.intended_action || item?.intendedAction || "先观察局势，再决定行动",
      trigger: item?.trigger || (scene?.core_conflict ? `面对${scene.core_conflict}` : "面对当前场景压力"),
      action: item?.action || item?.intended_action || item?.intendedAction || "做出符合当前目标的选择",
      knownInformation: Array.isArray(item?.known_information) ? item.known_information : Array.isArray(item?.knownInformation) ? item.knownInformation : [],
      subjectiveJudgment: item?.subjective_judgment || item?.subjectiveJudgment || "",
      goal: item?.goal || "",
      immediateReaction: item?.immediate_reaction || item?.immediateReaction || "",
      actionChoices: Array.isArray(item?.action_choices) ? item.action_choices : Array.isArray(item?.actionChoices) ? item.actionChoices : [],
      dialogueTendency: item?.dialogue_tendency || item?.dialogueTendency || "",
      conflict: item?.conflict || item?.conflictSummary || "",
      confidence: Number(item?.confidence || 0),
      knowledgeBasis: Array.isArray(item?.knowledge_basis) ? item.knowledge_basis : Array.isArray(item?.knowledgeBasis) ? item.knowledgeBasis : [],
      alternatives: Array.isArray(item?.alternatives) ? item.alternatives : Array.isArray(item?.alternative_actions) ? item.alternative_actions : [],
      status: ["kept", "rejected"].includes(item?.status) ? item.status : "candidate",
    }
  })
  const beatsSource = Array.isArray(source?.beats)
    ? source.beats
    : Array.isArray(scriptSource?.beats) ? scriptSource.beats : []
  const beats = beatsSource.map((item, index) => ({
    id: String(item?.beat_id || item?.beatId || item?.id || `beat-${index + 1}`),
    beatId: String(item?.beat_id || item?.beatId || item?.id || `beat-${index + 1}`),
    title: item?.title || item?.purpose || `推进 ${index + 1}`,
    detail: item?.detail || item?.description || [item?.action, item?.consequence].filter(Boolean).join(" → ") || "等待作者补充",
    action: item?.action || "",
    consequence: item?.consequence || "",
    actors: Array.isArray(item?.actors) ? item.actors : [],
    hardAnchor: Boolean(item?.hard_anchor ?? item?.hardAnchor),
  }))
  return {
    status: reactions.length || beats.length || source?.narrative_plan ? "ready" : "draft",
    plan: String(source?.narrative_plan || scriptSource?.narrative_plan || source?.plan || ""),
    scriptText: String(source?.script_text || scriptSource?.script_text || ""),
    sourceTaskId: provenance.sourceTaskId || null,
    contextSnapshotId: provenance.contextSnapshotId || null,
    reactions,
    beats,
    warnings: Array.isArray(source?.warnings) ? source.warnings : [],
    generatedAt: new Date().toISOString(),
  }
}

function runtimeResult(progress) {
  return progress?.result
    || progress?.output
    || progress?.data
    || progress?.preview
    || progress?.raw?.result
    || progress?.raw?.output
    || progress?.raw?.data
    || progress?.raw?.preview
    || null
}

function runtimeProvenance(progress, result, meta = {}) {
  const source = result?.preview || result?.result?.preview || result?.result || result || {}
  const sourceTaskId = progress?.taskId
    || progress?.raw?.task_id
    || progress?.raw?.id
    || result?.task_id
    || result?.taskId
    || source?.task_id
    || source?.taskId
    || progress?.raw?.result?.task_id
    || progress?.raw?.result?.taskId
    || meta?.taskId
    || null
  const contextSnapshotId = result?.context_snapshot_id
    || result?.contextSnapshotId
    || result?.meta?.context_snapshot_id
    || result?.meta?.contextSnapshotId
    || source?.context_snapshot_id
    || source?.contextSnapshotId
    || source?.meta?.context_snapshot_id
    || source?.meta?.contextSnapshotId
    || progress?.raw?.context_snapshot_id
    || progress?.raw?.result?.context_snapshot_id
    || progress?.raw?.meta?.context_snapshot_id
    || meta?.contextSnapshotId
    || null
  return {
    sourceTaskId: sourceTaskId ? String(sourceTaskId).slice(0, 120) : null,
    contextSnapshotId: contextSnapshotId ? String(contextSnapshotId).slice(0, 160) : null,
  }
}

function acceptedReactionPayload(simulation) {
  return (simulation?.reactions || [])
    .filter((item) => item.status === "kept" && item.characterId)
    .map((item) => ({
      character_id: item.characterId,
      known_information: item.knownInformation || [],
      subjective_judgment: item.subjectiveJudgment || null,
      goal: item.goal || null,
      immediate_reaction: item.immediateReaction || null,
      action_choices: item.actionChoices || [],
      dialogue_tendency: item.dialogueTendency || null,
      conflict: item.conflict || null,
      confidence: item.confidence || 0,
      intended_action: item.action || "继续观察并回应当前压力",
      internal_pressure: item.stance || "面对当前场景压力",
      knowledge_basis: item.knowledgeBasis || [],
      alternatives: item.alternatives || [],
    }))
}

function acceptedBeatPayload(simulation) {
  return (simulation?.beats || []).map((item) => ({
    beat_id: item.beatId || item.id,
    purpose: item.title || "推进场景",
    actors: item.actors || [],
    action: item.action || item.detail || "",
    consequence: item.consequence || "",
    hard_anchor: Boolean(item.hardAnchor),
  })).filter((item) => item.action && item.consequence)
}

export function useStorySceneWorkspace({ projectId, selectedItem, selectedSceneId }) {
  const api = getApi() || {}
  const router = getRouter()
  const toast = getToast()
  const activeTab = ref(runtimeTabFromQuery())
  const characters = ref([])
  const scripts = ref([])
  const cardDraft = reactive({
    characterId: null,
    cardId: null,
    expectedRevisionId: null,
    personality: "",
    currentGoal: "",
    currentState: "",
    currentEmotion: "",
    authorNotes: "",
  })
  const cardHistory = ref([])
  const generatedCard = ref(null)
  const cardSaving = ref(false)
  const cardHistoryLoading = ref(false)
  const scriptHistory = ref([])
  const scriptPreview = ref(null)
  const scriptDraftSource = ref(null)
  const activeScriptFileId = ref(null)
  const newScriptTitle = ref("")
  const scriptHistoryLoading = ref(false)
  const notes = reactive({})
  const scriptDrafts = reactive({})
  const scriptDraft = ref("")
  const simulation = ref(null)
  const selectedCharacterId = ref(null)
  const validation = ref([])
  const loading = ref(false)
  const loadError = ref(null)
  const scriptSaving = ref(false)
  const scriptSavedAt = ref(null)
  const requestGeneration = ref(0)
  const disposed = ref(false)

  const scene = computed(() => selectedItem?.value?.scene || null)
  const sceneId = computed(() => selectedSceneId?.value || scene.value?.id || null)
  const taskState = computed(() => sceneRuntimeManager.state)
  const runtimeStage = computed(() => taskState.value.meta?.stage || null)
  const simulationRunning = computed(() => Boolean(
    taskState.value.ownerProjectId === projectId
      && taskState.value.ownerSceneId === sceneId.value
      && (taskState.value.submitting || (taskState.value.taskId && !taskState.value.progress?.terminal)),
  ))
  const characterCardRunning = computed(() => Boolean(
    runtimeStage.value === "character-card"
      && taskState.value.ownerProjectId === projectId
      && taskState.value.ownerSceneId === sceneId.value
      && (taskState.value.submitting || (taskState.value.taskId && !taskState.value.progress?.terminal)),
  ))
  const reactionRunning = computed(() => Boolean(
    runtimeStage.value === "reaction"
      && taskState.value.ownerProjectId === projectId
      && taskState.value.ownerSceneId === sceneId.value
      && (taskState.value.submitting || (taskState.value.taskId && !taskState.value.progress?.terminal)),
  ))
  const scriptGenerating = computed(() => Boolean(
    runtimeStage.value === "script"
      && taskState.value.ownerProjectId === projectId
      && taskState.value.ownerSceneId === sceneId.value
      && (taskState.value.submitting || (taskState.value.taskId && !taskState.value.progress?.terminal)),
  ))
  const simulationProgress = computed(() => (
    taskState.value.ownerProjectId === projectId && taskState.value.ownerSceneId === sceneId.value
      ? taskState.value.progress
      : null
  ))

  function owns(token, targetSceneId = sceneId.value) {
    const state = getAppState()
    return !disposed.value
      && token === requestGeneration.value
      && state?.currentProjectId === projectId
      && state?.currentView === "outline"
      && state?.currentSubView === "scenes"
      && targetSceneId === sceneId.value
  }

  function restoreDraft(targetSceneId = sceneId.value) {
    const current = sceneRuntimeSession(projectId, targetSceneId)
    activeScriptFileId.value = current.activeScriptFileId || null
    scriptDraft.value = current.scriptDraft || ""
    Object.keys(scriptDrafts).forEach((key) => delete scriptDrafts[key])
    if (current.scriptDrafts && typeof current.scriptDrafts === "object") Object.assign(scriptDrafts, current.scriptDrafts)
    simulation.value = current.simulation ? { ...current.simulation } : null
    scriptPreview.value = current.scriptPreview ? { ...current.scriptPreview } : null
    scriptDraftSource.value = current.scriptDraftSource ? { ...current.scriptDraftSource } : null
    selectedCharacterId.value = current.selectedCharacterId || null
    Object.keys(notes).forEach((key) => delete notes[key])
    if (current.notes && typeof current.notes === "object") Object.assign(notes, current.notes)
    scriptSavedAt.value = current.updatedAt || null
  }

  function persistDraft() {
    if (!sceneId.value) return null
    const saved = persistSceneRuntimeDraft(projectId, sceneId.value, {
      activeScriptFileId: activeScriptFileId.value,
      scriptDraft: scriptDraft.value,
      scriptDrafts: {
        ...scriptDrafts,
        ...(activeScriptFileId.value ? { [activeScriptFileId.value]: scriptDraft.value } : {}),
      },
      simulation: simulation.value,
      scriptPreview: scriptPreview.value,
      scriptDraftSource: scriptDraftSource.value,
      selectedCharacterId: selectedCharacterId.value,
      notes: { ...notes },
    })
    scriptSavedAt.value = saved.updatedAt
    return saved
  }

  function additionalNotes() {
    return [
      ...Object.values(notes),
      cardDraft.authorNotes,
    ].map((value) => String(value || "").trim()).filter(Boolean).join("\n") || null
  }

  function clearCardEditor() {
    Object.assign(cardDraft, {
      characterId: null,
      cardId: null,
      expectedRevisionId: null,
      personality: "",
      currentGoal: "",
      currentState: "",
      currentEmotion: "",
      authorNotes: "",
    })
    cardHistory.value = []
    generatedCard.value = null
  }

  function editCharacter(characterId) {
    const character = characters.value.find((item) => item.id === characterId)
    if (!character) return false
    if (selectedCharacterId.value === characterId && cardDraft.characterId === characterId) {
      selectedCharacterId.value = null
      clearCardEditor()
      persistDraft()
      return false
    }
    selectedCharacterId.value = characterId
    persistDraft()
    Object.assign(cardDraft, {
      characterId: character.id,
      cardId: character.cardId || null,
      expectedRevisionId: character.currentRevisionId || null,
      personality: character.personality || "",
      currentGoal: character.currentGoal || "",
      currentState: character.status || "",
      currentEmotion: character.currentEmotion || "",
      authorNotes: character.authorNotes || notes[character.id] || "",
    })
    generatedCard.value = null
    return true
  }

  function updateCardDraft(field, value) {
    if (!(field in cardDraft)) return
    cardDraft[field] = String(value || "")
  }

  function applyGeneratedCard() {
    const content = generatedCard.value?.content || generatedCard.value?.preview?.content
    if (!content) return false
    Object.assign(cardDraft, {
      personality: content.personality || cardDraft.personality,
      currentGoal: content.current_goal || cardDraft.currentGoal,
      currentState: content.current_state || cardDraft.currentState,
      currentEmotion: content.current_emotion || cardDraft.currentEmotion,
      authorNotes: content.author_notes || cardDraft.authorNotes,
    })
    toast("已将人物卡建议放入编辑器，请确认后保存", "info")
    return true
  }

  async function loadCardHistory(cardId = cardDraft.cardId) {
    if (!cardId || typeof api.story?.listCharacterCardRevisions !== "function") {
      cardHistory.value = []
      return []
    }
    const token = requestGeneration.value
    cardHistoryLoading.value = true
    try {
      const result = await api.story.listCharacterCardRevisions(cardId, projectId)
      if (!owns(token)) return []
      cardHistory.value = listItems(result)
      return cardHistory.value
    } catch (err) {
      if (owns(token)) loadError.value = err?.message || "人物卡历史加载失败"
      return []
    } finally {
      if (owns(token)) cardHistoryLoading.value = false
    }
  }

  async function saveCharacterCard() {
    if (!sceneId.value || !cardDraft.characterId || !cardDraft.personality.trim()) {
      loadError.value = "人物卡至少需要填写人物底色"
      return false
    }
    if (typeof api.story?.saveCharacterCard !== "function") {
      loadError.value = "人物卡保存服务暂不可用；本次编辑仍保留在当前页面"
      return false
    }
    const token = requestGeneration.value
    cardSaving.value = true
    try {
      const result = await api.story.saveCharacterCard(projectId, sceneId.value, cardDraft.characterId, {
        card_id: cardDraft.cardId,
        expected_revision_id: cardDraft.expectedRevisionId,
        confirmed: true,
        content: {
          version: "character_card.v1",
          personality: cardDraft.personality,
          current_goal: cardDraft.currentGoal || null,
          current_state: cardDraft.currentState || null,
          current_emotion: cardDraft.currentEmotion || null,
          author_notes: cardDraft.authorNotes || null,
        },
      })
      if (!owns(token)) return false
      const current = characters.value.find((item) => item.id === cardDraft.characterId)
      if (current) Object.assign(current, normalizeCharacter(result, characters.value.indexOf(current), new Map()))
      selectedCharacterId.value = cardDraft.characterId
      Object.assign(cardDraft, {
        cardId: current?.cardId || result?.id || cardDraft.cardId,
        expectedRevisionId: current?.currentRevisionId || result?.current_revision_id || cardDraft.expectedRevisionId,
      })
      await loadCardHistory(current?.cardId || result?.id || cardDraft.cardId)
      toast("人物卡已保存为新版本", "success")
      return true
    } catch (err) {
      if (owns(token)) loadError.value = err?.message || "人物卡保存失败；当前编辑仍保留在本机"
      return false
    } finally {
      if (owns(token)) cardSaving.value = false
    }
  }

  async function restoreCardRevision(revision) {
    if (!revision?.id || !cardDraft.cardId || typeof api.story?.restoreCharacterCardRevision !== "function") return false
    const token = requestGeneration.value
    cardSaving.value = true
    try {
      const result = await api.story.restoreCharacterCardRevision(cardDraft.cardId, projectId, {
        revision_id: revision.id,
        expected_revision_id: cardDraft.expectedRevisionId,
        confirmed: true,
      })
      if (!owns(token)) return false
      const current = characters.value.find((item) => item.id === cardDraft.characterId)
      if (current) Object.assign(current, normalizeCharacter(result, characters.value.indexOf(current), new Map()))
      selectedCharacterId.value = cardDraft.characterId
      Object.assign(cardDraft, {
        cardId: current?.cardId || cardDraft.cardId,
        expectedRevisionId: current?.currentRevisionId || result?.current_revision_id || cardDraft.expectedRevisionId,
      })
      await loadCardHistory(cardDraft.cardId)
      toast("已按历史版本创建新的人物卡版本", "success")
      return true
    } catch (err) {
      if (owns(token)) loadError.value = err?.message || "人物卡历史恢复失败；当前编辑仍保留"
      return false
    } finally {
      if (owns(token)) cardSaving.value = false
    }
  }

  function selectTab(tab) {
    const normalized = normalizeSceneRuntimeTab(tab)
    const changed = activeTab.value !== normalized
    activeTab.value = normalized
    if (sceneId.value) sceneRuntimeSession(projectId, sceneId.value).activeTab = normalized
    commitSceneRuntimeTab(projectId, sceneId.value, normalized, "push", router)
    if (!changed && normalized !== "management") void loadWorkspace()
  }

  async function loadWorldCharacters(targetScene, token) {
    const loader = api.world?.listEntities
    if (typeof loader !== "function") return []
    try {
      const response = await loader({
        novel_id: projectId,
        scene_id: targetScene.id,
        entity_type: "character",
        display_state: "active",
        skip: 0,
        limit: 24,
      })
      if (!owns(token, targetScene.id)) return null
      return listItems(response)
    } catch {
      return []
    }
  }

  async function loadWorkspace() {
    const targetScene = scene.value
    if (!targetScene?.id || activeTab.value === "management") return false
    const token = ++requestGeneration.value
    loading.value = true
    loadError.value = null
    restoreDraft(targetScene.id)
    try {
      let context = null
      let contextError = null
      if (typeof api.story?.getSceneContext === "function") {
        try {
          context = await api.story.getSceneContext(projectId, targetScene.id)
        } catch (err) {
          contextError = err
        }
      }
      if (!owns(token, targetScene.id)) return false

      const worldItems = await loadWorldCharacters(targetScene, token)
      if (!owns(token, targetScene.id)) return false
      const worldById = new Map(listItems(worldItems).map((item) => [String(item?.id || item?.entity_id || ""), item]))
      let cardItems = listItems(context?.character_cards)
      if (typeof api.story?.listCharacterCards === "function") {
        try {
          const listedCards = listItems(await api.story.listCharacterCards(projectId, targetScene.id, { limit: 24 }))
          const merged = [...cardItems, ...listedCards]
          const seen = new Set()
          cardItems = merged.filter((item) => {
            const key = String(item?.character_id || item?.id || item?.entity_id || item?.name || "")
            if (!key || seen.has(key)) return false
            seen.add(key)
            return true
          })
        } catch (err) {
          contextError = contextError || err
        }
      }
      if (!cardItems.length) {
        const inline = targetScene.present_characters
          || targetScene.characters
          || targetScene.scene_characters
          || targetScene.character_cards
          || []
        const inlineItems = Array.isArray(inline)
          ? inline.map((item) => typeof item === "string" ? (worldById.get(String(item)) || { id: item }) : item)
          : []
        const povId = targetScene.pov_character_id ? String(targetScene.pov_character_id) : null
        cardItems = inlineItems.length
          ? inlineItems
          : povId
            ? [worldById.get(povId) || { id: povId }]
            : []
      }
      characters.value = cardItems.map((item, index) => normalizeCharacter(item, index, worldById))

      let scriptItems = listItems(context?.script_files)
      if (!scriptItems.length && typeof api.story?.listSceneScripts === "function") {
        try {
          scriptItems = listItems(await api.story.listSceneScripts(projectId, targetScene.id, { limit: 12 }))
        } catch (err) {
          contextError = contextError || err
        }
      }
      if (!owns(token, targetScene.id)) return false
      scripts.value = scriptItems.map(normalizeScriptFile)
      if (!scripts.value.some((item) => item.fileId === activeScriptFileId.value)) {
        activeScriptFileId.value = scripts.value[0]?.fileId || null
      }
      const selectedScript = activeScriptFile()
      if (selectedScript?.fileId) {
        scriptDraft.value = scriptDrafts[selectedScript.fileId]
          ?? scriptDraft.value
          ?? selectedScript.content
          ?? ""
        scriptDrafts[selectedScript.fileId] = scriptDraft.value.slice(0, MAX_SCRIPT_LENGTH)
      }
      if (!simulation.value && taskState.value.ownerSceneId === targetScene.id && taskState.value.result) {
        simulation.value = normalizeSimulation(taskState.value.result, targetScene, characters.value)
      }
      if (contextError && !characters.value.length && !scripts.value.length) {
        throw contextError
      }
      if (activeTab.value === "script" && selectedScript?.fileId) void loadScriptHistory(selectedScript.fileId, token)
      return true
    } catch (err) {
      if (!owns(token, targetScene.id)) return false
      loadError.value = err?.message || "场景辅助资料加载失败"
      return false
    } finally {
      if (owns(token, targetScene.id)) loading.value = false
    }
  }

  function updateNote(characterId, value) {
    if (!characterId) return
    notes[characterId] = String(value || "")
    persistDraft()
  }

  function selectCharacter(characterId) {
    selectedCharacterId.value = selectedCharacterId.value === characterId ? null : characterId
    persistDraft()
  }

  function updateScript(value, source = null) {
    scriptDraft.value = String(value || "").slice(0, MAX_SCRIPT_LENGTH)
    scriptDraftSource.value = source?.sourceTaskId || source?.contextSnapshotId
      ? {
        sourceTaskId: source.sourceTaskId ? String(source.sourceTaskId).slice(0, 120) : null,
        contextSnapshotId: source.contextSnapshotId ? String(source.contextSnapshotId).slice(0, 160) : null,
      }
      : null
    if (activeScriptFileId.value) scriptDrafts[activeScriptFileId.value] = scriptDraft.value
    persistDraft()
  }

  function validateScript() {
    const findings = []
    if (!scriptDraft.value.trim()) findings.push({ level: "error", message: "还没有剧本草稿" })
    if (scriptDraft.value.trim() && scriptDraft.value.trim().length < 80) {
      findings.push({ level: "warning", message: "草稿较短，建议确认人物行动和场景结果是否完整" })
    }
    if (scene.value?.must_happen && scriptDraft.value.trim()) {
      findings.push({ level: "info", message: "请人工确认“必须发生”已在正文中兑现" })
    }
    validation.value = findings
    return findings
  }

  function activeScriptFile() {
    return scripts.value.find((item) => item.fileId === activeScriptFileId.value) || scripts.value[0] || null
  }

  function selectScriptFile(fileId) {
    const next = scripts.value.find((item) => item.fileId === fileId)
    if (!next) return false
    activeScriptFileId.value = next.fileId
    scriptDraft.value = scriptDrafts[next.fileId] ?? next.content ?? ""
    scriptDraftSource.value = null
    scriptDrafts[next.fileId] = scriptDraft.value
    scriptHistory.value = []
    scriptSavedAt.value = null
    persistDraft()
    if (activeTab.value === "script") void loadScriptHistory(next.fileId)
    return true
  }

  function updateNewScriptTitle(value) {
    newScriptTitle.value = String(value || "").slice(0, 255)
  }

  async function createScriptFile() {
    if (!sceneId.value || typeof api.story?.createSceneScriptFile !== "function") {
      loadError.value = "剧本文件服务暂不可用；当前草稿未改变"
      return false
    }
    const title = newScriptTitle.value.trim()
    if (!title) {
      loadError.value = "请先填写剧本文件名称"
      return false
    }
    const usedKeys = new Set(scripts.value.map((item) => item.fileKey))
    let suffix = scripts.value.length + 1
    let fileKey = `script-${suffix}`
    while (usedKeys.has(fileKey)) fileKey = `script-${++suffix}`
    const token = requestGeneration.value
    scriptSaving.value = true
    try {
      const result = await api.story.createSceneScriptFile(projectId, sceneId.value, { file_key: fileKey, title })
      if (!owns(token)) return false
      const next = normalizeScriptFile(result)
      scripts.value = [...scripts.value.filter((item) => item.fileId !== next.fileId), next]
      activeScriptFileId.value = next.fileId
      scriptDraft.value = next.content || ""
      scriptDraftSource.value = null
      scriptDrafts[next.fileId] = scriptDraft.value
      scriptHistory.value = []
      newScriptTitle.value = ""
      persistDraft()
      toast("已建立新的剧本文件", "success")
      return true
    } catch (err) {
      if (owns(token)) {
        loadError.value = `${err?.message || "剧本文件创建失败"}；当前草稿未改变`
        toast(loadError.value, "error")
      }
      return false
    } finally {
      if (owns(token)) scriptSaving.value = false
    }
  }

  async function loadScriptHistory(fileId = activeScriptFile()?.fileId, token = requestGeneration.value) {
    if (!fileId || typeof api.story?.listSceneScriptRevisions !== "function") {
      scriptHistory.value = []
      return []
    }
    scriptHistoryLoading.value = true
    try {
      const result = await api.story.listSceneScriptRevisions(fileId, projectId)
      if (!owns(token)) return []
      scriptHistory.value = listItems(result).map(normalizeScriptRevision)
      return scriptHistory.value
    } catch (err) {
      if (owns(token)) loadError.value = err?.message || "剧本版本历史加载失败"
      return []
    } finally {
      if (owns(token)) scriptHistoryLoading.value = false
    }
  }

  async function saveScript({ remote = true, adopt = false } = {}) {
    if (!sceneId.value || !scriptDraft.value.trim()) {
      validateScript()
      return false
    }
    persistDraft()
    if (!remote || typeof api.story?.saveSceneScript !== "function") {
      loadError.value = "剧本保存服务暂不可用；草稿已保存在本机，请稍后重试"
      toast(loadError.value, "error")
      return false
    }
    const token = requestGeneration.value
    scriptSaving.value = true
    try {
      let result = await api.story.saveSceneScript(projectId, sceneId.value, {
        file_key: activeScriptFile()?.fileKey || "draft",
        content: scriptDraft.value,
        confirmed: true,
        expected_revision_id: activeScriptFile()?.currentRevisionId || null,
        adopt: false,
        ...(scriptDraftSource.value?.sourceTaskId ? { source_task_id: scriptDraftSource.value.sourceTaskId } : {}),
        ...(scriptDraftSource.value?.contextSnapshotId ? { context_snapshot_id: scriptDraftSource.value.contextSnapshotId } : {}),
        provenance: {
          workflow: "scene_runtime",
          author_confirmed: true,
          ...(scriptDraftSource.value?.sourceTaskId ? { source_task_id: scriptDraftSource.value.sourceTaskId } : {}),
          ...(scriptDraftSource.value?.contextSnapshotId ? { context_snapshot_id: scriptDraftSource.value.contextSnapshotId } : {}),
        },
      })
      if (!owns(token)) return false
      let nextFile = normalizeScriptFile(result)
      if (adopt && nextFile.fileId && nextFile.currentRevisionId && typeof api.story?.adoptSceneScriptRevision === "function") {
        result = await api.story.adoptSceneScriptRevision(
          nextFile.fileId,
          nextFile.currentRevisionId,
          projectId,
          nextFile.adoptedRevisionId || null,
        )
        if (!owns(token)) return false
        nextFile = normalizeScriptFile(result)
      }
      scripts.value = scripts.value.length
        ? scripts.value.map((item) => item.fileId === nextFile.fileId ? nextFile : item)
        : [nextFile]
      scriptSavedAt.value = new Date().toISOString()
      persistDraft()
      await loadScriptHistory(nextFile.fileId, token)
      toast(adopt ? "本稿已保存并采用" : "剧本草稿已保存为新版本", "success")
      return true
    } catch (err) {
      if (!owns(token)) return false
      persistDraft()
      loadError.value = `${err?.message || "剧本草稿保存失败"}；草稿已保存在本机`
      toast(loadError.value, "error")
      return false
    } finally {
      if (owns(token)) scriptSaving.value = false
    }
  }

  async function adoptScriptRevision(revision) {
    const file = activeScriptFile()
    if (!file?.fileId || !revision?.id || typeof api.story?.adoptSceneScriptRevision !== "function") return false
    const token = requestGeneration.value
    scriptSaving.value = true
    try {
      const result = await api.story.adoptSceneScriptRevision(
        file.fileId,
        revision.id,
        projectId,
        file.adoptedRevisionId || null,
      )
      if (!owns(token)) return false
      const next = normalizeScriptFile(result)
      scripts.value = scripts.value.map((item) => item.fileId === next.fileId ? next : item)
      await loadScriptHistory(file.fileId, token)
      toast("已将该历史版本设为当前采用版本", "success")
      return true
    } catch (err) {
      if (owns(token)) {
        loadError.value = `${err?.message || "剧本采用失败"}；当前草稿未被替换`
        toast(loadError.value, "error")
      }
      return false
    } finally {
      if (owns(token)) scriptSaving.value = false
    }
  }

  async function unadoptScriptFile() {
    const file = activeScriptFile()
    if (!file?.fileId || !file.adoptedRevisionId || typeof api.story?.unadoptSceneScriptFile !== "function") return false
    const token = requestGeneration.value
    scriptSaving.value = true
    try {
      const result = await api.story.unadoptSceneScriptFile(file.fileId, projectId, file.adoptedRevisionId)
      if (!owns(token)) return false
      const next = normalizeScriptFile(result)
      scripts.value = scripts.value.map((item) => item.fileId === next.fileId ? next : item)
      await loadScriptHistory(file.fileId, token)
      toast("已撤销当前采用；历史版本仍保留", "success")
      return true
    } catch (err) {
      if (owns(token)) {
        loadError.value = `${err?.message || "撤销采用失败"}；当前剧本版本未改变`
        toast(loadError.value, "error")
      }
      return false
    } finally {
      if (owns(token)) scriptSaving.value = false
    }
  }

  function applyScriptPreview() {
    if (!scriptPreview.value?.content) return false
    updateScript(scriptPreview.value.content, scriptPreview.value)
    toast("已将剧本建议放入可编辑草稿，请先检查再保存", "info")
    return true
  }

  async function submitConfirmedStoryTask(stage, runner, payload, taskLabel) {
    const targetScene = scene.value
    if (!targetScene?.id || typeof runner !== "function") {
      loadError.value = `${taskLabel}服务暂不可用；当前草稿和已有结果未改变`
      return false
    }
    const requestToken = ++requestGeneration.value
    let confirmation
    try {
      confirmation = await confirmAiReference({
        novel_id: projectId,
        action: stage === "character-card" ? "story.character_card.generate" : stage === "reaction" ? "story.reaction.generate" : "story.script.generate",
        task: taskLabel,
        scope: "project",
        scene_id: targetScene.id,
        visible_until_scene_id: targetScene.id,
        character_ids: payload.character_ids || (payload.character_id ? [payload.character_id] : []),
        include_pending_objects: false,
      })
      if (!owns(requestToken, targetScene.id)) return false
    } catch (err) {
      if (owns(requestToken, targetScene.id)) loadError.value = err?.message || `已取消${taskLabel}`
      return false
    }
    const submission = sceneRuntimeManager.beginSubmission(projectId, targetScene.id, stage)
    if (!submission) return false
    try {
      const response = await runner({
        ...payload,
        novel_id: projectId,
        scene_id: targetScene.id,
        context_confirmation_id: confirmation.id,
        operation_id: submission.operationId,
        additional_notes: additionalNotes(),
        ...(stage === "character-card" ? {} : {
          accepted_reactions: acceptedReactionPayload(simulation.value),
          accepted_beats: acceptedBeatPayload(simulation.value),
        }),
        confirmed: true,
      })
      if (!owns(requestToken, targetScene.id)) return false
      if (!response?.task_id) throw new Error(`${taskLabel}未能开始，请稍后重试`)
      sceneRuntimeManager.adopt(response, { sceneId: targetScene.id, stage }, projectId, targetScene.id)
      toast(`${taskLabel}已提交`, "success")
      return true
    } catch (err) {
      if (owns(requestToken, targetScene.id)) {
        loadError.value = `${err?.message || `${taskLabel}失败`}；当前草稿和已有结果未改变`
        toast(loadError.value, "error")
      }
      return false
    } finally {
      sceneRuntimeManager.endSubmission(submission)
    }
  }

  async function startCharacterCardGeneration() {
    const characterId = cardDraft.characterId || selectedCharacterId.value
    if (!characterId) {
      loadError.value = "请先选择要生成的人物卡"
      return false
    }
    if (!cardDraft.characterId) editCharacter(characterId)
    return submitConfirmedStoryTask(
      "character-card",
      api.story?.startCharacterCardTask,
      { character_id: characterId },
      "人物卡建议",
    )
  }

  async function startReactionGeneration() {
    const characterIds = characters.value.map((item) => item.id).filter((id) => id && !id.startsWith("character-"))
    if (!characterIds.length) {
      loadError.value = "本场还没有可用于推演的人物"
      return false
    }
    return submitConfirmedStoryTask(
      "reaction",
      api.story?.startReactionTask,
      { character_ids: characterIds },
      "人物反应建议",
    )
  }

  async function startScriptGeneration() {
    const characterIds = characters.value.map((item) => item.id).filter((id) => id && !id.startsWith("character-"))
    if (!characterIds.length) {
      loadError.value = "本场还没有可用于生成剧本的人物"
      return false
    }
    return submitConfirmedStoryTask(
      "script",
      api.story?.startScriptTask,
      { character_ids: characterIds },
      "剧本建议",
    )
  }

  async function startSimulation() {
    const targetScene = scene.value
    if (!targetScene?.id || simulationRunning.value) return false
    const characterIds = characters.value.map((item) => item.id).filter((id) => id && !id.startsWith("character-"))
    if (!characterIds.length) {
      loadError.value = "先在场景管理关联人物或建立人物卡，再开始一键推演"
      toast(loadError.value, "warning")
      return false
    }
    const requestToken = ++requestGeneration.value
    const submission = sceneRuntimeManager.beginSubmission(projectId, targetScene.id, "simulation")
    if (!submission) return false
    const runner = api.story?.startOneClickTask || api.story?.startSceneSimulation
    try {
      if (typeof runner !== "function") {
        loadError.value = "一键推演服务暂不可用；当前草稿和已有结果未改变"
        toast(loadError.value, "error")
        return false
      }
      const oneClickPayload = {
        novel_id: projectId,
        scene_id: targetScene.id,
        character_ids: characterIds,
        operation_id: submission.operationId,
        submit_authorized: true,
        additional_notes: additionalNotes(),
        accepted_reactions: acceptedReactionPayload(simulation.value),
        accepted_beats: acceptedBeatPayload(simulation.value),
      }
      const response = api.story?.startOneClickTask
        ? await runner(oneClickPayload)
        : await runner(projectId, targetScene.id, oneClickPayload)
      if (!owns(requestToken, targetScene.id)) return false
      if (response?.task_id) {
        sceneRuntimeManager.adopt(response, { sceneId: targetScene.id, stage: "simulation" }, projectId, targetScene.id)
        return true
      }
      if (response?.preview || response?.result) {
        applyRuntimeResult({ result: response, taskId: response?.task_id || null }, { sceneId: targetScene.id, stage: "simulation" })
        return true
      }
      throw new Error("一键推演未返回可审阅结果")
    } catch (err) {
      if (!owns(requestToken, targetScene.id)) return false
      loadError.value = `${err?.message || "场景推演失败"}；当前草稿和已有结果未改变`
      toast(loadError.value, "error")
      return false
    } finally {
      sceneRuntimeManager.endSubmission(submission)
    }
  }

  async function cancelSimulation() {
    if (!sceneId.value) return false
    try {
      return await sceneRuntimeManager.cancel(projectId, sceneId.value)
    } catch (err) {
      toast(err?.message || "停止推演失败", "error")
      return false
    }
  }

  function setReactionStatus(reactionId, status) {
    if (!simulation.value?.reactions) return
    const next = simulation.value.reactions.map((item) => item.id === reactionId ? { ...item, status } : item)
    simulation.value = { ...simulation.value, reactions: next }
    persistDraft()
  }

  function applyRuntimeResult(progress, meta) {
    const result = runtimeResult(progress)
    if (!result || meta?.sceneId !== sceneId.value) return
    const stage = meta?.stage || "simulation"
    const provenance = runtimeProvenance(progress, result, meta)
    if (stage === "character-card") {
      generatedCard.value = result.preview || result.result?.preview || result.result || result
      return
    }
    if (stage === "script") {
      const preview = result.preview || result.result?.preview || result.result || result
      scriptPreview.value = {
        content: String(preview?.script_text || preview?.content || ""),
        plan: String(preview?.narrative_plan || preview?.plan || ""),
        beats: Array.isArray(preview?.beats) ? preview.beats : [],
        warnings: Array.isArray(preview?.warnings) ? preview.warnings : [],
        sourceTaskId: provenance.sourceTaskId,
        contextSnapshotId: provenance.contextSnapshotId,
      }
      persistDraft()
      return
    }
    const next = normalizeSimulation(result, scene.value, characters.value, provenance)
    if (next.scriptText) {
      scriptPreview.value = {
        content: next.scriptText,
        plan: next.plan,
        beats: next.beats,
        warnings: next.warnings,
        sourceTaskId: next.sourceTaskId,
        contextSnapshotId: next.contextSnapshotId,
      }
    }
    if (stage === "reaction" && simulation.value) {
      simulation.value = { ...simulation.value, reactions: next.reactions, warnings: next.warnings, generatedAt: next.generatedAt }
    } else {
      simulation.value = next
    }
    persistDraft()
  }

  const unsubscribeTerminal = sceneRuntimeManager.subscribeTerminal((progress, meta) => {
    applyRuntimeResult(progress, meta)
  })

  watch(sceneId, (next, previous) => {
    if (next === previous) return
    characters.value = []
    scripts.value = []
    activeScriptFileId.value = null
    newScriptTitle.value = ""
    clearCardEditor()
    scriptHistory.value = []
    scriptPreview.value = null
    scriptDraftSource.value = null
    validation.value = []
    loadError.value = null
    restoreDraft(next)
    if (activeTab.value !== "management") void loadWorkspace()
  })

  watch(activeTab, (tab) => {
    if (tab !== "management") void loadWorkspace()
  })

  onMounted(() => {
    sceneRuntimeManager.recover(projectId, sceneId.value)
    restoreDraft(sceneId.value)
    if (taskState.value.ownerSceneId === sceneId.value && taskState.value.result) {
      applyRuntimeResult({
        result: taskState.value.result,
        taskId: taskState.value.taskId || taskState.value.progress?.taskId || taskState.value.result?.task_id || null,
      }, taskState.value.meta)
    }
    if (activeTab.value !== "management") void loadWorkspace()
  })

  onBeforeUnmount(() => {
    disposed.value = true
    requestGeneration.value += 1
    unsubscribeTerminal?.()
  })

  return {
    activeTab,
    activeScriptFileId,
    adoptScriptRevision,
    applyScriptPreview,
    cardDraft,
    cardHistory,
    cardHistoryLoading,
    cardSaving,
    cancelSimulation,
    characters,
    characterCardRunning,
    applyGeneratedCard,
    clearCardEditor,
    createScriptFile,
    editCharacter,
    generatedCard,
    hasScene: computed(() => Boolean(scene.value?.id)),
    loadError,
    loadWorkspace,
    loadCardHistory,
    loadScriptHistory,
    loading,
    notes,
    persistDraft,
    scriptDraft,
    scriptDraftSource,
    scriptGenerating,
    scriptHistory,
    scriptHistoryLoading,
    scriptPreview,
    scriptSavedAt,
    scriptSaving,
    scripts,
    newScriptTitle,
    unadoptScriptFile,
    restoreCardRevision,
    saveCharacterCard,
    saveScript,
    selectScriptFile,
    selectTab,
    selectCharacter,
    selectedCharacterId,
    scene,
    setReactionStatus,
    simulation,
    simulationProgress,
    simulationRunning,
    reactionRunning,
    startCharacterCardGeneration,
    startReactionGeneration,
    startScriptGeneration,
    startSimulation,
    updateCardDraft,
    updateNewScriptTitle,
    updateNote,
    updateScript,
    validateScript,
    validation,
  }
}
