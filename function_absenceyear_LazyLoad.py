import azure.functions as func
import logging
import requests
import datetime
import os
import calendar
import json
from datetime import timedelta, date, time
from azure.identity import DefaultAzureCredential
from dateutil import tz 

bp = func.Blueprint()

# --- CONFIGURATION ---
TIMEZONE_NAME = 'Europe/Oslo'
WORK_HOURS_START = time(9, 30)
WORK_HOURS_END   = time(14, 30)

# URL for monthly view (back-link)
MONTH_URL_VIEW = "/api/GetAbsenceMonth?code=CynCJKFuvKV-Mbqd4jMZaHuFOuAh1qIReLNlV7-RJErzAzFu5RSW7w==&dept="

NORWEGIAN_MONTHS = {
    1: "Januar", 2: "Februar", 3: "Mars", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Desember"
}

DEPARTMENTS_CONFIG = {
    "it": {"title": "Fraværsliste - IT", "gids": ["88d8f237-f90c-4862-b511-2001d7b594d0"]},
    "admin": {
        "title": "Fraværsliste - Admin",
        "gids": ["ebde949d-25d0-4f85-9649-3975202324ea", "10b4976f-0027-4b0d-a34a-6be134d7d60f", "5448534f-6a5a-455c-92a2-c16f8e38da24", "88f7095d-4d08-4ea4-be46-fccc1d775634"]
    },
    "dart": {"title": "Fraværsliste - Dart", "gids": ["2ec6f95a-ef58-4b6c-bb0f-3ac28b50bb4c"]},
    "sand": {"title": "Fraværsliste - Sand", "gids": ["a830b4cd-9236-44a2-81be-7c037ca01607"]},
    "samba": {"title": "Fraværsliste - Samba", "gids": ["bc904b3f-5b34-4eba-a928-804118c9e967"]},
    "bamjo": {"title": "Fraværsliste - Bamjo", "gids": ["773eedea-6d81-4a71-b9e3-53c86b736177"]}
}

COLORS = {
    'FREE': "#ffffff", 'WEEKEND': "#888888", 'TODAY': "#ffffaa",
    'VACATION': "#f37366", 'LEAVE': "#cccccc", 'BUSINESS_TRIP': "#fff79a",
    'TIME_OFF': "#6ecff6", 'OTHER': "#f49ac2", 'PRESENT': "#f4cfb4",
    'BUSY': "#8493ca", 'HOME_OFFICE': "#c0f0c0", 'ERROR': "#ff0000",
    'ELSEWHERE':"#a187be",'TENTATIVE':"#7ec699"
}

@bp.route(route="GetAbsenceYear", auth_level=func.AuthLevel.FUNCTION)
def GetAbsenceYear(req: func.HttpRequest) -> func.HttpResponse:
    dept_key = req.params.get('dept', 'it').lower()
    year_val = req.params.get('year')
    month_val = req.params.get('month') # If present, we return ONLY that month's HTML
    
    norway_tz = tz.gettz(TIMEZONE_NAME)
    now = datetime.datetime.now(norway_tz)
    viewing_year = int(year_val) if year_val and year_val.isdigit() else now.year


    if dept_key not in DEPARTMENTS_CONFIG:
        return func.HttpResponse("Invalid Dept", status_code=400)
    
    selected_dept = DEPARTMENTS_CONFIG[dept_key]

    # --- ROUTE 1: AJAX LOAD (Single Month Data) ---
    if month_val:
        return get_month_data_fragment(int(month_val), viewing_year, selected_dept, now)

    # --- ROUTE 2: FULL PAGE LOAD (The Shell) ---
    return get_page_shell(viewing_year, selected_dept, dept_key, req.params.get('code', ''))


