"""Generate the Larkspur Residences demo traces.

    python backend/seed/generate_seed.py

Writes
- backend/seed/larkspur_traces.jsonl      (what the app imports; contains NO labels)
- backend/tests/fixtures/planted_truth.json (which planted failures each trace carries; tests only)

Deterministic: same output every run. The traces are deliberately messy: typos, terse SMS,
multi-turn, mixed OpenAI / Anthropic message formats, a malformed line, an empty record and a
duplicate, so the import report has something to say.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "larkspur_traces.jsonl"
TRUTH = HERE.parent / "tests" / "fixtures" / "planted_truth.json"

SYSTEM_V13 = """You are Lark, the virtual leasing assistant for Larkspur Residences, a group of three apartment communities in the Austin area:
- Larkspur Commons (South Austin, 78704)
- Larkspur at Riverside (East Riverside, 78741)
- Larkspur Heights (Round Rock, 78664)

You talk with prospects and current residents over SMS, email, the website chat widget and phone (voice).

Your job:
- Answer questions about availability, pricing, pet policy, parking, fees and amenities.
- Search units with check_availability and present options that match what the person asked for.
- Book, move or cancel tours with schedule_tour, reschedule_tour and cancel_tour.
- Look up residents with lookup_resident and file maintenance requests with create_maintenance_request.
- Hand the conversation to the leasing team with handoff_to_human when needed.

Be warm, concise and helpful. Always try to move the prospect toward a tour or application.
Office hours: Mon-Sat 9am-6pm, Sun 12pm-5pm (Central)."""

SYSTEM_V14 = SYSTEM_V13 + """

Formatting: on SMS, reply in plain text only, 480 characters max."""

PROPERTIES = {
    "Larkspur Commons": [
        dict(unit="C-104", beds=1, baths=1, sqft=712, rent=1385, floor=1, pets=True, available="2026-10-01"),
        dict(unit="C-215", beds=1, baths=1, sqft=748, rent=1440, floor=2, pets=True, available="2026-09-20"),
        dict(unit="C-308", beds=2, baths=2, sqft=1050, rent=1895, floor=3, pets=True, available="2026-10-15"),
        dict(unit="C-112", beds=2, baths=1, sqft=960, rent=1720, floor=1, pets=False, available="2026-10-05"),
        dict(unit="C-402", beds=0, baths=1, sqft=540, rent=1190, floor=4, pets=True, available="2026-09-28"),
        dict(unit="C-220", beds=3, baths=2, sqft=1310, rent=2450, floor=2, pets=True, available="2026-11-01"),
    ],
    "Larkspur at Riverside": [
        dict(unit="R-101", beds=0, baths=1, sqft=498, rent=1050, floor=1, pets=True, available="2026-09-25"),
        dict(unit="R-118", beds=1, baths=1, sqft=690, rent=1210, floor=1, pets=True, available="2026-10-01"),
        dict(unit="R-207", beds=1, baths=1, sqft=705, rent=1265, floor=2, pets=False, available="2026-10-10"),
        dict(unit="R-230", beds=2, baths=2, sqft=1010, rent=1575, floor=2, pets=True, available="2026-10-01"),
        dict(unit="R-305", beds=2, baths=2, sqft=1040, rent=1620, floor=3, pets=True, available="2026-11-01"),
        dict(unit="R-140", beds=3, baths=2, sqft=1280, rent=2050, floor=1, pets=True, available="2026-10-20"),
    ],
    "Larkspur Heights": [
        dict(unit="H-21", beds=1, baths=1, sqft=730, rent=1195, floor=2, pets=True, available="2026-10-01"),
        dict(unit="H-12", beds=2, baths=2, sqft=1120, rent=1540, floor=1, pets=True, available="2026-09-30"),
        dict(unit="H-33", beds=3, baths=2, sqft=1350, rent=1980, floor=1, pets=False, available="2026-10-12"),
    ],
}
PROP_NAMES = list(PROPERTIES)
SHORT = {"Larkspur Commons": "Commons", "Larkspur at Riverside": "Riverside", "Larkspur Heights": "Heights"}

FIRST = ["Maria", "Jordan", "Priya", "Devon", "Alex", "Sam", "Taylor", "Chris", "Aisha", "Marcus", "Lena", "Diego",
         "Hannah", "Kevin", "Noor", "Brianna", "Tomás", "Wei", "Grace", "Andre", "Olivia", "Raj", "Jess", "Luis",
         "Keisha", "Ethan", "Fatima", "Cole", "Mei", "Darnell"]
LAST = ["Garcia", "Nguyen", "Patel", "Johnson", "Kim", "Okafor", "Rivera", "Smith", "Haddad", "Brooks", "Chen",
        "Lopez", "Walker", "Singh", "Martinez", "Turner", "Ali", "Bennett"]

BED_WORDS = {0: "studio", 1: "1 bedroom", 2: "2 bedroom", 3: "3 bedroom"}
BED_SHORT = {0: "studio", 1: "1br", 2: "2br", 3: "3br"}


def wd(d: datetime) -> str:
    return d.strftime("%A")


def md(d: datetime) -> str:
    return d.strftime("%B ") + str(d.day)


def full(d: datetime) -> str:
    return f"{wd(d)}, {md(d)}"


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")


def hm(h: int) -> str:
    return f"{h - 12 if h > 12 else h}{'pm' if h >= 12 else 'am'}"


class Conv:
    """Neutral event list, rendered later into OpenAI or Anthropic message format."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.ev: list[tuple] = []
        self.n = 0

    def user(self, t: str):
        self.ev.append(("user", t))
        return self

    def bot(self, t: str):
        self.ev.append(("assistant", t))
        return self

    def tool(self, name: str, args: dict, result):
        self.n += 1
        cid = f"call_{self.rng.randrange(16**8):08x}"
        self.ev.append(("call", name, args, cid))
        self.ev.append(("result", cid, result if isinstance(result, str) else json.dumps(result)))
        return self

    def render(self, system: str, style: str) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": system}]
        if style == "openai":
            i = 0
            while i < len(self.ev):
                e = self.ev[i]
                if e[0] == "user":
                    msgs.append({"role": "user", "content": e[1]})
                elif e[0] == "assistant":
                    m = {"role": "assistant", "content": e[1]}
                    j = i + 1
                    calls = []
                    while j < len(self.ev) and self.ev[j][0] == "call":
                        calls.append(self.ev[j]); j += 1
                        if j < len(self.ev) and self.ev[j][0] == "result":
                            break
                    if calls:
                        m["tool_calls"] = [{"id": c[3], "type": "function", "function": {"name": c[1], "arguments": json.dumps(c[2])}} for c in calls]
                        i = j - 1
                    msgs.append(m)
                elif e[0] == "call":
                    msgs.append({"role": "assistant", "content": None, "tool_calls": [
                        {"id": e[3], "type": "function", "function": {"name": e[1], "arguments": json.dumps(e[2])}}]})
                elif e[0] == "result":
                    msgs.append({"role": "tool", "tool_call_id": e[1], "content": e[2]})
                i += 1
        else:  # anthropic content blocks
            for e in self.ev:
                if e[0] == "user":
                    msgs.append({"role": "user", "content": e[1]})
                elif e[0] == "assistant":
                    msgs.append({"role": "assistant", "content": [{"type": "text", "text": e[1]}]})
                elif e[0] == "call":
                    blk = {"type": "tool_use", "id": e[3], "name": e[1], "input": e[2]}
                    if msgs[-1]["role"] == "assistant" and isinstance(msgs[-1]["content"], list):
                        msgs[-1]["content"].append(blk)
                    else:
                        msgs.append({"role": "assistant", "content": [blk]})
                elif e[0] == "result":
                    msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": e[1], "content": e[2]}]})
        return msgs


