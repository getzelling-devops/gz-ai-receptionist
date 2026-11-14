import copy
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import uuid4

import httpx
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore

from receptionist import booking
from receptionist.rescheduling import reschedule


class CalendarRules(unittest.TestCase):
    def test_quarter_hour_starts_keep_the_original_reservation_lengths(self):
        now = datetime(2031, 4, 9, 9, tzinfo=booking.MIAMI)
        for minute in (0, 15, 30, 45):
            start = now.replace(day=10, hour=12, minute=minute)
            self.assertEqual(booking.slot_policy(start, "first_call", now)[0]-start,
                             timedelta(minutes=30))
            self.assertEqual(booking.slot_policy(start, "listing_presentation", now)[0]-start,
                             timedelta(hours=1))
        with self.assertRaises(booking.ToolError):
            booking.slot_policy(now.replace(day=10, hour=17, minute=15), "listing_presentation", now)
        start = now.replace(day=10, hour=12, minute=45)
        self.assertEqual(list(booking.cells(start, start+timedelta(hours=1))),
                         ["t1245", "t1300", "t1315", "t1330"])

    def test_exclusion_keeps_overlapping_other_events_and_blocking_calendars(self):
        calls = []
        def respond(request):
            calls.append(request)
            if request.method == "POST":
                self.assertEqual(__import__("json").loads(request.content)["items"], [{"id": "personal"}])
                return httpx.Response(200, json={"calendars": {"personal": {"busy": [
                    {"start": "2031-04-10T13:00:00-04:00", "end": "2031-04-10T14:00:00-04:00"}]}}})
            if request.url.path.endswith("/calendars/booking"):
                return httpx.Response(200, json={"timeZone": "America/New_York"})
            if request.url.params.get("pageToken") == "next":
                return httpx.Response(200, json={"items": [
                    {"id": "holiday", "start": {"date": "2031-04-11"}, "end": {"date": "2031-04-12"}},
                    {"id": "free", "transparency": "transparent"}, {"id": "deleted", "status": "cancelled"}]})
            return httpx.Response(200, json={"nextPageToken": "next", "items": [
                {"id": "self", "start": {"dateTime": "2031-04-10T13:00:00-04:00"},
                 "end": {"dateTime": "2031-04-10T14:00:00-04:00"}},
                {"id": "another", "start": {"dateTime": "2031-04-10T13:15:00-04:00"},
                 "end": {"dateTime": "2031-04-10T13:45:00-04:00"}}]})
        cal = object.__new__(booking.Calendar)
        cal.id = "booking"; cal.calendars = ["booking", "personal"]
        cal.events = "https://calendar.test/calendar/v3/calendars/booking/events"
        with httpx.Client(transport=httpx.MockTransport(respond)) as cal.http:
            start = datetime(2031, 4, 10, tzinfo=booking.MIAMI)
            busy = cal.busy(start, start+timedelta(days=3), exclude_event_id="self")
        self.assertEqual(len(busy), 3)
        self.assertIn((start.replace(hour=13), start.replace(hour=14)), busy)
        self.assertIn((start.replace(hour=13, minute=15), start.replace(hour=13, minute=45)), busy)
        self.assertIn((start+timedelta(days=1), start+timedelta(days=2)), busy)
        self.assertTrue(any(r.url.params.get("pageToken") == "next" for r in calls))

    def test_calendar_move_is_conditional_and_reports_a_concurrent_edit(self):
        def respond(request):
            self.assertEqual(request.method, "PATCH")
            self.assertEqual(request.headers["If-Match"], '"version-one"')
            return httpx.Response(412)
        cal = object.__new__(booking.Calendar)
        cal.events = "https://calendar.test/events"
        with httpx.Client(transport=httpx.MockTransport(respond)) as cal.http:
            with self.assertRaisesRegex(booking.ToolError, "changed"):
                cal.update("appointment", {"start": {}}, '"version-one"')


