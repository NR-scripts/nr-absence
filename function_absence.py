import azure.functions as func
import logging
import json
import requests
import datetime
import os
from datetime import timedelta, date, time
from azure.identity import DefaultAzureCredential
from dateutil import tz 

bp = func.Blueprint()

# --- CONFIGURATION ---
TIMEZONE_NAME = 'Europe/Oslo'
WORK_HOURS_START = time(9, 30)
WORK_HOURS_END   = time(14, 30)

# Norwegian Day Names mapping
NORWEGIAN_DAYS = {
    0: "Man", 1: "Tir", 2: "Ons", 3: "Tor", 4: "Fre", 5: "Lør", 6: "Søn"
}

# --- DEPARTMENT CONFIGURATION ---
DEPARTMENTS_CONFIG = {
    "it": {
        "title": "Fraværsliste - IT",
        "gids": ["88d8f237-f90c-4862-b511-2001d7b594d0"]
    },
    "admin": {
        "title": "Fraværsliste - Admin",
        "gids": [
            "ebde949d-25d0-4f85-9649-3975202324ea", 
            "10b4976f-0027-4b0d-a34a-6be134d7d60f", 
            "5448534f-6a5a-455c-92a2-c16f8e38da24", 
            "88f7095d-4d08-4ea4-be46-fccc1d775634"  
        ]
    },
    "dart": {
        "title": "Fraværsliste - Dart",
        "gids": ["2ec6f95a-ef58-4b6c-bb0f-3ac28b50bb4c"]
    },
    "sand": {
        "title": "Fraværsliste - Sand",
        "gids": ["a830b4cd-9236-44a2-81be-7c037ca01607"]
    },
    "samba": {
        "title": "Fraværsliste - Samba",
        "gids": ["bc904b3f-5b34-4eba-a928-804118c9e967"]
    },
    "bamjo": {
        "title": "Fraværsliste - Bamjo",
        "gids": ["773eedea-6d81-4a71-b9e3-53c86b736177"]
    }
}

# Colors
COLORS = {
    'FREE': "#ffffff", 'WEEKEND': "#888888", 'TODAY': "#ffffaa",
    'VACATION': "#f37366", 'LEAVE': "#cccccc", 'BUSINESS_TRIP': "#fff79a",
    'TIME_OFF': "#6ecff6", 'OTHER': "#f49ac2", 'PRESENT': "#f4cfb4",
    'BUSY': "#8493ca", 'HOME_OFFICE': "#c0f0c0", 'ERROR': "#ff0000",
    'ELSEWHERE':"#a187be",'TENTATIVE':"#7ec699"
}

