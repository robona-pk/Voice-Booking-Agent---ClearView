import os
import sqlite3, uuid
from datetime import date, datetime, timedelta
from fastapi import FastAPI
from pydantic import BaseModel

# Vercel functions can write only to /tmp. The database is demo-only there and
# may reset on a cold start; production needs a managed database.
DB = os.getenv("CLEARVIEW_DB", "/tmp/clearview.db" if os.getenv("VERCEL") else "app.db")
app = FastAPI()

def q(sql, args=(), one=False, commit=False):
    con = sqlite3.connect(DB); con.row_factory = sqlite3.Row
    cur = con.execute(sql, args)
    rows = cur.fetchall()
    if commit: con.commit()
    con.close()
    return (rows[0] if rows else None) if one else rows

def init():
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS pincodes(pincode TEXT PRIMARY KEY, city TEXT, area TEXT);
    CREATE TABLE IF NOT EXISTS slots(id INTEGER PRIMARY KEY, pincode TEXT, date TEXT, time TEXT, booked INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS bookings(id TEXT PRIMARY KEY, call_id TEXT, name TEXT, phone TEXT, service TEXT,
        pincode TEXT, address TEXT, date TEXT, time TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS waitlist(id INTEGER PRIMARY KEY, name TEXT, phone TEXT, pincode TEXT, created_at TEXT);
    CREATE TABLE IF NOT EXISTS call_events(id INTEGER PRIMARY KEY, call_id TEXT, step TEXT, ts TEXT);
    CREATE TABLE IF NOT EXISTS calls(call_id TEXT PRIMARY KEY, transcript TEXT, outcome TEXT, duration_s REAL, created_at TEXT);
    """)
    pins = [("560001", "Bengaluru", "MG Road"), ("560008", "Bengaluru", "H.A.L. II Stage"), ("560034", "Bengaluru", "Koramangala"),
            ("110001", "Delhi", "Connaught Place"), ("400001", "Mumbai", "Fort"),
            ("122001", "Gurugram", "Sector 14")]
    con.executemany("INSERT OR IGNORE INTO pincodes VALUES(?,?,?)", pins)
    for pincode, _, _ in pins:
        if con.execute("SELECT COUNT(*) FROM slots WHERE pincode=?", (pincode,)).fetchone()[0] == 0:
            for offset in range(1, 8):
                for time in ["10:00", "12:00", "14:00", "16:00", "18:00"]:
                    con.execute("INSERT INTO slots(pincode,date,time) VALUES(?,?,?)", (pincode, (date.today() + timedelta(days=offset)).isoformat(), time))
    con.commit(); con.close()
init()

@app.get("/serviceability/{pincode}")
def serviceability(pincode: str):
    r = q("SELECT * FROM pincodes WHERE pincode=?", (pincode,), one=True)
    if not r: return {"serviceable": False}
    return {"serviceable": True, "city": r["city"], "area": r["area"]}

@app.get("/slots")
def slots(pincode: str, date: str):
    # Show a spread across the day, including an after-work option, rather than
    # returning only the first three morning/afternoon rows.
    rows = q("""SELECT id,time FROM slots WHERE pincode=? AND date=? AND booked=0
                ORDER BY CASE time WHEN '10:00' THEN 1 WHEN '14:00' THEN 2 WHEN '18:00' THEN 3 ELSE 4 END
                LIMIT 3""", (pincode, date))
    return {"slots": [dict(r) for r in rows]}

class Booking(BaseModel):
    call_id: str; name: str; phone: str; service: str
    pincode: str; address: str; date: str; time: str

@app.post("/book")
def book(b: Booking):
    s = q("SELECT id FROM slots WHERE pincode=? AND date=? AND time=? AND booked=0", (b.pincode, b.date, b.time), one=True)
    if not s: return {"success": False, "reason": "slot_taken"}
    bid = "CV" + uuid.uuid4().hex[:6].upper()
    q("UPDATE slots SET booked=1 WHERE id=?", (s["id"],), commit=True)
    q("INSERT INTO bookings VALUES(?,?,?,?,?,?,?,?,?,?)",
      (bid, b.call_id, b.name, b.phone, b.service, b.pincode, b.address, b.date, b.time, datetime.now().isoformat()), commit=True)
    return {"success": True, "booking_id": bid}

class Waitlist(BaseModel):
    name: str; phone: str; pincode: str

@app.post("/waitlist")
def waitlist(w: Waitlist):
    q("INSERT INTO waitlist(name,phone,pincode,created_at) VALUES(?,?,?,?)",
      (w.name, w.phone, w.pincode, datetime.now().isoformat()), commit=True)
    return {"success": True}

class Event(BaseModel):
    call_id: str; step: str

@app.post("/event")
def event(e: Event):
    q("INSERT INTO call_events(call_id,step,ts) VALUES(?,?,?)", (e.call_id, e.step, datetime.now().isoformat()), commit=True)
    return {"ok": True}
