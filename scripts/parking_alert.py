"""
NYC Parking Alert - Skillman / Barnett Ave area, Woodside Queens
Scrapes three NYC sources and sends a weekly summary email via Gmail.
"""

import os
import re
import smtplib
import sys
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup

# ── Target streets ────────────────────────────────────────────────────────────
STREET_PATTERNS = [
    r"skillman\s+av(e(nue)?)?",
    r"barnett\s+av(e(nue)?)?",
    r"4[6-9](th|st|nd|rd)?\s+st(reet)?",
    r"5[0-4](th|st|nd|rd)?\s+st(reet)?",
]
CROSS_PATTERNS = [
    r"skillman",
    r"barnett",
    r"43(rd)?\s+av(e(nue)?)?",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ParkingAlertBot/1.0)"}


# ── Helpers ───────────────────────────────────────────────────────────────────
def week_range():
    """Return the Sunday–Saturday range for next week."""
    today = date.today()
    days_until_sunday = (6 - today.weekday() + 1) % 7 or 7
    next_sunday = today + timedelta(days=days_until_sunday)
    next_saturday = next_sunday + timedelta(days=6)
    return next_sunday, next_saturday


def matches_area(text: str) -> bool:
    t = text.lower()
    has_street = any(re.search(p, t) for p in STREET_PATTERNS)
    has_cross = any(re.search(p, t) for p in CROSS_PATTERNS)
    return has_street or has_cross


def fmt_date(d: date) -> str:
    return d.strftime("%B %-d, %Y")


# ── Source 1: Resurfacing schedule ────────────────────────────────────────────
def fetch_resurfacing() -> list[str]:
    url = "https://nycstreets.net/PavementWorks/Project/WeeklyResurfacingSchedule/Q"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        hits = []
        for row in soup.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in row.find_all(["td", "th"])]
            row_text = " | ".join(cells)
            if matches_area(row_text) and len(cells) > 1:
                if not all(c.lower() in ("street", "from", "to", "borough", "status", "") for c in cells):
                    hits.append(row_text)
        return hits if hits else []
    except Exception as e:
        return [f"⚠️ Could not fetch resurfacing schedule: {e}"]


# ── Source 2: ASP suspensions ─────────────────────────────────────────────────
ASP_HOLIDAYS = {
    date(2026, 1, 1):  "New Year's Day",
    date(2026, 1, 6):  "Three Kings' Day",
    date(2026, 1, 19): "Martin Luther King Jr.'s Birthday",
    date(2026, 2, 12): "Lincoln's Birthday",
    date(2026, 2, 16): "Washington's Birthday / Lunar New Year's Eve",
    date(2026, 2, 17): "Lunar New Year",
    date(2026, 2, 18): "Ash Wednesday / Losar",
    date(2026, 3, 3):  "Purim",
    date(2026, 3, 20): "Idul-Fitr (Eid Al-Fitr)",
    date(2026, 3, 21): "Idul-Fitr (Eid Al-Fitr)",
    date(2026, 4, 2):  "Holy Thursday / Passover",
    date(2026, 4, 3):  "Good Friday / Passover",
    date(2026, 4, 8):  "Passover (7th/8th Days)",
    date(2026, 4, 9):  "Passover (7th/8th Days) / Holy Thursday (Orthodox)",
    date(2026, 4, 10): "Good Friday (Orthodox)",
    date(2026, 5, 14): "Solemnity of the Ascension",
    date(2026, 5, 22): "Shavuoth",
    date(2026, 5, 23): "Shavuoth",
    date(2026, 5, 25): "Memorial Day ★",
    date(2026, 5, 27): "Idul-Adha (Eid Al-Adha)",
    date(2026, 5, 28): "Idul-Adha (Eid Al-Adha)",
    date(2026, 6, 19): "Juneteenth",
    date(2026, 7, 3):  "Independence Day ★",
    date(2026, 7, 4):  "Independence Day ★",
    date(2026, 7, 23): "Tisha B'Av",
    date(2026, 8, 15): "Feast of the Assumption",
    date(2026, 9, 7):  "Labor Day ★",
    date(2026, 9, 12): "Rosh Hashanah",
    date(2026, 9, 13): "Rosh Hashanah",
    date(2026, 9, 21): "Yom Kippur",
    date(2026, 9, 26): "Succoth",
    date(2026, 9, 27): "Succoth",
    date(2026, 10, 3): "Shemini Atzereth",
    date(2026, 10, 4): "Simchas Torah",
    date(2026, 10, 12):"Columbus Day",
    date(2026, 11, 1): "All Saints' Day",
    date(2026, 11, 3): "Election Day",
    date(2026, 11, 8): "Diwali",
    date(2026, 11, 11):"Veterans Day",
    date(2026, 11, 26):"Thanksgiving Day ★",
    date(2026, 12, 8): "Immaculate Conception",
    date(2026, 12, 25):"Christmas Day ★",
}

