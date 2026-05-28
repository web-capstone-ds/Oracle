"""CONTROL_CMD threshold approval handlers."""

from __future__ import annotations

from db import rule_db
from engine.isolation_forest import invalidate_model_cache
from utils.logging_config import get_logger

log = get_logger(__name__)


async def handle_threshold_approval(payload: dict) -> None:
    proposal_id = payload.get("proposal_id")
    approved_by = payload.get("approved_by") or payload.get("operator_id") or "unknown"
    if not proposal_id:
        log.warning("threshold_approval_missing_proposal_id")
        return

    proposal = await rule_db.load_threshold_proposal(proposal_id)
    if not proposal:
        log.warning("threshold_proposal_not_found", proposal_id=proposal_id)
        return
    if proposal["status"] != "pending":
        log.info("threshold_proposal_already_processed", proposal_id=proposal_id)
        return

    await rule_db.update_threshold(
        recipe_id=proposal["recipe_id"],
        rule_id=proposal["rule_id"],
        new_warning=proposal["proposed_warning"],
        new_critical=proposal["proposed_critical"],
        approved_by=approved_by,
        lot_basis=proposal["lot_basis"],
    )
    await rule_db.insert_change_history(
        recipe_id=proposal["recipe_id"],
        rule_id=proposal["rule_id"],
        metric=proposal["metric"],
        old_warning=proposal["current_warning"],
        new_warning=proposal["proposed_warning"],
        old_critical=proposal["current_critical"],
        new_critical=proposal["proposed_critical"],
        approved_by=approved_by,
        change_source="ewma_mad",
        ai_basis=proposal.get("basis"),
    )
    invalidate_model_cache(proposal["recipe_id"])
    await rule_db.mark_threshold_proposal_processed(
        proposal_id,
        status="approved",
        processed_by=approved_by,
    )
    log.info("threshold_proposal_approved", proposal_id=proposal_id, approved_by=approved_by)


async def handle_threshold_rejection(payload: dict) -> None:
    proposal_id = payload.get("proposal_id")
    rejected_by = payload.get("rejected_by") or payload.get("operator_id") or "unknown"
    reason = payload.get("reason", "")
    if not proposal_id:
        log.warning("threshold_rejection_missing_proposal_id")
        return

    proposal = await rule_db.load_threshold_proposal(proposal_id)
    if not proposal or proposal["status"] != "pending":
        return

    await rule_db.insert_change_history(
        recipe_id=proposal["recipe_id"],
        rule_id=proposal["rule_id"],
        metric=proposal["metric"],
        old_warning=proposal["current_warning"],
        new_warning=None,
        old_critical=proposal["current_critical"],
        new_critical=None,
        approved_by=rejected_by,
        change_source="ewma_mad_rejected",
        ai_basis=f"{proposal.get('basis') or ''} | rejected: {reason}",
    )
    await rule_db.mark_threshold_proposal_processed(
        proposal_id,
        status="rejected",
        processed_by=rejected_by,
    )
    log.info("threshold_proposal_rejected", proposal_id=proposal_id, rejected_by=rejected_by)