# ------------------------------------------------------------------ helpers
def typo(rng: random.Random, s: str, p: float = 0.35) -> str:
    if rng.random() > p:
        return s
    swaps = [("you", "u"), ("are", "r"), ("available", "availble"), ("apartment", "apt"), ("bedroom", "bdrm"),
             ("tomorrow", "tmrw"), ("please", "pls"), ("thanks", "thx"), ("schedule", "schedual"), ("really", "rly"),
             ("I'm", "im"), ("don't", "dont"), ("what", "wat"), ("because", "bc")]
    for a, b in rng.sample(swaps, k=4):
        if a in s and rng.random() < 0.6:
            s = s.replace(a, b, 1)
    if rng.random() < 0.5:
        s = s.lower()
    return s


def units_for(prop: str, beds=None, max_rent=None, pets=None, floor=None):
    out = []
    for u in PROPERTIES[prop]:
        if beds is not None and u["beds"] != beds:
            continue
        if max_rent is not None and u["rent"] > max_rent:
            continue
        if pets and not u["pets"]:
            continue
        if floor is not None and u["floor"] != floor:
            continue
        out.append(u)
    return out


def unit_line(u: dict) -> str:
    b = "Studio" if u["beds"] == 0 else f"{u['beds']}BR/{u['baths']}BA"
    return f"Unit {u['unit']}: {b}, {u['sqft']} sq ft, ${u['rent']:,}/mo, available {u['available']}"


def name(rng):
    return rng.choice(FIRST), rng.choice(LAST)


def tour_time(rng, base: datetime, days_ahead: int):
    d = base + timedelta(days=days_ahead)
    h = rng.choice([10, 11, 13, 14, 15, 16, 17]) if d.weekday() != 6 else rng.choice([13, 14, 15])
    return d, h


