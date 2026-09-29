import sqlite3
from datetime import date, timedelta
con = sqlite3.connect("app.db")
pins = [("560001","Bengaluru","MG Road"),("560034","Bengaluru","Koramangala"),
        ("110001","Delhi","Connaught Place"),("400001","Mumbai","Fort"),("122001","Gurugram","Sector 14")]
con.executemany("INSERT OR IGNORE INTO pincodes VALUES(?,?,?)", pins)
for p,_,_ in pins:
    for d in range(1, 8):
        day = (date.today()+timedelta(days=d)).isoformat()
        for t in ["10:00","12:00","14:00","16:00","18:00"]:
            con.execute("INSERT INTO slots(pincode,date,time) VALUES(?,?,?)", (p, day, t))
con.commit()
print("Seeded.")

