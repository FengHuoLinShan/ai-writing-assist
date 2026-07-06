# DeepSeek Scene Probe Decisions

Last updated: 2026-07-06

This document records the DeepSeek probe decisions for redesigning deep import
scene slicing. The probe-proven shape is now translated into the production
Phase0/Phase1 path as a character-budgeted window plan.

## Current Default

Use this as the current Phase1a baseline for long-form Chinese web novel scene
slicing:

- Provider/model: official DeepSeek API, `deepseek-v4-flash [1M]`.
- Thinking: enabled.
- Reasoning effort: `max`.
- Prompt: `minimal`.
- Prompt layout: source text first, task instructions after the text.
- Production window shape: dynamic complete-chapter windows targeting `72,000`
  input characters, capped at `20` chapters, with fixed right overlap `2`.
- Rounds: `1`.
- Fusion: disabled.
- Probe concurrency: `3` for parameter testing only.
- Phase1a deep-import concurrency: `50`.
- Phase1b enrichment concurrency: `200`.
- `max_tokens`: computed by Phase0 from actual input chars. Use `0.36` max
  tokens per input character, with floor `13000` and cap `32768` for the current
  `minimal` prompt.

The old probe shorthand `20 + overlap 3` remains historical evidence that
around 70k-75k Chinese characters per request works well. Production no longer
sets a fixed batch size; it fills each request by actual chapter character
counts and then uses the last 2 covered chapters as right-side context unless
the window is the final one.

## Evidence

Test source:

`/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_前60章.txt`

Observed source size, excluding whitespace:

| Metric | Value |
|---|---:|
| Chapters | 60 |
| Total chars | 213,802 |
| Average chars/chapter | 3,563 |
| Median chars/chapter | 3,482 |
| P90 chars/chapter | 4,099 |
| Min chars/chapter | 2,641 |
| Max chars/chapter | 4,865 |

Important runs:

| Run | Shape | Result |
|---|---|---|
| `ds60-overlap-grid-textfirst` | `b20_o3`, `max_tokens=32768` | 4 calls, 0 errors, 0 length finishes, avg density `0.982` |
| `ds60-overlap-grid-textfirst` | `b30_o3` | avg density `0.747`, weaker than 20-chapter windows |
| `ds60-overlap-grid-textfirst` | `b40_o3` | avg density `0.708`, visibly coarser |
| `ds-single-b60-textfirst-mt32768` | one 60-chapter request | density `0.317`, too coarse |
| `ds60-b20-o3-minimal-mt16384` | `b20_o3`, `max_tokens=16384` | 4 calls, 0 errors, 0 length finishes, avg density `1.064` |
| `ds60-b20-o3-minimal-mt12288` | `b20_o3`, `max_tokens=12288` | 4 calls, 0 errors, 0 length finishes, avg density `0.882` |
| `ds60-b20-o3-minimal-mt10240` | `b20_o3`, `max_tokens=10240` | 4 calls, 0 errors, 1 length finish; short-tail window produced no parsed scenes |
| `ds60-prompt-detail-b20-o3-mt32768` | `minimal` prompt | 4 calls, 0 errors, 0 length finishes, avg density `1.052`, avg seconds `99.52` |
| `ds60-prompt-detail-b20-o3-mt32768` | `medium` prompt | 4 calls, 0 errors, 0 length finishes, avg density `0.940`, avg seconds `132.52` |
| `ds60-prompt-detail-b20-o3-mt32768` | `detailed` prompt | 4 calls, 0 errors, 0 length finishes, avg density `1.108`, avg seconds `199.22` |
| `ds60-minimal-r3-fusion-b20-o3-mt24576` | `minimal`, 3 extraction rounds | 12 calls, 0 errors, 0 length finishes, avg density `0.960`, avg seconds `81.86` |
| `ds60-minimal-r3-fusion-b20-o3-mt24576` | `minimal_fusion` | 4 calls, 0 errors, 0 length finishes, avg density `0.940`, avg seconds `120.08` |
| `phase01-standard-charbudget72000-o2-c036-tool-logic` | production Phase0+1 standard path | 61 calls, 0 failed Phase1a windows, 0 Phase1b fallbacks, 57 scenes, total `360.08s` |

