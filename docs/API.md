# ClearView API reference

Local base URL: `http://localhost:8001`  
Deployed base URL: your Vercel domain

The public business endpoints are mounted below `/api` in the deployed app,
for example `/api/serviceability/560034`. The agent calls the same business
logic in-process, so it does not depend on a second localhost server.

## Business API

| Method and path | What it does | Input | Response |
|---|---|---|---|
| `GET /api/serviceability/{pincode}` | Checks whether ClearView serves a six-digit pincode. | Path: `pincode` | `serviceable`, plus `city` and `area` when available. |
| `GET /api/slots?pincode=&date=` | Returns up to three unbooked slots for an area and date. | Query: `pincode`, ISO `date` | `slots`: slot ID and time. |
| `POST /api/book` | Reserves one available slot and creates a booking ID. | `call_id`, name, phone, service, pincode, address, date, time | `success` and `booking_id`, or `slot_taken`. |
| `POST /api/waitlist` | Saves an interest request for an unserviceable area. | name, phone, pincode | `success`. |
| `POST /api/event` | Logs a funnel step for later analysis. | `call_id`, `step` | `ok`. |

### Booking request example

```json
{
  "call_id": "a1b2c3d4",
  "name": "Asha Sharma",
  "phone": "9876543210",
  "service": "home eye test",
  "pincode": "560034",
  "address": "12, 5th Cross, near Forum Mall",
  "date": "2026-10-02",
  "time": "14:00"
}
```

## Voice-agent API

| Method and path | What it does | Input | Response |
|---|---|---|---|
| `POST /start` | Creates an isolated call session and returns Charlie's greeting plus the first question. | None | `session_id`, `reply`. |
| `POST /chat` | Accepts one caller answer, validates only the current expected field, advances at most one stage, and returns one next question. | `session_id`, `text` | `reply`. |
| `GET /phone` | Serves the browser phone-call demo. | None | HTML page. |

The agent server is the enforcement point: it only calls `/slots` after a serviceable pincode and date, `/book` after explicit confirmation, and `/waitlist` only for unserviceable pincodes.
