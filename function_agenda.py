import azure.functions as func
import logging
import json
import requests
import datetime

from datetime import time, timedelta
from azure.identity import DefaultAzureCredential
from dateutil import tz

# Create a Blueprint instead of an App
bp = func.Blueprint()

# --- CONFIGURATION ---
TIMEZONE_NAME = 'Europe/Oslo'

AGENDA_CONFIG = [
    {"name": "Adm. dir.",         "gid": "10b4976f-0027-4b0d-a34a-6be134d7d60f"},
    {"name": "Research director", "gid": "5448534f-6a5a-455c-92a2-c16f8e38da24"},
    {"name": "Admin",             "gid": "ebde949d-25d0-4f85-9649-3975202324ea"},
    {"name": "IT",                "gid": "88f7095d-4d08-4ea4-be46-fccc1d775634"},
    {"name": "Bamjo",             "gid": "773eedea-6d81-4a71-b9e3-53c86b736177"},
    {"name": "Dart",              "gid": "2ec6f95a-ef58-4b6c-bb0f-3ac28b50bb4c"},
    {"name": "Sand",              "gid": "a830b4cd-9236-44a2-81be-7c037ca01607"},
    {"name": "Samba",             "gid": "bc904b3f-5b34-4eba-a928-804118c9e967"}
]