Production validation for `phase01-standard-charbudget72000-o2-c036-tool-logic`:

| Window | Owned range | Input chars | max_tokens |
|---|---|---:|---:|
| `1-19` | `1-17` | 69,017 | 24,846 |
| `18-36` | `18-34` | 69,153 | 24,895 |
| `35-54` | `35-52` | 68,712 | 24,736 |
| `53-60` | `53-60` | 26,531 | 13,000 |

The validation used standard `deepseek-v4-flash` only; high-quality
`deepseek-v4-pro` was intentionally skipped for this run.

The `12288` run produced all expected `.response.txt` and `.parsed.json` files,
but it is only a tested lower bound, not the production floor. The `10240` run
hit `finish_reason=length` in the 52-60 short-tail window, with all 10,240
completion tokens consumed by reasoning. The current production default keeps
`13000` as the protection floor and uses `0.36` max-token/input-char for the
dynamic budget.

## Phase0 Dynamic Sizing Decision

Phase0 should own parameter calculation before Phase1a starts. It should count
actual chapter length from the uploaded/imported text and derive the scene
slicing parameters from the observed text size.

Phase0 should compute:

- `chapter_char_count`: non-whitespace character count per chapter.
- `total_chars`.
- `avg_chars_per_chapter`.
- `median_chars_per_chapter`.
- `p90_chars_per_chapter`.
- `estimated_input_chars_per_window`.
- selected complete-chapter window ranges, owned ranges, right overlap, and
  `max_tokens`.

Current sizing constants:

- Baseline average chapter length: about `3,560` chars/chapter.
- Baseline measured 20-chapter input: about `73,519` chars for chapters 1-20.
- Baseline successful input window: about `70,000-75,000` chars per 20-chapter
  request.
- Target input chars per Phase1a request: `72,000`.
- Overlap: fixed `2` right-side chapters for non-final windows.
- Production output coefficient: `0.36` max tokens per input char.
- Production budget for the measured 20-chapter baseline:
  `round(73,519 * 0.36) = 26,467` max tokens.

Recommended v1 calculation:

```text
target_input_chars = 72000
max_chapters_per_window = 20
right_overlap_chapters = 2
baseline_chars = 73519
max_tokens_per_input_char = 0.36
min_max_tokens = 13000
max_max_tokens = 32768

covered chapters = append complete chapters from owned_start until adding the
next chapter would exceed target_input_chars, capped at max_chapters_per_window

owned_end = covered_end - right_overlap_chapters for non-final windows
owned_end = final requested chapter for the final window

actual_input_chars = sum(chapter_char_count for covered chapters)
max_tokens = round(actual_input_chars * max_tokens_per_input_char)
max_tokens = clamp(max_tokens, min_max_tokens, max_max_tokens)
```

For the tested source:

```text
target_input_chars = 72000
right_overlap_chapters = 2
max_chapters_per_window = 20
expected windows for chapters 1-60:
1-19 owned 1-17
18-36 owned 18-34
35-54 owned 35-52
53-60 owned 53-60
```

Do not increase above 20 chapters in v1, even for short chapters. The 30/40/60
chapter tests showed that chapter-count compression can make the model summarize
instead of slicing. Short-chapter expansion can be tested later as a separate
matrix.

For unusually long chapters, Phase0 automatically produces fewer covered
chapters because it stops when the next complete chapter would exceed the
character budget. Examples:

| Chapter shape | Covered chapters |
|---|---:|
| very short chapters | capped at 20 |
| 4,500 chars/chapter | about 16 |
| 6,000 chars/chapter | about 12 |
| one 80,000-char chapter | 1 |

