import azure.functions as func
import logging
import json
import requests
import datetime
import os
import calendar
from datetime import timedelta, date, time
from azure.identity import DefaultAzureCredential
from dateutil import tz 

bp = func.Blueprint()

# --- CONFIGURATION ---
TIMEZONE_NAME = 'Europe/Oslo'
WORK_HOURS_START = time(9, 30)
WORK_HOURS_END   = time(14, 30)

#PROD URLS
YEAR_URL_VIEW="/api/GetAbsenceYear?code=luvGjmeF0DAb3GsTD7x7z61dm6DgzD2eaGHedIB1l7u6AzFu6ezBuA==&dept="
#DEVURLS
#YEAR_URL_VIEW="/api/GetAbsenceYear?code=6kOrJcabiv7MypuJm4qkLZNNOKfhD86ShvSAb-rO_g5YAzFu2T9d3Q==&dept="


# Norwegian Translations
NORWEGIAN_MONTHS = {
    1: "Januar", 2: "Februar", 3: "Mars", 4: "April", 5: "Mai", 6: "Juni",
    7: "Juli", 8: "August", 9: "September", 10: "Oktober", 11: "November", 12: "Desember"
}

NORWEGIAN_MONTHS_SHORT = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mai", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Des"
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

# Colors matching your image
COLORS = {
     'FREE': "#ffffff", 'WEEKEND': "#888888", 'TODAY': "#ffffaa",
    'VACATION': "#f37366", 'LEAVE': "#cccccc", 'BUSINESS_TRIP': "#fff79a",
    'TIME_OFF': "#6ecff6", 'OTHER': "#f49ac2", 'PRESENT': "#f4cfb4",
    'BUSY': "#8493ca", 'HOME_OFFICE': "#c0f0c0", 'ERROR': "#ff0000",
    'ELSEWHERE':"#a187be",'TENTATIVE':"#7ec699"
}

