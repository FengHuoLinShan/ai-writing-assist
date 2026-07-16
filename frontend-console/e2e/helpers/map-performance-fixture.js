import { createHash } from "node:crypto"
import { readFile } from "node:fs/promises"
import { fileURLToPath } from "node:url"
import {
  API_BASE,
  cleanupProject,
  createEntity,
  confirmMapObservation,
  createLocationBindings,
  createMap,
  createMapMarker,
  createMapObservation,
  createProject,
  createScene,
  createTerritories,
  getMapLayerTree,
  getMapState,
  listTerritories,
} from "./api-client.js"

const manifestPath = fileURLToPath(
  new URL("./fixtures/map-performance-manifest.json", import.meta.url),
)

function stableValue(value) {
  if (Array.isArray(value)) return value.map(stableValue)
  if (!value || typeof value !== "object") return value
  return Object.fromEntries(
    Object.keys(value).sort().map((key) => [key, stableValue(value[key])]),
  )
}

function checksum(value) {
  return createHash("sha256")
    .update(JSON.stringify(stableValue(value)))
    .digest("hex")
}

async function readMapCollection(path) {
  const response = await fetch(`${API_BASE}${path}`)
  if (!response.ok) {
    throw new Error(`map performance fixture verification failed (${response.status})`)
  }
  return response.json()
}

function sortedRows(rows) {
  return [...rows].sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)))
}

function replaceKnownIds(value, aliases) {
  if (Array.isArray(value)) return value.map((item) => replaceKnownIds(item, aliases))
  if (!value || typeof value !== "object") return aliases.get(value) || value
  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [key, replaceKnownIds(item, aliases)]),
  )
}

function canonicalDynamicItem(item, aliases, statusField) {
  return {
    target: aliases.get(item.target_entity_id) || item.target_name || null,
    target_entity_type: item.target_entity_type || null,
    target_name: item.target_name || null,
    dynamic_type: item.dynamic_type,
    time_anchor: replaceKnownIds(item.time_anchor || null, aliases),
    spatial_anchor: replaceKnownIds(item.spatial_anchor || null, aliases),
    value_json: replaceKnownIds(item.value_json || null, aliases),
    confidence: Number(item.confidence),
    status: item[statusField],
    source_ref: replaceKnownIds(item.source_ref || null, aliases),
    evidence_text: item.evidence_text || null,
    scene: aliases.get(item.scene_id) || null,
    scene_index: item.scene_index ?? null,
  }
}

function canonicalApiPayload({ state, layerTree, territories, observations, facts, fixture }) {
  const aliases = new Map([
    [fixture.project.id, "project"],
    [fixture.map.id, "map"],
    [fixture.markerEntity.id, fixture.markerEntity.name],
    [fixture.faction.id, fixture.faction.name],
    [fixture.scene.id, "scene-0"],
    ...fixture.locations.map((location) => [location.id, location.name]),
  ])
  return stableValue({
    map: {
      map_type: state.map?.map_type,
      grid_width: state.map?.grid_width,
      grid_height: state.map?.grid_height,
      hex_size: state.map?.hex_size,
    },
    tiles: (state.tiles || [])
      .map((tile) => [tile.hex_q, tile.hex_r, tile.terrain_type, Number(tile.elevation || 0)])
      .sort((left, right) => left[0] - right[0] || left[1] - right[1]),
    location_bindings: sortedRows((state.location_bindings || []).map((binding) => [
      aliases.get(binding.location_entity_id) || binding.location_entity_id,
      binding.hex_q,
      binding.hex_r,
      Boolean(binding.is_center),
    ])),
    markers: sortedRows((state.markers || []).map((marker) => [
      aliases.get(marker.entity_id) || marker.entity_id,
      marker.marker_type,
      marker.hex_q,
      marker.hex_r,
      marker.label || null,
      Boolean(marker.visible),
    ])),
    territories: sortedRows((territories || []).map((territory) => [
      aliases.get(territory.faction_entity_id) || territory.faction_entity_id,
      territory.hex_q,
      territory.hex_r,
    ])),
    layer_keys: (layerTree.nodes || [])
      .map((node) => node.layer_key)
      .filter(Boolean)
      .sort(),
    observations: sortedRows((observations.items || []).map((item) => (
      canonicalDynamicItem(item, aliases, "review_state")
    ))),
    facts: sortedRows((facts.items || []).map((item) => (
      canonicalDynamicItem(item, aliases, "fact_status")
    ))),
  })
}

