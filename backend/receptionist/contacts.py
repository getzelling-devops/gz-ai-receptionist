"""Contact formatting preserves email punctuation; it never guesses an address."""
import re

def us_phone(value):
    if not isinstance(value, str):
        return value
    if not re.fullmatch(r"\+?[0-9\s().-]+", value.strip()):
        return value
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if re.fullmatch(r"[2-9]\d{2}[2-9]\d{6}", digits):
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return value

def confirmed_email(value, confirmed):
    if confirmed is not True or not isinstance(value, str):
        return None
    value = value.strip()
    if len(value) > 254 or not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}", value):
        return None
    local, domain = value.rsplit("@", 1)
    if local.startswith(".") or local.endswith(".") or ".." in local or ".." in domain:
        return None
    return value
