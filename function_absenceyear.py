import azure.functions as func
import logging
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
MONTH_URL_VIEW="/api/GetAbsenceMonth?code=wptSSdtJe3Lr6SAkxQ9lmyzXNxjWK64Y80gSS2v1X8RvAzFuNVQFag==&dept="

#DEVURLS
#MONTH_URL_VIEW="/api/GetAbsenceMonth?code=CynCJKFuvKV-Mbqd4jMZaHuFOuAh1qIReLNlV7-RJErzAzFu5RSW7w==&dept="


# Norwegian Month Names
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
    logging.info('Processing Yearly Absence Request.')
    
    current_user_email = req.headers.get("X-MS-CLIENT-PRINCIPAL-NAME", "Unknown User")
    user_info_html = f"<div style='margin-bottom:10px; font-weight:bold;'>Innlogget som: {current_user_email}</div>"

    # 1. Params & Date Logic
    dept_param = (req.params.get('dept') or "").lower()
    year_param = req.params.get('year')
    code_key = req.params.get('code', '') 
      
    norway_tz = tz.gettz(TIMEZONE_NAME)
    now = datetime.datetime.now(norway_tz)

    start_time = datetime.datetime.now(norway_tz) 
    start_time_str = start_time.strftime('%H:%M:%S')
    

    # year + month define the START of the 12-month window