def fetch_asp(sun: date, sat: date) -> list[dict]:
    suspensions = []
    d = sun
    while d <= sat:
        if d in ASP_HOLIDAYS:
            suspensions.append({
                "date": d,
                "day": d.strftime("%A"),
                "holiday": ASP_HOLIDAYS[d],
            })
        d += timedelta(days=1)
    return suspensions


# ── Source 3: DOT Weekly Traffic Advisory ────────────────────────────────────
def fetch_traffic_advisory() -> list[str]:
    url = "https://www.nyc.gov/html/dot/html/motorist/weektraf.shtml"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        queens_header = soup.find(lambda tag: tag.name in ("h2", "h3", "h4") and "queens" in tag.get_text().lower())
        hits = []
        if queens_header:
            for sibling in queens_header.find_next_siblings():
                if sibling.name in ("h2", "h3", "h4"):
                    break
                text = sibling.get_text(" ", strip=True)
                if text and matches_area(text):
                    hits.append(text)
        return hits if hits else []
    except Exception as e:
        return [f"⚠️ Could not fetch traffic advisory: {e}"]


# ── Email builder ─────────────────────────────────────────────────────────────
def build_email(sun: date, sat: date, resurfacing: list, asp: list, traffic: list) -> tuple[str, str, str]:
    week_str = f"{fmt_date(sun)} – {fmt_date(sat)}"
    subject = f"🚗 Parking Alert: Skillman/Barnett Area — Week of {sun.strftime('%b %-d')}"

    lines = [
        f"SKILLMAN / BARNETT AREA PARKING ALERT",
        f"Week of {week_str}",
        "=" * 44,
        "",
        "ALTERNATE SIDE PARKING",
        "-" * 24,
    ]
    if asp:
        lines.append(f"⚠️  {len(asp)} suspension(s) this week:")
        for s in asp:
            star = " (Major holiday — meters also suspended)" if "★" in s["holiday"] else ""
            lines.append(f"  • {s['day']} {fmt_date(s['date'])}: SUSPENDED — {s['holiday']}{star}")
    else:
        lines.append("✅  ASP in effect all week. No suspensions.")
    lines += ["", "RESURFACING WORK", "-" * 16]
    if resurfacing and not resurfacing[0].startswith("⚠️"):
        lines.append(f"⚠️  {len(resurfacing)} project(s) near your streets:")
        for r in resurfacing:
            lines.append(f"  • {r}")
    elif resurfacing and resurfacing[0].startswith("⚠️"):
        lines += resurfacing
    else:
        lines.append("✅  No resurfacing scheduled in your area this week.")
    lines += ["", "TRAFFIC ADVISORIES (Queens)", "-" * 26]
    if traffic and not traffic[0].startswith("⚠️"):
        lines.append(f"⚠️  {len(traffic)} advisory/advisories:")
        for t in traffic:
            lines.append(f"  • {t}")
    elif traffic and traffic[0].startswith("⚠️"):
        lines += traffic
    else:
        lines.append("✅  No advisories for Skillman Ave or Barnett Ave this week.")
    lines += [
        "",
        "─" * 44,
        "Sources:",
        "• https://nycstreets.net/PavementWorks/Project/WeeklyResurfacingSchedule/Q",
        "• https://www.nyc.gov/html/dot/html/motorist/alternate-side-parking.shtml",
        "• https://www.nyc.gov/html/dot/html/motorist/weektraf.shtml#queens",
        "",
        "★ = Major legal holiday: meters also suspended.",
        "For emergency ASP suspensions (weather), check @NYCASP on X or NYC 311.",
    ]
    plain = "\n".join(lines)

    def section(title, color, items, empty_msg):
        if not items:
            return f"""
            <tr><td style="padding:20px 24px 0">
              <h2 style="margin:0 0 8px;font-size:15px;font-weight:600;color:#111">{title}</h2>
              <p style="margin:0;color:#3a7d44;font-size:14px">✅ &nbsp;{empty_msg}</p>
            </td></tr>"""
        rows = "".join(f'<li style="margin:4px 0;font-size:14px;color:#333">{i}</li>' for i in items)
        return f"""
            <tr><td style="padding:20px 24px 0">
              <h2 style="margin:0 0 8px;font-size:15px;font-weight:600;color:#111">{title}</h2>
              <div style="background:{color};border-radius:6px;padding:12px 16px">
                <ul style="margin:0;padding-left:18px">{rows}</ul>
              </div>
            </td></tr>"""

    asp_items = [f"<strong>{s['day']} {fmt_date(s['date'])}</strong>: SUSPENDED — {s['holiday']}" + (" <em>(Major holiday — meters also suspended)</em>" if "★" in s["holiday"] else "") for s in asp]
    resurfacing_items = resurfacing if resurfacing else []
    traffic_items = traffic if traffic else []

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:32px 0">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08)">
  <tr><td style="background:#1a1a2e;padding:24px 24px 20px">
    <p style="margin:0;font-size:11px;font-weight:600;letter-spacing:.08em;color:#8888aa;text-transform:uppercase">Woodside, Queens</p>
    <h1 style="margin:4px 0 0;font-size:20px;font-weight:700;color:#fff">Skillman / Barnett Parking Alert</h1>
    <p style="margin:6px 0 0;font-size:13px;color:#9999bb">Week of {week_str}</p>
  </td></tr>
  {section("🅿️  Alternate Side Parking", "#fff8e1", asp_items, "ASP in effect all week. No suspensions.")}
  {section("🚧  Resurfacing Work", "#fff3e0", resurfacing_items, "No resurfacing scheduled in your area this week.")}
  {section("🚦  Traffic Advisories", "#fce4ec", traffic_items, "No advisories for Skillman Ave or Barnett Ave.")}
  <tr><td style="padding:20px 24px 24px">
    <p style="margin:0;font-size:12px;color:#999;border-top:1px solid #eee;padding-top:16px">
      Sources: <a href="https://nycstreets.net/PavementWorks/Project/WeeklyResurfacingSchedule/Q" style="color:#555">Resurfacing</a> &nbsp;·&nbsp;
      <a href="https://www.nyc.gov/html/dot/html/motorist/alternate-side-parking.shtml" style="color:#555">ASP Calendar</a> &nbsp;·&nbsp;
      <a href="https://www.nyc.gov/html/dot/html/motorist/weektraf.shtml#queens" style="color:#555">DOT Advisory</a><br>
      ★ Major holidays: meters also suspended. &nbsp;Emergency suspensions: <a href="https://x.com/NYCASP" style="color:#555">@NYCASP</a> or NYC 311.
    </p>
  </td></tr>
