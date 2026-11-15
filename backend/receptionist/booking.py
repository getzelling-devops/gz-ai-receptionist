"""Quarter-hour start times with Calendar as the authority for busy time."""
import os
import re
from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import quote
from uuid import uuid4
from zoneinfo import ZoneInfo

from firebase_admin import firestore
import google.auth
from google.auth import impersonated_credentials
from google.auth.transport.requests import AuthorizedSession

from .config import PROJECT
from .contacts import us_phone
from .records import key_for

MIAMI = ZoneInfo("America/New_York")
STEP = timedelta(minutes=15)
DURATIONS = {"first_call": timedelta(minutes=30), "general_inquiry": timedelta(minutes=30),
             "listing_presentation": timedelta(hours=1)}
API = "https://www.googleapis.com/calendar/v3"


class ToolError(ValueError):
    """Safe text to send to the assistant."""


def parse_start(value):
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            raise ValueError()
        return stamp.astimezone(MIAMI)
    except (ValueError, TypeError):
        raise ToolError("Give an ISO date and time with a UTC offset.") from None


def slot_policy(start, kind, now, duration=None):
    if kind not in DURATIONS:
        raise ToolError("Choose first_call, general_inquiry or listing_presentation.")
    duration = duration or DURATIONS[kind]
    if start <= now or start.minute not in (0, 15, 30, 45) or start.second or start.microsecond:
        raise ToolError("Choose a future slot at :00, :15, :30 or :45.")
    close = datetime.combine(start.date(), time(18), MIAMI)
    if start.hour < 9 or start + duration > close:
        raise ToolError("Choose a slot that fits entirely between 9 am and 6 pm Miami time.")
    tentative = start.weekday() >= 5 or (kind == "listing_presentation" and
                                        start.astimezone(UTC) - now.astimezone(UTC) < timedelta(days=1))
    return start + duration, "tentative" if tentative else "confirmed"


class Calendar:
    def __init__(self):
        self.id = os.environ["BOOKING_CALENDAR_ID"]
        extra = os.getenv("BUSY_CALENDAR_IDS", "").split(",")
        self.calendars = sorted({self.id, *(item.strip() for item in extra if item.strip())})
        self.events = f"{API}/calendars/{quote(self.id, safe='')}/events"
        source, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        creds = impersonated_credentials.Credentials(
            source_credentials=source,
            target_principal=os.getenv("CALENDAR_SERVICE_ACCOUNT", f"receptionist-calendar@{PROJECT}.iam.gserviceaccount.com"),
            target_scopes=["https://www.googleapis.com/auth/calendar.events",
                           "https://www.googleapis.com/auth/calendar.freebusy",
                           "https://www.googleapis.com/auth/calendar.calendars.readonly"],
            lifetime=600,
        )
        self.http = AuthorizedSession(creds)

    def busy(self, start, end, exclude_event_id=None):
        ids = [i for i in self.calendars if not (exclude_event_id and i == self.id)]
        intervals = []
        if ids:
            res = self.http.post(f"{API}/freeBusy", json={"timeMin": start.isoformat(),
                                 "timeMax": end.isoformat(), "items": [{"id": i} for i in ids]}, timeout=5)
            res.raise_for_status()
            calendars = res.json()["calendars"]
            for cal_id in ids:
                value = calendars[cal_id]
                if value.get("errors"):
                    raise RuntimeError("Calendar availability unavailable")
                intervals.extend((parse_start(b["start"]), parse_start(b["end"])) for b in value["busy"])
        if exclude_event_id:
            # Free/busy merges overlapping events. Subtracting our old interval could
            # hide a different event, so list this calendar and exclude only our ID.
            params = {"timeMin": start.isoformat(), "timeMax": end.isoformat(),
                      "singleEvents": "true", "maxResults": 2500}
            while True:
                response = self.http.get(self.events, params=params, timeout=5)
                response.raise_for_status()
                page = response.json()
                for event in page.get("items", []):
                    if (event["id"] == exclude_event_id or event.get("status") == "cancelled"
                            or event.get("transparency") == "transparent"):
                        continue
                    def stamp(part):
                        if "dateTime" in part:
                            return parse_start(part["dateTime"])
                        if not getattr(self, "zone", None):
                            metadata = self.http.get(self.events.rsplit("/events", 1)[0], timeout=5)
                            metadata.raise_for_status()
                            self.zone = ZoneInfo(metadata.json()["timeZone"])
                        return datetime.combine(date.fromisoformat(part["date"]), time(), self.zone)
                    intervals.append((stamp(event["start"]), stamp(event["end"])))
                if not page.get("nextPageToken"):
                    break
                params["pageToken"] = page["nextPageToken"]
        return intervals

    def find(self, event_id):
        res = self.http.get(f"{self.events}/{event_id}", timeout=5)
        if res.status_code == 404:
            return None
        res.raise_for_status()
        return res.json()

    def insert(self, event):
        res = self.http.post(self.events, json=event, timeout=5)
        if res.status_code == 409:
            existing = self.find(event["id"])
            if existing and existing.get("status") != "cancelled":
                return existing
        res.raise_for_status()
        return res.json()

    def update(self, event_id, changes, etag):
        if not etag:
            raise ToolError("The appointment version is unavailable. Offer a team callback.")
        res = self.http.patch(f"{self.events}/{event_id}", json=changes,
                              headers={"If-Match": etag}, timeout=5)
        if res.status_code == 412:
            raise ToolError("The appointment changed while being checked. Ask the team to review it.")
        res.raise_for_status()
        return res.json()


