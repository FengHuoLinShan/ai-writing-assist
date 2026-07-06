# DeepSeek Scene Probe

Standalone probe for testing DeepSeek scene-boundary prompts against different
chapter-window lengths and prompt detail levels.

This tool is intentionally isolated from the project backend:

- no imports from `backend/`
- no database writes
- no `.env` dependency
- API key stays in ignored `config.local.json`
- model responses are written under ignored `runs/`

## Codex Workflow

1. Edit or add prompt templates under `tools/deepseek_scene_probe/prompts/`.
2. Run `probe.py` with one or more prompt names, batch sizes, and overlaps.
3. Run `analyze.py` to generate `analysis.md`.
4. Inspect `analysis.md`, selected `.prompt.txt`, and `.response.txt` files.
5. Adjust prompt text and rerun with a new `--run-name`.
6. For unstable prompts, run 2-3 rounds plus fusion and compare the fused output.

Prompt templates are plain text. Supported placeholders:

- `{START}`
- `{END}`
- `{OWNED_START}`
- `{OWNED_END}`
- `{OVERLAP_RANGE_TEXT}`
- `{TEXT}`

JSON braces in prompt examples do not need escaping.

Extraction prompts are text-first: the rendered user prompt starts with the
chapter text and places task instructions after it. This keeps the longest
shared prefix on identical source windows, which is friendlier to provider
prefix caching when comparing prompt variants or repeated rounds.

All requests in one run share a stable `user_id` derived from `user_id_prefix`
and `--run-name`. This keeps DeepSeek KVCache scoped to the benchmark run while
allowing repeated source windows inside that run to hit cache.

## Setup

```bash
cp tools/deepseek_scene_probe/config.example.json \
  tools/deepseek_scene_probe/config.local.json
```

Fill `api_key` in `config.local.json`.

Default DeepSeek settings:

```json
{
  "base_url": "https://api.deepseek.com",
  "model": "deepseek-v4-flash",
  "model_display_name": "deepseek-v4-flash [1M]",
  "model_context_length": "1M",
  "thinking": {
    "type": "enabled"
  },
  "reasoning_effort": "max",
  "ssl_verify": true,
  "ca_bundle": "",
  "api_key": ""
}
```

`model` is the official API value and should stay `deepseek-v4-flash` or
`deepseek-v4-pro`. The `[1M]` marker is recorded separately in
`model_display_name` / `model_context_length` for analysis. Defaults use
thinking mode with `reasoning_effort=max` to test the model's stronger
reasoning path; override these two fields in `config.local.json` for faster
non-thinking probes.

HTTPS verification stays enabled. The probe uses `certifi` when available; set
`ca_bundle` only when your local network requires a specific CA bundle.

## Dry Run

Build prompts and summary metrics without calling DeepSeek:

```bash
python3 tools/deepseek_scene_probe/probe.py \
  --config tools/deepseek_scene_probe/config.local.json \
  --source "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt" \
  --chapter-start 1 \
  --chapter-end 60 \
  --batch-sizes 10,20,40 \
  --overlaps 2,3 \
  --prompt-levels minimal,medium,detailed \
  --limit-batches 1 \
  --dry-run
```

Dry runs still create a run directory, full prompt files, request metadata, and
`summary.jsonl`, so they are useful for prompt debugging before spending tokens.

## Real Calls

Run one 20-chapter batch with the minimal prompt:

```bash
python3 tools/deepseek_scene_probe/probe.py \
  --config tools/deepseek_scene_probe/config.local.json \
  --source "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt" \
  --chapter-start 1 \
  --chapter-end 20 \
  --batch-sizes 20 \
  --overlaps 3 \
  --prompt-levels minimal
```

Give a run a stable name when comparing variants:

```bash
python3 tools/deepseek_scene_probe/probe.py \
  --config tools/deepseek_scene_probe/config.local.json \
  --source "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt" \
  --chapter-start 1 \
  --chapter-end 60 \
  --batch-sizes 20 \
  --overlaps 3 \
  --prompt-levels minimal \
  --run-name minimal-20x3-v1
```

Compare prompt detail on the first batch only:

```bash
python3 tools/deepseek_scene_probe/probe.py \
  --config tools/deepseek_scene_probe/config.local.json \
  --source "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt" \
  --chapter-start 1 \
  --chapter-end 60 \
  --batch-sizes 20 \
  --overlaps 3 \
  --prompt-levels minimal,medium,detailed \
  --limit-batches 1
```

Run the 60-chapter batch/overlap grid with probe-level concurrency:

```bash
python3 tools/deepseek_scene_probe/probe.py \
  --config tools/deepseek_scene_probe/config.local.json \
  --source "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_前60章.txt" \
  --chapter-start 1 \
  --chapter-end 60 \
  --batch-sizes 20,30,40 \
  --overlaps 0,2,3,5 \
  --prompt-levels minimal \
  --rounds 1 \
  --concurrency 3 \
  --max-tokens 32768 \
  --no-fusion \
  --run-name ds60-overlap-grid
```

The default `--matrix-filter phase1a-overlap` skips low-value combinations
where `batch_size > 20` and `overlap=2`. Pass `--matrix-filter none` to run the
full cross product.

Run three independent samples and fuse them:

```bash
python3 tools/deepseek_scene_probe/probe.py \
  --config tools/deepseek_scene_probe/config.local.json \
  --source "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt" \
  --chapter-start 1 \
  --chapter-end 60 \
  --batch-sizes 20 \
  --overlaps 3 \
  --prompt-levels minimal \
  --rounds 3 \
  --fusion \
  --run-name minimal-20x3-r3-fusion
```

Fusion is logged as an additional call with prompt names like
`minimal_fusion`. It reads the round outputs, not the original chapter text, so
it is useful for cheap consistency testing rather than full re-extraction.

Enable streaming in `config.local.json`:

```json
{
  "stream": true,
  "stream_options_include_usage": true
}
```

Then optionally print streamed text:

```bash
python3 tools/deepseek_scene_probe/probe.py ... --print-stream
```

## Output

Each invocation creates a timestamped or named run directory:

```text
tools/deepseek_scene_probe/runs/<run-name>/
```

The latest run path is written to:

```text
tools/deepseek_scene_probe/runs/latest
```

Each request/response pair is stored as:

```text
runs/<run-name>/<combo>_<prompt>_<batch>.prompt.txt
runs/<run-name>/<combo>_<prompt>_<batch>.request.json
runs/<run-name>/<combo>_<prompt>_<batch>.response.txt
runs/<run-name>/<combo>_<prompt>_<batch>.parsed.json
```

When `--rounds` is greater than 1, filenames include the round suffix:

```text
runs/<run-name>/<combo>_<prompt>_<batch>_r01.response.txt
runs/<run-name>/<combo>_<prompt>_<batch>_r02.response.txt
runs/<run-name>/<combo>_<prompt>_fusion_<batch>_fusion.response.txt
```

The request file truncates prompt text for inspection. The `.prompt.txt` file
keeps the full prompt sent to the model. Raw model output is saved verbatim in
`.response.txt`; when it parses as JSON, `.parsed.json` stores the structured
form for analysis. Run outputs should not be committed.

Each run also writes:

```text
runs/<run-name>/run_meta.json
runs/<run-name>/summary.jsonl
```

Key metrics:

- `elapsed_seconds`
- `batch_size`
- `overlap`
- `combo_label`
- `request_chars`
- `estimated_input_tokens`
- `max_tokens`
- `finish_reason`
- `usage`
- `scene_count`
- `scene_density`
- `error_kind`
- `response_path`
- `parsed_path`
- `response_preview`
- `round_label`
- `source_round_labels` for fusion calls

## Analyze

Analyze the latest run:

```bash
python3 tools/deepseek_scene_probe/analyze.py
```

Analyze a specific run:

```bash
python3 tools/deepseek_scene_probe/analyze.py \
  tools/deepseek_scene_probe/runs/minimal-20x3-v1
```

The analyzer prints a Markdown report and writes:

```text
runs/<run-name>/analysis.md
```

Important signals:

- `scene_density < 0.6`: model probably summarized instead of slicing.
- `finish_reason=length`: raise `max_tokens` or simplify the prompt.
- With `thinking.enabled` and `reasoning_effort=max`, `minimal` needs about
  `32768` output tokens for 20-chapter batches; `8192` can be consumed entirely
  by reasoning tokens before JSON output starts.