@bp.route(route="GetAbsence", auth_level=func.AuthLevel.FUNCTION)
def GetAbsence(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Processing weekly absence request.')
    current_user_email = req.headers.get("X-MS-CLIENT-PRINCIPAL-NAME", "Unknown User")
    user_info_html = f"<div style='margin-bottom:10px; font-weight:bold;'>Innlogget som: {current_user_email}</div>"

      # 1. Get Parameters
    dept_param = req.params.get('dept')
    date_param = req.params.get('date')
    code_key = req.params.get('code', '') 
    
    is_htmx = req.headers.get("HX-Request") == "true"

    # 2. Load Holidays
    common_days_off = []
    holidays_env = os.environ.get('HOLIDAYS', "")
    if holidays_env:
        common_days_off = [d.strip() for d in holidays_env.split(',') if d.strip()]

    # 3. Validate Department
    if not dept_param or dept_param.lower() not in DEPARTMENTS_CONFIG:
        valid_keys = ", ".join(DEPARTMENTS_CONFIG.keys())
        return func.HttpResponse(f"Error: Invalid 'dept'. Valg: {valid_keys}", status_code=400)

    selected_dept = DEPARTMENTS_CONFIG[dept_param.lower()]
    dept_title = selected_dept['title']
    target_gids = selected_dept['gids']

    # 4. Handle Date Logic
    norway_tz = tz.gettz(TIMEZONE_NAME)
    
    if not date_param:
        target_date = datetime.datetime.now(norway_tz).date()
    else:
        try:
            target_date = datetime.datetime.strptime(date_param, "%Y-%m-%d").date()
        except ValueError:
            target_date = datetime.datetime.now(norway_tz).date()
    
    start_of_week = target_date - timedelta(days=target_date.weekday())
    week_dates = [start_of_week + timedelta(days=i) for i in range(7)]
    prev_week = start_of_week - timedelta(days=7)
    next_week = start_of_week + timedelta(days=7)

    # 5. Auth & Graph
    rows_html = ""
    try:
        credential = DefaultAzureCredential()
        token = credential.get_token('https://graph.microsoft.com/.default').token
        rows_html = generate_real_data_rows(token, target_gids, week_dates, common_days_off)
    except Exception as e:
        logging.error(f"Graph API Error: {str(e)}")
        rows_html = f"<tr><td colspan='8' style='color:red; text-align:center;'>Systemfeil: {str(e)}</td></tr>"

    # 6. Generate Buttons (Norwegian Labels)
    controls_html = f"""
    <div style="margin-bottom: 20px; display: flex; align-items: center; gap: 15px;">
        <button style="padding: 8px 16px; cursor: pointer; background: #0078D4; color: white; border: none; border-radius: 4px;" 
            hx-get="/api/GetAbsence?code={code_key}&date={prev_week}&dept={dept_param}" 
            hx-target="#container" hx-swap="outerHTML">
           &laquo; Forrige uke
        </button>
        
        <span style="font-weight:bold; font-size: 1.1em; font-family: sans-serif;">
            Uke {start_of_week.isocalendar()[1]} ({start_of_week.isocalendar()[0]})
        </span>
        
        <button style="padding: 8px 16px; cursor: pointer; background: #0078D4; color: white; border: none; border-radius: 4px;" 
            hx-get="/api/GetAbsence?code={code_key}&date={next_week}&dept={dept_param}" 
            hx-target="#container" hx-swap="outerHTML">
           Neste uke &raquo;
        </button>
        <span class="htmx-indicator" style="color:#0078D4; font-family: sans-serif;"> Laster data...</span>
    </div>
    """

    # 7. Generate Table Headers (Norwegian Day Names)
    th_cells = ""
    today_norway = datetime.datetime.now(norway_tz).date()

    for d in week_dates:
        is_off = d.weekday() >= 5 or str(d) in common_days_off
        
        if d == today_norway:
            style = f"background:{COLORS['TODAY']}; border-bottom: 3px solid #666;"
        elif is_off:
            style = "background:#f4f4f4; color: #888;"
        else:
            style = "background:#ffffff;"
            
        day_name_no = NORWEGIAN_DAYS[d.weekday()]
        th_cells += f"<th style='{style}; min-width: 80px; padding: 10px; border: 1px solid #ccc;'>{d.day}.{d.month}<br><small>{day_name_no}</small></th>"

    table_html = f"""
    <div id="container">
        {controls_html}
        <table border="1" cellpadding="5" style="border-collapse: collapse; width: 100%; background: white; font-family: 'Segoe UI', sans-serif; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
            <thead>
                <tr>
                    <th style="text-align:left; background:#e0e0e0; min-width: 150px; padding: 10px; border: 1px solid #ccc;">Ansatt</th>
                    {th_cells}
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        <div style="margin-top:5px; color:#888; font-size:0.8em; font-family: sans-serif;">
            {user_info_html}
            Oppdatert: {datetime.datetime.now(norway_tz).strftime('%H:%M:%S')}
        </div>
    </div>
    """

    if is_htmx:
        return func.HttpResponse(table_html, mimetype="text/html")

    full_page = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{dept_title}</title>
        <script src="https://unpkg.com/htmx.org@1.9.6"></script>
        <style>
            body {{ font-family: "Arial, Helvetica, sans"; padding: 20px; background-color: #f9f9f9; }}
            .htmx-indicator {{ display:none; }}
            .htmx-request .htmx-indicator {{ display:inline; }}
            td {{ border: 1px solid #ccc; }}
        </style>
    </head>
    <body>
        <h1 style="color: #333;">{dept_title}</h1>        
    <p>Oversikten brukes også for å beregne hvor mye mat som bestilles av kantinen.</p>
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
        {table_html}
    </body>
    </html>
    """

    return func.HttpResponse(full_page, mimetype="text/html")

# --- HELPER FUNCTIONS ---

def generate_real_data_rows(token, gids_list, week_dates, holidays):
    headers = {
        'Authorization': 'Bearer ' + token, 
        'Prefer': f'outlook.timezone="{TIMEZONE_NAME}"',
        'Content-Type': 'application/json'
    }

    all_users_dict = {}
    for gid in gids_list:
        url = f"https://graph.microsoft.com/v1.0/groups/{gid}/members?$select=displayName,userPrincipalName,id&$top=999"
        while url:
            try:
                r = requests.get(url, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    for u in data.get('value', []):
                        if 'userPrincipalName' in u:
                            all_users_dict[u['userPrincipalName']] = u
                    url = data.get('@odata.nextLink')
                else: break
            except: break

    users = sorted(all_users_dict.values(), key=lambda x: x['displayName'])

    html_rows = ""
    start_dt = f"{week_dates[0]}T00:00:00"
    end_dt   = f"{week_dates[-1]}T23:59:59"

    for u in users:
        upn = u['userPrincipalName']
        sched_url = f"https://graph.microsoft.com/v1.0/users/{upn}/calendar/getSchedule"
        payload = {
            "schedules": [upn],
            "startTime": { "dateTime": start_dt, "timeZone": TIMEZONE_NAME },
            "endTime":   { "dateTime": end_dt,   "timeZone": TIMEZONE_NAME },
            "availabilityViewInterval": 1440
        }
        
        try:
            sched_res = requests.post(sched_url, json=payload, headers=headers)
            row_cells = ""
            if sched_res.status_code == 200:
                data = sched_res.json()
                events = data['value'][0]['scheduleItems']
                for day_date in week_dates:
                    color, tooltip = get_status_for_day(events, day_date, holidays)
                    row_cells += f"<td style='background-color:{color};' title='{tooltip}'></td>"
            else:
                row_cells = f"<td colspan='7'>Error</td>"
        except:
            row_cells = "<td colspan='7'>No Access</td>"

        html_rows += f"<tr><td style='font-weight:500; padding: 5px 10px;'>{u['displayName']}</td>{row_cells}</tr>"

    return html_rows

def get_status_for_day(events, target_date, holidays):
    if target_date.weekday() >= 5 or str(target_date) in holidays:
        return COLORS['WEEKEND'], "Helg/Helligdag"

    work_start = datetime.datetime.combine(target_date, WORK_HOURS_START)
    work_end = datetime.datetime.combine(target_date, WORK_HOURS_END)
    
    final_color = COLORS['FREE']
    final_text = ""

    for e in events:
        try:
            s = datetime.datetime.strptime(e['start']['dateTime'][:19], '%Y-%m-%dT%H:%M:%S')
            end = datetime.datetime.strptime(e['end']['dateTime'][:19], '%Y-%m-%dT%H:%M:%S')

            if s <= work_start and end >= work_end:
                status = e['status']
                subject = "(Privat)" if e.get('isPrivate') else e.get('subject', '').lower()
                
                if status == 'tentative': final_color = COLORS['TENTATIVE']
                elif status == 'free' and 'tilstede' in subject: final_color = COLORS['PRESENT']
                elif status == 'busy': final_color = COLORS['BUSY']
                elif status == 'oof':                                
                    if 'ferie' in subject: final_color = COLORS['VACATION']
                    elif 'permisjon' in subject: final_color = COLORS['LEAVE']
                    elif 'jobbreise' in subject: final_color = COLORS['BUSINESS_TRIP']
                    elif 'avspas' in subject: final_color = COLORS['TIME_OFF']
                    elif 'annet' in subject: final_color = COLORS['OTHER']
                    else: final_color=COLORS['OTHER']
                elif status == 'workingElsewhere':
                     if any(k in subject for k in ['hjemmekont', 'heimekont', 'home off', 'hjemme kont']):
                         final_color = COLORS['HOME_OFFICE']
                     else:   
                         final_color = COLORS['ELSEWHERE']
                final_text = subject
        except:
            continue
    return final_color, final_text