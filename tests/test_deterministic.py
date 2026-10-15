from pathlib import Path

from clearsheet import verify
from clearsheet.schedule import slots
from clearsheet.scrub import scrub

ROOT = Path(__file__).resolve().parent.parent
DOC = (ROOT / "samples" / "01_heart_failure.txt").read_text()


def test_scrub_masks_identifiers_and_restores():
    r = scrub(DOC)
    for secret in ("Margaret Ellison", "4471-2093", "5584-226-914-QT", "1951-03-14", "(613) 555-0142"):
        assert secret not in r.text
    assert "Furosemide 40 mg PO BID" in r.text  # clinical content untouched
    assert r.restore(r.text) == DOC


def test_scrub_catches_first_name_used_alone():
    doc = (ROOT / "samples" / "08_pediatric_asthma.txt").read_text()
    r = scrub(doc)
    assert "Mila" not in r.text and "Oksana" not in r.text


def test_grounded_item_passes():
    item = {"name": "Furosemide", "dose": "40 mg", "frequency": "BID", "status": "changed",
            "source_quote": "Furosemide 40 mg PO BID (INCREASED from 20 mg daily)."}
    r = verify.check_item("medication", item, DOC)
    assert r["grounding"] == 1.0
    assert r["state"] == "review"  # dose change always goes to a nurse


def test_wrong_number_is_blocked():
    item = {"name": "Furosemide", "dose": "80 mg", "frequency": "BID", "status": "changed",
            "source_quote": "Furosemide 40 mg PO BID (INCREASED from 20 mg daily)."}
    assert verify.check_item("medication", item, DOC)["state"] == "blocked"


def test_invented_quote_is_blocked():
    item = {"instruction": "Drink 3 L of water a day", "source_quote": "Drink 3 L of water a day."}
    assert verify.check_item("self_care", item, DOC)["state"] == "blocked"


def test_high_alert_medicine_flagged():
    assert verify.high_alert_class("Apixaban") == "anticoagulant"
    assert verify.high_alert_class("Insulin glargine") == "insulin"
    assert verify.high_alert_class("Ramipril") is None


def test_translation_number_drift_detected():
    item = {"name": "Spironolactone", "dose": "12.5 mg", "source_quote": "Spironolactone 12.5 mg PO daily (NEW)."}
    ok = verify.check_translation(item, "Take 12.5 mg once a day.", "Приймайте Spironolactone 12.5 мг один раз на день.",
                                  "Take Spironolactone 12.5 mg once a day.", "Spironolactone")
    assert ok == []
    bad = verify.check_translation(item, "Take 12.5 mg once a day.", "Приймайте Spironolactone 125 мг один раз на день.",
                                   "Take Spironolactone 125 mg once a day.", "Spironolactone")
    assert bad


def test_arabic_digits_normalised():
    assert verify.numbers("٤٠ ملغ") == ["40"]


def test_schedule_slots():
    assert slots("BID")["slots"] == ["morning", "evening"]
    assert slots("at bedtime")["slots"] == ["bedtime"]
    assert slots("q6h PRN")["prn"] is True and slots("q6h PRN")["slots"] == []
    assert slots("TID")["slots"] == ["morning", "midday", "evening"]
    assert slots("whenever the moon is full") is None


def test_number_present_elsewhere_in_quote_still_blocked():
    doc = (ROOT / "samples" / "05_cholecystectomy_opioid.txt").read_text()
    quote = "Oxycodone 5 mg PO q4h PRN severe pain only. 10 tablets dispensed. No refills."
    good = {"name": "Oxycodone", "dose": "5 mg", "frequency": "q4h PRN", "source_quote": quote}
    bad = dict(good, dose="10 mg")  # 10 appears in the quote, but as "10 tablets"
    assert verify.check_item("medication", good, doc)["state"] == "review"  # opioid -> nurse
    assert verify.check_item("medication", bad, doc)["state"] == "blocked"


def test_softened_emergency_line_flagged():
    item = {"sign": "black or bloody stools",
            "source_quote": "Seek emergency care if: black or bloody stools, vomiting blood, severe headache."}
    soft = verify.check_translation(item, "Tell your doctor if you have black or bloody stools.", "x", "x", None, "warning")
    assert soft and "urgency" in soft[0]
    ok = verify.check_translation(item, "Go to the emergency department if you have black or bloody stools.", "x",
                                  "Go to emergency if you have black stools.", None, "warning")
    assert ok == []