- `error_kind=missing_api_key`: config key is still blank.
- `Quality Samples`: response file links plus the first few parsed scenes for
  each parameter combination.
- Compare `minimal` vs `minimal_fusion` to see whether 2-3 samples stabilize
  weak boundaries.

## Phase1b Enrichment Probe

Phase1b enrichment is tested by a separate runner:

```text
tools/deepseek_scene_probe/phase1b.py
```

It consumes Phase1a scenes, sends one request per Scene, and only parses
enrichment fields:

- `emotional_beat`
- `must_happen`
- `must_not_happen`
- `narrative_tag`
- `confidence`
- `needs_review`
- `review_reason`

Locked fields (`title`, `goal`, `core_conflict`, chapter range,
`boundary_status`, `scene_chunks`) are never parsed from Phase1b LLM output.
The final `.final.json` file copies locked fields from Phase1a and generates
chapter-level `scene_chunks` deterministically from `start_chapter` /
`end_chapter`.

Dry-run a small sample from a Phase1a probe run:

```bash
python3 tools/deepseek_scene_probe/phase1b.py \
  --config tools/deepseek_scene_probe/config.local.json \
  --source "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_前60章.txt" \
  --phase1a-run-dir tools/deepseek_scene_probe/runs/ds60-overlap-grid-textfirst \
  --sample-size 12 \
  --max-tokens 2048 \
  --dry-run \
  --run-name dryrun-phase1b-sample
```

Run the 12-Scene real LLM sample. The historical lower-bound test used
`2048`, but the current default is `4096` because one full-run Scene reached
`finish_reason=length` at `2048`.

```bash
python3 tools/deepseek_scene_probe/phase1b.py \
  --config tools/deepseek_scene_probe/config.local.json \
  --source "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_前60章.txt" \
  --phase1a-run-dir tools/deepseek_scene_probe/runs/ds60-overlap-grid-textfirst \
  --sample-size 12 \
  --max-tokens 4096 \
  --concurrency 5 \
  --run-name ds60-phase1b-sample-mt4096
```

If you want to recheck the lower bound, run the same sample with
`--max-tokens 2048`; do not use `2048` as the production default unless the
full-run failure has been addressed by a retry policy.

Run the full 60-chapter Phase1b enrichment over all Phase1a scenes:

```bash
python3 tools/deepseek_scene_probe/phase1b.py \
  --config tools/deepseek_scene_probe/config.local.json \
  --source "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_前60章.txt" \
  --phase1a-run-dir tools/deepseek_scene_probe/runs/ds60-overlap-grid-textfirst \
  --max-tokens 4096 \
  --concurrency 5 \
  --run-name ds60-phase1b-full-mt4096
```

Analyze the latest Phase1b run:

```bash
python3 tools/deepseek_scene_probe/analyze_phase1b.py
```

Or analyze a named run:

```bash
python3 tools/deepseek_scene_probe/analyze_phase1b.py \
  tools/deepseek_scene_probe/runs/ds60-phase1b-sample-mt2048
```

Phase1b outputs:

```text
runs/<run-name>/phase1b_<scene-id>_<start>-<end>.prompt.txt
runs/<run-name>/phase1b_<scene-id>_<start>-<end>.request.json
runs/<run-name>/phase1b_<scene-id>_<start>-<end>.response.txt
runs/<run-name>/phase1b_<scene-id>_<start>-<end>.parsed.json
runs/<run-name>/phase1b_<scene-id>_<start>-<end>.final.json
```

Important Phase1b signals:

- `parse_ok=true`: response parsed into enrichment fields without fallback.
- `fallback=true`: this Scene should enter manual review.
- `finish_reason=length`: keep `--max-tokens 4096` or retry the failed Scene
  with a higher cap if a prompt changes.
- `scene_chunks_mismatch_count` should stay `0`.
- `final_path` is the merged Scene candidate ready for Phase2-style input.

## Prompt Levels

- `minimal`: title / goal / core_conflict / start_chapter / end_chapter / boundary_status
- `medium`: minimal plus scene_type / confidence / boundary_reason
- `detailed`: chunk anchors and quality notes, useful for stress testing but more likely to be slow
- `fusion`: combines multiple candidate outputs for the same prompt/batch
- `phase1b_enrich`: per-Scene enrichment only; used by `phase1b.py`
- `phase2_world_minimal` / `phase2_world_strict`: simplified Phase2 world
  extraction probes
