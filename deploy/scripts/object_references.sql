-- Executed only against an isolated database restored from the paired dump.
SELECT coalesce(json_agg(row_to_json(ref) ORDER BY novel_id, category, key), '[]'::json)
FROM (
  SELECT novel_id::text, :'map_bucket' AS bucket, object_key AS key,
         sha256, byte_size, 'map_page' AS category
  FROM map_atlas_pages WHERE object_key IS NOT NULL
  UNION ALL
  SELECT novel_id::text, :'map_bucket', mask_object_key, NULL, NULL, 'map_mask'
  FROM map_atlas_pages WHERE mask_object_key IS NOT NULL
  UNION ALL
  SELECT novel_id::text, :'world_bucket',
         'world-objects/' || novel_id::text || '/entities/' || id::text ||
         '/images/' || image_version::text || '/' || variant || '.webp',
         NULL, NULL, 'world_' || variant
  FROM core_entities CROSS JOIN (VALUES ('full'), ('thumbnail')) AS variants(variant)
  WHERE image_version IS NOT NULL
) AS ref;