# ------------------------------------------------------------------ scenarios
def sc_availability(rng, ch, fails, now):
    c = Conv(rng)
    prop = rng.choice(PROP_NAMES)
    beds = rng.choice([1, 1, 2, 2, 2, 0, 3])
    first, last = name(rng)
    constraint = rng.choice(["budget", "pets", "floor"])
    pool = units_for(prop, beds=beds)
    while not pool:
        beds = rng.choice([1, 2])
        pool = units_for(prop, beds=beds)
    cheapest = min(u["rent"] for u in pool)
    nomatch = "robotic_dead_end" in fails
    if constraint == "budget":
        cap = cheapest - rng.choice([60, 110, 150]) if nomatch else max(u["rent"] for u in pool) - rng.choice([25, 40])
        if not nomatch and cap < cheapest:
            cap = cheapest + 50
        cdesc_sms = f"under {cap}"
        cdesc = f"my budget is ${cap:,} max"
        filt = dict(max_rent=cap)
    elif constraint == "pets":
        cdesc_sms = "must allow dogs"
        cdesc = "I have a 40 lb dog so it has to be pet friendly"
        filt = dict(pets=True)
        if not [u for u in pool if u["pets"]] or (not nomatch and all(u["pets"] for u in pool) and "ignores_constraint" in fails):
            constraint = "budget"
            cap = max(u["rent"] for u in pool) - 30 if len(pool) > 1 else pool[0]["rent"] + 40
            cdesc_sms, cdesc, filt = f"under {cap}", f"my budget is ${cap:,} max", dict(max_rent=cap)
    else:
        cdesc_sms = "ground floor only (bad knee)"
        cdesc = "I need a ground floor unit, I can't do stairs"
        filt = dict(floor=1)
    if "ignores_constraint" in fails:
        # Make sure there is at least one violating unit to (wrongly) present.
        viol = [u for u in pool if not units_for(prop, beds=beds, **filt) or u not in units_for(prop, beds=beds, **filt)]
        if not viol:
            # Force budget constraint below the most expensive unit.
            top = max(pool, key=lambda u: u["rent"])
            cap = top["rent"] - 75
            cdesc_sms, cdesc, filt, constraint = f"under {cap}", f"my budget is ${cap:,} max", dict(max_rent=cap), "budget"
            viol = [top]

    if ch == "sms":
        c.user(typo(rng, rng.choice([
            f"hi do u have any {BED_SHORT[beds]} at {SHORT[prop]}? {cdesc_sms}",
            f"{BED_SHORT[beds]} available at {SHORT[prop]}?? {cdesc_sms}",
            f"Looking for a {BED_WORDS[beds]} at {prop}, {cdesc_sms}. what do you have",
        ]), 0.6))
    elif ch == "email":
        c.user(f"Hello,\n\nI'm relocating to Austin for work and I'm interested in a {BED_WORDS[beds]} apartment at {prop}. "
               f"{cdesc[0].upper() + cdesc[1:]}. I'd like to move in sometime in the next month or so. Could you tell me what's available and what the total monthly cost would look like?\n\nThanks,\n{first} {last}")
    elif ch == "voice":
        c.user(f"Hi, yeah, um, I'm calling about apartments at {SHORT[prop]}. I'm looking for a {BED_WORDS[beds]}, and, uh, {cdesc}.")
    else:
        c.user(typo(rng, rng.choice([
            f"Hi! Do you have any {BED_WORDS[beds]} units at {prop}? {cdesc}.",
            f"what {BED_WORDS[beds]}s do you have open at {SHORT[prop]}? {cdesc}",
            f"Hey there, looking at {prop}. {BED_WORDS[beds]}, {cdesc}. Anything?",
        ]), 0.3))

    args = {"property": prop, "bedrooms": beds}
    if "ignores_constraint" in fails:
        result = units_for(prop, beds=beds)  # constraint dropped from the search
    else:
        args.update({k if k != "pets" else "pets_allowed": v for k, v in filt.items()})
        result = units_for(prop, beds=beds, **filt)
    c.tool("check_availability", args, {"units": result, "count": len(result)})

    good = units_for(prop, beds=beds, **filt)
    md_sms = "markdown_sms" in fails
    if "ignores_constraint" in fails:
        shown = sorted(result, key=lambda u: -u["rent"])[:2]
        if not any(u not in good for u in shown):
            shown = [u for u in result if u not in good][:1] + shown[:1]
        lines = [unit_line(u) for u in shown]
        if md_sms:
            text = f"**Great news!** Here's what's open at {SHORT[prop]}:\n\n" + "\n".join(f"- **{l.split(':')[0]}**:{l.split(':', 1)[1]}" for l in lines) + "\n\nWant to [book a tour](https://larkspurliving.com/tour)?"
        elif ch == "voice":
            text = f"Sure! So at {SHORT[prop]} I have " + " and ".join(f"unit {u['unit']} at {u['rent']:,} a month" for u in shown) + ". Both are really nice. Would you like to come see them?"
        else:
            text = f"Great news, we have options at {prop}!\n" + "\n".join(lines) + "\nWould you like to schedule a tour?"
        c.bot(text)
        if rng.random() < 0.5 and ch != "email":
            if constraint == "budget":
                c.user(typo(rng, "wait isnt that over my budget??", 0.7))
                c.bot(f"I understand! {shown[0]['unit']} is a great value for the space. We also have a move-in special this month. Want to see it in person?")
            elif constraint == "pets":
                c.user("is that one pet friendly though?")
                c.bot(f"Great question! Most of our units welcome pets. Would you like to schedule a tour of {shown[0]['unit']}?")
            else:
                c.user("what floor is that on")
                c.bot(f"Unit {shown[0]['unit']} is on floor {shown[0]['floor']} with elevator access to most buildings. Want to come take a look?")
    elif nomatch or not good:
        alt_prop = "Larkspur at Riverside" if prop != "Larkspur at Riverside" else "Larkspur Heights"
        alts = units_for(alt_prop, beds=beds, **filt) or units_for(alt_prop, beds=beds)
        if "robotic_dead_end" in fails:
            if md_sms:
                text = "**Sorry!** There are currently no units matching your criteria:\n- Bedrooms: " + BED_WORDS[beds] + f"\n- Property: {prop}\n\nIs there anything else I can help with?"
            else:
                text = rng.choice([
                    "Unfortunately there are no units available that match your criteria at this time. Is there anything else I can help you with?",
                    "I'm sorry, we don't have any units that meet your requirements right now. Please check back later.",
                    f"There are currently 0 results for your search at {prop}. Is there anything else I can assist you with today?",
                ])
            c.bot(text)
            if rng.random() < 0.5:
                c.user(typo(rng, rng.choice(["ok", "oh ok thanks", "nvm then", "ok bye"]), 0.5))
                c.bot("You're welcome! Have a great day.")
        else:
            c.tool("check_availability", {"property": alt_prop, "bedrooms": beds}, {"units": alts, "count": len(alts)})
            alt = alts[0] if alts else None
            text = (f"Nothing at {SHORT[prop]} fits that right now, but our sister community {alt_prop} has {unit_line(alt).lower()} — about 10 minutes away. "
                    if alt else f"Nothing at {SHORT[prop]} fits that right now. ")
            text += "I can also put you on our notify list so you hear first when a match opens at " + SHORT[prop] + ". Want either of those?"
            if md_sms:
                text = (f"**No exact match at {SHORT[prop]}**, but here are options:\n\n"
                        + (f"- **{alt_prop}**: {unit_line(alt)}\n" if alt else "") + "- Join our **notify list** for new openings\n\nWhich works for you?")
            c.bot(text)
            c.user(typo(rng, "sure add me to the list", 0.5))
            c.tool("add_to_waitlist", {"property": prop, "bedrooms": beds, **{k: v for k, v in filt.items()}}, {"status": "added", "position": rng.randint(2, 9)})
            c.bot(f"Done, you're on the list for {SHORT[prop]}. I'll text you as soon as something opens up.")
    else:
        shown = good[:2]
        if md_sms:
            text = f"Here's what we have at **{prop}**:\n\n" + "\n".join(f"* {unit_line(u)}" for u in shown) + "\n\n**Next step:** reply TOUR to book a visit!"
        elif ch == "sms":
            text = f"We have {len(good)} that fit: " + "; ".join(f"{u['unit']} ${u['rent']:,}/mo, avail {u['available'][5:]}" for u in shown) + ". Want to tour? I can book you this week."
        elif ch == "voice":
            text = f"Okay, I found {len(good)} at {SHORT[prop]}. " + " ".join(f"Unit {u['unit']} is {u['rent']:,} a month and available {u['available']}." for u in shown) + " Would you like to come see one?"
        elif ch == "email":
            text = (f"Hi {first},\n\nThanks for reaching out about {prop}! Here's what fits your search:\n\n" + "\n".join(unit_line(u) for u in shown)
                    + "\n\nOn top of rent there's a $45 monthly utility/trash package and a $250 refundable deposit (plus $300 pet deposit and $25/mo pet rent if you're bringing a pet).\n\nWould you like to come by for a tour? Just reply with a couple of times that work.\n\nBest,\nLark — Larkspur Residences")
        else:
            text = f"Yes! At {prop} these match:\n" + "\n".join(unit_line(u) for u in shown) + "\nWant me to book a tour?"
        c.bot(text)
        if "wrong_date" in fails:
            wrong = now + timedelta(days=rng.choice([-6, -5, 3, 4]))
            c.user(typo(rng, "how soon could i move in? like next week?", 0.5))
            c.bot(f"Absolutely! Since today is {full(wrong)}, the earliest move-in for {shown[0]['unit']} would be {shown[0]['available']}. Want to lock it in with an application?")
        if "promise_no_followup" in fails:
            q = rng.choice(["is there covered parking? and how much", "do these have in unit washer/dryer?", "whats the parking situation"])
            c.user(q)
            c.bot(rng.choice([
                "Good question! Let me check on that and get back to you shortly.",
                "I'll confirm that with the team and follow up with you!",
                "Let me look into that for you and I'll get back to you soon.",
            ]))
        elif rng.random() < 0.35 and ch in ("chat", "sms"):
            c.user(typo(rng, "is there parking", 0.6))
            c.bot(f"Yes — every {SHORT[prop]} lease includes one uncovered spot. Covered spots are $40/mo and garages are $125/mo, subject to availability.")
    return c, prop


