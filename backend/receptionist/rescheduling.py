"""Move an owned appointment in place; reconcile uncertain PATCH responses."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from firebase_admin import firestore

from .booking import (MIAMI, STEP, ToolError, appointment_reply, cells, day_slots,
                      owned_appointment, parse_start, slot_policy)
from .records import key_for


def reschedule(db, cal, operation_id, args, conversation):
    appointment_id = args.get("appointment_id")
    appointment = owned_appointment(db, cal, appointment_id, conversation)
    start = parse_start(args.get("start"))
    kind = appointment["arguments"]["appointment_type"]
    event_id = appointment["event_id"]
    ref = db.collection("booking_moves").document(operation_id)
    saved = ref.get().to_dict() or {}
    event = cal.find(event_id)
    if not event or event.get("status") == "cancelled" or event.get("recurrence"):
        raise ToolError("The appointment is no longer an active individual event. Offer a team callback.")
    duration = parse_start(event["end"]["dateTime"]) - parse_start(event["start"]["dateTime"])
    if saved.get("duration_seconds"):
        duration = timedelta(seconds=saved["duration_seconds"])
    finish = start + duration
    slots = list(cells(start, finish))
    target = db.collection("appointments").document(appointment_id)
    day = db.collection("booking_days").document(key_for(cal.id, start.date().isoformat()))
    owner = uuid4().hex
    now = datetime.now(UTC)

    @firestore.transactional
    def reserve(tx):
        prior = ref.get(transaction=tx).to_dict() or {}
        current = target.get(transaction=tx).to_dict()
        holds = day.get(transaction=tx).to_dict() or {}
        if not current or current.get("conversation_id") != conversation or current["calendar"] != cal.id:
            raise ToolError("This appointment cannot be changed from this conversation.")
        if prior and (prior["arguments"] != args or prior["conversation_id"] != conversation):
            raise ToolError("This tool call ID was already used for a different appointment change.")
        if prior.get("reply"):
            return prior
        if prior.get("state") == "conflict":
            return {"conflict": True}
        if current.get("pending_move") not in (None, operation_id):
            raise ToolError("A previous change is still being reconciled. Do not create another appointment.")
        if prior and prior["lease_until"] > now:
            raise ToolError("This change is being checked. Do not confirm another time yet.")
        if prior:
            status = prior["status"]
        else:
            _, status = slot_policy(start, kind, now, duration)
        if any(holds.get(k) not in (None, operation_id) for k in slots):
            if prior:
                raise ToolError("The reserved time changed during reconciliation. Ask the team to review it.")
            tx.create(ref, {"arguments": args, "conversation_id": conversation, "state": "conflict"})
            return {"conflict": True}
        changes = {"arguments": args, "conversation_id": conversation, "calendar": cal.id,
                   "status": status, "owner": owner, "lease_until": now + timedelta(minutes=2),
                   "state": "pending", "expected_etag": prior.get("expected_etag", event.get("etag")),
                   "duration_seconds": prior.get("duration_seconds", duration.total_seconds())}
        tx.set(ref, changes)
        tx.set(day, dict.fromkeys(slots, operation_id), merge=True)
        tx.update(target, {"pending_move": operation_id})
        return changes

    state = reserve(db.transaction())
    if state.get("reply"):
        if "result" in state["reply"]:
            return appointment_reply(target.get().to_dict(), "Currently scheduled")
        return state["reply"]

    def conflict():
        alternative = day_slots(db, cal, start + STEP, kind,
                                exclude_event_id=event_id, duration=duration,
                                ignore_operation=operation_id)
        offer = f"Offer {alternative}." if alternative else "Offer a team callback."
        return {"error": "That new time is unavailable. The original appointment is unchanged. " + offer}

    if state.get("conflict"):
        reply = conflict()
        ref.set({"reply": reply, "state": "done"}, merge=True)
        return reply

    @firestore.transactional
    def complete(tx, reply, moved=None):
        operation = ref.get(transaction=tx).to_dict()
        current = target.get(transaction=tx).to_dict()
        if operation["owner"] != owner or current.get("pending_move") != operation_id:
            raise ToolError("The appointment change is being reconciled. Do not create another booking.")
        tx.update(ref, {"state": "done", "reply": reply})
        tx.update(day, dict.fromkeys(slots, firestore.DELETE_FIELD))
        changes = {"pending_move": firestore.DELETE_FIELD}
        if moved:
            changes.update(start=moved["start"]["dateTime"], end=moved["end"]["dateTime"],
                           status=moved["status"], updated_at=firestore.SERVER_TIMESTAMP,
                           arguments={**current["arguments"], "start": moved["start"]["dateTime"]})
        tx.update(target, changes)
        return reply

    # A lost PATCH response is reconciled by its operation marker, never another insert.
    private = event.get("extendedProperties", {}).get("private", {})
    if private.get("gz_move_operation") == operation_id:
        return complete(db.transaction(), appointment_reply(
            {"event_id": event_id, "start": event["start"]["dateTime"], "status": event["status"]}, "Rescheduled"), event)
    if event.get("etag") != state["expected_etag"]:
        return complete(db.transaction(), {"error": "The appointment was edited elsewhere. "
                                          "No change was made. Ask the team to review its current details."})
    if start <= datetime.now(UTC) or cal.busy(start, finish, exclude_event_id=event_id):
        return complete(db.transaction(), conflict())
    properties = {**event.get("extendedProperties", {}),
                  "private": {**private, "gz_move_operation": operation_id}}
    try:
        moved = cal.update(event_id, {
            "start": {"dateTime": start.isoformat(), "timeZone": MIAMI.key},
            "end": {"dateTime": finish.isoformat(), "timeZone": MIAMI.key},
            "status": state["status"], "extendedProperties": properties,
        }, state["expected_etag"])
    except ToolError as exc:
        return complete(db.transaction(), {"error": str(exc)})
    reply = appointment_reply({"event_id": event_id, "start": moved["start"]["dateTime"],
                               "status": moved["status"]}, "Rescheduled")
    return complete(db.transaction(), reply, moved)