#    year_param = req.params.get('year')
    view_month = req.params.get('month')

    viewing_year = int(year_param) if year_param and year_param.isdigit() else now.year
    viewing_month = (
        int(view_month)
        if view_month and view_month.isdigit() and 1 <= int(view_month) <= 12
        else now.month
    )

   
     # 3. Validate Department
    if not dept_param or dept_param.lower() not in DEPARTMENTS_CONFIG:
        valid_keys = ", ".join(DEPARTMENTS_CONFIG.keys())
        return func.HttpResponse(f"Error: Invalid 'dept'. Valid: {valid_keys}", status_code=400)

    #if dept_param not in DEPARTMENTS_CONFIG:
    #    return func.HttpResponse("Invalid Dept", status_code=400)
    
    selected_dept = DEPARTMENTS_CONFIG[dept_param.lower()]

    common_days_off = [d.strip() for d in os.environ.get('HOLIDAYS', "").split(',') if d.strip()]

    # 2. Auth & User Fetch
    try:
        credential = DefaultAzureCredential()
        token = credential.get_token('https://graph.microsoft.com/.default').token
        users = get_users_in_groups(token, selected_dept['gids'])
    except Exception as e:
        return func.HttpResponse(f"Auth Error: {str(e)}", status_code=500)

    # 3. Build HTML for 12 months    
    full_year_html = ""
    #For Hooliday Summary
    holiday_summary = {u['userPrincipalName'].lower(): {"name": u['displayName'], "count": 0} for u in users}
     
    current_base = date(now.year, now.month, 1)
    prev_base = date(now.year - 1, now.month, 1)
    next_base = date(now.year + 1, now.month, 1)
    
    base_date = date(viewing_year, now.month, 1)


    if base_date <= prev_base:
        base_date = prev_base
    elif base_date >= next_base:
        base_date = next_base
    else:
        base_date = current_base



    month_list = []
    for i in range(12):
        year_offset = (base_date.month - 1 + i) // 12
        month = (base_date.month - 1 + i) % 12 + 1
        year = base_date.year + year_offset
        month_list.append((year, month))


    for year, month in month_list:    # Add months dynamically
        month_date = date(year, month, 1)
        days_in_month = calendar.monthrange(year, month)[1]

        #month_date = date(viewing_year, month_idx, 1)       
        
        month_dates = [month_date + timedelta(days=i) for i in range(days_in_month)]
        
        # Monthly Table Header
        th_cells = ""
        for d in month_dates:
            is_off = d.weekday() >= 5 or str(d) in common_days_off
            style = "min-width: 25px; width: 25px; padding: 2px;"
            if d == now.date(): 
                style += f"background:{COLORS['TODAY']}; border-bottom: 3px solid #666;"
            elif is_off: 
                style += f"background:{COLORS['WEEKEND']}; color: white;"
            th_cells += f"<th style='{style}'>{d.day:02d}</th>"

        # Fetch Data for this month block
        #rows_html = generate_rows_for_range(token, users, month_dates, common_days_off)
        rows_html,month_counts = generate_rows_for_range(token, users, month_dates, common_days_off)
         # ADD THIS: Accumulate the counts
        for upn, count in month_counts.items():
            holiday_summary[upn]["count"] += count

        # Get Norwegian Month Name
        #month_label_no = f"{NORWEGIAN_MONTHS[month_idx]} {viewing_year}"
        month_label_no = f"{NORWEGIAN_MONTHS[month]} {year}"


        full_year_html += f"""
        <div style="margin-top: 15px;">
            <h3 style="color: #333; font-family: Arial; margin-bottom: 8px;">{month_label_no}</h3>
            <div style="overflow-x: auto;">
                <table class="month-table">
                    <thead>
                        <tr>
                            <th style="text-align:left; min-width: 180px; background:#e0e0e0; z-index:10; position:sticky; left:0;">Ansatt</th>
                            {th_cells}
                        </tr>
                    </thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </div>
        </div>"""

    # 4. Navigation & Legend
    # controls_html = f"""
    # <div style="margin-bottom: 15px; display: flex; align-items: center; gap: 15px;">
    #     <a href="?dept={dept_param}&code={code_key}&year={viewing_year-1}" class="nav-btn">&laquo; {viewing_year-1}</a>
    #     <span style="font-weight:bold; font-size: 1.5em; min-width: 100px; text-align:center;">{viewing_year}</span>
    #     <a href="?dept={dept_param}&code={code_key}&year={viewing_year+1}" class="nav-btn">{viewing_year+1} &raquo;</a>
    #     <a href="{MONTH_URL_VIEW}{dept_param}" class="nav-btn" style="background:#666; margin-left:20px;">Trykk her for månedsvisning</a>
    # </div>
    # """
   

    # Only allow ONE step back
    
    
    if base_date == current_base:
        # Current window: Prev -> Previous, Next -> Next
        prev_html = f'<a href="?dept={dept_param}&code={code_key}&year={prev_base.year}&month={prev_base.month}" class="nav-btn">&laquo; Forrige</a>'
        next_html = f'<a href="?dept={dept_param}&code={code_key}&year={next_base.year}&month={next_base.month}" class="nav-btn">Neste &raquo;</a>'

    elif base_date == prev_base:
        # Previous window: Prev disabled, Next -> Current
        prev_html = f'<span class="nav-btn" style="background:#ccc; cursor:not-allowed;">&laquo; Forrige</span>'
        next_html = f'<a href="?dept={dept_param}&code={code_key}&year={current_base.year}&month={current_base.month}" class="nav-btn">Neste &raquo;</a>'

    else:  # base_date == next_base
        # Next window: Prev -> Current, Next disabled
        prev_html = f'<a href="?dept={dept_param}&code={code_key}&year={current_base.year}&month={current_base.month}" class="nav-btn">&laquo; Forrige</a>'
        next_html = f'<span class="nav-btn" style="background:#ccc; cursor:not-allowed;">Neste &raquo;</span>'


    controls_html = f"""
    <div style="margin-bottom: 15px; display: flex; align-items: center; gap: 15px;">
        {prev_html}

        <span style="font-weight:bold; font-size: 1.5em; min-width: 180px; text-align:center;">
            {NORWEGIAN_MONTHS[base_date.month]} {base_date.year}
        </span>
         {next_html}
        <a href="{MONTH_URL_VIEW}{dept_param}" class="nav-btn" style="background:#666; margin-left:20px;">
            Trykk her for månedsvisning
        </a>
    </div>
    """

    legend_html = f"""
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
    """
    # ADD THIS: Create the summary table HTML
    summary_rows = ""
    for entry in sorted(holiday_summary.values(), key=lambda x: x['name']):
        summary_rows += f"<tr><td style='text-align:left; padding:5px;'>{entry['name']}</td><td style='font-weight:bold;'>{entry['count']}</td></tr>"

    summary_table_html = f"""
    <div style="margin-top: 40px; max-width: 405px;">
        <h3 style="color: #333; font-family: Arial;">Feriedager registrert i egen kalender for {viewing_year}</h3>
        <table class="month-table" style="width: 100%;">
            <thead>
                <tr style="background:#e0e0e0;">
                    <th style="text-align:left; padding:5px;">Ansatt</th>
                    <th style="width:150px;">Antall feriedager</th>
                </tr>
            </thead>
            <tbody>{summary_rows}</tbody>
        </table>
    </div>
    """

    full_page = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{selected_dept['title']} - År</title>
        <style>
            body {{ font-family: "Arial, Helvetica, sans"; padding: 10px; background-color: #f9f9f9; }}
            .month-table {{ border-collapse: collapse; background: white; font-size: 0.85em; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            .month-table th, .month-table td {{ border: 1px solid #666; text-align: center; height: 25px; }}
            .nav-btn {{ text-decoration: none; padding: 6px 12px; background: #0078D4; color: white; border-radius: 4px; font-weight: bold; font-size: 0.9em; }}
            .sticky-name {{ text-align:left; padding-left:5px; font-weight:500; position:sticky; left:0; background:white; z-index:5; border-right:2px solid #666 !important; }}
        </style>
    </head>
    <body>
        <h1 style="color: #333;">{selected_dept['title']} - Årsoversikt</h1>
        {legend_html}
        {controls_html}
        {full_year_html}              
        <div style="margin-top:20px; color:#888; font-size:0.8em;">
        {user_info_html}
        Oppdatert: {now.strftime('%H:%M:%S')}
        </div>
    </body>
    </html>
    """
    return func.HttpResponse(full_page, mimetype="text/html")
# {summary_table_html} feridedager list is removed from the view. Logic is in place.
# --- HELPER FUNCTIONS ---

def get_users_in_groups(token, gids):
    headers = {'Authorization': f'Bearer {token}'}
    users_dict = {}
    for gid in gids:
        url = f"https://graph.microsoft.com/v1.0/groups/{gid}/members?$select=displayName,userPrincipalName,id,accountEnabled&$top=999"  #accountEnabled
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            for u in r.json().get('value', []):
                #if 'userPrincipalName' in u: users_dict[u['userPrincipalName']] = u
                 if 'userPrincipalName' in u and u.get('accountEnabled') is True:
                    users_dict[u['userPrincipalName']] = u
    return sorted(users_dict.values(), key=lambda x: x['displayName'])

def generate_rows_for_range(token, users, dates, holidays):
    """
    REWRITTEN: Now performs 1 API call for all users in the month 
    instead of 1 call per user.
    """
    headers = {
        'Authorization': f'Bearer {token}', 
        'Prefer': f'outlook.timezone="{TIMEZONE_NAME}"', 
        'Content-Type': 'application/json'
    }
    
    start_dt, end_dt = f"{dates[0]}T00:00:00", f"{dates[-1]}T23:59:59"
    upns = [u['userPrincipalName'] for u in users]

    # Split users into chunks of 20 (Microsoft Graph Limit)
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
    counts = {u['userPrincipalName'].lower(): 0 for u in users}
    html_rows = ""
    for u in users:
        upn_lower = u['userPrincipalName'].lower()
        user_events = all_schedules_map.get(upn_lower, [])
        
        row_cells = ""
        for d in dates:
            color, title = get_status_for_day(user_events, d, holidays)
            row_cells += f"<td style='background-color:{color};' title='{title}'></td>"
            if color == COLORS['VACATION']:
                counts[upn_lower] += 1
            
        html_rows += f"<tr><td class='sticky-name'>{u['displayName']}</td>{row_cells}</tr>"

    # Add Total Row (Optional, simplified count based on users)
    html_rows += f"<tr><td style='font-weight:bold; text-align:right; padding-right:5px;'>Total: {len(users)}</td><td colspan='{len(dates)}'></td></tr>"

    return html_rows, counts

def get_status_for_day(events, target_date, holidays):
    if target_date.weekday() >= 5 or str(target_date) in holidays:
        return COLORS['WEEKEND'], "Helg/Helligdag"
    
    
    work_start = datetime.datetime.combine(target_date, WORK_HOURS_START)
    work_end = datetime.datetime.combine(target_date, WORK_HOURS_END)
    
    final_color, final_text = COLORS['FREE'], ""
    for e in events:
        try:
            s = datetime.datetime.strptime(e['start']['dateTime'][:19], '%Y-%m-%dT%H:%M:%S')
            end = datetime.datetime.strptime(e['end']['dateTime'][:19], '%Y-%m-%dT%H:%M:%S')
            if s <= work_start and end >= work_end:
                #status, subject = e.get('status', 'busy'), e.get('subject', '').lower()
                status, subject = e.get('status', 'busy'),"(Privat)" if e.get('isPrivate') else e.get('subject', '').lower()
                
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
                    else: final_color = COLORS['OTHER']
                elif status == 'workingElsewhere':
                    if any(k in subject for k in ['hjemmekont', 'heimekont', 'home off', 'hjemme kont']): 
                        final_color = COLORS['HOME_OFFICE']
                    else: final_color = COLORS['ELSEWHERE']
                final_text = subject
        except: continue
    return final_color, final_text