def _tour_intro(rng, ch, prop, first, when_word):
    if ch == "sms":
        return typo(rng, rng.choice([
            f"can i tour {SHORT[prop]} {when_word}",
            f"hi id like to come see a unit at {SHORT[prop]} {when_word}. whats open?",
            f"tour {when_word}?",
        ]), 0.6)
    if ch == "email":
        return f"Hi there,\n\nI'd like to schedule a tour at {prop} {when_word}. Afternoon works best for me.\n\nThank you,\n{first}"
    if ch == "voice":
        return f"Hey, yeah, hi. I wanted to set up a time to come see {SHORT[prop]}, um, {when_word} if possible?"
    return typo(rng, f"Hi, I'd like to book a tour at {prop} {when_word}. Do you have any time slots?", 0.3)


def sc_tour(rng, ch, fails, now):
    c = Conv(rng)
    prop = rng.choice(PROP_NAMES)
    first, last = name(rng)
    phone = f"512-555-{rng.randint(1000, 9999)}"
    wants_virtual = "virtual_vs_inperson" in fails and rng.random() < 0.6 or (not fails and rng.random() < 0.15)
    days = rng.choice([1, 1, 2, 3])
    when_word = "tomorrow" if days == 1 else rng.choice(["this week", "in a couple days", "later this week"])
    d, h = tour_time(rng, now, days)
    if "wrong_date" in fails:
        d = now + timedelta(days=rng.choice([-5, -3, 4, 6]))
        when_word = "tomorrow"
    intro = _tour_intro(rng, ch, prop, first, when_word)
    if wants_virtual:
        intro += " Do you do virtual tours? I'm still out of state." if ch != "sms" else " do u do virtual tours? im out of state"
    c.user(intro)
    c.bot(f"I'd love to set that up! What's your full name and the best phone number to reach you?" if ch != "voice"
          else "Sure thing! Can I get your full name and a good callback number?")
    c.user(f"{first} {last}, {phone}" if ch != "voice" else f"Yeah it's {first} {last}, and my number is {phone.replace('-', ' ')}.")
    slot = f"{iso(d)}T{h:02d}:00"
    tour_type = "in_person"
    args = {"property": prop, "datetime": slot, "tour_type": tour_type, "prospect_name": f"{first} {last}", "phone": phone}
    booking = f"TR-{rng.randint(10000, 99999)}"
    c.tool("schedule_tour", args, {"status": "confirmed", "booking_id": booking, "property": prop, "datetime": slot, "tour_type": tour_type})
    when = f"{full(d)} at {hm(h)}" if "wrong_date" not in fails else f"tomorrow, {full(d)} at {hm(h)}"
    md_sms = "markdown_sms" in fails
    if "virtual_vs_inperson" in fails:
        text = rng.choice([
            f"You're all set! Your virtual tour of {prop} is booked for {when}. You'll receive a video link by text 15 minutes before. Confirmation: {booking}.",
            f"Done! I've scheduled your virtual tour for {when} (confirmation {booking}). Our agent will walk you through the unit over video so you don't need to travel.",
            f"Perfect, {first}! Virtual tour confirmed for {when}. Just click the link we send and you can see everything from home. Booking #{booking}",
        ])
        if md_sms:
            text = f"**Booked!** Virtual tour on **{when}**\n- Confirmation: {booking}\n- Link sent 15 min before"
    elif wants_virtual:
        text = (f"We don't offer virtual tours, but I booked an in-person tour for {when} (confirmation {booking}). "
                "If you can't make it in person, our self-guided tour app lets a friend or family member tour for you any day 9-6.")
    elif md_sms:
        text = f"**You're booked!** 🎉\n\n* **When:** {when}\n* **Where:** {prop} leasing office\n* **Confirmation #:** {booking}\n\nBring a photo ID. Reply **C** to cancel."
    elif ch == "sms":
        text = f"Booked! In-person tour {when} at the {SHORT[prop]} leasing office. Confirmation {booking}. Bring a photo ID. Text back if you need to change it."
    elif ch == "voice":
        text = f"Alright, you're booked for an in-person tour on {when}. Your confirmation number is {booking}. Just check in at the leasing office when you arrive."
    else:
        text = f"You're confirmed for an in-person tour at {prop} on {when}. Confirmation number: {booking}. Please bring a photo ID and check in at the leasing office."
    c.bot(text)
    if rng.random() < 0.4:
        follow = rng.choice(["thx!", "great thanks", "perfect see u then", "Do I need to bring anything?"])
        c.user(follow)
        c.bot("Just a photo ID. See you then!" if "?" in follow else "You're welcome! See you soon.")
    return c, prop


