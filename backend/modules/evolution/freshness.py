"""Bounded prefix proofs guarded by transactional, project-local source tokens."""

from collections import OrderedDict
from dataclasses import dataclass
from uuid import UUID
from weakref import WeakKeyDictionary

from sqlalchemy import event, select

from core.errors import ConflictError
from modules.evolution.ledger_contracts import LedgerDependency
from modules.evolution.models import EvolutionSourceEpoch
from modules.evolution.reading import require_current_prefix

_RESULTS = WeakKeyDictionary()
MAX_CACHED_PREFIXES = 4096
MAX_CACHED_PROOF_SCOPES = 65536


async def require_cached_prefix(db, store, frozen):
    dependency = LedgerDependency(
        run_key=frozen.run_id,
        attempt_id=frozen.attempt_id,
        scene_id=frozen.payload["scene_id"],
        scene_index=frozen.payload["scene_index"],
        source_manifest_hash=frozen.source_manifest_hash,
    )
    if not await dependency_current(db, store, dependency):
        raise ConflictError("理解前序来源已变化，请重新理解并核对候选")


def attempt_scope(run_key, attempt_id):
    return f"attempt:{len(run_key)}:{run_key}:{attempt_id}"


@dataclass(frozen=True)
class PrefixProof:
    root: str
    rows: tuple
    tokens: dict

    def scopes(self, through):
        return {self.root} | {scope for row in self.rows[: through + 1] for scope in row}


async def _tokens(db, novel_id, scopes):
    # Column reads bypass the identity map and autoflush pending source edits.
    # A large prefix must not exceed asyncpg's bind-parameter limit. The outer
    # project guards detect a concurrent commit spanning these bounded reads.
    values, result = sorted(set(scopes)), {}
    for start in range(0, len(values), 4096):
        rows = await db.execute(
            select(
                EvolutionSourceEpoch.scope_key,
                EvolutionSourceEpoch.epoch,
            ).where(
                EvolutionSourceEpoch.novel_id == UUID(str(novel_id)),
                EvolutionSourceEpoch.scope_key.in_(values[start : start + 4096]),
            )
        )
        result.update(rows.all())
    return result


async def _epoch(db, novel_id):
    return (await _tokens(db, novel_id, ["project"])).get("project")


async def _verify_fresh_prefix(db, store, frozen, verified):
    # Source facades select ORM rows. A retained identity-map object must not
    # turn a new source token into a proof of stale values. Refresh all SELECTs
    # only during this full verifier; autoflush preserves pending local writes.
    session = getattr(db, "sync_session", getattr(db, "session", None))

    def fresh_rows(execution):
        if execution.is_select:
            execution.update_execution_options(populate_existing=True)

    if session is not None:
        event.listen(session, "do_orm_execute", fresh_rows)
    try:
        await require_current_prefix(db, store, frozen, verified=verified)
    finally:
        if session is not None:
            event.remove(session, "do_orm_execute", fresh_rows)


def _row_scopes(receipt, row):
    binding = row.payload_json["source_binding"]
    return (
        f"run:{receipt.run_key}",
        attempt_scope(receipt.run_key, receipt.attempt_key),
        f"scene:{row.payload_json['scene_id']}",
        *(
            f"chapter:{part['chapter_index']}"
            for part in [binding, *binding.get("additional_sources", [])]
        ),
    )


def _trim_proofs(results):
    # Many append/revise runs can have overlapping long prefixes. Count each
    # shared proof once, and retain only a bounded amount of detailed metadata.
    # Epoch-only snapshots remain safe and fast until the project token changes;
    # they then use the complete verifier instead of selective promotion.
    kept, discarded, weight = set(), set(), 0
    for cached in reversed(results.values()):
        proof = cached.get("proof")
        if proof is None or id(proof) in kept or id(proof) in discarded:
            continue
        size = len(proof.tokens) + sum(len(row) for row in proof.rows)
        if weight + size <= MAX_CACHED_PROOF_SCOPES:
            kept.add(id(proof))
            weight += size
        else:
            discarded.add(id(proof))
    for cached in results.values():
        if id(cached.get("proof")) in discarded:
            cached["proof"] = None


async def dependency_current(db, store, dependency):
    # Production sessions disable autoflush. Never read an old guard token or
    # overwrite dirty source objects with populate_existing during validation.
    await db.flush()
    bind = db.get_bind()
    engine = getattr(bind, "engine", bind)
    epoch = (
        await _epoch(db, store.novel_id) if bind.dialect.name == "postgresql" else None
    )
    results = _RESULTS.setdefault(engine, OrderedDict())
    identity = (
        str(store.novel_id),
        dependency.run_key,
        dependency.attempt_id,
        dependency.source_manifest_hash,
    )
    cached = results.get(identity) if epoch is not None else None
    if cached:
        results.move_to_end(identity)
        if cached["epoch"] == epoch:
            return cached["valid"]
        if cached["valid"] and cached.get("proof") is not None:
            proof = cached["proof"]
            scopes = proof.scopes(cached["through"])
            current = await _tokens(db, store.novel_id, scopes)
            if all(
                current.get(scope) == proof.tokens.get(scope)
                and current.get(scope) is not None
                for scope in scopes
            ):
                if await _epoch(db, store.novel_id) != epoch:
                    return False
                cached["epoch"] = epoch
                return True
    frozen = await store.load_frozen(dependency.run_key, dependency.attempt_id)
    valid = frozen is not None and (
        frozen.source_manifest_hash == dependency.source_manifest_hash
    )
    verified = []
    if valid:
        try:
            await _verify_fresh_prefix(db, store, frozen, verified)
        except ConflictError:
            valid = False
    if epoch is not None:
        proof = None
        if valid:
            rows = tuple(_row_scopes(receipt, row) for receipt, row in verified)
            root = f"run:{dependency.run_key}"
            scopes = {root} | {scope for row in rows for scope in row}
            tokens = await _tokens(db, store.novel_id, scopes)
            if len(tokens) == len(scopes):
                proof = PrefixProof(root, rows, tokens)
        # READ COMMITTED may span a concurrent commit. Never publish a mixed
        # snapshot. Random UUID tokens cannot repeat after a rolled-back write.
        if await _epoch(db, store.novel_id) != epoch:
            return False
        if proof:
            for index, (receipt, row) in enumerate(verified):
                # Inherited source runs need their own prefix structure proof.
                if receipt.run_key != dependency.run_key:
                    continue
                key = (
                    str(store.novel_id),
                    receipt.run_key,
                    row.attempt_key,
                    row.source_manifest_hash,
                )
                results[key] = {
                    "epoch": epoch,
                    "valid": True,
                    "proof": proof,
                    "through": index,
                }
                results.move_to_end(key)
        if not valid:
            results[identity] = {"epoch": epoch, "valid": False}
            results.move_to_end(identity)
        while len(results) > MAX_CACHED_PREFIXES:
            results.popitem(last=False)
        _trim_proofs(results)
    return valid
