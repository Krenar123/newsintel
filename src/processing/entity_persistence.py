"""Persistence policy for extracted entities.

Curated lexicon matches are safe for client publication. Model discoveries are
stored for review, but are not exposed to clients until a reviewer approves
them. Trust metadata lives in Entity.metadata_json to avoid a schema migration.
"""

from sqlalchemy.orm import Session

from src.models.database import Entity, EntityStatus, EntityType
from src.search.normalization import search_blob


def get_or_create_extracted_entity(session: Session, extracted) -> Entity:
    """Persist an extraction without promoting uncurated model output."""
    entity_type = EntityType(extracted.entity_type)
    entity = (
        session.query(Entity)
        .filter(
            Entity.canonical_name == extracted.canonical_name,
            Entity.entity_type == entity_type,
        )
        .first()
    )

    desired_status = (
        EntityStatus.APPROVED
        if extracted.publishable
        else EntityStatus.NEEDS_REVIEW
    )
    if entity is None:
        entity = Entity(
            name=extracted.name,
            canonical_name=extracted.canonical_name,
            entity_type=entity_type,
            status=desired_status,
        )
        session.add(entity)
        session.flush()
    elif extracted.publishable:
        # Curated configuration is the source of truth, including when a noisy
        # legacy record was hidden before the alias was added to the lexicon.
        entity.name = extracted.name
        entity.status = EntityStatus.APPROVED
    elif entity.status == EntityStatus.AUTO:
        entity.status = EntityStatus.NEEDS_REVIEW

    metadata = dict(entity.metadata_json or {})
    existing_provenance = metadata.get("provenance", [])
    if isinstance(existing_provenance, str):
        existing_provenance = [existing_provenance]
    metadata["provenance"] = sorted(
        {str(value) for value in [*existing_provenance, *extracted.provenance] if value}
    )

    existing_aliases = metadata.get("aliases", [])
    if isinstance(existing_aliases, str):
        existing_aliases = [existing_aliases]
    metadata["aliases"] = sorted(
        {str(value) for value in [*existing_aliases, *extracted.matched_aliases] if value},
        key=str.casefold,
    )
    metadata["matched_aliases"] = list(metadata["aliases"])
    metadata["confidence"] = max(
        float(metadata.get("confidence") or 0.0),
        float(extracted.confidence),
    )
    metadata["publishable"] = entity.status == EntityStatus.APPROVED
    entity.metadata_json = metadata
    entity.search_text = search_blob(
        entity.name,
        entity.canonical_name,
        *metadata["aliases"],
    )
    return entity