def get_month_data_fragment(month_idx, viewing_year, selected_dept, now):
    """Generates the HTML table for one specific month using BULK API fetching."""
    try:
        credential = DefaultAzureCredential()
        token = credential.get_token('https://graph.microsoft.com/.default').token
        users = get_users_in_groups(token, selected_dept['gids'])
        holidays = [d.strip() for d in os.environ.get('HOLIDAYS', "").split(',') if d.strip()]

        month_date = date(viewing_year, month_idx, 1)
        days_in_month = calendar.monthrange(viewing_year, month_idx)[1]
        month_dates = [month_date + timedelta(days=i) for i in range(days_in_month)]

      
        # 1. Table Headers
        th_cells = ""
        for d in month_dates:
            is_off = d.weekday() >= 5 or str(d) in holidays
            style = "min-width:25px; width:25px;"
            if d == now.date(): style += f"background:{COLORS['TODAY']}; border-bottom: 2px solid #333;"
            elif is_off: style += f"background:{COLORS['WEEKEND']}; color: white;"
            th_cells += f"<th style='{style}'>{d.day:02d}</th>"

        # 2. BULK DATA FETCH
        rows_html = generate_rows_bulk(token, users, month_dates, holidays)

        month_label = f"{NORWEGIAN_MONTHS[month_idx]} {viewing_year}"
        html = f"""
            <h3 class="month-title">{month_label}</h3>
            <div class="table-wrapper">
                <table class="month-table">
                    <thead>
                        <tr><th class="sticky-name-head">Ansatt</th>{th_cells}</tr>
                    </thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </div>
        """
        return func.HttpResponse(html, mimetype="text/html")
    except Exception as e:
        return func.HttpResponse(f"Feil: {str(e)}", status_code=500)