- `phase3_structure_minimal` / `phase3_structure_thread_arc`: simplified
  Phase3 narrative-structure probes

## Phase2 World Probe

`phase2_world_probe.py` tests the simplified Phase2 design without touching the
backend or database. It consumes Phase1b `.final.json` scenes, optionally
overlays repair runs, and writes one `.prompt.txt`, `.request.json`,
`.response.txt`, `.parsed.json`, and `.final.json` per request.

Dry-run the full matrix shape:

```bash
python3 tools/deepseek_scene_probe/phase2_world_probe.py \
  --config tools/deepseek_scene_probe/config.local.json \
  --source "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_前60章.txt" \
  --phase1b-run-dir tools/deepseek_scene_probe/runs/ds60-phase1b-full-mt2048 \
  --phase1b-repair-run-dir tools/deepseek_scene_probe/runs/ds60-phase1b-repair-S0008-mt4096 \
  --chapter-start 1 \
  --chapter-end 60 \
  --window-modes phase0_charbudget,single_range \
  --input-modes scenes_plus_text,scenes_only \
  --prompt-levels minimal,strict \
  --max-tokens-list 8192,12288,16384 \
  --concurrency 3 \
  --dry-run \
  --run-name dryrun-ds60-phase2-world-matrix
```

Run real calls by removing `--dry-run`. Analyze the latest Phase2 run:

```bash
python3 tools/deepseek_scene_probe/analyze_phase2.py
```

Important Phase2 signals:

- `parse_ok=true`, `error_kind=null`, `finish_reason != length`
- `invalid_scene_ref_count=0`
- object/relation/delta counts are useful but not NER-like noise
- compare `scenes_only` against `scenes_plus_text` manually using response links

## Phase3 Structure Probe

`phase3_structure_probe.py` consumes Phase1b scenes plus one selected Phase2
combo. If `--phase2-combo-label` is omitted, it automatically prefers the
first successful `phase0_charbudget + scenes_plus_text + minimal + mt12288`
style combo available in the Phase2 run.

```bash
python3 tools/deepseek_scene_probe/phase3_structure_probe.py \
  --config tools/deepseek_scene_probe/config.local.json \
  --source "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑_前60章.txt" \
  --phase1b-run-dir tools/deepseek_scene_probe/runs/ds60-phase1b-full-mt2048 \
  --phase1b-repair-run-dir tools/deepseek_scene_probe/runs/ds60-phase1b-repair-S0008-mt4096 \
  --phase2-run-dir tools/deepseek_scene_probe/runs/ds60-phase2-world-matrix \
  --chapter-start 1 \
  --chapter-end 60 \
  --input-modes scenes_plus_world,scenes_only \
  --prompt-levels minimal,thread_arc \
  --max-tokens-list 8192,12288 \
  --concurrency 2 \
  --run-name ds60-phase3-structure-matrix
```

Analyze:

```bash
python3 tools/deepseek_scene_probe/analyze_phase3.py \
  tools/deepseek_scene_probe/runs/ds60-phase3-structure-matrix
```

Important Phase3 signals:

- all structural items have valid `supporting_scene_ids`
- no future spoilers beyond the provided chapter range
- `scenes_plus_world` is better only if it adds structure without hallucination

## Custom Prompts

Create a new file:

```text
tools/deepseek_scene_probe/prompts/minimal_v2.txt
```

Then run:

```bash
python3 tools/deepseek_scene_probe/probe.py \
  --config tools/deepseek_scene_probe/config.local.json \
  --source "/Users/tywww/Desktop/项目/wirting skill/诡秘之主_第一部 小丑.txt" \
  --chapter-start 1 \
  --chapter-end 60 \
  --batch-sizes 20 \
  --overlaps 3 \
  --prompt-levels minimal_v2 \
  --run-name minimal-v2-20x3
```

You can also pass a direct prompt path as one prompt level:

```bash
--prompt-levels tools/deepseek_scene_probe/prompts/minimal_v2.txt
```
