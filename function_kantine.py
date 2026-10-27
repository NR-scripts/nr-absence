import azure.functions as func
import logging
import json
import requests
import datetime
import os
from datetime import timedelta, time
from azure.identity import DefaultAzureCredential
from dateutil import tz

bp = func.Blueprint()

# --- CONFIGURATION ---
TIMEZONE_NAME = 'Europe/Oslo'
LUNCH_START = time(11, 30)
LUNCH_END   = time(13, 0)
DAYS_TO_FORECAST = 31 

# Users to ALWAYS ignore
IGNORE_USERS = [
    "erik@nr.no",
    "karlas@nr.no"
]

# Group IDs (Combined list)
KANTINE_GROUPS = [
    "10b4976f-0027-4b0d-a34a-6be134d7d60f", # CEO 
    "ebde949d-25d0-4f85-9649-3975202324ea", # Admin 
    #"5448534f-6a5a-455c-92a2-c16f8e38da24", # Admin
    "88d8f237-f90c-4862-b511-2001d7b594d0",  #Admin IT
    "88f7095d-4d08-4ea4-be46-fccc1d775634", # Admin 
    "773eedea-6d81-4a71-b9e3-53c86b736177", # Bamjo 
    "2ec6f95a-ef58-4b6c-bb0f-3ac28b50bb4c", # Dart 
    "a830b4cd-9236-44a2-81be-7c037ca01607", # Sand 
    "bc904b3f-5b34-4eba-a928-804118c9e967"  # Samba 

]

COMMON_DAYS_OFF_FILE = 'felles_fridager.txt'