def get_page_shell(year, dept_info, dept_key, code):
    """The initial instant-load page with placeholders and scroll logic."""
    norway_tz = tz.gettz(TIMEZONE_NAME)
    start_time = datetime.datetime.now(norway_tz)   
    start_time_str = start_time.strftime('%H:%M:%S')
    placeholders = ""
    for i in range(1, 13):
        placeholders += f"""
        <div id="month-{i}" class="month-placeholder" data-month="{i}">
            <div class="loading-label">{NORWEGIAN_MONTHS[i]} {year}...</div>
            <div class="skeleton-line"></div>
        </div>"""

    legend_html = f"""
        <div style="margin-top:20px; color:#30183A; font-size:0.9em;font-weight:bold">Denne oversikten ble generert når du lastet inn siden  {start_time_str} .</div>
        <p>Kalenderinformasjonen 11:30 - 13:00 brukes for å beregne hvor mye mat som bestilles av kantinen</p>
        <p>For å vises her, lag oppføringer i egen kalender som minimum dekker 09:30 til 14:30</p>
        <table cellspacing="0" cellpadding="2" border="1" style="border-collapse:collapse;">
            <tr><td bgcolor="#f37366" width="100"><b>Ferie</b></td><td>Start emnefeltet med "Ferie" <b>og</b> sett "Show as" til <em>Away</em> eller <em>Out of office</em></td></tr>
            <tr><td bgcolor="#cccccc"><b>Permisjon</b></td><td>Start emnefeltet med "Permisjon" <b>og</b> sett "Show as" til <em>Away</em> eller <em>Out of office</em></td></tr>
            <tr><td bgcolor="#FFF79A"><b>Jobbreise</b></td><td>Start emnefeltet med "Jobbreise" <b>og</b> sett "Show as" til <em>Away</em> eller <em>Out of office</em></td></tr>
            <tr><td bgcolor="#6ECFF6"><b>Avspasering</b></td><td>Start emnefeltet med "Avspasering" <b>og</b> sett "Show as" til <em>Away</em> eller <em>Out of office</em></td></tr>
            <tr><td bgcolor="#F49AC2"><b>Annet fravær</b></td><td>Start emnefeltet med "Annet" <b>og</b> sett "Show as" til <em>Away</em> eller <em>Out of office</em></td></tr>
            <tr><td bgcolor="#c0f0c0"><b>Hjemmekontor</b></td><td>Start emnefeltet med "Hjemmekontor" <b>og</b> sett "Show as" til <em>Working elsewhere</em></td></tr>
        </table>
        <p>Hvis emnefeltet <em>ikke</em> er satt til en av kodene over så vil "Show as"-informasjonen brukes:</p>
        <table cellspacing="0" cellpadding="2" border="1" style="border-collapse:collapse;">
            <tr><td bgcolor="#A187BE" width="100"><b>Jobber ute</b></td><td>Sett "Show as" til <em>Working elsewhere</em></td></tr>
            <tr><td bgcolor="#8493CA"><b>Opptatt</b></td><td>Sett "Show as" til <em>Busy</em></td></tr>
            <tr><td bgcolor="#7ec699"><b>Ikke besvart</b></td><td>Sett "Show as" til <em>Tentative</em></td></tr>
        </table>
        <br>
    """
    controls_html = f"""
    <div style="margin-bottom: 15px; display: flex; align-items: center; gap: 15px;">
        <a href="?dept={dept_key}&code={code}&year={year-1}" class="nav-btn">&laquo; {year-1}</a>
        <span style="font-weight:bold; font-size: 1.5em; min-width: 100px; text-align:center;">{year}</span>
        <a href="?dept={dept_key}&code={code}&year={year+1}" class="nav-btn">{year+1} &raquo;</a>
        <a href="{MONTH_URL_VIEW}{dept_key}" class="nav-btn" style="background:#666; margin-left:20px;">Månedsvisning</a>
    </div>
    """
    return func.HttpResponse(f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{dept_info['title']} {year}</title>
        <style>
            body {{ font-family: "Arial, Helvetica, sans"; padding: 20px; background-color: #f9f9f9; }}
            .month-placeholder {{ background: white; margin-bottom: 30px; border-radius: 8px; padding: 15px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); min-height: 150px; }}
            .loading-label {{ color: #888; font-weight: bold; margin-bottom: 10px; }}
            .skeleton-line {{ height: 100px; background: linear-gradient(90deg, #eee 25%, #f5f5f5 50%, #eee 75%); background-size: 200% 100%; animation: loading 1.5s infinite; }}
            @keyframes loading {{ 0% {{ background-position: 100% 0; }} 100% {{ background-position: -100% 0; }} }}
            
            .month-table {{ border-collapse: collapse; background: white; font-size: 0.85em; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .month-table th, .month-table td {{ border-collapse: collapse; background: white; font-size: 0.85em; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .sticky-name {{text-align:left; padding-left:5px; font-weight:500; position:sticky; left:0; background:white; z-index:5; border-right:1px solid #666 !important; }}
            .sticky-name-head {{ text-align:left;width:125px; padding-left:8px; position:sticky; left:0; background:#eee; z-index:3; border-right: 1px solid #ccc !important; }}
            .table-wrapper {{ overflow-x: auto; }}
            .nav-btn {{ text-decoration: none; padding: 6px 12px; background: #0078D4; color: white; border-radius: 4px; font-weight: bold; font-size: 0.9em; }}
        </style>
    </head>
    <body>
        {legend_html}
        <h1>{dept_info['title']} - {year}</h1>
        {controls_html}     
        <div id="container">{placeholders}</div>
        <script>
            const observer = new IntersectionObserver((entries) => {{
                entries.forEach(entry => {{
                    if (entry.isIntersecting) {{
                        const div = entry.target;
                        const month = div.dataset.month;
                        fetch(window.location.href + '&month=' + month)
                            .then(r => r.text())
                            .then(html => {{
                                div.innerHTML = html;
                                div.style.minHeight = "auto";
                            }});
                        observer.unobserve(div);
                    }}
                }});
            }}, {{ rootMargin: "300px" }});

            document.querySelectorAll('.month-placeholder').forEach(m => observer.observe(m));
        </script>
    </body>
    </html>
    """, mimetype="text/html")

def generate_rows_bulk(token, users, dates, holidays):
    """Fetches up to 20 users in a single Microsoft Graph call."""
    headers = {'Authorization': f'Bearer {token}', 'Prefer': f'outlook.timezone="{TIMEZONE_NAME}"', 'Content-Type': 'application/json'}
    upns = [u['userPrincipalName'] for u in users]
    
    # Graph 'getSchedule' supports max 20 per call. We chunk them just in case.
    chunks = [upns[i:i + 20] for i in range(0, len(upns), 20)]
    all_data = {}

    for chunk in chunks:
        payload = {
            "schedules": chunk,
            "startTime": {"dateTime": f"{dates[0]}T00:00:00", "timeZone": TIMEZONE_NAME},
            "endTime": {"dateTime": f"{dates[-1]}T23:59:59", "timeZone": TIMEZONE_NAME},
            "availabilityViewInterval": 1440
        }
        res = requests.post(f"https://graph.microsoft.com/v1.0/users/{chunk[0]}/calendar/getSchedule", json=payload, headers=headers)
        if res.status_code == 200:
            for item in res.json().get('value', []):
                all_data[item['scheduleId'].lower()] = item.get('scheduleItems', [])

    rows_html = ""
    for u in users:
        upn_lower = u['userPrincipalName'].lower()
        events = all_data.get(upn_lower, [])
        row_cells = ""
        for d in dates:
            color, title = get_status_for_day(events, d, holidays)
            row_cells += f"<td style='background-color:{color};' title='{title}'></td>"
        rows_html += f"<tr><td class='sticky-name'>{u['displayName']}</td>{row_cells}</tr>"
    
    return rows_html

def get_status_for_day(events, target_date, holidays):
    if target_date.weekday() >= 5 or str(target_date) in holidays:
        return COLORS['WEEKEND'], "Helg"
    
    work_start = datetime.datetime.combine(target_date, WORK_HOURS_START)
    work_end = datetime.datetime.combine(target_date, WORK_HOURS_END)
    
    final_color, final_text = COLORS['FREE'], ""
    for e in events:
        try:
            s = datetime.datetime.strptime(e['start']['dateTime'][:19], '%Y-%m-%dT%H:%M:%S')
            end = datetime.datetime.strptime(e['end']['dateTime'][:19], '%Y-%m-%dT%H:%M:%S')
            if s <= work_start and end >= work_end:
                status, subj = e.get('status', 'busy'), e.get('subject', '').lower()
                if status == 'tentative': final_color = COLORS['TENTATIVE']
                elif status == 'free' and 'tilstede' in subj: final_color = COLORS['PRESENT']
                elif status == 'busy': final_color = COLORS['BUSY']
                elif status == 'oof':
                    if 'ferie' in subj: final_color = COLORS['VACATION']
                    elif 'permisjon' in subj: final_color = COLORS['LEAVE']
                    elif 'jobbreise' in subj: final_color = COLORS['BUSINESS_TRIP']
                    elif 'avspas' in subj: final_color = COLORS['TIME_OFF']
                    else: final_color = COLORS['OTHER']
                elif status == 'workingElsewhere':
                    if any(x in subj for x in ['hjemmekont', 'home off']): final_color = COLORS['HOME_OFFICE']
                    else: final_color = COLORS['ELSEWHERE']
                final_text = subj
        except: continue
    return final_color, final_text

def get_users_in_groups(token, gids):
    headers = {'Authorization': f'Bearer {token}'}
    users_dict = {}
    for gid in gids:
        url = f"https://graph.microsoft.com/v1.0/groups/{gid}/members?$select=displayName,userPrincipalName&$top=999"
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            for u in r.json().get('value', []):
                if 'userPrincipalName' in u: users_dict[u['userPrincipalName']] = u
    return sorted(users_dict.values(), key=lambda x: x['displayName'])