def day_slots(db, calendar, start, kind, days=14, exclude_event_id=None, duration=None,
              ignore_operation=None):
    if kind not in DURATIONS:
        raise ToolError("Unknown appointment type.")
    now = datetime.now(MIAMI)
    start = max(start, now)
    end_date = start.date() + timedelta(days=days)
    end = datetime.combine(end_date, time(), MIAMI)
    duration = duration or DURATIONS[kind]
    busy = (calendar.busy(start, end, exclude_event_id=exclude_event_id)
            if exclude_event_id else calendar.busy(start, end))
    for offset in range(days):
        day = start.date() + timedelta(days=offset)
        candidate = datetime.combine(day, time(9), MIAMI)
        holds = db.collection("booking_days").document(key_for(calendar.id, day.isoformat())).get().to_dict() or {}
        while candidate.hour < 18:
            finish = candidate + duration
            if (candidate >= start and finish <= candidate.replace(hour=18, minute=0)
                    and all(k not in holds or holds[k] == ignore_operation for k in cells(candidate, finish))
                    and not any(a < finish and b > candidate for a, b in busy)):
                _, status = slot_policy(candidate, kind, now, duration)
                return f"{candidate.isoformat()} Miami time ({status})"
            candidate += STEP
    return None


def cells(start, end):
    while start < end:
        yield start.strftime("t%H%M")
        start += STEP


def appointment_reply(appointment, action="Scheduled"):
    status = appointment["status"]
    note = ("Held pending team confirmation." if status == "tentative" else
            "The GetZelling team will contact the caller if anything changes.")
    return {"result": f"{action} for {appointment['start']} Miami time ({status}). {note} "
                      f"Internal appointment reference: {appointment['event_id']}. "
                      "Keep this reference for changes; do not read it aloud."}


def owned_appointment(db, cal, appointment_id, conversation):
    if not isinstance(appointment_id, str) or not re.fullmatch(r"[0-9a-f]{64}", appointment_id):
        raise ToolError("Use the appointment reference returned when this conversation booked it.")
    value = db.collection("appointments").document(appointment_id).get().to_dict()
    if (not value or not conversation or value.get("conversation_id") != conversation
            or value.get("calendar") != cal.id):
        raise ToolError("This appointment cannot be changed from this conversation. Offer a team callback.")
    return value