class TestCalendar:
    def __init__(self):
        self.id = uuid4().hex
        self.events = {}
        self.extra_busy = []
        self.inserts = 0
        self.updates = 0
        self.lose_response = False
        self.entered = None
        self.release = None

    def find(self, event_id):
        return copy.deepcopy(self.events.get(event_id))

    def busy(self, start, end, exclude_event_id=None):
        events = [(booking.parse_start(e["start"]["dateTime"]), booking.parse_start(e["end"]["dateTime"]))
                  for eid, e in self.events.items() if eid != exclude_event_id and e.get("status") != "cancelled"]
        return [(a, b) for a, b in events+self.extra_busy if a < end and b > start]

    def insert(self, event):
        self.inserts += 1
        self.events[event["id"]] = {**copy.deepcopy(event), "etag": '"v1"'}
        return self.find(event["id"])

    def update(self, event_id, changes, etag):
        self.updates += 1
        if self.entered:
            self.entered.set()
            if not self.release.wait(10):
                raise TimeoutError("test release timed out")
        if self.events[event_id]["etag"] != etag:
            raise booking.ToolError("The appointment changed elsewhere.")
        self.events[event_id].update(copy.deepcopy(changes))
        self.events[event_id]["etag"] = '"v' + str(self.updates+1) + '"'
        if self.lose_response:
            self.lose_response = False
            raise httpx.ReadTimeout("PATCH response lost after calendar update")
        return self.find(event_id)


@unittest.skipUnless(os.getenv("FIRESTORE_EMULATOR_HOST", "").startswith("127.0.0.1:"),
                     "set FIRESTORE_EMULATOR_HOST to a loopback emulator")
