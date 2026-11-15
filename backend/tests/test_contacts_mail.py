import unittest
from receptionist.contacts import confirmed_email, us_phone
from receptionist.mail import render
from receptionist.records import extract_lead

class ContactsMail(unittest.TestCase):
    def test_email_preserves_only_confirmed_exact_punctuation(self):
        self.assertEqual(confirmed_email("jmunoz@example.com",True),"jmunoz@example.com")
        self.assertEqual(confirmed_email("j.munoz@example.com",True),"j.munoz@example.com")
        self.assertIsNone(confirmed_email("j.munoz@example.com",False))
        self.assertIsNone(confirmed_email("j. munoz@example.com",True))
        self.assertIsNone(confirmed_email("bad\r\nBcc:other@example.com",True))

    def test_phone_formats_only_full_us_numbers(self):
        for value in ["954 77. 0. 8. 428","(954) 770-8428","+1 9547708428"]:
            self.assertEqual(us_phone(value),"954-770-8428")
        self.assertEqual(us_phone("+44 20 7946 0958"),"+44 20 7946 0958")
        self.assertEqual(us_phone("123"),"123")

    def test_extract_does_not_promote_unconfirmed_email(self):
        message={"call":{"id":"test"},"analysis":{"structuredData":{"email":"a.b@example.com","phone":"954 77. 0. 8. 428"}}}
        lead=extract_lead(message)
        self.assertIsNone(lead["email"]);self.assertEqual(lead["phone"],"954-770-8428")
        message["analysis"]["structuredData"]["email_confirmed"]=True
        self.assertEqual(extract_lead(message)["email"],"a.b@example.com")

    def test_email_layout_escapes_untrusted_content_and_uses_confirmed_reply(self):
        html=render("New inquiry","Plain",{"name":'<img src=x onerror="attack()">',"email":"alex@example.com",
          "email_confirmed":True,"phone":"9547708428","summary":"A & B",
          "transcript":"<script>attack()</script>","recording_url":"javascript:attack()",
          "timestamp":"2026-11-15T19:51:50Z","channel":"web"})
        self.assertIn("#0B2545",html);self.assertIn("#8C6844",html)
        self.assertIn("Reply to lead",html);self.assertIn("mailto:alex@example.com",html)
        self.assertIn("954-770-8428",html);self.assertIn("&lt;script&gt;",html)
        self.assertNotIn("<script>",html);self.assertNotIn("javascript:",html)
        self.assertNotIn("{{",html);self.assertNotIn("[BROKERAGE",html)
        self.assertIn("2:51 PM EST",html)

    def test_no_email_creates_call_action_and_plain_notification_works(self):
        html=render("New inquiry","Plain",{"phone":"9547708428"})
        self.assertIn('href="tel:+19547708428"',html);self.assertIn("Call lead",html)
        self.assertNotIn("mailto:None",html)
        self.assertIn("Urgent &lt;message&gt;",render("Urgent","Urgent <message>"))