def book(db, cal, op_id, args, conversation=None):
    start = parse_start(args.get("start"))
    kind = args.get("appointment_type")
    if not isinstance(kind, str) or kind not in DURATIONS:
        raise ToolError("Choose first_call, general_inquiry or listing_presentation.")
    contact = args.get("contact_name")
    callback = args.get("phone")
    if not all(isinstance(v, str) and 0 < len(v.strip()) <= 160 for v in (contact, callback)):
        raise ToolError("Ask for the contact name and callback number before booking.")
    callback = us_phone(callback)
    args = {**args, "phone": callback}
    details = args.get("meeting_details", "")
    if not isinstance(details, str) or len(details) > 1000:
        raise ToolError("Keep meeting location and contact details under 1,000 characters.")
    if not isinstance(args.get("additional_appointment", False), bool):
        raise ToolError("Specify whether the caller explicitly requested an additional appointment.")
    ref = db.collection("bookings").document(op_id)
    normalized_phone = re.sub(r"\D", "", callback)
    if len(normalized_phone) == 11 and normalized_phone.startswith("1"):
        normalized_phone = normalized_phone[1:]
    group = (db.collection("appointment_groups").document(
        key_for(conversation, cal.id, kind, normalized_phone)) if conversation else None)
    day = db.collection("booking_days").document(key_for(cal.id, start.date().isoformat()))
    finish = start + DURATIONS[kind]
    slots = list(cells(start, finish))
    owner = uuid4().hex
    now = datetime.now(UTC)

    @firestore.transactional
    def reserve(tx):
        previous = ref.get(transaction=tx).to_dict() or {}
        if previous and (previous["arguments"] != args or previous["calendar"] != cal.id):
            raise ToolError("This tool call ID was already used for a different request.")
        if previous.get("reply"):
            return previous["reply"]
        if previous.get("state") == "conflict":
            return "occupied"
        if previous and previous["lease_until"] > now:
            raise ToolError("Booking is being checked. Do not confirm yet.")
        active = (group.get(transaction=tx).to_dict() or {}) if group else {}
        if (active.get("appointment_id") not in (None, op_id)
                and not args.get("additional_appointment", False)):
            raise ToolError(f"An appointment of this type already exists in this conversation. "
                            f"Use reschedule-appointment with reference {active['appointment_id']} "
                            "to change its time. Create another only if the caller explicitly wants a separate meeting.")
        holds = day.get(transaction=tx).to_dict() or {}
        if any(holds.get(k) not in (None, op_id) for k in slots):
            tx.create(ref, {"arguments": args, "calendar": cal.id, "state": "conflict"})
            return "occupied"
        if previous:
            status = previous["status"]
        else:
            _, status = slot_policy(start, kind, now)
        tx.set(day, dict.fromkeys(slots, op_id), merge=True)
        tx.set(ref, {"arguments": args, "calendar": cal.id, "status": status, "owner": owner,
                     "conversation_id": conversation,
                     "lease_until": now + timedelta(minutes=2), "state": "pending"})
        if group:
            tx.set(group, {"appointment_id": op_id})
        return None

    def conflict_reply():
        alternative = day_slots(db, cal, start + STEP, kind, ignore_operation=op_id)
        text = f"Offer {alternative}." if alternative else "Offer a callback to arrange another time."
        return {"error": "That slot is unavailable. Apologize. " + text}

    prior = reserve(db.transaction())
    if prior == "occupied":
        reply = conflict_reply()
        ref.update({"reply": reply, "state": "done"})
        return reply
    if prior:
        if conversation and "result" in prior:
            current = db.collection("appointments").document(op_id).get().to_dict()
            if current:
                if current.get("pending_move"):
                    raise ToolError("The appointment change is still being reconciled. Do not confirm its old time.")
                return appointment_reply(current)
        return prior

    @firestore.transactional
    def complete(tx, reply, event=None):
        current = ref.get(transaction=tx).to_dict()
        active = (group.get(transaction=tx).to_dict() or {}) if group else {}
        if current["owner"] != owner:
            raise ToolError("Booking is being reconciled. Do not confirm yet.")
        tx.update(ref, {"reply": reply, "state": "done"})
        tx.update(day, dict.fromkeys(slots, firestore.DELETE_FIELD))
        if event and conversation:
            appointment = {"event_id": op_id, "calendar": cal.id, "conversation_id": conversation,
                           "arguments": args, "start": event["start"]["dateTime"],
                           "end": event["end"]["dateTime"], "status": event["status"],
                           "updated_at": firestore.SERVER_TIMESTAMP}
            tx.create(db.collection("appointments").document(op_id), appointment)
        elif group and active.get("appointment_id") == op_id:
            tx.update(group, {"appointment_id": firestore.DELETE_FIELD})
        return reply

    # Recover a lost insert response before querying free/busy (which includes our event).
    event = cal.find(op_id)
    if event and event.get("status") == "cancelled":
        return complete(db.transaction(), {"error": "This booking was cancelled. Offer a new slot."})
    if not event:
        if start <= datetime.now(UTC) or cal.busy(start, finish):
            return complete(db.transaction(), conflict_reply())
        status = ref.get().get("status")
        event = cal.insert({"id": op_id, "summary": kind.replace("_", " ").title() + " — " + contact,
                            "description": f"Callback: {callback}\n{details}".strip(), "status": status, "transparency": "opaque",
                            "start": {"dateTime": start.isoformat(), "timeZone": MIAMI.key},
                            "end": {"dateTime": finish.isoformat(), "timeZone": MIAMI.key}})
    reply = appointment_reply({"event_id": op_id, "start": event["start"]["dateTime"], "status": event["status"]})
    return complete(db.transaction(), reply, event)


def availability(db, cal, args, conversation=None):
    try:
        day = date.fromisoformat(args["date"])
    except (KeyError, ValueError, TypeError):
        raise ToolError("Give a date in YYYY-MM-DD format.") from None
    kind = args.get("appointment_type", "general_inquiry")
    excluded = None
    duration = None
    if args.get("appointment_id"):
        appointment = owned_appointment(db, cal, args["appointment_id"], conversation)
        if appointment.get("pending_move"):
            raise ToolError("The previous appointment change is still being reconciled. Do not create another booking.")
        event = cal.find(appointment["event_id"])
        if not event or event.get("status") == "cancelled":
            raise ToolError("This appointment is no longer active. Offer a team callback.")
        kind = appointment["arguments"]["appointment_type"]
        duration = parse_start(event["end"]["dateTime"]) - parse_start(event["start"]["dateTime"])
        excluded = appointment["event_id"]
    requested = args.get("start")
    start = parse_start(requested) if requested is not None else datetime.combine(day, time(9), MIAMI)
    if requested is not None:
        if start.date() != day:
            raise ToolError("The requested time and date must describe the same Miami day.")
        slot_policy(start, kind, datetime.now(MIAMI), duration)
    slot = day_slots(db, cal, start, kind, exclude_event_id=excluded, duration=duration)
    if requested is not None:
        if slot and slot.startswith(start.isoformat() + " Miami time"):
            return {"result": f"Requested slot available: {slot}. Confirm this exact time with the caller before booking."}
        alternative = f"Offer {slot}." if slot else "Offer a callback to arrange another time."
        return {"error": f"The requested time {start.isoformat()} is unavailable. {alternative} "
                         "Get the caller's explicit agreement before booking a different time."}
    return {"result": f"Next available: {slot}."} if slot else {"error": "No slot in the next 14 days. Offer a callback."}