def sc_reschedule(rng, ch, fails, now):
    c = Conv(rng)
    prop = rng.choice(PROP_NAMES)
    first, last = name(rng)
    phone = f"512-555-{rng.randint(1000, 9999)}"
    old_d, old_h = tour_time(rng, now, rng.choice([1, 2]))
    new_d, new_h = tour_time(rng, now, rng.choice([3, 4, 5]))
    old_id = f"TR-{rng.randint(10000, 99999)}"
    if ch == "sms":
        c.user(typo(rng, f"hey this is {first}, i have a tour {wd(old_d).lower()} at {hm(old_h)} but something came up. can i move it to {wd(new_d).lower()} {hm(new_h)}?", 0.6))
    elif ch == "voice":
        c.user(f"Hi, this is {first} {last}. I've got a tour booked for {wd(old_d)} but I need to push it to {wd(new_d)}, around {hm(new_h)}?")
    else:
        c.user(f"Hi, I need to reschedule my tour at {SHORT[prop]} from {wd(old_d)} to {wd(new_d)} at {hm(new_h)} if that's open. Name is {first} {last}.")
    c.tool("lookup_tours", {"phone": phone, "name": f"{first} {last}"},
           {"bookings": [{"booking_id": old_id, "property": prop, "datetime": f"{iso(old_d)}T{old_h:02d}:00", "tour_type": "in_person", "status": "confirmed"}]})
    slot = f"{iso(new_d)}T{new_h:02d}:00"
    if "duplicate_booking" in fails:
        new_id = f"TR-{rng.randint(10000, 99999)}"
        c.tool("schedule_tour", {"property": prop, "datetime": slot, "tour_type": "in_person", "prospect_name": f"{first} {last}", "phone": phone},
               {"status": "confirmed", "booking_id": new_id, "property": prop, "datetime": slot, "tour_type": "in_person"})
        c.bot(rng.choice([
            f"No problem, {first}! You're now booked for {full(new_d)} at {hm(new_h)}. Confirmation: {new_id}.",
            f"Done! Your tour is set for {wd(new_d)} at {hm(new_h)} (confirmation {new_id}). See you then!",
        ]))
        if rng.random() < 0.5:
            c.user(typo(rng, f"great so the {wd(old_d).lower()} one is cancelled right?", 0.5))
            c.bot(f"Yes, you're all set for {wd(new_d)}!")
    else:
        if "wrong_date" in fails:
            new_d = now + timedelta(days=rng.choice([-4, -2]))
            slot = f"{iso(new_d)}T{new_h:02d}:00"
        c.tool("reschedule_tour", {"booking_id": old_id, "new_datetime": slot},
               {"status": "rescheduled", "booking_id": old_id, "datetime": slot})
        c.bot(f"Done — I moved booking {old_id} from {wd(old_d)} to {full(new_d)} at {hm(new_h)}. Your old time is released, so there's nothing else you need to do.")
    return c, prop


HUMAN_ASKS = {
    "sms": ["can i talk to a real person", "AGENT", "pls just connect me w someone in the office", "i want to speak to a human"],
    "chat": ["Can I speak with an actual person please?", "I'd rather talk to someone from the leasing office.", "transfer me to a human"],
    "voice": ["Can I just talk to a representative?", "Representative. Representative.", "Is there a real person I can speak to?"],
    "email": ["I would like to speak with the property manager directly, not an automated assistant. Please have someone call me."],
}


