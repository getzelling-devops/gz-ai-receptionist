"""Replay outstanding operations after a provider outage using the original IDs."""
import logging

from google.cloud.firestore_v1.base_query import FieldFilter

from .booking import Calendar, book
from .config import database
from .records import deliver
from .rescheduling import reschedule


def run():
    db = database()
    failed = False
    for item in db.collection("deliveries").where(filter=FieldFilter("status", "==", "pending")).stream():
        try:
            deliver(db, item.reference)
        except Exception as exc:
            logging.error("Delivery %s: %s", item.id, type(exc).__name__)
            failed = True
    for item in db.collection("bookings").where(filter=FieldFilter("state", "==", "pending")).stream():
        try:
            cal = Calendar()
            try:
                record = item.to_dict()
                book(db, cal, item.id, record["arguments"], record.get("conversation_id"))
            finally:
                cal.http.close()
        except Exception as exc:
            logging.error("Booking %s: %s", item.id, type(exc).__name__)
            failed = True
    for item in db.collection("booking_moves").where(filter=FieldFilter("state", "==", "pending")).stream():
        try:
            cal = Calendar()
            try:
                record = item.to_dict()
                reschedule(db, cal, item.id, record["arguments"], record["conversation_id"])
            finally:
                cal.http.close()
        except Exception as exc:
            logging.error("Appointment move %s: %s", item.id, type(exc).__name__)
            failed = True
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(run())