@bp.route(route="GetAbsenceMonth", auth_level=func.AuthLevel.FUNCTION)
def GetAbsenceMonth(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Processing Monthly Absence Request.')

    current_user_email = req.headers.get("X-MS-CLIENT-PRINCIPAL-NAME", "Unknown User")
    user_info_html = f"<div style='margin-bottom:10px; font-weight:bold;'>Innlogget som: {current_user_email}</div>"

    # 1. Get Parameters
    dept_param = req.params.get('dept').lower()
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
        return func.HttpResponse(f"Error: Invalid 'dept'. Valid: {valid_keys}", status_code=400)

    selected_dept = DEPARTMENTS_CONFIG[dept_param.lower()]

    # 4. Handle MONTHLY Date Logic
    norway_tz = tz.gettz(TIMEZONE_NAME)
    start_time = datetime.datetime.now(norway_tz) 
    start_time_str = start_time.strftime('%H:%M:%S')
    
    if not date_param:
        now = datetime.datetime.now(norway_tz).date()
        target_date = date(now.year, now.month, 1)
    else:
        try:
            d = datetime.datetime.strptime(date_param, "%Y-%m-%d").date()
            target_date = date(d.year, d.month, 1)
        except ValueError:
            target_date = datetime.datetime.now(norway_tz).date().replace(day=1)
    
    days_in_month_count = calendar.monthrange(target_date.year, target_date.month)[1]
    month_dates = [target_date + timedelta(days=i) for i in range(days_in_month_count)]
    
    # Calculate Prev/Next Month
    prev_month_end = target_date - timedelta(days=1)
    prev_month_start = date(prev_month_end.year, prev_month_end.month, 1)
    next_month_start = target_date + timedelta(days=days_in_month_count)

    # 5. Auth & Graph
    rows_html = ""
    try:
        credential = DefaultAzureCredential()
        token = credential.get_token('https://graph.microsoft.com/.default').token
        rows_html = generate_monthly_rows(token, selected_dept['gids'], month_dates, common_days_off)
    except Exception as e:
        logging.error(f"Graph API Error: {str(e)}")
        rows_html = f"<tr><td colspan='32'>System Error: {str(e)}</td></tr>"
    
        

    # 6. Generate Buttons and Title using Norwegian Names
    month_display_name = f"{NORWEGIAN_MONTHS[target_date.month]} {target_date.year}"
    prev_month_btn_label = NORWEGIAN_MONTHS_SHORT[prev_month_start.month]
    next_month_btn_label = NORWEGIAN_MONTHS_SHORT[next_month_start.month]
    
    controls_html = f"""
    <div style="margin-bottom: 10px; display: flex; align-items: center; gap: 15px;">
        <button class="nav-btn" 
            hx-get="/api/GetAbsenceMonth?code={code_key}&date={prev_month_start}&dept={dept_param}" 
            hx-target="#container" hx-swap="outerHTML">
           &laquo; {prev_month_btn_label}
        </button>
        
        <span style="font-weight:bold; font-size: 1.2em; min-width: 150px; text-align:center;">
            {month_display_name}
        </span>
        
        <button class="nav-btn" 
            hx-get="/api/GetAbsenceMonth?code={code_key}&date={next_month_start}&dept={dept_param}" 
            hx-target="#container" hx-swap="outerHTML">
           {next_month_btn_label} &raquo;
        </button>
       
        <a href="{YEAR_URL_VIEW}{dept_param}" class="nav-btn" style="background:#666; margin-left:20px;text-decoration:none">Trykk her for årsvisning</a>
        <span class="htmx-indicator" style="color:#0078D4;"> Laster...</span>
    </div>
    """
    #""" <span style="font-weight:bold !important"> (tar lengre tid å generere) </span>"""
    # 7. Generate Table Headers
    th_cells = ""
    today_norway = datetime.datetime.now(norway_tz).date()

    for d in month_dates:
        is_off = d.weekday() >= 5 or str(d) in common_days_off
        style = "min-width: 25px; width: 25px; padding: 2px;"
        
        if d == today_norway:
            style += f"background:{COLORS['TODAY']}; border-bottom: 3px solid #666;"
        elif is_off:
            style += f"background:{COLORS['WEEKEND']}; color: white;"
        else:
            style += "background:#ffffff;"
            
        th_cells += f"<th style='{style}'>{d.day:02d}</th>"

    table_html = f"""
    <div id="container">
        {controls_html}
        <div style="overflow-x: auto;">
            <table class="month-table">
                <thead>
                    <tr>
                        <th style="text-align:left; min-width: 180px; background:#e0e0e0; z-index:10; position:sticky; left:0;">
                            {selected_dept['title'].replace('Fraværsliste - ', '')}
                        </th>
                        {th_cells}
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
        <div style="margin-top:5px; color:#888; font-size:0.8em;">
            {user_info_html}
            Oppdatert: {datetime.datetime.now(norway_tz).strftime('%H:%M:%S')}
        </div>
    </div>
    """
    # --- Generate Footer Row (Total + Day Numbers) ---
        
    if is_htmx:
        return func.HttpResponse(table_html, mimetype="text/html")

    full_page = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{selected_dept['title']}</title>
        <script src="https://unpkg.com/htmx.org@1.9.6"></script>
        <style>
            body {{ font-family: "Arial, Helvetica, sans"; padding: 10px; background-color: #f9f9f9; }}
            .htmx-indicator {{ display:none; }}
            .htmx-request .htmx-indicator {{ display:inline; }}
            .month-table {{ border-collapse: collapse; background: white; font-size: 0.85em; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .month-table th, .month-table td {{ border: 1px solid #666; text-align: center; height: 25px; }}
            .nav-btn {{ padding: 6px 12px; cursor: pointer; background: #0078D4; color: white; border: none; border-radius: 4px; }}
        </style>
    </head>
    <body>
        <h1 style="color: #333;">{selected_dept['title']}</h1>
        <div style="margin-top:20px; color:#30183A; font-size:0.9em;font-weight:bold">Denne oversikten ble generert når du lastet inn siden  {start_time_str} . Det tok faktisk {(datetime.datetime.now(norway_tz) - start_time).total_seconds():.2f} sekunder å generere denne.</div>
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
        {table_html}
    </body>
    </html>
    """
    return func.HttpResponse(full_page, mimetype="text/html")

# --- HELPER FUNCTIONS ---

def generate_monthly_rows(token, gids_list, month_dates, holidays):
    headers = {
        'Authorization': 'Bearer ' + token, 
        'Prefer': f'outlook.timezone="{TIMEZONE_NAME}"',
        'Content-Type': 'application/json'
    }

    all_users_dict = {}
    for gid in gids_list:
        url = f"https://graph.microsoft.com/v1.0/groups/{gid}/members?$select=displayName,userPrincipalName,id,accountEnabled&$top=999"
        while url:
            try:
                r = requests.get(url, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    for u in data.get('value', []):
                        #if 'userPrincipalName' in u:
                        if 'userPrincipalName' in u and u.get('accountEnabled') is True:
                            all_users_dict[u['userPrincipalName']] = u
                    url = data.get('@odata.nextLink')
                else: break
            except: break

    users = sorted(all_users_dict.values(), key=lambda x: x['displayName'])
    
    start_dt = f"{month_dates[0]}T00:00:00"
    end_dt   = f"{month_dates[-1]}T23:59:59"

    upns = [u['userPrincipalName'] for u in users]
    
    #chunks = [upns[i:i + 20] for i in range(0, len(upns), 20)]
    if len(upns) <= 10:
        chunk_size = 4  # Small chunks for small groups (High accuracy)
    else:
    # Use 20 for efficiency in large groups,     
        chunk_size = 20 if len(upns) >= 20 else len(upns)

    chunks = [upns[i:i + chunk_size] for i in range(0, len(upns), chunk_size)]
    
    # Store all schedules in a dictionary { upn: [events] }
    all_schedules_map = {}
    
    for chunk in chunks:
        payload = {
            "schedules": chunk, 
            "startTime": {"dateTime": start_dt, "timeZone": TIMEZONE_NAME}, 
            "endTime": {"dateTime": end_dt, "timeZone": TIMEZONE_NAME}, 
            "availabilityViewInterval": 1440
        }
        # We use the first user in the chunk to access the shared getSchedule endpoint
        url = f"https://graph.microsoft.com/v1.0/users/{chunk[0]}/calendar/getSchedule"
        try:
            res = requests.post(url, json=payload, headers=headers)
            if res.status_code == 200:
                results = res.json().get('value', [])
                for item in results:
                    all_schedules_map[item['scheduleId'].lower()] = item.get('scheduleItems', [])
        except Exception as e:
            logging.error(f"Error fetching bulk schedule: {e}")

    # Now build the HTML rows using the pre-fetched data
    html_rows = ""
    for u in users:
        upn_lower = u['userPrincipalName'].lower()
        user_events = all_schedules_map.get(upn_lower, [])        
        row_cells = ""
        for day_date in month_dates:
            color, tooltip = get_status_for_day(user_events, day_date, holidays)
            row_cells += f"<td style='background-color:{color};' title='{tooltip}'></td>"
            
        html_rows += f"<tr><td class='sticky-name'>{u['displayName']}</td>{row_cells}</tr>"
   
     # Add Total Row (Optional, simplified count based on users)
    html_rows += f"<tr><td style='font-weight:bold; text-align:right; padding-right:5px;'>Total: {len(users)}</td><td colspan='{len(month_dates)}'></td></tr>"

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
                logging.info(f"user event status & subject: {status} {subject}")
                if status == 'tentative': final_color = COLORS['TENTATIVE']
                elif status == 'free':
                    if 'tilstede' in subject: final_color = COLORS['PRESENT']
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