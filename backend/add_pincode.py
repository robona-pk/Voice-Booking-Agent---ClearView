import sqlite3, sys
from datetime import date, timedelta

pincode, city, area = sys.argv[1], sys.argv[2], sys.argv[3]
con = sqlite3.connect("app.db")
con.execute("INSERT OR IGNORE INTO pincodes VALUES(?,?,?)", (pincode, city, area))
exists = con.execute("SELECT COUNT(*) FROM slots WHERE pincode=?", (pincode,)).fetchone()[0]
if exists:
    print("Slots already exist for", pincode)
else:
    for d in range(1, 8):
        day = (date.today() + timedelta(days=d)).isoformat()
        for t in ["10:00", "12:00", "14:00", "16:00", "18:00"]:
            con.execute("INSERT INTO slots(pincode,date,time) VALUES(?,?,?)", (pincode, day, t))
con.commit()
print("Added", pincode, city, area)

