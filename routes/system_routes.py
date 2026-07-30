"""System/automation routes — SLA reminder job, triggered by an external scheduler."""

import os
from flask import Blueprint, request, jsonify
from database import get_db, sla_status, log_action
from mailer import send_email, render_sla_reminder_email

system_bp = Blueprint("system", __name__)

CRON_SECRET = os.environ.get("CRON_SECRET")
APP_BASE_URL = os.environ.get("APP_BASE_URL", "")  # e.g. https://tia-ticketing-1.onrender.com — used to build links in emails
REMINDER_COOLDOWN_HOURS = 4  # don't re-notify the same ticket more than once per this window
OPEN_STATUSES = ("open", "in_progress", "pending")


@system_bp.route("/check-sla", methods=["POST"])
def check_sla():
    # Shared-secret auth — this endpoint has no user session, it's called by a cron trigger.
    auth = request.headers.get("Authorization", "")
    if not CRON_SECRET or auth != f"Bearer {CRON_SECRET}":
        return jsonify(error="Unauthorized."), 401

    db  = get_db()
    cur = db.cursor()
    cur.execute(
        f"""SELECT * FROM tickets
            WHERE status IN ({','.join(['%s']*len(OPEN_STATUSES))})""",
        OPEN_STATUSES
    )
    tickets = cur.fetchall()

    notified = []
    for t in tickets:
        status = sla_status(t)
        if not (status["sla_response_breached"] or status["sla_resolution_breached"]):
            continue

        # Throttle: skip if we already reminded within the cooldown window
        if t["last_sla_reminder_at"]:
            cur.execute(
                "SELECT NOW() - %s < (%s || ' hours')::interval as recent",
                (t["last_sla_reminder_at"], REMINDER_COOLDOWN_HOURS)
            )
            if cur.fetchone()["recent"]:
                continue

        breach_kind = []
        if status["sla_response_breached"]:   breach_kind.append("first response")
        if status["sla_resolution_breached"]: breach_kind.append("resolution")
        breach_text = " and ".join(breach_kind)

        message = f"SLA breach ({breach_text}) on {t['ticket_no']}: {t['title']}"

        # Recipients: assigned technician, or every staff member if unassigned
        if t["assigned_to"]:
            cur.execute("SELECT id, name, email FROM users WHERE id=%s", (t["assigned_to"],))
            recipients = cur.fetchall()
        else:
            cur.execute("SELECT id, name, email FROM users WHERE role IN ('admin','agent','technician')")
            recipients = cur.fetchall()

        ticket_link = f"{APP_BASE_URL}/ticket/{t['id']}" if APP_BASE_URL else None

        for r in recipients:
            cur.execute(
                "INSERT INTO notifications (user_id, message, link) VALUES (%s,%s,%s)",
                (r["id"], message, f"/ticket/{t['id']}")
            )
            if r["email"]:
                html_body = render_sla_reminder_email(
                    technician_name=r["name"],
                    ticket_no=t["ticket_no"],
                    title=t["title"],
                    request_level=t["request_level"],
                    breach_text=breach_text,
                    ticket_link=ticket_link,
                )
                send_email(r["email"], r["name"], f"SLA Breach Alert – {t['ticket_no']}", html_body)

        log_action(cur, t["id"], None, "sla_reminder", breach_text)
        cur.execute("UPDATE tickets SET last_sla_reminder_at = NOW() WHERE id=%s", (t["id"],))
        notified.append(t["ticket_no"])

    db.commit()
    cur.close()
    db.close()
    return jsonify(checked=len(tickets), reminders_sent=len(notified), tickets=notified)
