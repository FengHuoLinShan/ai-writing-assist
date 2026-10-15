"""Rebind copied map fingerprints after Project rewrites destination identities."""

from modules.world.map_structure_geometry import geometry_hash
from modules.world.map_structure_schemas import MapDocument


def prepare_map_demo_copy_rows(rows, source_documents):
    revisions = {str(row["id"]): row for row in rows.get("map_atlas_revisions", [])}
    previous_hashes = {
        key: geometry_hash(MapDocument.model_validate(document))
        for key, document in source_documents.items()
    }
    for revision_id, row in revisions.items():
        document = MapDocument.model_validate(row["document"])
        previous_hash = previous_hashes[revision_id]
        copied_hash = geometry_hash(document)
        # A previously stale calibration must stay stale in the copied project.
        for placement in document.images:
            if placement.geometry_hash == previous_hash:
                placement.geometry_hash = copied_hash
        row["document"] = document.model_dump(mode="json")
        row["geometry_hash"] = copied_hash
    for row in rows.get("map_atlas_nodes", []):
        receipt = row.get("merge_metadata")
        if (
            receipt
            and (revision := revisions.get(receipt.get("source_revision_id")))
            and receipt.get("source_geometry_hash")
            == previous_hashes[str(revision["id"])]
        ):
            receipt["source_geometry_hash"] = revision["geometry_hash"]
    for row in rows.get("map_atlas_pages", []):
        revision = revisions.get(str(row.get("source_map_revision_id")))
        if (
            revision is not None
            and row.get("source_geometry_hash") == previous_hashes[str(revision["id"])]
        ):
            row["source_geometry_hash"] = revision["geometry_hash"]
