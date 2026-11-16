"""GetZelling 1b Midnight email layout, adapted from the website form template."""
from datetime import datetime, UTC
from functools import lru_cache
from html import escape
from pathlib import Path
import re
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .contacts import confirmed_email, us_phone

@lru_cache
def template():
    return Path(__file__).with_name("lead-email.html").read_text()

def row(label, value):
    return (f'<tr><td class="rule t-muted" width="132" valign="top" style="width:132px;padding:13px 0;'
            f'border-top:1px solid #E4DCCD;font:13px/20px Geist,Arial,sans-serif;color:#716D62">{escape(label)}</td>'
            f'<td class="rule t-body" valign="top" style="padding:13px 0;border-top:1px solid #E4DCCD;'
            f'font:14px/21px Geist,Arial,sans-serif;color:#4A4436;word-break:break-word">{value}</td></tr>')

def render(subject, body, lead=None):
    lead = lead or {}
    email = confirmed_email(lead.get("email"), lead.get("email_confirmed"))
    phone = us_phone(lead.get("phone"))
    when = lead.get("timestamp")
    try:
        moment = datetime.fromisoformat(when.replace("Z", "+00:00")) if isinstance(when,str) else datetime.now(UTC)
        if moment.tzinfo is None: moment = moment.replace(tzinfo=UTC)
    except ValueError:
        moment = datetime.now(UTC)
    local = moment.astimezone(ZoneInfo("America/New_York"))
    href = "mailto:gizelle@getzelling.com?subject=" + quote(subject, safe="")
    label = "Email Gizelle"
    if email:
        href = "mailto:" + quote(email,safe="@.+-") + "?subject=" + quote("Re: Your GetZelling inquiry",safe="")
        label = "Reply to lead"
    elif isinstance(phone,str) and re.fullmatch(r"\d{3}-\d{3}-\d{4}",phone):
        href = "tel:+1" + phone.replace("-","")
        label = "Call lead"
    contact = f'<a href="mailto:{escape(quote(email,safe="@.+-"))}" style="color:#CDD4E0">{escape(email)}</a>' if email else escape(phone or "Contact details not provided")
    details = []
    for key,title in [("name","Name"),("email","Confirmed email"),("phone","Phone"),("lead_type","Lead type"),("summary","Summary")]:
        value = email if key=="email" else phone if key=="phone" else lead.get(key)
        if value: details.append(row(title,escape(str(value)).replace("\n","<br>")))
    if not lead:
        details.append(row("Message",escape(body).replace("\n","<br>")))
    transcript=lead.get("transcript")
    if transcript:
        excerpt=transcript[:12000]
        details.append(row("Transcript",escape(excerpt).replace("\n","<br>")+
                           ("<br><em>Excerpt. Full transcript retained in the lead record.</em>" if len(transcript)>len(excerpt) else "")))
    url=lead.get("recording_url")
    if isinstance(url,str) and url.startswith("https://"):
        details.append(row("Recording",f'<a class="lnk" href="{escape(url,quote=True)}" style="color:#0B2545">Listen to recording</a>'))
    if lead.get("call_id"): details.append(row("Call reference",escape(str(lead["call_id"]))))
    vals = {
        "subject":escape(subject),"preheader":escape(lead.get("summary") or subject),
        "logo_url":"https://gz-gz-website.web.app/assets/email/logo-reversed-navy-2x.png",
        "eyebrow":"Gizelle · New inquiry","full_name":escape(lead.get("name") or "GetZelling inquiry"),
        "contact_line":contact,"reply_href":escape(href,quote=True),"reply_label":label,
        "chip_label":"Lead type","chip_value":escape(lead.get("lead_type") or "Inquiry"),
        "received_time":escape(local.strftime("%I:%M %p %Z").lstrip("0")),
        "referrer_path":escape("Web voice" if lead.get("channel") in ("web", "web_voice") else "Phone" if lead.get("channel")=="phone" else "Web text" if lead.get("channel")=="web_text" else "Gizelle"),
        "field_rows":"".join(details),
        "meta_rows":row("Received",escape(local.strftime("%b %d, %Y · %I:%M %p %Z"))),
        "footer_blurb":"Internal lead notification for the GetZelling team. Sent by Gizelle.",
        "url":"https://getzelling.com/","url_display":"getzelling.com",
    }
    return re.sub(r"{{([a-z_]+)}}",lambda m:vals[m[1]],template())