If the full selected range fits in one calculated window, Phase1a should
run a single request and treat all chapters as owned; no right overlap is needed.

## max_tokens Decision

Current production-style default for `minimal`:

```text
max_tokens = clamp(
    round(actual_input_chars * 0.36),
    13000,
    32768,
)
```

The `12288` probe run is the validated tested lower bound for the current
prompt, but production should keep the safer `13000` floor. The `10240` probe
run failed by length in the short-tail window. The dynamic default now uses
`0.36` max tokens per input char after the later production safety adjustment.

### Phase-specific max_tokens coefficients

The coefficients below are based on real DeepSeek API `usage` from the Phase2/3
probe runs, not on tokenizer estimates.

Phase1a should keep the already validated scene-slicing rule:

```text
max_tokens = clamp(round(source_chars * 0.36), 13000, 32768)
```

Phase2 windowed world extraction should use the stricter prompt and the higher
floor observed in `ds60-phase2-world-charbudget-hi-mt`:

```text
max_tokens = clamp(round(source_chars * 0.36), 24576, 32768)
```

If implementation computes from final rendered prompt chars instead of source
chapter chars, use this equivalent production rule:

```text
max_tokens = clamp(round(prompt_chars * 0.31), 24576, 32768)
```

Phase3 narrative-structure extraction should use the smaller structure-specific
coefficient:

```text
max_tokens = clamp(round(prompt_chars * 0.20), 12288, 24576)
```

Phase3 retry tiers:

```text
8192 = rejected by real run
12288 = current default floor
16384 = first retry
24576 = final retry cap
```

Measured token ratios:

| Phase / successful combo | Basis | prompt_tokens ratio | completion_tokens ratio | reasoning_tokens ratio | max_tokens ratio |
|---|---|---:|---:|---:|---:|
| Phase2 `charbudget + scenes_plus_text + strict + 24576` | source chars | `0.696-0.727` | `0.203-0.471` | `0.112-0.307` | `0.354-0.923` |
| Phase2 `charbudget + scenes_plus_text + strict + 24576` | rendered prompt chars | `0.582-0.604` | `0.203-0.471` | `0.112-0.307` | `0.304-0.738` |
| Phase3 `scenes_plus_world + minimal + 12288` | rendered prompt chars | `0.395` | `0.168` | `0.115` | `0.199` |
| Phase3 `scenes_only + minimal + 12288` | rendered prompt chars | `0.459` | `0.221` | `0.138` | `0.390` |

The Phase2 short-tail window only had `26,633` source chars, but still consumed
`15,684` completion tokens and `10,207` reasoning tokens in the strict 24576
run. That is why Phase2 needs the `24576` protection floor even when the source
text is short.

Escalation tiers:

| Condition | Action |
|---|---|
| `finish_reason=length` | Retry same request with `24576` |
| Missing or invalid JSON caused by truncation | Retry same request with `24576` |
| `24576` still truncates | Retry with `32768` |
| Prompt changes from `minimal` to `medium` or adds required fields | Start at `24576` |
| Detailed prompt or fusion output | Start at `32768` unless separately tested |

Keep `max_tokens` even when streaming is enabled. Streaming improves receiving
large outputs and avoids waiting for a single buffered response, but it does not
remove the provider-side output cap.

## Prompt and Cache Decisions

- Put the full chapter text at the start of the rendered prompt.
- Put instructions and JSON schema after the text.
- Use a stable `user_id` per probe run so DeepSeek KVCache can hit across
  related requests in the same benchmark run.
- Do not rely on API-side chat history as a true long-lived session for Phase1a.
  Each extraction request should be self-contained, with source text included in
  the prompt.
- Keep `minimal` as the default Phase1a prompt for now.

The probe confirmed cache hits after switching to text-first prompts plus stable
run-scoped `user_id`. This improves parameter tests, but correctness must not
depend on cache being present.

