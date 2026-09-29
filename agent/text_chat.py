import json, uuid, httpx
from datetime import date

API = "http://localhost:8000"
LLM = "http://localhost:11434/v1/chat/completions"
MODEL = "qwen2.5:3b-instruct"
call_id = uuid.uuid4().hex[:8]

today = date.today()
system = open("agent/prompt.md").read().replace(
    "{today}", f"{today.strftime('%A, %d %B %Y')} ({today.isoformat()})")

serviceable_pins = {}

def log(step):
    httpx.post(f"{API}/event", json={"call_id": call_id, "step": step})

def check_serviceability(pincode):
    if len(str(pincode)) != 6 or not str(pincode).isdigit():
        return {"error": "Pincode must be exactly 6 digits. Ask the caller to repeat it."}
    r = httpx.get(f"{API}/serviceability/{pincode}").json()
    serviceable_pins[pincode] = bool(r.get("serviceable"))
    log("pincode_captured")
    if r.get("serviceable"):
        log("serviceable")
        r["next_step"] = "Serviceable. Do NOT use the waitlist. Ask for house/flat number and landmark, then the preferred date."
    else:
        r["next_step"] = "Not serviceable. Apologise and offer the waitlist."
    return r

def get_slots(pincode, date):
    r = httpx.get(f"{API}/slots", params={"pincode": pincode, "date": date}).json()
    log("slots_offered")
    return r

def book_appointment(**kw):
    r = httpx.post(f"{API}/book", json={**kw, "call_id": call_id}).json()
    if r.get("success"): log("booked")
    return r

def join_waitlist(**kw):
    if serviceable_pins.get(kw.get("pincode")):
        return {"error": "This pincode IS serviceable. Do not waitlist. Ask for the preferred date and call get_slots."}
    r = httpx.post(f"{API}/waitlist", json=kw).json()
    log("waitlisted")
    return r

TOOLS = {"check_serviceability": check_serviceability, "get_slots": get_slots,
         "book_appointment": book_appointment, "join_waitlist": join_waitlist}

def fn(name, desc, props):
    return {"type": "function", "function": {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": {k: {"type": "string"} for k in props},
                           "required": props}}}

SCHEMAS = [
    fn("check_serviceability", "Check if a 6-digit pincode is serviceable", ["pincode"]),
    fn("get_slots", "Get available slots for a pincode and date (YYYY-MM-DD)", ["pincode", "date"]),
    fn("book_appointment", "Book the appointment after the caller confirms",
       ["name", "phone", "service", "pincode", "address", "date", "time"]),
    fn("join_waitlist", "Add caller to waitlist ONLY if the pincode is not serviceable", ["name", "phone", "pincode"]),
]

messages = [{"role": "system", "content": system},
            {"role": "user", "content": "(call connected)"}]
log("call_started")

def agent_turn():
    while True:
        r = httpx.post(LLM, timeout=180, json={"model": MODEL, "messages": messages,
                       "tools": SCHEMAS, "max_tokens": 150}).json()
        msg = r["choices"][0]["message"]
        messages.append(msg)
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"])
                print(f"   [tool] {name}({args})")
                try:
                    result = TOOLS[name](**args)
                except Exception as e:
                    result = {"error": f"Tool call failed: {e}. Check the arguments and try again."}
                print(f"   [result] {result}")
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": json.dumps(result)})
            continue
        print("\nCharlie:", msg["content"], "\n")
        return

agent_turn()
while True:
    user = input("You: ").strip()
    if user in ("quit", "exit"): break
    messages.append({"role": "user", "content": user})
    agent_turn()