async function validateCreatedFixture(fixture, profile, expectedPayloadChecksum) {
  const projectId = fixture.project.id
  const mapId = fixture.map.id
  const novelId = encodeURIComponent(projectId)
  const encodedMapId = encodeURIComponent(mapId)
  const [state, layerTree, territories, observations, facts] = await Promise.all([
    getMapState(projectId, mapId),
    getMapLayerTree(projectId, mapId),
    listTerritories(projectId, mapId),
    readMapCollection(
      `/world/maps/${encodedMapId}/observations?novel_id=${novelId}`,
    ),
    readMapCollection(
      `/world/maps/${encodedMapId}/facts?novel_id=${novelId}&fact_status=confirmed`,
    ),
  ])
  const actualCounts = {
    tiles: state.tiles?.length || 0,
    location_bindings: state.location_bindings?.length || 0,
    markers: state.markers?.length || 0,
    territory_tiles: territories?.length || 0,
    layer_nodes: layerTree.nodes?.length || 0,
    labels: (state.location_bindings || []).filter((item) => item.is_center).length,
    facts: facts.total,
    candidates: (observations.items || []).filter(
      (item) => item.review_state === "candidate",
    ).length,
  }
  for (const [name, expected] of Object.entries(profile.counts)) {
    if (actualCounts[name] !== expected) {
      throw new Error(
        `map performance fixture API count mismatch: ${name} expected ${expected}, got ${actualCounts[name]}`,
      )
    }
  }
  const actualLayerKeys = (layerTree.nodes || [])
    .map((node) => node.layer_key)
    .filter(Boolean)
    .sort()
  const expectedLayerKeys = [...profile.layer.keys].sort()
  if (JSON.stringify(actualLayerKeys) !== JSON.stringify(expectedLayerKeys)) {
    throw new Error("map performance fixture API layer keys do not match the manifest")
  }
  const terrainCounts = {}
  for (const tile of state.tiles || []) {
    terrainCounts[tile.terrain_type] = (terrainCounts[tile.terrain_type] || 0) + 1
  }
  if (Object.keys(terrainCounts).length < 3) {
    throw new Error("map performance fixture must contain at least three terrain types")
  }
  const canonicalPayload = canonicalApiPayload({
    state,
    layerTree,
    territories,
    observations,
    facts,
    fixture,
  })
  const actualPayloadChecksum = checksum(canonicalPayload)
  if (actualPayloadChecksum !== expectedPayloadChecksum) {
    throw new Error(
      `map performance fixture payload checksum mismatch: expected ${expectedPayloadChecksum}, got ${actualPayloadChecksum}`,
    )
  }
  return {
    actualCounts,
    terrainCounts: stableValue(terrainCounts),
    actualPayloadChecksum,
  }
}

export async function loadMapPerformanceManifest() {
  const manifest = JSON.parse(await readFile(manifestPath, "utf8"))
  if (manifest.version !== 2 || !manifest.profiles?.standard || !manifest.profiles?.stress) {
    throw new Error("map performance manifest is incomplete")
  }
  for (const [profileName, profile] of Object.entries(manifest.profiles)) {
    const actualChecksum = mapPerformanceProfileChecksum(profile)
    if (manifest.checksums?.[profileName] !== actualChecksum) {
      throw new Error(`map performance manifest checksum mismatch: ${profileName}`)
    }
    if (!/^[0-9a-f]{64}$/.test(manifest.payload_checksums?.[profileName] || "")) {
      throw new Error(`map performance payload checksum is missing: ${profileName}`)
    }
    validateProfileShape(profileName, profile)
  }
  return manifest
}

function validateProfileShape(profileName, profile) {
  const expected = profile.counts || {}
  const actual = {
    tiles: profile.grid.width * profile.grid.height,
    location_bindings: profile.locations.length,
    markers: profile.marker ? 1 : 0,
    territory_tiles: profile.territory.hexes.length,
    layer_nodes: profile.layer.keys.length,
    labels: profile.locations.length,
    facts: profile.dynamic?.confirmed ? 1 : 0,
    candidates: profile.dynamic?.candidate ? 1 : 0,
  }
  for (const [key, value] of Object.entries(actual)) {
    if (expected[key] !== value) {
      throw new Error(
        `map performance manifest count mismatch: ${profileName}.${key}`,
      )
    }
  }
  if (!['continent', 'islands'].includes(profile.template)) {
    throw new Error(`map performance fixture must use a mixed terrain template: ${profileName}`)
  }
}

export function mapPerformanceProfileChecksum(profile) {
  return checksum(profile)
}