Prompt-detail test result:

| Prompt | Avg density | Avg seconds | Avg completion tokens | Avg reasoning tokens | Decision |
|---|---:|---:|---:|---:|---|
| `minimal` | `1.052` | `99.52` | `8,473` | `7,192` | Default |
| `medium` | `0.940` | `132.52` | `10,806` | `8,990` | Not default |
| `detailed` | `1.108` | `199.22` | `18,369` | `15,536` | Not default |

`medium` added useful fields, but it was slower, less dense in the tested range,
and produced out-of-enum `scene_type` values in at least one sample. It can be
revisited as a review/repair prompt if strict schema validation is added.

`detailed` had the highest density, but it is not suitable as the default
because it omits top-level `start_chapter` / `end_chapter`, making current
analysis and downstream mapping weaker. Its `scene_chunks` anchors also showed
sampled drift, where a chunk's chapter index and anchor text did not align
cleanly. Use it only as a later boundary-location experiment after tightening
the schema.

Stability and fusion test result:

| Batch | Extraction scene counts | Count range | Fusion scenes | Decision |
|---|---:|---:|---:|---|
| `B0001-1-20` | `18 / 18 / 17` | `1` | `15` | Fusion is coarser |
| `B0002-18-37` | `12 / 15 / 16` | `4` | `14` | Fusion stabilizes but does not dominate best round |
| `B0003-35-54` | `16 / 15 / 16` | `1` | `16` | Single round stable |
| `B0004-52-60` | `9 / 10 / 9` | `1` | `10` | Single round stable; short-tail count is acceptable |

All stability/fusion calls produced `.response.txt` and `.parsed.json`, with no
errors and no length finishes. Fusion is not worth enabling by default: it is
slower than extraction in this probe, has slightly lower average density, and
can make stable windows coarser. Keep `rounds=1` and `fusion=false` for the
default Phase1a path. Fusion may be kept as a manual repair/review experiment
for specifically unstable windows, but not as an automatic full-run step.

## Rejected or Deferred Choices

- One-shot 60-chapter extraction is rejected for Phase1a scene slicing: it
  produced too few scenes and behaved like an outline summary.
- `batch_size=40` is rejected as the default: quality was materially coarser
  than 20-chapter windows.

## Phase2/3 Probe Results

Phase2/3 probe tools were added under `tools/deepseek_scene_probe/` so the next
deep-import simplification can be tested before touching production DB code:

- `phase2_world_probe.py`
- `phase3_structure_probe.py`
- `analyze_phase2.py`
- `analyze_phase3.py`

The tools consume Phase1b final Scene files, write raw LLM output under ignored
`runs/`, and preserve the same prompt-first logging shape as Phase1a/1b probes.

Phase2 matrix run:

```text
run = ds60-phase2-world-matrix
requests = 60
parse_ok = 7
length_finishes = 53
avg_seconds = 103.24
```

Important Phase2 findings:

| Combination | Rows | OK | Length | Result |
|---|---:|---:|---:|---|
| `phase0_charbudget + scenes_plus_text + minimal + 8192` | 4 | 0 | 4 | Too small |
| `phase0_charbudget + scenes_plus_text + minimal + 12288` | 4 | 0 | 4 | Too small |
| `phase0_charbudget + scenes_plus_text + minimal + 16384` | 4 | 2 | 2 | Useful but unstable |
| `phase0_charbudget + scenes_plus_text + strict + 16384` | 4 | 1 | 3 | Worse than minimal |
| `phase0_charbudget + scenes_only + strict + 16384` | 4 | 2 | 2 | Useful but unstable |
| `single_range + scenes_plus_text + strict + 16384` | 1 | 1 | 0 | Best first-pass candidate |
| `single_range + scenes_only + strict + 16384` | 1 | 1 | 0 | Usable, slightly less clean names |

The successful `single_range + scenes_plus_text + strict + 16384` output for
chapters 1-60 produced:

```text
objects = 42
relations = 11
deltas = 10
invalid_scene_ref_count = 0
low_confidence_count = 0
elapsed_seconds = 66.07
```

Quality sample was acceptable: it extracted durable assets such as 克莱恩·莫雷蒂,
廷根市值夜者小队, 塔罗会, 灰雾之上空间, 安提哥努斯家族笔记, 罗塞尔大帝秘密日记,
封印物0-08, and avoided obvious road-side NER noise. The `scenes_only`
variant also worked, but names were less canonical, e.g. `克莱恩·莫雷蒂 / 周明瑞`.

Temporary Phase2 conclusion:

- `8192` and `12288` are rejected for merged Phase2 world extraction with
  thinking enabled.
- `16384` is the tested lower bound only for strict single-range extraction;
  it is not safe for charbudget windows.
- For a simple v1 Phase2, prefer a single 60-scene style request with
  `scenes_plus_text + strict + max_tokens=16384`.
- For longer books, do not assume 60 chapters is a universal range. Use this as
  a first 60-chapter evidence point, then test larger ranges or fall back to
  Phase0-style windows with a higher cap (`24576` or `32768`).

Follow-up Phase2 high-token charbudget run:

```text
run = ds60-phase2-world-charbudget-hi-mt
requests = 16
parse_ok = 15
length_finishes = 1
avg_seconds = 152.10
```

| Combination | Rows | OK | Length | Avg seconds | Result |
|---|---:|---:|---:|---:|---|
| `phase0_charbudget + scenes_plus_text + minimal + 24576` | 4 | 3 | 1 | 136.39 | Not safe |
| `phase0_charbudget + scenes_plus_text + minimal + 32768` | 4 | 4 | 0 | 158.67 | Safe but verbose |
| `phase0_charbudget + scenes_plus_text + strict + 24576` | 4 | 4 | 0 | 148.41 | Best window candidate |
| `phase0_charbudget + scenes_plus_text + strict + 32768` | 4 | 4 | 0 | 164.92 | Safe retry tier |

Updated Phase2 temporary default:

- For production-like windowed Phase2, prefer
  `phase0_charbudget + scenes_plus_text + strict + max_tokens=24576`.
- Retry truncation or invalid JSON with `32768`.
- Keep `single_range + scenes_plus_text + strict + 16384` as a cheap 60-chapter
  experiment path, not as the default for full books.
- `minimal` is not the Phase2 default because it failed one charbudget window at
  `24576`; it only became stable at `32768`.

Phase3 matrix run:

```text
run = ds60-phase3-structure-matrix
phase2 input = single_range_scenes_plus_text_strict_mt16384
requests = 8
parse_ok = 3
length_finishes = 5
avg_seconds = 77.28
```

Important Phase3 findings:

| Combination | OK | Length | Result |
|---|---:|---:|---|
| `scenes_plus_world + minimal + 8192` | 0 | 1 | Too small |
| `scenes_plus_world + minimal + 12288` | 1 | 0 | Best first-pass candidate |
| `scenes_plus_world + thread_arc + 12288` | 1 | 0 | Usable but less complete arcs |
| `scenes_only + minimal + 12288` | 1 | 0 | Usable, cheaper input |
| `scenes_only + thread_arc + 12288` | 0 | 1 | Too verbose/unstable |

The successful `scenes_plus_world + minimal + 12288` output produced:

```text
plot_threads = 3
arcs = 4
foreshadowing = 7
reveals = 7
turning_points = 8
invalid_scene_ref_count = 0
low_confidence_count = 0
elapsed_seconds = 80.84
```

Temporary Phase3 conclusion:

- `8192` is rejected for Phase3 structure extraction with thinking enabled.
- `12288` is the current tested lower bound.
- `minimal` is better than `thread_arc` as the default because it is less likely
  to hit length and produced fuller structure.