</table>
</td></tr></table>
</body></html>"""

    return subject, plain, html


# ── Send email ────────────────────────────────────────────────────────────────
def send_email(subject: str, plain: str, html: str):
    gmail_user = os.environ["GMAIL_USER"]
    gmail_pass = os.environ["GMAIL_APP_PASSWORD"]
    to_addr    = os.environ.get("ALERT_EMAIL", gmail_user)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Parking Alert <{gmail_user}>"
    msg["To"]      = to_addr
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html,  "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_pass)
        server.sendmail(gmail_user, to_addr, msg.as_string())
    print(f"✅ Email sent to {to_addr}")


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    sun, sat = week_range()
    print(f"Generating alert for {fmt_date(sun)} – {fmt_date(sat)}")

    resurfacing = fetch_resurfacing()
    print(f"  Resurfacing hits: {len(resurfacing)}")

    asp = fetch_asp(sun, sat)
    print(f"  ASP suspensions: {len(asp)}")

    traffic = fetch_traffic_advisory()
    print(f"  Traffic advisories: {len(traffic)}")

    subject, plain, html = build_email(sun, sat, resurfacing, asp, traffic)

    if "--dry-run" in sys.argv:
        print("\n" + plain)
    else:
        send_email(subject, plain, html)


if __name__ == "__main__":
    main()