export async function createMapPerformanceFixture(profileName = "standard") {
  const manifest = await loadMapPerformanceManifest()
  const profile = manifest.profiles[profileName]
  if (!profile) throw new Error(`unknown map performance profile: ${profileName}`)

  const project = await createProject({
    title: `地图性能夹具 ${profile.name}`,
    genre: "fantasy",
    language: "zh",
  })
  try {
    const map = await createMap(project.id, {
      name: `性能地图 ${profile.name}`,
      map_type: "world",
      grid_width: profile.grid.width,
      grid_height: profile.grid.height,
      template: profile.template,
    })

    const locations = []
    for (const item of profile.locations) {
      const entity = await createEntity(project.id, {
        name: item.name,
        entity_type: "location",
        status: "canonical",
      })
      await createLocationBindings(project.id, map.id, {
        location_entity_id: entity.id,
        hexes: [{ hex_q: item.q, hex_r: item.r, is_center: true }],
      })
      locations.push(entity)
    }

    const markerEntity = await createEntity(project.id, {
      name: profile.marker.name,
      entity_type: profile.marker.entity_type,
      status: "canonical",
    })
    await createMapMarker(project.id, map.id, {
      entity_id: markerEntity.id,
      marker_type: profile.marker.marker_type,
      hex_q: profile.marker.q,
      hex_r: profile.marker.r,
      label: profile.marker.name,
      visible: true,
    })

    const faction = await createEntity(project.id, {
      name: profile.territory.name,
      entity_type: profile.territory.entity_type,
      status: "canonical",
    })
    await createTerritories(project.id, map.id, {
      faction_entity_id: faction.id,
      hexes: profile.territory.hexes.map(([hex_q, hex_r]) => ({ hex_q, hex_r })),
    })

    const scene = await createScene(project.id, {
      scene_index: 0,
      title: `性能基准 ${profile.name}`,
      narrative_tag: "draft",
      chapter_ids: [],
      scene_chunks: [],
    })
    const dynamicItems = {}
    for (const [reviewKind, item] of Object.entries(profile.dynamic)) {
      const location = locations[item.location_index]
      const valueJson = item.dynamic_type === "location"
        ? {
            schema_version: 1,
            type: "location",
            location_entity_id: location.id,
            movement_mode: "walk",
          }
        : {
            schema_version: 1,
            type: "status",
            field_key: "alert_level",
            value: "alert",
          }
      const observation = await createMapObservation(project.id, map.id, {
        target_entity_id: markerEntity.id,
        target_entity_type: profile.marker.entity_type,
        target_name: profile.marker.name,
        dynamic_type: item.dynamic_type,
        time_anchor: { kind: "initial_state", scene_id: scene.id, scene_index: 0 },
        spatial_anchor: {
          location_entity_id: location.id,
          hex_q: item.q,
          hex_r: item.r,
        },
        value_json: valueJson,
        confidence: reviewKind === "confirmed" ? 1 : 0.72,
        review_state: "candidate",
        source_ref: {
          source: "map_performance_fixture",
          manifest_version: manifest.version,
        },
        evidence_text: `固定性能样本 ${reviewKind}`,
        scene_id: scene.id,
        scene_index: 0,
      })
      dynamicItems[reviewKind] = reviewKind === "confirmed"
        ? await confirmMapObservation(project.id, map.id, observation)
        : observation
    }
    return {
      project,
      map,
      locations,
      markerEntity,
      faction,
      scene,
      dynamicItems,
      manifestVersion: manifest.version,
      profileName,
      checksum: mapPerformanceProfileChecksum(profile),
      expectedPayloadChecksum: manifest.payload_checksums[profileName],
      semanticPayload: stableValue(profile),
    }
  } catch (error) {
    await cleanupProject(project.id)
    throw error
  }
}

export async function validateMapPerformanceFixture(fixture) {
  const manifest = await loadMapPerformanceManifest()
  const profile = manifest.profiles[fixture.profileName]
  if (!profile) throw new Error(`unknown map performance profile: ${fixture.profileName}`)
  return validateCreatedFixture(
    fixture,
    profile,
    manifest.payload_checksums[fixture.profileName],
  )
}

export function databaseFingerprint(rawUrl = process.env.DATABASE_URL || "") {
  if (!rawUrl) return null
  try {
    const parsed = new URL(rawUrl)
    return checksum({
      protocol: parsed.protocol,
      host: parsed.hostname,
      port: parsed.port,
      database: parsed.pathname.replace(/^\//, ""),
      user: parsed.username,
    })
  } catch {
    return checksum({ configured: true, parseable: false })
  }
}