# Office 365 event status, pretty names
STATUS = {
    'oof':              'Away',
    'free':             'Free',
    'workingElsewhere': 'Working elsewhere',
    'tentative':        'Tentative',
    'busy':             'Busy',
}
COLORS = {
     'FREE': "#ffffff", 'WEEKEND': "#888888", 'TODAY': "#ffffaa",
    'VACATION': "#f37366", 'LEAVE': "#cccccc", 'BUSINESS_TRIP': "#fff79a",
    'TIME_OFF': "#6ecff6", 'OTHER': "#f49ac2", 'PRESENT': "#f4cfb4",
    'BUSY': "#8493ca", 'HOME_OFFICE': "#c0f0c0", 'ERROR': "#ff0000",
    'ELSEWHERE':"#a187be",'TENTATIVE':"#7ec699"
}
# Note: We use @bp.route, not @app.route
@bp.route(route="GetAgenda", auth_level=func.AuthLevel.FUNCTION)
def GetAgenda(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Processing Agenda Request via Blueprint.')

    output_format = req.params.get('format', 'html') 
    
    norway_tz = tz.gettz(TIMEZONE_NAME)
    now_norway = datetime.datetime.now(norway_tz)
    today_date = now_norway.date()

    agenda_results = []
    
    try:
        credential = DefaultAzureCredential()
        token = credential.get_token('https://graph.microsoft.com/.default').token
        
        for section in AGENDA_CONFIG:
            users_data = fetch_agenda_for_group(token, section['gid'], today_date)
            agenda_results.append({
                "section": section['name'],
                "users": users_data
            })

    except Exception as e:
        logging.error(f"Agenda Error: {str(e)}")
        return func.HttpResponse(f"System Error: {str(e)}", status_code=500)

    if output_format == 'json':
        return func.HttpResponse(json.dumps(agenda_results, indent=2), mimetype="application/json")

    html = generate_agenda_html(agenda_results, today_date, now_norway)
    return func.HttpResponse(html, mimetype="text/html")


# --- HELPER FUNCTIONS (Specific to Agenda) ---
"""
def fetch_agenda_for_group(token, gid, target_date):
    headers = {
        'Authorization': 'Bearer ' + token, 
        'Prefer': f'outlook.timezone="{TIMEZONE_NAME}"',
        'Content-Type': 'application/json'
    }

    # 1. Get Users
    users = []
    url = f"https://graph.microsoft.com/v1.0/groups/{gid}/members?$select=displayName,userPrincipalName,id&$top=999"
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            raw = r.json().get('value', [])
            users = [u for u in raw if 'userPrincipalName' in u]
            users.sort(key=lambda x: x['displayName'])
    except:
        return []

    # 2. Get Schedules
    start_dt = f"{target_date}T00:00:00"
    end_dt   = f"{target_date}T23:59:59"
    
    result_list = []

    for u in users:
        user_info = {"name": u['displayName'], "events": []}
        
        sched_url = f"https://graph.microsoft.com/v1.0/users/{u['userPrincipalName']}/calendar/getSchedule"
        payload = {
            "schedules": [u['userPrincipalName']],
            "startTime": { "dateTime": start_dt, "timeZone": TIMEZONE_NAME },
            "endTime":   { "dateTime": end_dt,   "timeZone": TIMEZONE_NAME },
            "availabilityViewInterval": 15
        }
        
        try:
            r = requests.post(sched_url, json=payload, headers=headers)
            if r.status_code == 200:
                data = r.json()
                items = data['value'][0]['scheduleItems']
                
                for item in items:
                    status = item['status']
                    subject = item.get('subject', '')
                    is_private = item.get('isPrivate', False)
                    if is_private: subject = "(Private)" 

                    #if status == 'free' and 'tilstede' not in subject.lower():
                    #    continue

                    start_str = item['start']['dateTime'][:19]
                    end_str = item['end']['dateTime'][:19]

                    event_start = datetime.datetime.fromisoformat(start_str)
                    event_end   = datetime.datetime.fromisoformat(end_str)

                    # Logic for Start Time Display
                    if event_start.date() != target_date:
                        start_display = f"{event_start.day:02}/{event_start.month:02}"
                    else:
                        start_display = f"{event_start.hour:02}:{event_start.minute:02}"

                    # Logic for Midnight/End Time
                    if event_end.hour == 0 and event_end.minute == 0:
                        # If it ends exactly at 00:00 today, it might be an event from yesterday ending now
                        if event_end.date() == target_date:
                            continue
                        # Subtract one day to show the "actual" end date if it's a multi-day event
                        event_end = event_end - datetime.timedelta(days=1)

                    if event_end.date() != target_date:
                        end_display = f"{event_end.day:02}/{event_end.month:02}"
                    else:
                        end_display = f"{event_end.hour:02}:{event_end.minute:02}"

                    user_info['events'].append({
                        "time": f"{start_display}-{end_display}",
                        "subject": subject,
                        "status": status
                        })
        except:
            pass
        if user_info['events']:
            result_list.append(user_info)
        
    return result_list
"""
def fetch_agenda_for_group(token, gid, target_date):
    headers = {
        'Authorization': 'Bearer ' + token, 
        'Prefer': f'outlook.timezone="{TIMEZONE_NAME}"',
        'Content-Type': 'application/json'
    }

    # 1. Get Members of the group
    users = []
    url = f"https://graph.microsoft.com/v1.0/groups/{gid}/members?$select=displayName,userPrincipalName,id,accountEnabled&$top=999"
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            raw = r.json().get('value', [])
            # Map UPN to DisplayName for easy lookup later
            #user_map = {u['userPrincipalName'].lower(): u['displayName'] for u in raw if 'userPrincipalName' in u}
            # Map UPN to DisplayName, filtering for users who have a UPN AND are enabled
            user_map = {
                u['userPrincipalName'].lower(): u['displayName'] 
                for u in raw 
                if 'userPrincipalName' in u and u.get('accountEnabled') is True
            }
            upns = list(user_map.keys())
        else:
            return []
    except Exception as e:
        logging.error(f"Error fetching group members: {e}")
        return []

    # 2. Prepare for Chunked Fetching
    start_dt = f"{target_date}T00:00:00"
    end_dt   = f"{target_date}T23:59:59"
    result_list = []
    
    # Split UPNs into chunks of 20
    chunks = [upns[i:i + 20] for i in range(0, len(upns), 20)]

    # 3. Fetch Schedules in Bulk
    for chunk in chunks:
        # We use the first user's endpoint for the bulk request
        sched_url = f"https://graph.microsoft.com/v1.0/users/{chunk[0]}/calendar/getSchedule"
        payload = {
            "schedules": chunk,
            "startTime": { "dateTime": start_dt, "timeZone": TIMEZONE_NAME },
            "endTime":   { "dateTime": end_dt,   "timeZone": TIMEZONE_NAME },
            "availabilityViewInterval": 15 # High granularity for agenda view
        }
        
        try:
            r = requests.post(sched_url, json=payload, headers=headers)
            if r.status_code == 200:
                schedules = r.json().get('value', [])
                
                for user_sched in schedules:
                    upn = user_sched.get('scheduleId', '').lower()
                    items = user_sched.get('scheduleItems', [])
                    
                    if not items:
                        continue
                        
                    user_info = {"name": user_map.get(upn, upn), "events": []}
                    
                    for item in items:
                        status = item.get('status')
                        subject = item.get('subject', '')
                        if item.get('isPrivate'): 
                            subject = "(Privat)"

                        start_str = item['start']['dateTime'][:19]
                        end_str = item['end']['dateTime'][:19]

                        event_start = datetime.datetime.fromisoformat(start_str)
                        event_end   = datetime.datetime.fromisoformat(end_str)

                        # --- Original logic for Start Time Display ---
                        if event_start.date() != target_date:
                            start_display = f"{event_start.day:02}/{event_start.month:02}"
                        else:
                            start_display = f"{event_start.hour:02}:{event_start.minute:02}"

                        # --- Original logic for Midnight/End Time ---
                        if event_end.hour == 0 and event_end.minute == 0:
                            if event_end.date() == target_date:
                                continue
                            # Multi-day adjustment
                            temp_end = event_end - datetime.timedelta(seconds=1)
                            end_display = f"{temp_end.day:02}/{temp_end.month:02}"
                        elif event_end.date() != target_date:
                            end_display = f"{event_end.day:02}/{event_end.month:02}"
                        else:
                            end_display = f"{event_end.hour:02}:{event_end.minute:02}"

                        user_info['events'].append({
                            "time": f"{start_display}-{end_display}",
                            "subject": subject,
                            "status": status
                        })
                    
                    if user_info['events']:
                        result_list.append(user_info)
        except Exception as e:
            logging.error(f"Error processing chunk: {e}")
            continue
            
    # Sort results by name before returning
    result_list.sort(key=lambda x: x['name'])
    return result_list

def generate_agenda_html(data, today_date, now_obj):
    full_html = ""
    for group in data:
        rows = ""
        for u in group['users']:
            events_html = ""
            if not u['events']:
                events_html = "<span style='color:#ccc; font-style:italic;'>Available</span>"
            else:
                for e in u['events']:
                   # bg = "#eee"
                    final_color = COLORS['OTHER']                    
                    status = e['status']
                    subject_lower = e['subject'].lower()

                    # -- CORRECTED LOGIC BLOCK --
                    if status == 'tentative': 
                        final_color = COLORS['TENTATIVE']

                    elif status == 'free':
                        if 'tilstede' in subject_lower: 
                            final_color = COLORS['PRESENT']
                        else:
                            final_color = COLORS['FREE']

                    elif status == 'busy': 
                        final_color = COLORS['BUSY']

                    elif status == 'oof':                                
                        if 'ferie' in subject_lower: final_color = COLORS['VACATION']
                        elif 'permisjon' in subject_lower: final_color = COLORS['LEAVE']
                        elif 'jobbreise' in subject_lower: final_color = COLORS['BUSINESS_TRIP']
                        elif 'avspas' in subject_lower: final_color = COLORS['TIME_OFF']
                        elif 'annet' in subject_lower: final_color = COLORS['OTHER']
                        else: final_color = COLORS['OTHER']

                    # working elsewhere
                    elif status == 'workingElsewhere':
                        # Check for variations of home office
                        if any(x in subject_lower for x in ['hjemmekont', 'heimekont', 'home off', 'hjemme kont']):
                            final_color = COLORS['HOME_OFFICE']
                        else:   
                            final_color = COLORS['ELSEWHERE']
                    status_text = STATUS.get(status, status).title()
                    events_html += f"""
                    <div style="font-size:0.9em; margin-bottom:2px;">
                        <span style=" font-family: Arial, Helvetica, sans; background:{final_color}; padding:1px 4px; border-radius:3px;">{e['time']}</span> 
                        {e['subject']} &mdash; <em>({status_text})</em> 
                    </div>"""
            
            rows += f"""
            <tr style="border-bottom:1px solid #f0f0f0;">
                <td style="padding:6px; width:30%; vertical-align:top; font-weight:500;">{u['name']}</td>
                <td style="padding:6px; vertical-align:top;">{events_html}</td>
            </tr>"""
            
        full_html += f"""
        <div style="margin-bottom: 20px; background:white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-radius:4px; overflow:hidden;">
            <div style="background:#0078D4; color:white; padding:10px; font-weight:bold;">{group['section']}</div>
            <table style="width:100%; border-collapse:collapse;">{rows}</table>
        </div>"""

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Agenda {today_date}</title>
        <meta charset="utf-8">
        <style>
            body {{  font-family: Arial, Helvetica, sans; background-color: #f4f4f4; padding: 20px; max-width: 900px; margin: 0 auto; }}
            h1 {{ color: #333; text-align:center; }}
            .footer {{ text-align:center; color:#666; font-size:0.8em; margin-top:20px; }}
        </style>
    </head>
    <body>    
        {full_html}
        <div class="footer">Updated: {now_obj.strftime('%H:%M')}</div>
    </body>
    </html>
    """

def generate_agenda_html01(data, today_date, now_obj):
    full_html = ""
    for group in data:
        rows = ""
        for u in group['users']:
            events_html = ""
            if not u['events']:
                events_html = "<span style='color:#ccc; font-style:italic;'>Available</span>"
            else:
                for e in u['events']:
                    # Default color
                    final_color = COLORS['OTHER']
                    
                    status = e['status']
                    subject_lower = e['subject'].lower()

                    # -- CORRECTED LOGIC BLOCK --
                    if status == 'tentative': 
                        final_color = COLORS['TENTATIVE']

                    elif status == 'free':
                        if 'tilstede' in subject_lower: 
                            final_color = COLORS['PRESENT']
                        else:
                            final_color = COLORS['FREE']

                    elif status == 'busy': 
                        final_color = COLORS['BUSY']

                    elif status == 'oof':                                
                        if 'ferie' in subject_lower: final_color = COLORS['VACATION']
                        elif 'permisjon' in subject_lower: final_color = COLORS['LEAVE']
                        elif 'jobbreise' in subject_lower: final_color = COLORS['BUSINESS_TRIP']
                        elif 'avspas' in subject_lower: final_color = COLORS['TIME_OFF']
                        elif 'annet' in subject_lower: final_color = COLORS['OTHER']
                        else: final_color = COLORS['OTHER']

                    # working elsewhere
                    elif status == 'workingElsewhere':
                        # Check for variations of home office
                        if any(x in subject_lower for x in ['hjemmekont', 'heimekont', 'home off', 'hjemme kont']):
                            final_color = COLORS['HOME_OFFICE']
                        else:   
                            final_color = COLORS['ELSEWHERE']
                    
                    bg = final_color
                    
                    status_text = STATUS.get(status, status).title()

                events_html += f"""
                    <div style="font-size:0.9em; margin-bottom:2px;">
                        <span style=" font-family: Arial, Helvetica, sans; background:{bg}; padding:1px 4px; border-radius:3px;">{e['time']}</span> 
                        {e['subject']}
                    </div>"""
            
            rows += f"""
            <tr style="border-bottom:1px solid #f0f0f0;">
                <td style="padding:6px; width:30%; vertical-align:top; font-weight:500;">{u['name']}</td>
                <td style="padding:6px; vertical-align:top;">{events_html}</td>
            </tr>"""
            
        full_html += f"""
        <div style="margin-bottom: 20px; background:white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-radius:4px; overflow:hidden;">
            <div style="background:#0078D4; color:white; padding:10px; font-weight:bold;">{group['section']}</div>
            <table style="width:100%; border-collapse:collapse;">{rows}</table>
        </div>"""

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Agenda {today_date}</title>
        <meta charset="utf-8">
        <style>
            body {{ font-family: Arial, Helvetica, sans; background-color: #f4f4f4; padding: 20px; max-width: 900px; margin: 0 auto; }}
            h1 {{ color: #333; text-align:center; }}
            .footer {{ text-align:center; color:#666; font-size:0.8em; margin-top:20px; }}
        </style>
    </head>
    <body>    
        {full_html}
        <div class="footer">Updated: {now_obj.strftime('%H:%M')}</div>
    </body>
    </html>
    """