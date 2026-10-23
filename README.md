# EventHub API

A Django REST Framework backend for browsing events, reserving seats, and cancelling reservations. The project uses SQLite for local development.

## How to run the project

**Prerequisite:** Python 3.11 or newer.

Open a terminal in the project folder containing `manage.py`, then run these commands on Windows:

```bat
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py runserver
```

If `.venv` already exists, skip the first command. These commands work in Command Prompt and PowerShell without activating the environment.

Open the API at <http://127.0.0.1:8000/api/>. Stop the server with `Ctrl+C`.

To run the automated tests:

```bat
.\.venv\Scripts\python.exe manage.py test
```

## What each endpoint does

All endpoint paths include the `/api/` prefix and end with a trailing slash.

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | `/api/events/` | List events ordered by date. |
| POST | `/api/events/` | Create an event with its venue, date, capacity, and status. |
| GET | `/api/events/{id}/` | Get an event's details, available seats, and confirmed reservation count. |
| PUT | `/api/events/{id}/` | Replace the event's writable fields. |
| PATCH | `/api/events/{id}/` | Update selected event fields. |
| DELETE | `/api/events/{id}/` | Delete an event and its related reservations. |
| GET | `/api/reservations/` | List reservations, newest first. |
| POST | `/api/reservations/` | Create a reservation and deduct its seats; returns `201 Created`. |
| GET | `/api/reservations/{id}/` | Get a reservation's details. |
| PUT | `/api/reservations/{id}/` | Replace writable reservation fields and adjust seat availability. |
| PATCH | `/api/reservations/{id}/` | Update attendee details, seat count, or event; adjust seats when needed. |
| DELETE | `/api/reservations/{id}/` | Delete a reservation and restore seats if it is still confirmed. |
| POST | `/api/reservations/{id}/cancel/` | Cancel a reservation and restore its seats; returns `200 OK`. No request body is needed. |

Supported filters:

- `/api/events/?status=upcoming` filters events by status.
- `/api/events/?venue=delhi` filters venues using a case-insensitive partial match.
- `/api/events/?status=upcoming&venue=delhi` combines both event filters.
- `/api/reservations/?event_id=1` lists reservations for a specific event.

Overbooking returns `400 Bad Request`. Cancelling an already cancelled reservation also returns `400` without restoring seats again. Cancelled reservations allow attendee-detail corrections, but their event and seat count cannot change.

## One design decision I made and why

I used `transaction.atomic()` to keep seat changes and reservation writes in a single database transaction. A booking needs both operations to succeed: deduct the seats and save the reservation. If saving the reservation fails, the seat deduction rolls back automatically. This prevents seats from being lost without a corresponding booking and keeps reservation data consistent with seat availability.

## Postman screenshots required

Import [EventHub.postman_collection.json](postman/EventHub.postman_collection.json) into Postman. Start the Django server and run the collection's requests in numbered order. The collection saves the event and reservation IDs automatically.

Capture these three screenshots with the request URL, response status, and response body visible:

- [ ] **Successful reservation (201 Created)** — Run **05 - Reserve 2 seats**. Show the created reservation with `status: confirmed`.
- [ ] **Overbooking failure (400 Bad Request)** — Run **07 - Try overbooking**. Show the error `Only 1 seat(s) available.`
- [ ] **Successful cancellation (200 OK)** — Run **08 - Cancel reservation**. Show the updated reservation with `status: cancelled`.

These screenshots must be captured in Postman and included with the submission.