def sc_human_request(rng, ch, fails, now):
    c = Conv(rng)
    prop = rng.choice(PROP_NAMES)
    first, last = name(rng)
    topic = rng.choice(["billing", "lease_break", "noise", "deposit", "transfer"])
    openers = {
        "billing": f"I was charged a ${rng.choice([75, 100, 150])} late fee but I paid on the 1st through the portal.",
        "lease_break": "I got a job offer in Denver and need to know what it costs to break my lease early.",
        "noise": "My upstairs neighbor has been stomping around at 2am every night for two weeks.",
        "deposit": "I moved out 5 weeks ago and still haven't gotten my deposit back.",
        "transfer": f"I want to transfer from my unit to a bigger one at {SHORT[prop]} but keep my move-in specials.",
    }
    o = openers[topic]
    c.user(typo(rng, o, 0.5 if ch == "sms" else 0.1) if ch != "email" else f"Hello,\n\n{o} This is the second time I've reached out about this.\n\n{first} {last}, {SHORT[prop]} resident")
    c.tool("lookup_resident", {"name": f"{first} {last}", "property": prop},
           {"resident_id": f"RS-{rng.randint(1000, 9999)}", "unit": rng.choice(PROPERTIES[prop])["unit"], "lease_end": "2027-03-31", "balance_due": rng.choice([0, 0, 75, 100])})
    if ch != "email":
        c.bot(rng.choice([
            "I'm sorry to hear that! I can help look into it. Could you tell me a bit more?",
            "Thanks for letting me know. I found your account. Can you share a few more details so I can help?",
        ]))
        ask = rng.choice(HUMAN_ASKS[ch])
        c.user(ask)
    else:
        ask = HUMAN_ASKS["email"][0]
        c.ev[0] = ("user", c.ev[0][1].replace(f"\n\n{first}", f" {ask}\n\n{first}"))
    if "no_handoff" in fails:
        replies = {
            "billing": "I completely understand your frustration! Late fees are applied when payment posts after the 5th. Payments made through the portal can take 1-3 business days to process. Is there anything else I can help you with?",
            "lease_break": "I can help with that! Breaking a lease early usually involves a fee equal to two months' rent, but it depends on your lease terms. Is there anything else I can help you with today?",
            "noise": "I'm sorry you're dealing with that! I'd recommend talking to your neighbor first. Quiet hours are 10pm-8am. Is there anything else I can help with?",
            "deposit": "I understand! Deposits are typically returned within 30 days of move-out. It may still be processing. Anything else I can do for you?",
            "transfer": "Great question! Transfers are subject to availability. I can check what larger units are open right now. Would you like me to search?",
        }
        if "promise_no_followup" in fails:
            c.bot("I hear you! Let me look into this on my end and I'll get back to you as soon as I can.")
        else:
            c.bot(replies[topic])
        if rng.random() < 0.6 and ch != "email":
            c.user(typo(rng, rng.choice(["i said i want a PERSON", "thats not what i asked", "can u not transfer me??", "ugh. ok."]), 0.5))
            c.bot(rng.choice([
                "I'm here to help! What else can I do for you?",
                "I understand. I'm able to answer most questions about your account. What would you like to know?",
                "Sorry for any confusion! Is there anything else I can help you with?",
            ]))
    else:
        c.tool("handoff_to_human", {"reason": topic, "summary": o[:120], "priority": "normal" if topic != "noise" else "high", "channel": ch},
               {"status": "queued", "ticket": f"HO-{rng.randint(1000, 9999)}", "expected_response": "within 1 business hour"})
        msg = {
            "sms": "Got it — I've passed this to our leasing team with the details. Someone will text you back within an hour during office hours.",
            "chat": "Of course. I've sent your conversation to our leasing team so you won't have to repeat yourself. A team member will reach out within the hour during office hours.",
            "voice": "Absolutely, I'm transferring you to a member of our leasing team now. I've shared what you told me so you won't need to start over.",
            "email": f"Hi {first},\n\nI'm sorry this is taking so long. I've forwarded your message to our property manager with your account details, and they'll call you within one business hour during office hours.\n\nLark — Larkspur Residences",
        }[ch]
        c.bot(msg)
    return c, prop


def sc_maintenance(rng, ch, fails, now):
    c = Conv(rng)
    prop = rng.choice(PROP_NAMES)
    first, last = name(rng)
    issue = rng.choice([
        ("my ac is blowing warm air and its 90 in here", "hvac", "high"),
        ("kitchen sink is leaking under the cabinet", "plumbing", "normal"),
        ("garbage disposal stopped working", "appliance", "low"),
        ("the dishwasher wont drain", "appliance", "normal"),
        ("bathroom fan makes a loud grinding noise", "electrical", "low"),
    ])
    unit = rng.choice(PROPERTIES[prop])["unit"]
    c.user(typo(rng, f"hi its {first} in {unit}, {issue[0]}", 0.6))
    rid = f"RS-{rng.randint(1000, 9999)}"
    c.tool("lookup_resident", {"name": first, "unit": unit, "property": prop},
           {"resident_id": rid, "name": f"{first} {last}", "unit": unit, "property": prop})
    if "promise_no_followup" in fails:
        if "markdown_sms" in fails:
            c.bot("**Sorry about that!** 😕\n\n- I'll check with our **maintenance team**\n- I'll get back to you on timing")
        else:
            c.bot("I'm sorry about that! Let me check with our maintenance team on their availability and get back to you.")
        if rng.random() < 0.5:
            c.user(typo(rng, "ok how long will that take", 0.5))
            c.bot("I'll follow up as soon as I hear back from them!")
        return c, prop
    tk = f"MR-{rng.randint(10000, 99999)}"
    c.tool("create_maintenance_request", {"resident_id": rid, "unit": unit, "category": issue[1], "priority": issue[2], "description": issue[0], "permission_to_enter": True},
           {"status": "created", "ticket": tk, "eta": "within 24 hours" if issue[2] != "high" else "same day"})
    if "markdown_sms" in fails:
        c.bot(f"**Maintenance request submitted!** ✅\n\n- **Ticket:** {tk}\n- **Category:** {issue[1].upper()}\n- **ETA:** {'same day' if issue[2] == 'high' else 'within 24 hours'}\n\n_We'll text you when a tech is on the way._")
    else:
        c.bot(f"Thanks {first} — I've filed ticket {tk} for {unit}. " + ("Since it's an AC issue in this heat, it's marked urgent and a tech should be out today." if issue[1] == "hvac" else "A technician should be out within 24 hours, and we have permission to enter if you're not home."))
    return c, prop


POLICY_QS = [
    ("pets", "whats ur pet policy? i have 2 cats", "We welcome up to 2 pets per home. It's a $300 pet deposit per pet and $25/mo pet rent per pet. Cats are always welcome, so your two are good to go!"),
    ("parking", "how does parking work", "Each lease includes one uncovered spot. Covered spots are $40/mo and detached garages $125/mo, subject to availability."),
    ("fees", "what fees are there besides rent", "Besides rent: a $50 application fee, $250 admin fee at signing, a $250 refundable deposit (can be higher based on screening), and a $45/mo utility and trash package."),
    ("amenities", "do you have a gym and pool", "Yes to both! There's a 24-hour fitness center and a resort-style pool open 8am-10pm, plus a dog park and package lockers."),
    ("income", "what are the income requirements", "We look for gross household income of 3x the monthly rent. Guarantors or an extra month's deposit can work if you're a bit under."),
]


