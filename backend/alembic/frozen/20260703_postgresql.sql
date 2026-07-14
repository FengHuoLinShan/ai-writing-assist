CREATE TABLE async_tasks (
	task_type VARCHAR(64) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	progress FLOAT, 
	meta JSON, 
	result JSON, 
	error_message TEXT, 
	started_at TIMESTAMP WITH TIME ZONE, 
	finished_at TIMESTAMP WITH TIME ZONE, 
	heartbeat_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	PRIMARY KEY (id)
);

CREATE TABLE projects (
	title VARCHAR(255) NOT NULL, 
	genre VARCHAR(64), 
	tone VARCHAR(64), 
	language VARCHAR(16) NOT NULL, 
	target_length VARCHAR(32), 
	current_stage VARCHAR(32), 
	default_reveal_policy VARCHAR(32) NOT NULL, 
	settings JSON NOT NULL, 
	deleted_at TIMESTAMP WITH TIME ZONE, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	PRIMARY KEY (id)
);

CREATE TABLE conflict_check_queue (
	novel_id UUID NOT NULL, 
	conflict_type VARCHAR(64) NOT NULL, 
	severity VARCHAR(32) NOT NULL, 
	source_module VARCHAR(64) NOT NULL, 
	target JSON NOT NULL, 
	target_hash VARCHAR(64), 
	summary TEXT NOT NULL, 
	evidence_refs_json JSON NOT NULL, 
	resolution_json JSON NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE context_confirmations (
	id UUID NOT NULL, 
	novel_id UUID NOT NULL, 
	action VARCHAR(128) NOT NULL, 
	task TEXT NOT NULL, 
	scope VARCHAR(32) NOT NULL, 
	context_mode VARCHAR(32) NOT NULL, 
	include_pending_objects BOOLEAN NOT NULL, 
	excluded_asset_ids JSON NOT NULL, 
	selected_asset_ids JSON NOT NULL, 
	user_note TEXT, 
	compile_options JSON NOT NULL, 
	warnings JSON NOT NULL, 
	result_refs JSON NOT NULL, 
	result_status VARCHAR(32) NOT NULL, 
	stale_reasons JSON NOT NULL, 
	compiled_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE context_snapshots (
	id UUID NOT NULL, 
	novel_id UUID NOT NULL, 
	task_id VARCHAR(64), 
	workflow_id VARCHAR(64), 
	phase VARCHAR(64) NOT NULL, 
	operation VARCHAR(128) NOT NULL, 
	scene_id VARCHAR(64), 
	scene_index INTEGER, 
	chapter_index INTEGER, 
	context_mode VARCHAR(32) NOT NULL, 
	include_pending_objects BOOLEAN NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	attempt INTEGER NOT NULL, 
	prompt_hash VARCHAR(64) NOT NULL, 
	prompt_name VARCHAR(128) NOT NULL, 
	model VARCHAR(128) NOT NULL, 
	compile_options JSON NOT NULL, 
	included_asset_ids JSON NOT NULL, 
	excluded_asset_ids JSON NOT NULL, 
	context_summary JSON NOT NULL, 
	section_metadata JSON NOT NULL, 
	token_metadata JSON NOT NULL, 
	rendered_context TEXT, 
	result_refs JSON NOT NULL, 
	error_kind VARCHAR(128), 
	error_message TEXT, 
	rendered_context_expires_at TIMESTAMP WITH TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE core_entities (
	entity_type VARCHAR(64) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	summary TEXT, 
	public_info TEXT, 
	hidden_truth TEXT, 
	content_json JSON, 
	importance FLOAT NOT NULL, 
	importance_level VARCHAR(16) NOT NULL, 
	reveal_level VARCHAR(16) NOT NULL, 
	embedding_text TEXT, 
	embedding VECTOR(768), 
	search_text TEXT GENERATED ALWAYS AS (name || ' ' || COALESCE(content_json->>'aliases', '')) STORED, 
	pinyin_string VARCHAR(1024), 
	created_by VARCHAR(64), 
	approved_by VARCHAR(64), 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE creation_suggestion_queue (
	novel_id UUID NOT NULL, 
	source_module VARCHAR(64) NOT NULL, 
	review_group VARCHAR(64) NOT NULL, 
	target_type VARCHAR(64) NOT NULL, 
	action_schema VARCHAR(128) NOT NULL, 
	payload_json JSON NOT NULL, 
	evidence_refs_json JSON NOT NULL, 
	risk_level VARCHAR(32) NOT NULL, 
	result_ref_json JSON NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE delta_log (
	entity_id UUID, 
	character_id UUID, 
	scene_index INTEGER, 
	category VARCHAR(32) NOT NULL, 
	field_path VARCHAR(255), 
	old_value TEXT, 
	new_value TEXT, 
	source VARCHAR(32) NOT NULL, 
	meta JSON, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID NOT NULL, 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE entity_profile_templates (
	novel_id UUID NOT NULL, 
	profile_type VARCHAR(64) NOT NULL, 
	template_schema_json JSON NOT NULL, 
	display_schema_json JSON NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_profile_template_type UNIQUE (novel_id, profile_type), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE foreshadowing_plans (
	name VARCHAR(255) NOT NULL, 
	summary TEXT, 
	surface_meaning TEXT, 
	hidden_meaning TEXT, 
	planned_seed_chapter INTEGER, 
	planned_reinforce_chapters JSON, 
	planned_payoff_chapter INTEGER, 
	planned_payoff_scene INTEGER, 
	related_entity_ids JSON, 
	related_thread_ids JSON, 
	provenance_meta JSON, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE import_records (
	file_name VARCHAR(255) NOT NULL, 
	file_type VARCHAR(16) NOT NULL, 
	file_size INTEGER NOT NULL, 
	total_chapters INTEGER NOT NULL, 
	imported_chapters INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	error_message TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE knowledge_tags (
	novel_id UUID NOT NULL, 
	slug VARCHAR(128) NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	description TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_knowledge_tag_slug UNIQUE (novel_id, slug), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE knowledge_visibility_policies (
	novel_id UUID NOT NULL, 
	target JSON NOT NULL, 
	target_hash VARCHAR(64) NOT NULL, 
	visibility_mode VARCHAR(32) NOT NULL, 
	policy_json JSON NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE memory_events (
	id UUID NOT NULL, 
	novel_id UUID NOT NULL, 
	chapter_index INTEGER NOT NULL, 
	sequence INTEGER NOT NULL, 
	event_type VARCHAR(64) NOT NULL, 
	entity_id UUID, 
	entity_type VARCHAR(32), 
	snapshot_before JSON, 
	snapshot_after JSON NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_memory_events_novel_chapter_sequence UNIQUE (novel_id, chapter_index, sequence), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE memory_snapshots (
	id UUID NOT NULL, 
	novel_id UUID NOT NULL, 
	chapter_index INTEGER NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	full_state JSON NOT NULL, 
	events_until INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE outline_arcs (
	title VARCHAR(255) NOT NULL, 
	arc_index INTEGER, 
	start_chapter INTEGER, 
	end_chapter INTEGER, 
	arc_goal TEXT, 
	core_conflict TEXT, 
	main_opposition TEXT, 
	entry_hook TEXT, 
	midpoint_turn TEXT, 
	climax TEXT, 
	result TEXT, 
	next_hook TEXT, 
	related_thread_ids JSON, 
	related_character_ids JSON, 
	related_entity_ids JSON, 
	provenance_meta JSON, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE plot_threads (
	name VARCHAR(255) NOT NULL, 
	thread_type VARCHAR(32) NOT NULL, 
	summary TEXT, 
	visible_goal TEXT, 
	hidden_truth TEXT, 
	start_chapter INTEGER, 
	planned_payoff_chapter INTEGER, 
	current_stage VARCHAR(32), 
	related_character_ids JSON, 
	related_entity_ids JSON, 
	related_memory_ids JSON, 
	reader_known_state TEXT, 
	author_known_state TEXT, 
	provenance_meta JSON, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE rag_chunks (
	novel_id UUID NOT NULL, 
	source_type VARCHAR(64) NOT NULL, 
	source_id UUID, 
	chapter_index INTEGER, 
	chunk_index INTEGER, 
	start_offset INTEGER, 
	end_offset INTEGER, 
	char_count INTEGER, 
	text TEXT NOT NULL, 
	summary TEXT, 
	entity_ids JSON NOT NULL, 
	character_ids JSON NOT NULL, 
	thread_ids JSON NOT NULL, 
	scene_id UUID, 
	visibility VARCHAR(32) NOT NULL, 
	importance FLOAT NOT NULL, 
	index_version VARCHAR(32) NOT NULL, 
	embedding_status VARCHAR(32) NOT NULL, 
	embedding_error TEXT, 
	index_warnings JSON NOT NULL, 
	embedding VECTOR(768), 
	meta JSON NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE reader_reveal_policies (
	novel_id UUID NOT NULL, 
	target JSON NOT NULL, 
	target_hash VARCHAR(64) NOT NULL, 
	reveal_chapter_index INTEGER, 
	reveal_scene_id UUID, 
	reveal_plan_id VARCHAR(128), 
	public_baseline BOOLEAN NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE reveal_plans (
	target_type VARCHAR(32) NOT NULL, 
	target_id UUID NOT NULL, 
	secret_summary TEXT NOT NULL, 
	reveal_stages JSON, 
	provenance_meta JSON, 
	status VARCHAR(32) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE scenes (
	scene_index INTEGER NOT NULL, 
	title VARCHAR(255), 
	goal TEXT, 
	core_conflict TEXT, 
	emotional_beat TEXT, 
	must_happen TEXT, 
	must_not_happen TEXT, 
	narrative_tag VARCHAR(32) NOT NULL, 
	source VARCHAR(32) NOT NULL, 
	scene_chunks JSON, 
	chapter_ids JSON, 
	pov_character_id VARCHAR(36), 
	structure_meta JSON, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE text_archive (
	entity_id UUID, 
	field_name VARCHAR(64) NOT NULL, 
	text_content TEXT, 
	scene_index INTEGER, 
	source VARCHAR(32) NOT NULL, 
	meta JSON, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, 
	id UUID NOT NULL, 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE world_bible_pages (
	novel_id UUID NOT NULL, 
	page_type VARCHAR(64) NOT NULL, 
	page_key VARCHAR(128) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	page_meta_json JSON NOT NULL, 
	free_text TEXT, 
	linked_asset_refs_json JSON NOT NULL, 
	activation_defaults_json JSON NOT NULL, 
	template_key VARCHAR(128), 
	template_version INTEGER NOT NULL, 
	version_number INTEGER NOT NULL, 
	sort_order INTEGER NOT NULL, 
	created_by VARCHAR(64), 
	updated_by VARCHAR(64), 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_world_bible_page_key UNIQUE (novel_id, page_key), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE writing_drafts (
	chapter_index INTEGER NOT NULL, 
	title TEXT, 
	content TEXT, 
	conflict_check_snapshot_json JSON, 
	provenance_json JSON, 
	version_number INTEGER NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_writing_draft_version UNIQUE (novel_id, chapter_index, version_number), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE asset_knowledge_tags (
	novel_id UUID NOT NULL, 
	target JSON NOT NULL, 
	target_hash VARCHAR(64) NOT NULL, 
	tag_id UUID NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(tag_id) REFERENCES knowledge_tags (id) ON DELETE CASCADE
);

CREATE TABLE characters (
	entity_id UUID NOT NULL, 
	novel_id UUID NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	aliases JSON NOT NULL, 
	role VARCHAR(64), 
	appearance TEXT, 
	personality TEXT, 
	desire TEXT, 
	fear TEXT, 
	secret TEXT, 
	weakness TEXT, 
	current_goal TEXT, 
	current_state TEXT, 
	current_emotion VARCHAR(64), 
	stance TEXT, 
	voice_style TEXT, 
	behavior_rules JSON NOT NULL, 
	relationship_summary TEXT, 
	meta JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (entity_id), 
	FOREIGN KEY(entity_id) REFERENCES core_entities (id) ON DELETE CASCADE, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE faction_profiles (
	ideology_summary TEXT, 
	leader_entity_ids_json JSON NOT NULL, 
	member_rules TEXT, 
	territory_refs_json JSON NOT NULL, 
	resources_json JSON NOT NULL, 
	public_baseline BOOLEAN NOT NULL, 
	novel_id UUID NOT NULL, 
	entity_id UUID NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	confidence FLOAT, 
	evidence_refs_json JSON NOT NULL, 
	extra_json JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (entity_id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(entity_id) REFERENCES core_entities (id) ON DELETE CASCADE
);

CREATE TABLE generic_entity_profiles (
	novel_id UUID NOT NULL, 
	entity_id UUID NOT NULL, 
	profile_type VARCHAR(64) NOT NULL, 
	template_id UUID, 
	data_json JSON NOT NULL, 
	extra_json JSON NOT NULL, 
	evidence_refs_json JSON NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	confidence FLOAT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_generic_profile_entity UNIQUE (novel_id, entity_id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(entity_id) REFERENCES core_entities (id) ON DELETE CASCADE, 
	FOREIGN KEY(template_id) REFERENCES entity_profile_templates (id) ON DELETE SET NULL
);

CREATE TABLE imported_chapters (
	novel_id UUID NOT NULL, 
	import_record_id UUID NOT NULL, 
	chapter_index INTEGER NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	content TEXT NOT NULL, 
	is_analyzed BOOLEAN NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(import_record_id) REFERENCES import_records (id) ON DELETE CASCADE
);

CREATE TABLE item_profiles (
	item_class VARCHAR(128), 
	powers_json JSON NOT NULL, 
	limitations_json JSON NOT NULL, 
	owner_entity_ids_json JSON NOT NULL, 
	origin_summary TEXT, 
	novel_id UUID NOT NULL, 
	entity_id UUID NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	confidence FLOAT, 
	evidence_refs_json JSON NOT NULL, 
	extra_json JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (entity_id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(entity_id) REFERENCES core_entities (id) ON DELETE CASCADE
);

CREATE TABLE location_profiles (
	map_refs_json JSON NOT NULL, 
	climate VARCHAR(128), 
	population_summary TEXT, 
	resources_json JSON NOT NULL, 
	hazards_json JSON NOT NULL, 
	controlling_faction_ids_json JSON NOT NULL, 
	novel_id UUID NOT NULL, 
	entity_id UUID NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	confidence FLOAT, 
	evidence_refs_json JSON NOT NULL, 
	extra_json JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (entity_id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(entity_id) REFERENCES core_entities (id) ON DELETE CASCADE
);

CREATE TABLE map_configs (
	name VARCHAR(255) NOT NULL, 
	map_type VARCHAR(32) NOT NULL, 
	description TEXT, 
	default_center_x FLOAT NOT NULL, 
	default_center_y FLOAT NOT NULL, 
	default_zoom FLOAT NOT NULL, 
	grid_width INTEGER NOT NULL, 
	grid_height INTEGER NOT NULL, 
	hex_size INTEGER NOT NULL, 
	parent_map_id UUID, 
	parent_entity_id UUID, 
	sort_order INTEGER NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(parent_map_id) REFERENCES map_configs (id) ON DELETE SET NULL, 
	FOREIGN KEY(parent_entity_id) REFERENCES core_entities (id) ON DELETE SET NULL, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE rule_profiles (
	rule_domain VARCHAR(128), 
	principle_summary TEXT, 
	constraints_json JSON NOT NULL, 
	exceptions_json JSON NOT NULL, 
	consequences_json JSON NOT NULL, 
	novel_id UUID NOT NULL, 
	entity_id UUID NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	confidence FLOAT, 
	evidence_refs_json JSON NOT NULL, 
	extra_json JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (entity_id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(entity_id) REFERENCES core_entities (id) ON DELETE CASCADE
);

CREATE TABLE scene_chapter_links (
	scene_id UUID NOT NULL, 
	chapter_index INTEGER NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_scene_chapter_links_novel_scene_chapter UNIQUE (novel_id, scene_id, chapter_index), 
	FOREIGN KEY(scene_id) REFERENCES scenes (id) ON DELETE CASCADE, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE secret_profiles (
	truth_summary TEXT, 
	holder_entity_ids_json JSON NOT NULL, 
	risk_level VARCHAR(32) NOT NULL, 
	reveal_status VARCHAR(32) NOT NULL, 
	linked_target_refs_json JSON NOT NULL, 
	novel_id UUID NOT NULL, 
	entity_id UUID NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	confidence FLOAT, 
	evidence_refs_json JSON NOT NULL, 
	extra_json JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (entity_id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(entity_id) REFERENCES core_entities (id) ON DELETE CASCADE
);

CREATE TABLE species_profiles (
	origin_summary TEXT, 
	physiology_summary TEXT, 
	lifespan VARCHAR(128), 
	abilities_json JSON NOT NULL, 
	weaknesses_json JSON NOT NULL, 
	culture_summary TEXT, 
	language_summary TEXT, 
	public_baseline BOOLEAN NOT NULL, 
	novel_id UUID NOT NULL, 
	entity_id UUID NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	confidence FLOAT, 
	evidence_refs_json JSON NOT NULL, 
	extra_json JSON NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (entity_id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(entity_id) REFERENCES core_entities (id) ON DELETE CASCADE
);

CREATE TABLE world_bible_page_projections (
	novel_id UUID NOT NULL, 
	page_id UUID NOT NULL, 
	projection_type VARCHAR(64) NOT NULL, 
	content TEXT, 
	source_spans_json JSON NOT NULL, 
	token_estimate INTEGER NOT NULL, 
	omitted_reasons_json JSON NOT NULL, 
	sensitivity VARCHAR(32) NOT NULL, 
	stale BOOLEAN NOT NULL, 
	stale_checked_at TIMESTAMP WITH TIME ZONE, 
	error_kind VARCHAR(64), 
	error_summary TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_world_bible_projection_type UNIQUE (novel_id, page_id, projection_type), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(page_id) REFERENCES world_bible_pages (id) ON DELETE CASCADE
);

CREATE TABLE world_bible_page_revisions (
	novel_id UUID NOT NULL, 
	page_id UUID NOT NULL, 
	version_number INTEGER NOT NULL, 
	snapshot_json JSON NOT NULL, 
	revision_reason VARCHAR(64) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(page_id) REFERENCES world_bible_pages (id) ON DELETE CASCADE
);

CREATE TABLE writing_conflict_checks (
	chapter_index INTEGER NOT NULL, 
	scene_id UUID, 
	draft_id UUID, 
	version_number INTEGER, 
	scope JSON NOT NULL, 
	include_candidates BOOLEAN NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	summary_json JSON NOT NULL, 
	ai_review_enabled BOOLEAN NOT NULL, 
	ai_review_status VARCHAR(32) NOT NULL, 
	ai_review_confirmation_id UUID, 
	ai_review_model VARCHAR(128), 
	ai_review_error TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(draft_id) REFERENCES writing_drafts (id) ON DELETE SET NULL, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE character_knowledge (
	novel_id UUID NOT NULL, 
	character_id UUID NOT NULL, 
	target_type VARCHAR(64) NOT NULL, 
	target_id UUID NOT NULL, 
	knowledge_level VARCHAR(32) NOT NULL, 
	known_content TEXT, 
	misconception TEXT, 
	source_chapter_index INTEGER, 
	source_memory_id UUID, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(character_id) REFERENCES characters (entity_id) ON DELETE CASCADE
);

CREATE TABLE character_knowledge_tags (
	novel_id UUID NOT NULL, 
	character_id UUID NOT NULL, 
	tag_id UUID NOT NULL, 
	grant_source VARCHAR(64) NOT NULL, 
	source_ref_type VARCHAR(64), 
	source_ref_id VARCHAR(128), 
	source_scene_id UUID, 
	source_chapter_index INTEGER, 
	source_memory_id UUID, 
	author_locked BOOLEAN NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	status VARCHAR(32) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_character_knowledge_tag_source UNIQUE (novel_id, character_id, tag_id, grant_source), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(character_id) REFERENCES characters (entity_id) ON DELETE CASCADE, 
	FOREIGN KEY(tag_id) REFERENCES knowledge_tags (id) ON DELETE CASCADE
);

CREATE TABLE entity_relations (
	novel_id UUID NOT NULL, 
	source_id UUID NOT NULL, 
	target_id UUID NOT NULL, 
	relation_type VARCHAR(64) NOT NULL, 
	description TEXT, 
	strength FLOAT NOT NULL, 
	source_chapter_id UUID, 
	caused_by_event_id UUID, 
	quote TEXT, 
	status VARCHAR(16) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	PRIMARY KEY (id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_id) REFERENCES core_entities (id) ON DELETE CASCADE, 
	FOREIGN KEY(target_id) REFERENCES core_entities (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_chapter_id) REFERENCES imported_chapters (id) ON DELETE SET NULL, 
	FOREIGN KEY(caused_by_event_id) REFERENCES core_entities (id) ON DELETE SET NULL
);

CREATE TABLE entity_revisions (
	entity_id UUID NOT NULL, 
	novel_id UUID NOT NULL, 
	snapshot JSON NOT NULL, 
	source_chapter_id UUID, 
	revision_reason VARCHAR(32) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(entity_id) REFERENCES core_entities (id) ON DELETE CASCADE, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_chapter_id) REFERENCES imported_chapters (id) ON DELETE SET NULL
);

CREATE TABLE events (
	entity_id UUID NOT NULL, 
	source_chapter_id UUID NOT NULL, 
	location_entity_id UUID NOT NULL, 
	timeline_order INTEGER NOT NULL, 
	occurrence_time_label VARCHAR(100), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (entity_id), 
	FOREIGN KEY(entity_id) REFERENCES core_entities (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_chapter_id) REFERENCES imported_chapters (id) ON DELETE CASCADE, 
	FOREIGN KEY(location_entity_id) REFERENCES core_entities (id) ON DELETE RESTRICT, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE knowledge_tag_exclusions (
	novel_id UUID NOT NULL, 
	character_id UUID NOT NULL, 
	tag_id UUID NOT NULL, 
	reason TEXT, 
	source VARCHAR(64) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_knowledge_tag_exclusion UNIQUE (novel_id, character_id, tag_id), 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE, 
	FOREIGN KEY(character_id) REFERENCES characters (entity_id) ON DELETE CASCADE, 
	FOREIGN KEY(tag_id) REFERENCES knowledge_tags (id) ON DELETE CASCADE
);

CREATE TABLE map_location_bindings (
	map_id UUID NOT NULL, 
	location_entity_id UUID NOT NULL, 
	hex_q INTEGER NOT NULL, 
	hex_r INTEGER NOT NULL, 
	is_center BOOLEAN NOT NULL, 
	label_override VARCHAR(255), 
	style_override JSON, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(map_id) REFERENCES map_configs (id) ON DELETE CASCADE, 
	FOREIGN KEY(location_entity_id) REFERENCES core_entities (id) ON DELETE CASCADE, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE map_location_layouts (
	map_id UUID NOT NULL, 
	location_entity_id UUID NOT NULL, 
	center_hex_q INTEGER NOT NULL, 
	center_hex_r INTEGER NOT NULL, 
	occupy_radius INTEGER NOT NULL, 
	locked BOOLEAN NOT NULL, 
	layout_source VARCHAR(32) NOT NULL, 
	layout_version INTEGER NOT NULL, 
	sync_geo_setting BOOLEAN NOT NULL, 
	meta JSON, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(map_id) REFERENCES map_configs (id) ON DELETE CASCADE, 
	FOREIGN KEY(location_entity_id) REFERENCES core_entities (id) ON DELETE CASCADE, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE map_markers (
	map_id UUID NOT NULL, 
	entity_id UUID NOT NULL, 
	marker_type VARCHAR(16) NOT NULL, 
	hex_q INTEGER NOT NULL, 
	hex_r INTEGER NOT NULL, 
	offset_x FLOAT NOT NULL, 
	offset_y FLOAT NOT NULL, 
	label VARCHAR(255), 
	style_json JSON, 
	start_scene_id UUID, 
	start_scene_index INTEGER, 
	end_scene_id UUID, 
	end_scene_index INTEGER, 
	visible BOOLEAN NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(map_id) REFERENCES map_configs (id) ON DELETE CASCADE, 
	FOREIGN KEY(entity_id) REFERENCES core_entities (id) ON DELETE CASCADE, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE map_observations (
	map_id UUID, 
	target_entity_id UUID, 
	target_entity_type VARCHAR(64), 
	target_name VARCHAR(255), 
	dynamic_type VARCHAR(64) NOT NULL, 
	time_anchor JSON, 
	spatial_anchor JSON, 
	value_json JSON, 
	confidence FLOAT NOT NULL, 
	review_state VARCHAR(32) NOT NULL, 
	source_ref JSON, 
	evidence_text TEXT, 
	scene_id UUID, 
	scene_index INTEGER, 
	source_chapter_index INTEGER, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(map_id) REFERENCES map_configs (id) ON DELETE SET NULL, 
	FOREIGN KEY(target_entity_id) REFERENCES core_entities (id) ON DELETE SET NULL, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE map_terrain_layers (
	map_id UUID NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	terrain_asset_key VARCHAR(64) NOT NULL, 
	opacity FLOAT NOT NULL, 
	z_index INTEGER NOT NULL, 
	visible BOOLEAN NOT NULL, 
	locked BOOLEAN NOT NULL, 
	meta JSON, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(map_id) REFERENCES map_configs (id) ON DELETE CASCADE, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE map_territory_tiles (
	map_id UUID NOT NULL, 
	faction_entity_id UUID NOT NULL, 
	hex_q INTEGER NOT NULL, 
	hex_r INTEGER NOT NULL, 
	style_override JSON, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(map_id) REFERENCES map_configs (id) ON DELETE CASCADE, 
	FOREIGN KEY(faction_entity_id) REFERENCES core_entities (id) ON DELETE CASCADE, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE map_tiles (
	map_id UUID NOT NULL, 
	hex_q INTEGER NOT NULL, 
	hex_r INTEGER NOT NULL, 
	terrain_type VARCHAR(32) NOT NULL, 
	elevation INTEGER NOT NULL, 
	style_override JSON, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(map_id) REFERENCES map_configs (id) ON DELETE CASCADE, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE writing_conflict_items (
	check_id UUID NOT NULL, 
	kind VARCHAR(64) NOT NULL, 
	severity VARCHAR(16) NOT NULL, 
	source_module VARCHAR(32) NOT NULL, 
	source_type VARCHAR(64), 
	source_id VARCHAR(128), 
	evidence_summary TEXT NOT NULL, 
	location_json JSON, 
	is_ai_judgment BOOLEAN NOT NULL, 
	needs_review BOOLEAN NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	confidence FLOAT, 
	source_confirmation_id UUID, 
	llm_rationale TEXT, 
	suggestion_status VARCHAR(32) NOT NULL, 
	suggestion_confirmation_id UUID, 
	ai_suggestion TEXT, 
	suggestion_error TEXT, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(check_id) REFERENCES writing_conflict_checks (id) ON DELETE CASCADE, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE map_facts (
	observation_id UUID, 
	map_id UUID, 
	target_entity_id UUID, 
	target_entity_type VARCHAR(64), 
	target_name VARCHAR(255), 
	dynamic_type VARCHAR(64) NOT NULL, 
	time_anchor JSON, 
	spatial_anchor JSON, 
	value_json JSON, 
	confidence FLOAT NOT NULL, 
	fact_status VARCHAR(32) NOT NULL, 
	source_ref JSON, 
	evidence_text TEXT, 
	scene_id UUID, 
	scene_index INTEGER, 
	source_chapter_index INTEGER, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(observation_id) REFERENCES map_observations (id) ON DELETE SET NULL, 
	FOREIGN KEY(map_id) REFERENCES map_configs (id) ON DELETE SET NULL, 
	FOREIGN KEY(target_entity_id) REFERENCES core_entities (id) ON DELETE SET NULL, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE map_terrain_regions (
	map_id UUID NOT NULL, 
	layer_id UUID NOT NULL, 
	name VARCHAR(255) NOT NULL, 
	region_status VARCHAR(32) NOT NULL, 
	meta JSON, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(map_id) REFERENCES map_configs (id) ON DELETE CASCADE, 
	FOREIGN KEY(layer_id) REFERENCES map_terrain_layers (id) ON DELETE CASCADE, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE map_terrain_bindings (
	map_id UUID NOT NULL, 
	region_id UUID NOT NULL, 
	location_entity_id UUID NOT NULL, 
	binding_type VARCHAR(32) NOT NULL, 
	review_state VARCHAR(32) NOT NULL, 
	source VARCHAR(64) NOT NULL, 
	meta JSON, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(map_id) REFERENCES map_configs (id) ON DELETE CASCADE, 
	FOREIGN KEY(region_id) REFERENCES map_terrain_regions (id) ON DELETE CASCADE, 
	FOREIGN KEY(location_entity_id) REFERENCES core_entities (id) ON DELETE CASCADE, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE TABLE map_terrain_patches (
	map_id UUID NOT NULL, 
	layer_id UUID NOT NULL, 
	region_id UUID NOT NULL, 
	hex_q INTEGER NOT NULL, 
	hex_r INTEGER NOT NULL, 
	strength FLOAT NOT NULL, 
	brush_source VARCHAR(32) NOT NULL, 
	id UUID NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()) NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc', now()), 
	novel_id UUID NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(map_id) REFERENCES map_configs (id) ON DELETE CASCADE, 
	FOREIGN KEY(layer_id) REFERENCES map_terrain_layers (id) ON DELETE CASCADE, 
	FOREIGN KEY(region_id) REFERENCES map_terrain_regions (id) ON DELETE CASCADE, 
	FOREIGN KEY(novel_id) REFERENCES projects (id) ON DELETE CASCADE
);

CREATE INDEX ix_async_tasks_status ON async_tasks (status);

CREATE INDEX ix_async_tasks_task_type ON async_tasks (task_type);

CREATE INDEX ix_conflict_check_queue_conflict_type ON conflict_check_queue (conflict_type);

CREATE INDEX ix_conflict_check_queue_novel_id ON conflict_check_queue (novel_id);

CREATE INDEX ix_conflict_check_queue_status ON conflict_check_queue (status);

CREATE INDEX ix_conflict_check_queue_target_hash ON conflict_check_queue (target_hash);

CREATE INDEX ix_context_confirmations_action ON context_confirmations (action);

CREATE INDEX ix_context_confirmations_novel_action ON context_confirmations (novel_id, action);

CREATE INDEX ix_context_confirmations_novel_id ON context_confirmations (novel_id);

CREATE INDEX ix_context_snapshots_novel_created ON context_snapshots (novel_id, created_at);

CREATE INDEX ix_context_snapshots_novel_id ON context_snapshots (novel_id);

CREATE INDEX ix_context_snapshots_novel_workflow_phase ON context_snapshots (novel_id, workflow_id, phase);

CREATE INDEX ix_context_snapshots_rendered_expires ON context_snapshots (rendered_context_expires_at);

CREATE INDEX ix_context_snapshots_status ON context_snapshots (status);

CREATE INDEX ix_context_snapshots_task_id ON context_snapshots (task_id);

CREATE INDEX ix_context_snapshots_workflow_id ON context_snapshots (workflow_id);

CREATE INDEX ix_core_entities_entity_type ON core_entities (entity_type);

CREATE INDEX ix_core_entities_novel_id ON core_entities (novel_id);

CREATE INDEX ix_core_entities_status ON core_entities (status);

CREATE INDEX ix_creation_suggestion_queue_novel_id ON creation_suggestion_queue (novel_id);

CREATE INDEX ix_creation_suggestion_queue_review_group ON creation_suggestion_queue (review_group);

CREATE INDEX ix_creation_suggestion_queue_source_module ON creation_suggestion_queue (source_module);

CREATE INDEX ix_creation_suggestion_queue_status ON creation_suggestion_queue (status);

CREATE INDEX ix_creation_suggestion_queue_target_type ON creation_suggestion_queue (target_type);

CREATE INDEX ix_delta_log_entity_id ON delta_log (entity_id);

CREATE INDEX ix_delta_log_novel_id ON delta_log (novel_id);

CREATE INDEX ix_entity_profile_templates_novel_id ON entity_profile_templates (novel_id);

CREATE INDEX ix_entity_profile_templates_status ON entity_profile_templates (status);

CREATE INDEX ix_foreshadowing_plans_novel_id ON foreshadowing_plans (novel_id);

CREATE INDEX ix_foreshadowing_plans_status ON foreshadowing_plans (status);

CREATE INDEX ix_import_records_novel_id ON import_records (novel_id);

CREATE UNIQUE INDEX uq_import_records_done_file_name ON import_records (novel_id, file_name) WHERE status = 'done';

CREATE INDEX ix_knowledge_tags_novel_id ON knowledge_tags (novel_id);

CREATE INDEX ix_knowledge_tags_status ON knowledge_tags (status);

CREATE INDEX ix_knowledge_visibility_policies_novel_id ON knowledge_visibility_policies (novel_id);

CREATE INDEX ix_knowledge_visibility_policies_status ON knowledge_visibility_policies (status);

CREATE INDEX ix_visibility_policies_target_hash ON knowledge_visibility_policies (novel_id, target_hash);

CREATE INDEX ix_memory_events_entity_id ON memory_events (entity_id);

CREATE INDEX ix_memory_events_event_type ON memory_events (event_type);

CREATE INDEX ix_memory_events_novel_id ON memory_events (novel_id);

CREATE INDEX ix_memory_snapshots_novel_id ON memory_snapshots (novel_id);

CREATE INDEX ix_outline_arcs_novel_id ON outline_arcs (novel_id);

CREATE INDEX ix_outline_arcs_status ON outline_arcs (status);

CREATE INDEX ix_plot_threads_novel_id ON plot_threads (novel_id);

CREATE INDEX ix_plot_threads_status ON plot_threads (status);

CREATE INDEX ix_rag_chunks_chapter_index ON rag_chunks (chapter_index);

CREATE INDEX ix_rag_chunks_novel_id ON rag_chunks (novel_id);

CREATE INDEX ix_rag_chunks_scene_id ON rag_chunks (scene_id);

CREATE INDEX ix_rag_chunks_source_id ON rag_chunks (source_id);

CREATE INDEX ix_reader_reveal_chapter ON reader_reveal_policies (novel_id, reveal_chapter_index);

CREATE INDEX ix_reader_reveal_policies_novel_id ON reader_reveal_policies (novel_id);

CREATE INDEX ix_reader_reveal_policies_status ON reader_reveal_policies (status);

CREATE INDEX ix_reader_reveal_target_hash ON reader_reveal_policies (novel_id, target_hash);

CREATE INDEX ix_reveal_plans_novel_id ON reveal_plans (novel_id);

CREATE INDEX ix_scenes_novel_id ON scenes (novel_id);

CREATE INDEX ix_scenes_scene_index ON scenes (scene_index);

CREATE INDEX ix_scenes_status ON scenes (status);

CREATE INDEX ix_text_archive_entity_id ON text_archive (entity_id);

CREATE INDEX ix_text_archive_novel_id ON text_archive (novel_id);

CREATE INDEX ix_world_bible_pages_novel_id ON world_bible_pages (novel_id);

CREATE INDEX ix_world_bible_pages_page_type ON world_bible_pages (page_type);

CREATE INDEX ix_world_bible_pages_status ON world_bible_pages (status);

CREATE INDEX ix_writing_drafts_chapter_index ON writing_drafts (chapter_index);

CREATE INDEX ix_writing_drafts_novel_id ON writing_drafts (novel_id);

CREATE INDEX ix_asset_knowledge_tags_novel_id ON asset_knowledge_tags (novel_id);

CREATE INDEX ix_asset_knowledge_tags_status ON asset_knowledge_tags (status);

CREATE INDEX ix_asset_knowledge_tags_target_hash ON asset_knowledge_tags (novel_id, target_hash);

CREATE INDEX ix_characters_novel_id ON characters (novel_id);

CREATE INDEX ix_characters_status ON characters (status);

CREATE INDEX ix_faction_profiles_novel_id ON faction_profiles (novel_id);

CREATE INDEX ix_faction_profiles_status ON faction_profiles (status);

CREATE INDEX ix_generic_entity_profiles_entity_id ON generic_entity_profiles (entity_id);

CREATE INDEX ix_generic_entity_profiles_novel_id ON generic_entity_profiles (novel_id);

CREATE INDEX ix_generic_entity_profiles_profile_type ON generic_entity_profiles (profile_type);

CREATE INDEX ix_generic_entity_profiles_status ON generic_entity_profiles (status);

CREATE INDEX ix_imported_chapters_novel_id ON imported_chapters (novel_id);

CREATE INDEX ix_item_profiles_novel_id ON item_profiles (novel_id);

CREATE INDEX ix_item_profiles_status ON item_profiles (status);

CREATE INDEX ix_location_profiles_novel_id ON location_profiles (novel_id);

CREATE INDEX ix_location_profiles_status ON location_profiles (status);

CREATE INDEX ix_map_configs_map_type ON map_configs (map_type);

CREATE INDEX ix_map_configs_novel_id ON map_configs (novel_id);

CREATE INDEX ix_map_configs_parent_entity_id ON map_configs (parent_entity_id);

CREATE INDEX ix_map_configs_parent_map_id ON map_configs (parent_map_id);

CREATE UNIQUE INDEX uq_map_config_novel_parent_name ON map_configs (novel_id, parent_map_id, name);

CREATE INDEX ix_rule_profiles_novel_id ON rule_profiles (novel_id);

CREATE INDEX ix_rule_profiles_status ON rule_profiles (status);

CREATE INDEX ix_scene_chapter_links_novel_chapter ON scene_chapter_links (novel_id, chapter_index);

CREATE INDEX ix_scene_chapter_links_novel_id ON scene_chapter_links (novel_id);

CREATE INDEX ix_scene_chapter_links_scene_id ON scene_chapter_links (scene_id);

CREATE INDEX ix_secret_profiles_novel_id ON secret_profiles (novel_id);

CREATE INDEX ix_secret_profiles_status ON secret_profiles (status);

CREATE INDEX ix_species_profiles_novel_id ON species_profiles (novel_id);

CREATE INDEX ix_species_profiles_status ON species_profiles (status);

CREATE INDEX ix_world_bible_page_projections_novel_id ON world_bible_page_projections (novel_id);

CREATE INDEX ix_world_bible_page_projections_page_id ON world_bible_page_projections (page_id);

CREATE INDEX ix_world_bible_page_projections_status ON world_bible_page_projections (status);

CREATE INDEX ix_world_bible_page_revisions_novel_id ON world_bible_page_revisions (novel_id);

CREATE INDEX ix_world_bible_page_revisions_page_id ON world_bible_page_revisions (page_id);

CREATE INDEX ix_writing_conflict_checks_chapter_index ON writing_conflict_checks (chapter_index);

CREATE INDEX ix_writing_conflict_checks_novel_id ON writing_conflict_checks (novel_id);

CREATE INDEX ix_writing_conflict_checks_scene_id ON writing_conflict_checks (scene_id);

CREATE INDEX ix_writing_conflict_checks_scope ON writing_conflict_checks (novel_id, chapter_index, scene_id, created_at);

CREATE INDEX ix_writing_conflict_checks_status ON writing_conflict_checks (status);

CREATE INDEX ix_character_knowledge_character_id ON character_knowledge (character_id);

CREATE INDEX ix_character_knowledge_novel_id ON character_knowledge (novel_id);

CREATE INDEX ix_character_knowledge_status ON character_knowledge (status);

CREATE INDEX ix_character_knowledge_target_id ON character_knowledge (target_id);

CREATE INDEX ix_character_knowledge_tags_character_id ON character_knowledge_tags (character_id);

CREATE INDEX ix_character_knowledge_tags_novel_id ON character_knowledge_tags (novel_id);

CREATE INDEX ix_character_knowledge_tags_status ON character_knowledge_tags (status);

CREATE INDEX ix_character_knowledge_tags_tag_id ON character_knowledge_tags (tag_id);

CREATE INDEX ix_entity_relations_novel_id ON entity_relations (novel_id);

CREATE INDEX ix_entity_relations_source_id ON entity_relations (source_id);

CREATE INDEX ix_entity_relations_target_id ON entity_relations (target_id);

CREATE INDEX ix_entity_revisions_entity_id ON entity_revisions (entity_id);

CREATE INDEX ix_events_novel_id ON events (novel_id);

CREATE INDEX ix_knowledge_tag_exclusions_novel_id ON knowledge_tag_exclusions (novel_id);

CREATE INDEX ix_map_location_bindings_location_entity_id ON map_location_bindings (location_entity_id);

CREATE INDEX ix_map_location_bindings_map_id ON map_location_bindings (map_id);

CREATE INDEX ix_map_location_bindings_novel_id ON map_location_bindings (novel_id);

CREATE UNIQUE INDEX uq_map_binding_map_entity_qr ON map_location_bindings (map_id, location_entity_id, hex_q, hex_r);

CREATE INDEX ix_map_location_layouts_location_entity_id ON map_location_layouts (location_entity_id);

CREATE INDEX ix_map_location_layouts_map_id ON map_location_layouts (map_id);

CREATE INDEX ix_map_location_layouts_novel_id ON map_location_layouts (novel_id);

CREATE UNIQUE INDEX uq_map_location_layout_map_entity ON map_location_layouts (map_id, location_entity_id);

CREATE INDEX ix_map_marker_map_scene ON map_markers (map_id, marker_type);

CREATE INDEX ix_map_markers_entity_id ON map_markers (entity_id);

CREATE INDEX ix_map_markers_map_id ON map_markers (map_id);

CREATE INDEX ix_map_markers_novel_id ON map_markers (novel_id);

CREATE INDEX ix_map_observation_map_review ON map_observations (map_id, review_state);

CREATE INDEX ix_map_observation_scene ON map_observations (scene_id, scene_index);

CREATE INDEX ix_map_observation_target ON map_observations (target_entity_id, dynamic_type);

CREATE INDEX ix_map_observations_dynamic_type ON map_observations (dynamic_type);

CREATE INDEX ix_map_observations_map_id ON map_observations (map_id);

CREATE INDEX ix_map_observations_novel_id ON map_observations (novel_id);

CREATE INDEX ix_map_observations_review_state ON map_observations (review_state);

CREATE INDEX ix_map_observations_scene_id ON map_observations (scene_id);

CREATE INDEX ix_map_observations_scene_index ON map_observations (scene_index);

CREATE INDEX ix_map_observations_target_entity_id ON map_observations (target_entity_id);

CREATE INDEX ix_map_terrain_layers_map_id ON map_terrain_layers (map_id);

CREATE INDEX ix_map_terrain_layers_novel_id ON map_terrain_layers (novel_id);

CREATE INDEX ix_map_territory_tiles_faction_entity_id ON map_territory_tiles (faction_entity_id);

CREATE INDEX ix_map_territory_tiles_map_id ON map_territory_tiles (map_id);

CREATE INDEX ix_map_territory_tiles_novel_id ON map_territory_tiles (novel_id);

CREATE UNIQUE INDEX uq_map_territory_map_faction_qr ON map_territory_tiles (map_id, faction_entity_id, hex_q, hex_r);

CREATE INDEX ix_map_tiles_map_id ON map_tiles (map_id);

CREATE INDEX ix_map_tiles_novel_id ON map_tiles (novel_id);

CREATE UNIQUE INDEX uq_map_tile_map_qr ON map_tiles (map_id, hex_q, hex_r);

CREATE INDEX ix_writing_conflict_items_check_id ON writing_conflict_items (check_id);

CREATE INDEX ix_writing_conflict_items_kind ON writing_conflict_items (kind);

CREATE INDEX ix_writing_conflict_items_novel_id ON writing_conflict_items (novel_id);

CREATE INDEX ix_writing_conflict_items_novel_status ON writing_conflict_items (novel_id, status);

CREATE INDEX ix_writing_conflict_items_severity ON writing_conflict_items (severity);

CREATE INDEX ix_writing_conflict_items_status ON writing_conflict_items (status);

CREATE INDEX ix_map_fact_map_status ON map_facts (map_id, fact_status);

CREATE INDEX ix_map_fact_scene ON map_facts (scene_id, scene_index);

CREATE INDEX ix_map_fact_target ON map_facts (target_entity_id, dynamic_type);

CREATE INDEX ix_map_facts_dynamic_type ON map_facts (dynamic_type);

CREATE INDEX ix_map_facts_fact_status ON map_facts (fact_status);

CREATE INDEX ix_map_facts_map_id ON map_facts (map_id);

CREATE INDEX ix_map_facts_novel_id ON map_facts (novel_id);

CREATE INDEX ix_map_facts_observation_id ON map_facts (observation_id);

CREATE INDEX ix_map_facts_target_entity_id ON map_facts (target_entity_id);

CREATE INDEX ix_map_terrain_regions_layer_id ON map_terrain_regions (layer_id);

CREATE INDEX ix_map_terrain_regions_map_id ON map_terrain_regions (map_id);

CREATE INDEX ix_map_terrain_regions_novel_id ON map_terrain_regions (novel_id);

CREATE INDEX ix_map_terrain_bindings_location_entity_id ON map_terrain_bindings (location_entity_id);

CREATE INDEX ix_map_terrain_bindings_map_id ON map_terrain_bindings (map_id);

CREATE INDEX ix_map_terrain_bindings_novel_id ON map_terrain_bindings (novel_id);

CREATE INDEX ix_map_terrain_bindings_region_id ON map_terrain_bindings (region_id);

CREATE UNIQUE INDEX uq_map_terrain_binding_region_location_type ON map_terrain_bindings (region_id, location_entity_id, binding_type);

CREATE INDEX ix_map_terrain_patches_layer_id ON map_terrain_patches (layer_id);

CREATE INDEX ix_map_terrain_patches_map_id ON map_terrain_patches (map_id);

CREATE INDEX ix_map_terrain_patches_novel_id ON map_terrain_patches (novel_id);

CREATE INDEX ix_map_terrain_patches_region_id ON map_terrain_patches (region_id);

CREATE UNIQUE INDEX uq_map_terrain_patch_map_layer_region_qr ON map_terrain_patches (map_id, layer_id, region_id, hex_q, hex_r);