class AppointmentMoves(unittest.TestCase):
    def setUp(self):
        self.db = firestore.Client(project="demo-receptionist", credentials=AnonymousCredentials())
        self.cal = TestCalendar()
        self.conversation = uuid4().hex
        self.start = (datetime.now(booking.MIAMI)+timedelta(days=10)).replace(
            hour=13, minute=0, second=0, microsecond=0)
        self.args = {"start": self.start.isoformat(), "appointment_type": "listing_presentation",
                     "contact_name": "Jordan Calendar Test", "phone": "202-555-0142",
                     "meeting_details": "Property visit: 123 Test Avenue"}
        self.appointment_id = uuid4().hex*2
        booking.book(self.db, self.cal, self.appointment_id, self.args, self.conversation)

    def move_args(self, start=None):
        return {"appointment_id": self.appointment_id,
                "start": (start or self.start+timedelta(minutes=30)).isoformat()}

    def test_overlap_with_original_is_available_and_moves_the_same_event(self):
        args = self.move_args()
        available = booking.availability(self.db, self.cal, {
            **args, "date": self.start.date().isoformat(), "appointment_type": "listing_presentation"
        }, self.conversation)
        self.assertIn("Requested slot available", available["result"])
        op = uuid4().hex
        result = reschedule(self.db, self.cal, op, args, self.conversation)
        self.assertIn("Rescheduled", result["result"])
        replay = reschedule(self.db, self.cal, op, args, self.conversation)
        self.assertIn(args["start"], replay["result"])
        with self.assertRaisesRegex(booking.ToolError, "different appointment change"):
            reschedule(self.db, self.cal, op, self.move_args(self.start+timedelta(hours=2)), self.conversation)
        self.assertEqual((self.cal.inserts, self.cal.updates, len(self.cal.events)), (1, 1, 1))
        event = self.cal.find(self.appointment_id)
        self.assertEqual(event["start"]["dateTime"], args["start"])
        self.assertEqual(booking.parse_start(event["end"]["dateTime"]), self.start+timedelta(minutes=90))
        self.assertIn("123 Test Avenue", event["description"])
        self.assertIn("202-555-0142", event["description"])
        self.assertIn(args["start"], booking.book(self.db, self.cal, self.appointment_id,
                                                self.args, self.conversation)["result"])

    def test_other_busy_event_blocks_move_without_changing_original(self):
        self.cal.extra_busy = [(self.start+timedelta(minutes=45), self.start+timedelta(hours=2))]
        result = reschedule(self.db, self.cal, uuid4().hex, self.move_args(), self.conversation)
        self.assertIn("original appointment is unchanged", result["error"])
        self.assertEqual(self.cal.find(self.appointment_id)["start"]["dateTime"], self.args["start"])
        self.assertEqual(self.cal.updates, 0)
        self.assertFalse(self.db.collection("appointments").document(self.appointment_id).get().to_dict().get("pending_move"))

    def test_a_new_tool_call_cannot_create_a_duplicate_when_changing_time(self):
        new = {**self.args, "start": (self.start+timedelta(hours=2)).isoformat(), "phone": "+1 (202) 555-0142"}
        with self.assertRaisesRegex(booking.ToolError, "reschedule-appointment"):
            booking.book(self.db, self.cal, uuid4().hex*2, new, self.conversation)
        self.assertEqual(self.cal.inserts, 1)
        booking.book(self.db, self.cal, uuid4().hex*2, {**new, "additional_appointment": True}, self.conversation)
        self.assertEqual(self.cal.inserts, 2)

    def test_another_conversation_cannot_move_this_appointment(self):
        with self.assertRaisesRegex(booking.ToolError, "cannot be changed"):
            reschedule(self.db, self.cal, uuid4().hex, self.move_args(), "other-call")
        self.assertEqual(self.cal.updates, 0)

    def test_lost_patch_response_is_reconciled_without_another_update_or_insert(self):
        op = uuid4().hex
        self.cal.lose_response = True
        with self.assertRaises(httpx.ReadTimeout):
            reschedule(self.db, self.cal, op, self.move_args(), self.conversation)
        with self.assertRaisesRegex(booking.ToolError, "reschedule-appointment"):
            booking.book(self.db, self.cal, uuid4().hex*2,
                         {**self.args, "start": (self.start+timedelta(hours=2)).isoformat()}, self.conversation)
        self.db.collection("booking_moves").document(op).update({"lease_until": datetime.now(UTC)})
        result = reschedule(self.db, self.cal, op, self.move_args(), self.conversation)
        self.assertIn("Rescheduled", result["result"])
        self.assertEqual((self.cal.inserts, self.cal.updates, len(self.cal.events)), (1, 1, 1))

    def test_external_edit_after_lost_response_is_preserved(self):
        op = uuid4().hex
        def lost(*args):
            raise httpx.ReadTimeout("request outcome uncertain")
        self.cal.update = lost
        with self.assertRaises(httpx.ReadTimeout):
            reschedule(self.db, self.cal, op, self.move_args(), self.conversation)
        self.cal.events[self.appointment_id]["etag"] = '"manual-edit"'
        self.cal.events[self.appointment_id]["description"] = "Owner's updated notes"
        self.db.collection("booking_moves").document(op).update({"lease_until": datetime.now(UTC)})
        result = reschedule(self.db, self.cal, op, self.move_args(), self.conversation)
        self.assertIn("edited elsewhere", result["error"])
        self.assertEqual(self.cal.events[self.appointment_id]["description"], "Owner's updated notes")

    def test_two_concurrent_moves_of_one_appointment_cannot_race(self):
        self.cal.entered, self.cal.release = Event(), Event()
        with ThreadPoolExecutor() as executor:
            first = executor.submit(reschedule, self.db, self.cal, uuid4().hex,
                                    self.move_args(), self.conversation)
            try:
                self.assertTrue(self.cal.entered.wait(10))
                with self.assertRaisesRegex(booking.ToolError, "previous change"):
                    reschedule(self.db, self.cal, uuid4().hex,
                               self.move_args(self.start+timedelta(hours=2)), self.conversation)
            finally:
                self.cal.release.set()
            self.assertIn("result", first.result())
        self.assertEqual(self.cal.updates, 1)

    def test_successive_time_changes_keep_one_event_and_retries_report_current_time(self):
        first = uuid4().hex
        reschedule(self.db, self.cal, first, self.move_args(), self.conversation)
        second_time = self.start+timedelta(hours=1, minutes=45)
        reschedule(self.db, self.cal, uuid4().hex, self.move_args(second_time), self.conversation)
        replay = reschedule(self.db, self.cal, first, self.move_args(), self.conversation)
        self.assertIn(second_time.isoformat(), replay["result"])
        self.assertEqual((self.cal.inserts, self.cal.updates, len(self.cal.events)), (1, 2, 1))

    def test_overlapping_moves_from_different_appointments_share_destination_locks(self):
        second_id = uuid4().hex*2
        second = {**self.args, "start": self.start.replace(hour=15).isoformat(), "phone": "2025550143"}
        booking.book(self.db, self.cal, second_id, second, self.conversation)
        self.cal.entered, self.cal.release = Event(), Event()
        with ThreadPoolExecutor() as executor:
            first = executor.submit(reschedule, self.db, self.cal, uuid4().hex,
                                    self.move_args(self.start.replace(hour=11, minute=15)), self.conversation)
            try:
                self.assertTrue(self.cal.entered.wait(10))
                result = reschedule(self.db, self.cal, uuid4().hex,
                                    {"appointment_id": second_id,
                                     "start": self.start.replace(hour=11, minute=45).isoformat()}, self.conversation)
                self.assertIn("unavailable", result["error"])
            finally:
                self.cal.release.set()
            self.assertIn("result", first.result())
        self.assertEqual(self.cal.updates, 1)
        self.assertEqual(self.cal.find(second_id)["start"]["dateTime"], second["start"])