def sc_policy(rng, ch, fails, now):
    c = Conv(rng)
    prop = rng.choice(PROP_NAMES)
    key, q, a = rng.choice(POLICY_QS)
    if ch == "email":
        c.user(f"Hi,\n\nQuick question about {prop}: {q[0].upper() + q[1:]}?\n\nThanks!")
    else:
        c.user(typo(rng, q + ("?" if not q.endswith("?") else ""), 0.6 if ch == "sms" else 0.2))
    if "promise_no_followup" in fails:
        c.bot("That's a great question! I want to make sure I give you accurate information, so let me double-check with the office and get back to you.")
        return c, prop
    if "markdown_sms" in fails:
        parts = a.split(". ")
        c.bot(f"## {key.title()} at {SHORT[prop]}\n\n" + "\n".join(f"- {p.strip('.')}" for p in parts) + "\n\n**Questions?** Just reply here!")
    else:
        c.bot(a + (" Want me to set up a tour so you can see it?" if rng.random() < 0.5 else ""))
    if rng.random() < 0.3:
        c.user(typo(rng, "ok thanks", 0.5))
        c.bot("Anytime! Text me if anything else comes up." if ch == "sms" else "You're welcome!")
    return c, prop


def sc_not_ready(rng, ch, fails, now):
    c = Conv(rng)
    prop = rng.choice(PROP_NAMES)
    first, _ = name(rng)
    opener = rng.choice([
        f"just browsing, my lease isnt up til {rng.choice(['march', 'april', 'february'])}",
        "honestly everything i've seen is too expensive. anything under 1000?",
        f"im not ready to apply yet, just comparing a few places. whats special about {SHORT[prop]}",
        "do you have anything for under $1,000 a month?",
    ])
    c.user(typo(rng, opener, 0.5) if ch != "email" else f"Hello,\n\n{opener[0].upper() + opener[1:]}. Just gathering information for now.\n\n{first}")
    if "1000" in opener or "1,000" in opener:
        c.tool("check_availability", {"property": prop, "max_rent": 1000}, {"units": [], "count": 0})
    if "robotic_dead_end" in fails:
        c.bot(rng.choice([
            "Thank you for your interest in Larkspur Residences. Unfortunately we do not have any units that match your request. Is there anything else I can help you with?",
            "Okay. Please let us know if you have any other questions.",
            "We currently have no availability in that price range. Have a nice day!",
            "Understood. Feel free to reach out when you are ready to apply.",
        ]))
    else:
        if "1000" in opener or "1,000" in opener:
            text = (f"Our lowest right now is a studio at Riverside for $1,050, and it comes with a free month on a 13-month lease, which works out to about $970/mo. "
                    "Want me to hold a tour slot, or text you if anything under $1,000 opens up?")
        else:
            text = (f"Totally fair — no pressure! A lot of people start looking 2-3 months out. {SHORT[prop]} is known for the shaded dog park and the free covered bike storage. "
                    "Want me to text you when units that fit your timing open up, or send a few floor plans to look over?")
        c.bot(text)
        c.user(typo(rng, rng.choice(["sure send me updates", "yeah text me", "maybe later, thx"]), 0.5))
        if "later" in c.ev[-1][1]:
            c.bot("Sounds good! I'll check back in a few weeks. Good luck with the search.")
        else:
            c.tool("add_to_waitlist", {"property": prop, "contact_pref": ch}, {"status": "added"})
            c.bot("Done! You'll get a heads up when something matches. Reply STOP anytime to opt out.")
    return c, prop


def sc_application(rng, ch, fails, now):
    c = Conv(rng)
    prop = rng.choice(PROP_NAMES)
    first, last = name(rng)
    c.user(typo(rng, f"hi its {first} {last}, i applied last week for {rng.choice(PROPERTIES[prop])['unit']}. any update??", 0.6))
    status = rng.choice(["pending_income_verification", "approved", "pending_guarantor"])
    c.tool("lookup_application", {"name": f"{first} {last}", "property": prop},
           {"application_id": f"AP-{rng.randint(1000, 9999)}", "status": status, "missing": ["paystub"] if "pending" in status else []})
    if "promise_no_followup" in fails:
        c.bot("Thanks for checking in! Let me check with our leasing team on the status and I'll get back to you.")
    elif "markdown_sms" in fails:
        c.bot(f"**Application status:** `{status}`\n\n" + ("- Missing: most recent paystub\n- Upload at [the portal](https://larkspurliving.com/apply)" if "pending" in status else "- 🎉 You're approved!\n- Next: sign your lease in the portal"))
    else:
        c.bot("Good news, you're approved! You'll get an email with the lease to sign within 24 hours." if status == "approved"
              else "You're almost there! We're just missing your most recent paystub. You can upload it in the resident portal under Documents, and we'll review it within 1 business day.")
    return c, prop


def sc_tool_error(rng, ch, fails, now):
    c = Conv(rng)
    prop = rng.choice(PROP_NAMES)
    c.user("Do you have any 2 bedrooms open next month?")
    c.tool("check_availability", {"property": prop, "bedrooms": 2}, {"error": "upstream timeout (yardi)", "code": 504})
    c.bot("Sorry, our availability system isn't responding right now. I've flagged it for the team. Could I grab your number so someone can text you current 2-bedroom options today?")
    c.user("512-555-0199")
    c.tool("handoff_to_human", {"reason": "availability_lookup_failed", "summary": "Prospect wants 2BR next month; availability API timed out.", "priority": "normal", "channel": ch},
           {"status": "queued", "ticket": f"HO-{rng.randint(1000, 9999)}"})
    c.bot("Thanks! A leasing agent will text you within the hour with what's open.")
    return c, prop


def sc_wrong_number(rng, ch, fails, now):
    c = Conv(rng)
    c.user(rng.choice(["who is this", "wrong number", "STOP"]))
    c.bot("This is Lark, the leasing assistant for Larkspur Residences apartments. Sorry for any confusion! Reply STOP and you won't hear from us again.")
    return c, rng.choice(PROP_NAMES)