- `scenes_plus_world` is the best quality candidate; `scenes_only` remains a
  useful cheaper fallback if Phase2 output is unavailable or low confidence.
- `batch_size=30` is not the default: it was better than 40 but still weaker
  than 20 in the tested text.
- `overlap=5` is not the default: quality was close enough that the cheaper
  `overlap=3` should win.
- `medium` prompt is not the default: it costs more than `minimal`, produced
  lower density in this run, and can drift on enum fields.
- `detailed` prompt is not the default: it is much slower, much more expensive,
  and its current schema lacks top-level chapter bounds.
- Multi-round extraction plus fusion is rejected as the default: 3-round
  extraction was mostly stable, while fusion was slower and sometimes coarser.
- Turning thinking off or lowering reasoning effort is deferred. It should be a
  separate cost/quality test, not mixed into batch sizing.

## Phase1b Enrichment Test Harness

Phase1b has a separate isolated probe runner:

```text
tools/deepseek_scene_probe/phase1b.py
```

Current intended Phase1b behavior:

- One independent request per Phase1a Scene.
- Parse only enrichment fields: `emotional_beat`, `must_happen`,
  `must_not_happen`, `narrative_tag`, `confidence`, `needs_review`,
  `review_reason`.
- Do not parse or trust locked fields from Phase1b output: `title`, `goal`,
  `core_conflict`, `start_chapter`, `end_chapter`, `boundary_status`,
  `scene_chunks`.
- Build final Scene payloads by copying locked fields from Phase1a and
  generating chapter-level `scene_chunks` from `start_chapter` / `end_chapter`.
- Do not do text-location, offset generation, recutting, or fusion in Phase1b.

The harness writes `.prompt.txt`, `.request.json`, `.response.txt`,
`.parsed.json`, `.final.json`, `summary.jsonl`, and `analysis_phase1b.md`.
Fallbacks are per-Scene and should be sent to manual review instead of blocking
the whole run.

Phase1b test results:

| Run | Shape | Result |
|---|---|---|
| `ds60-phase1b-sample-mt2048` | 12 Scene sample, `max_tokens=2048`, concurrency `5` | 12 calls, 12 parsed, 0 errors, 0 fallback, 0 length, avg seconds `18.21` |
| `ds60-phase1b-full-mt2048` | 57 Scene full run, `max_tokens=2048`, concurrency `5` | 56 parsed, 1 fallback, 1 length finish (`S0008`), 0 chunk mismatches, avg seconds `13.55` |
| `ds60-phase1b-repair-S0008-mt4096` | failed Scene retry, `max_tokens=4096` | 1 parsed, 0 errors, 0 fallback, 0 length, avg seconds `10.56` |

Decision: use `max_tokens=4096` as the Phase1b enrichment default. The `2048`
sample passed, but the full run proved it is not a safe production default. A
per-Scene retry from `2048` to `4096` is viable, but the simpler v1 default is
to start at `4096`.

Default test sequence:

1. 12-Scene sample, `max_tokens=4096`, `concurrency=5`.
2. Full 60-chapter Phase1b run over the accepted Phase1a output, also with
   `max_tokens=4096`.
3. If a future prompt hits length / invalid JSON / incomplete fields, retry the
   failed Scene with a higher cap and record the new result.

The Phase1b harness has passed local dry-run, unit tests, a 12-Scene real LLM
sample, and a full 57-Scene run with one successful targeted 4096-token repair.

## Next Tests

Run these only after the current default is wired or when a new prompt shape is
introduced:

1. Optionally run a full Phase1b enrichment pass at `max_tokens=4096` to replace
   the 2048+repair evidence with a single clean full-run artifact.
2. Design and test `minimal_v2` only if a specific weakness is found in
   `minimal`; do not add fields speculatively.
3. `thinking=max` vs lower effort or disabled thinking at fixed prompt/size.
4. Short-chapter expansion test before allowing `batch_size > 20`.