@bp.route(route="GetKantine", auth_level=func.AuthLevel.FUNCTION)
def GetKantine(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Processing Kantine Request.')

    norway_tz = tz.gettz(TIMEZONE_NAME)
    now_norway = datetime.datetime.now(norway_tz)
    today = now_norway.date()
    
    # Load Holidays
    common_days_off = []
    holidays_env = os.environ.get('HOLIDAYS', "")

    if holidays_env:
            common_days_off = [d.strip() for d in holidays_env.split(',') if d.strip()]


#    try:
 #       file_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), COMMON_DAYS_OFF_FILE)
  #      if os.path.exists(file_path):
  #          with open(file_path, 'r') as f:
  #              common_days_off = f.read().strip().split()
  #  except:
#        pass

    try:
        credential = DefaultAzureCredential()
        token = credential.get_token('https://graph.microsoft.com/.default').token
        
        # 1. Get All Unique Users
        users = get_all_users(token, KANTINE_GROUPS)
        
        if not users:
             return func.HttpResponse("Error: No users found. Check Group IDs.", status_code=500)

        # 2. Calculate Counts
        forecast = calculate_forecast(token, users, today, common_days_off)
        
        # 3. Generate HTML with Colors
        html = generate_kantine_html(forecast, now_norway)
        
        return func.HttpResponse(html, mimetype="text/html")

    except Exception as e:
        logging.error(f"Kantine Error: {str(e)}")
        return func.HttpResponse(f"System Error: {str(e)}", status_code=500)


# --- HELPER FUNCTIONS ---

def get_all_users(token, gids):
    headers = {'Authorization': 'Bearer ' + token}
    users_dict = {}

    for gid in gids:
        if len(gid) < 10: continue

        url = f"https://graph.microsoft.com/v1.0/groups/{gid}/members?$select=displayName,userPrincipalName,id,accountEnabled&$top=999"
        while url:
            try:
                r = requests.get(url, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    for u in data.get('value', []):
                        upn = u.get('userPrincipalName', '').lower()
                        #if upn and upn not in IGNORE_USERS and '@' in upn:
                        if upn and upn not in IGNORE_USERS and '@' in upn and u.get('accountEnabled') is True:
                            users_dict[upn] = u
                    url = data.get('@odata.nextLink')
                else:
                    break
            except:
                break
    return list(users_dict.values())

def calculate_forecast(token, users, start_date, holidays):
    """OPTIMERT: Henter 20 brukere av gangen."""
    headers = {
        'Authorization': 'Bearer ' + token, 
        'Prefer': f'outlook.timezone="{TIMEZONE_NAME}"',
        'Content-Type': 'application/json'
    }

    forecast_map = {}
    for i in range(DAYS_TO_FORECAST):
        d = start_date + timedelta(days=i)
        is_off = (d.weekday() >= 5 or str(d) in holidays)
        forecast_map[d] = {"date": d, "count": 0, "is_off": is_off}

    # API-et krever tekststrenger (ISO format)
    start_dt_str = f"{start_date}T00:00:00"
    end_date_obj = start_date + timedelta(days=DAYS_TO_FORECAST)
    end_dt_str   = f"{end_date_obj}T23:59:59"

    upns = [u['userPrincipalName'] for u in users]
    chunks = [upns[i:i + 20] for i in range(0, len(upns), 20)]
    
    for chunk in chunks:
        payload = {
            "schedules": chunk, 
            "startTime": {"dateTime": start_dt_str, "timeZone": TIMEZONE_NAME}, 
            "endTime": {"dateTime": end_dt_str, "timeZone": TIMEZONE_NAME}, 
            "availabilityViewInterval": 60 # Viktig for lunsj-sjekk
        }
        
        url = f"https://graph.microsoft.com/v1.0/users/{chunk[0]}/calendar/getSchedule"
        try:
            res = requests.post(url, json=payload, headers=headers)
            if res.status_code == 200:
                data_list = res.json().get('value', [])
                for user_result in data_list:
                    events = user_result.get('scheduleItems', [])
                    # Sjekk hver dag for denne brukeren
                    for day_date, day_data in forecast_map.items():
                        if day_data["is_off"]: continue
                        if is_present_for_lunch(events, day_date):
                            day_data["count"] += 1
            else:
                logging.error(f"Graph API Error: {res.text}")
        except Exception as e:
            logging.error(f"Chunk error: {e}")
            continue

    return sorted(forecast_map.values(), key=lambda x: x['date'])
"""
def calculate_forecast(token, users, start_date, holidays):
    headers = {
        'Authorization': 'Bearer ' + token, 
        'Prefer': f'outlook.timezone="{TIMEZONE_NAME}"',
        'Content-Type': 'application/json'
    }

    forecast_map = {}
    for i in range(DAYS_TO_FORECAST):
        d = start_date + timedelta(days=i)
        is_off = False
        if d.weekday() >= 5 or str(d) in holidays:
            is_off = True
        forecast_map[d] = {"date": d, "count": 0, "is_off": is_off}

    start_dt_str = f"{start_date}T00:00:00"
    end_date = start_date + timedelta(days=DAYS_TO_FORECAST)
    end_dt_str   = f"{end_date}T23:59:59"

    for u in users:
        upn = u['userPrincipalName']
        payload = {
            "schedules": [upn],
            "startTime": { "dateTime": start_dt_str, "timeZone": TIMEZONE_NAME },
            "endTime":   { "dateTime": end_dt_str,   "timeZone": TIMEZONE_NAME },
            "availabilityViewInterval": 60 
        }

        try:
            url = f"https://graph.microsoft.com/v1.0/users/{upn}/calendar/getSchedule"
            r = requests.post(url, json=payload, headers=headers)
            
            if r.status_code == 200:
                data = r.json().get('value', [])
                if data:
                    events = data[0].get('scheduleItems', [])
                    for day_date, day_data in forecast_map.items():
                        if day_data["is_off"]: continue
                        if is_present_for_lunch(events, day_date):
                            day_data["count"] += 1
        except Exception:
            continue

    return list(forecast_map.values())
"""
def is_present_for_lunch(events, target_date):
    lunch_start = datetime.datetime.combine(target_date, LUNCH_START)
    lunch_end   = datetime.datetime.combine(target_date, LUNCH_END)
    
    for e in events:
        try:
            s = datetime.datetime.strptime(e['start']['dateTime'][:19], '%Y-%m-%dT%H:%M:%S')
            e_end = datetime.datetime.strptime(e['end']['dateTime'][:19], '%Y-%m-%dT%H:%M:%S')
            
            if s <= lunch_start and e_end >= lunch_end:
                status = e['status']
                subject = e.get('subject', '').lower()
                
                if 'tilstede' in subject or 'til stede' in subject: return True
                #if status in ['oof', 'workingElsewhere', 'busy']: return False
                if status in ['oof', 'workingElsewhere']: return False
        except:
            continue
    return True

def generate_kantine_html(forecast, now_obj):
    rows = ""
    today_date = now_obj.date()
    
    norwegian_days = {
        0: "Mandag", 1: "Tirsdag", 2: "Onsdag", 3: "Torsdag", 4: "Fredag", 5: "Lørdag", 6: "Søndag"
    }
    norwegian_months = {
        1: "januar", 2: "februar", 3: "mars", 4: "april", 5: "mai", 6: "juni",
        7: "juli", 8: "august", 9: "september", 10: "oktober", 11: "november", 12: "desember"
    }
    
    for f in forecast:
        day_name = norwegian_days[f['date'].weekday()]
        month_name = norwegian_months[f['date'].month]
        date_str = f"{day_name} {f['date'].day}. {month_name}"
        
        val = str(f['count'])
        
        # --- COLOR LOGIC ---
        bg_color = "white" # Default
        
        if f['date'] == today_date:
            bg_color = "#c0f0c0" # Green for Today
        elif f['is_off']:
            bg_color = "#f0c0f0" # Pink for Weekends/Holidays
            val = "" # No count shown for weekends
            
        rows += f"""
        <tr style="background-color: {bg_color}; border-bottom: 1px solid #ccc;">
            <td style="padding: 6px 15px; border-right: 1px solid #ccc;">{date_str}</td>
            <td style="padding: 6px 15px; font-weight:bold;">{val}</td>
        </tr>
        """

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Kantinetelling</title>
        <meta charset="utf-8">
        <style>
            body {{  font-family: Arial, Helvetica, sans;padding: 20px; max-width: 500px; margin: 0 auto; background: #fff; }}
            h2 {{ margin-bottom: 5px; font-size: 1.2em; }}
            .timestamp {{ color: #666; font-size: 0.8em; margin-bottom: 15px; }}
            table {{ border-collapse: collapse; width: 100%; border: 1px solid #999; }}
            td {{ color: #000; }}
        </style>
    </head>
    <body>
        <h2>Kantinetelling - Alle avdelinger</h2>
        <div class="timestamp">Oppdateres live. Sist oppdatert: {now_obj.strftime('%d. %b kl %H:%M')}</div>
        
        <p style="font-size: 0.85em; margin-bottom: 10px;">
            De som telles med er ikke opptatt i perioden 11:30 - 13:00 med en sammenhengende event.
        </p>
        
        <table>
            {rows}
        </table>
    </body>
    </html>
    """