SCEN = {
    "availability": sc_availability, "tour": sc_tour, "reschedule": sc_reschedule, "human_request": sc_human_request,
    "maintenance": sc_maintenance, "policy": sc_policy, "not_ready": sc_not_ready, "application": sc_application,
    "tool_error": sc_tool_error, "wrong_number": sc_wrong_number,
}

MD, IC, VI, DB, WD, PR, NH, RB = ("markdown_sms", "ignores_constraint", "virtual_vs_inperson", "duplicate_booking",
                                  "wrong_date", "promise_no_followup", "no_handoff", "robotic_dead_end")


def specs() -> list[tuple[str, str, list[str]]]:
    s: list[tuple[str, str, list[str]]] = []

    def add(n, sc, ch, f):
        s.extend([(sc, ch, list(f))] * n)

    # Doubles
    add(2, "availability", "sms", [MD, IC])
    add(1, "availability", "sms", [MD, RB])
    add(1, "tour", "sms", [MD, WD])
    add(1, "maintenance", "sms", [MD, PR])
    add(1, "tour", "chat", [VI, WD])
    add(1, "human_request", "chat", [NH, PR])
    add(1, "availability", "email", [IC, PR])
    # Singles
    add(2, "availability", "sms", [MD]); add(2, "tour", "sms", [MD]); add(2, "policy", "sms", [MD]); add(1, "application", "sms", [MD])
    add(3, "availability", "chat", [IC]); add(1, "availability", "email", [IC]); add(1, "availability", "sms", [IC]); add(1, "availability", "voice", [IC])
    add(2, "tour", "voice", [VI]); add(1, "tour", "email", [VI]); add(1, "tour", "sms", [VI])
    add(1, "reschedule", "sms", [DB]); add(2, "reschedule", "chat", [DB]); add(1, "reschedule", "voice", [DB])
    add(1, "tour", "chat", [WD]); add(1, "tour", "email", [WD]); add(1, "tour", "voice", [WD]); add(1, "availability", "chat", [WD])
    add(2, "maintenance", "chat", [PR]); add(1, "application", "sms", [PR]); add(1, "policy", "email", [PR])
    add(3, "human_request", "sms", [NH]); add(2, "human_request", "chat", [NH]); add(1, "human_request", "voice", [NH]); add(1, "human_request", "email", [NH])
    add(2, "not_ready", "chat", [RB]); add(2, "not_ready", "sms", [RB]); add(1, "not_ready", "email", [RB]); add(1, "availability", "voice", [RB])
    # Clean
    add(6, "availability", "sms", []); add(7, "availability", "chat", []); add(4, "availability", "email", []); add(3, "availability", "voice", [])
    add(4, "tour", "sms", []); add(5, "tour", "chat", []); add(2, "tour", "email", []); add(3, "tour", "voice", [])
    add(2, "reschedule", "sms", []); add(2, "reschedule", "chat", []); add(1, "reschedule", "voice", [])
    add(3, "human_request", "sms", []); add(3, "human_request", "chat", []); add(2, "human_request", "voice", []); add(1, "human_request", "email", [])
    add(3, "maintenance", "sms", []); add(2, "maintenance", "chat", [])
    add(2, "policy", "sms", []); add(3, "policy", "chat", []); add(2, "policy", "email", [])
    add(2, "not_ready", "chat", []); add(2, "not_ready", "sms", []); add(1, "not_ready", "email", [])
    add(2, "application", "sms", []); add(1, "application", "chat", [])
    add(1, "tool_error", "chat", []); add(1, "wrong_number", "sms", [])
    return s


def main() -> None:
    rng = random.Random(20260914)
    plan = specs()
    rng.shuffle(plan)
    start = datetime(2026, 9, 1, 8, 0)
    records, truth = [], {}
    for i, (sc, ch, fails) in enumerate(plan):
        now = start + timedelta(days=int(i * 29 / len(plan)), hours=rng.randint(0, 12), minutes=rng.randint(0, 59))
        conv, prop = SCEN[sc](rng, ch, set(fails), now)
        pv = "v1.3" if (MD in fails or rng.random() < 0.72) else "v1.4"
        style = "anthropic" if rng.random() < 0.22 else "openai"
        tid = f"lk-{now.strftime('%m%d')}-{rng.randrange(16**4):04x}"
        fb = None
        r = rng.random()
        if fails:
            fb = "thumbs_down" if r < 0.4 else ("thumbs_up" if r < 0.48 else None)
        else:
            fb = "thumbs_up" if r < 0.22 else ("thumbs_down" if r < 0.27 else None)
        rec = {
            "id": tid,
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S-05:00"),
            "channel": {"sms": "SMS", "chat": "chat_widget", "email": "email", "voice": "voice"}[ch],
            "property": prop,
            "prompt_version": pv,
            "latency_ms": rng.randint(900, 4200) + 600 * conv.n,
            "messages": conv.render(SYSTEM_V14 if pv == "v1.4" else SYSTEM_V13, style),
        }
        if fb:
            rec["user_feedback"] = fb
        if rng.random() < 0.15:
            rec.pop("latency_ms")  # missing fields happen
        records.append(rec)
        truth[tid] = {"failures": sorted(fails), "scenario": sc, "channel": ch}

    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    # Mess: one malformed line, one record with no conversation, one exact duplicate.
    lines.insert(37, '{"id": "lk-0911-broken", "timestamp": "2026-09-11T10:02:00-05:00", "messages": [{"role": "user", "content": "hi is the pool op')
    lines.insert(64, json.dumps({"id": "lk-0917-empty", "timestamp": "2026-09-17T13:40:00-05:00", "channel": "SMS", "messages": []}))
    lines.insert(90, lines[12])
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    TRUTH.parent.mkdir(parents=True, exist_ok=True)
    TRUTH.write_text(json.dumps(truth, indent=1), encoding="utf-8")
    n_fail = sum(1 for t in truth.values() if t["failures"])
    print(f"wrote {len(records)} traces ({len(records) - n_fail} clean, {n_fail} with planted failures) + 3 messy lines -> {OUT.name}")


if __name__ == "__main__":
    main()
