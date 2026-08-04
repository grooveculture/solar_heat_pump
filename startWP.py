#!/usr/bin/python3
import requests
import json
import logging
import fcntl
import os
import sys  
import time
import config
from datetime import datetime, timedelta

min_temp = 50
# FALLBACK ONLY. The live threshold is computed at runtime by
# compute_adaptive_prod_level() (see below, ~0.78 x recent daily peak). This 1300
# is used only if the PV query returns no data. Do not "fix" it here - tune
# PEAK_FACTOR / PEAK_WINDOW_DAYS instead.
solar_prod_level = 1300
actual_use_limit = 850
red_for_bad_weather = 1000

def is_winter():
    current_month = datetime.now().month
    return current_month in [11, 12, 1, 2]  # November, December, January, February

# Check if it's winter and adjust parameters
if is_winter():
    min_temp = 50  # Set minimum temperature for winter
    solar_prod_level = 1000  # winter fallback only (see note above; runtime value is adaptive)
    red_for_bad_weather = 750  # Set reduction for bad weather in winter

def instance_already_running():
    lock_file_pointer = os.open(f"/tmp/startWP.lock", os.O_WRONLY | os.O_CREAT)
    try:
        fcntl.lockf(lock_file_pointer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        already_running = False
    except IOError:
        already_running = True
    return already_running

if instance_already_running():
    print('Process already running')
    sys.exit(0)

start_time = time.time()

logging.basicConfig(filename='/home/dan/Documents/programming/IoT/dsnj-homie/controlWP.log', format='%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S', level=logging.INFO)

DB_NAME = ''
DB_USER = ''
DB_PASS = ''

# Read configuration
try:
    from config import *
except ImportError:
    pass

try:
    import mysql.connector
    print("mysql.connector importiert, version:", getattr(mysql.connector, "__version__", "unbekannt"))
except Exception as e:
    import traceback, sys
    print("Fehler beim Import von mysql.connector:", e)
    traceback.print_exc()
    sys.exit(1)

connection = mysql.connector.connect(host='localhost', database=DB_NAME, user=DB_USER, password=DB_PASS, auth_plugin='mysql_native_password')

#check weahter conditions 
#if weather is not good later today but 

def fetchShelly(description):
    cursor = connection.cursor(prepared=True)
    cursor.execute('SELECT id FROM shelly_cfg WHERE description = ?;', (description,))
    row = cursor.fetchone()
    cursor.close()
    return requests.get('http://192.168.137.'+str(row[0])+'/status', timeout=10)

def fetchTemp():
    cursor = connection.cursor(prepared=True)
    cursor.execute('SELECT temp_speicher FROM temp_speicher ORDER BY createdAt DESC LIMIT 1;')
    row = cursor.fetchone()
    print(row[0])
    cursor.close()
    return int(row[0])

def calcTotal(state, field):
    total  = state['emeters'][0][field]
    total += state['emeters'][1][field]
    total += state['emeters'][2][field]
    total = float("{0:.2f}".format(total))
    print(total)
    return total

def fetchWeather():
    cursor = connection.cursor(prepared=True)

    # Get the current time and 15:00 on the current or next day
    current_time = datetime.now()
    if current_time.hour < 15:
        start_time = current_time
        end_time = current_time.replace(hour=15, minute=0, second=0, microsecond=0)
    else:
        start_time = (current_time + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        end_time = (current_time + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)

    # Calculate the average value of the clouds_all column from the start time until the end time
    query = f"SELECT AVG(clouds_all) FROM weather_data WHERE dt_txt >= '{start_time}' AND dt_txt <= '{end_time}'"
    cursor.execute(query)
    result = cursor.fetchone()
    if result:
        avg_clouds_all = result[0]
        avg_clouds_all = float(avg_clouds_all)
        print(f"The average value of clouds_all from {start_time} until {end_time} is {avg_clouds_all}.")

    # Get the current value of clouds_all
    query = "SELECT clouds_all FROM weather_data ORDER BY dt DESC LIMIT 1"
    cursor.execute(query)
    result = cursor.fetchone()
    if result:
        current_clouds_all = result[0]
        current_clouds_all = float(current_clouds_all)
        print(f"The current value of clouds_all is {current_clouds_all}.")

    cursor.close()
    return avg_clouds_all, current_clouds_all

def get_avg_max_sol_w_last_two_years():
    """
    Get the average of the maximum sol_w of the last two years in a timerange of 5 days before and 15 days after today's date.

    Returns:
        float: The average of the maximum sol_w of the last two years in the timerange.
    """
    cursor = connection.cursor(prepared=True)
    # Calculate the start and end dates of the timerange for last year
    start_date_last_year = (datetime.now() - timedelta(weeks=52)).strftime('%Y-%m-%d %H:%M:%S')
    end_date_last_year = (datetime.now() - timedelta(weeks=52) + timedelta(days=20)).strftime('%Y-%m-%d %H:%M:%S')

    # Calculate the start and end dates of the timerange for the year before last year
    start_date_year_before_last_year = (datetime.now() - timedelta(weeks=104)).strftime('%Y-%m-%d %H:%M:%S')
    end_date_year_before_last_year = (datetime.now() - timedelta(weeks=104) + timedelta(days=20)).strftime('%Y-%m-%d %H:%M:%S')

    # Get the maximum sol_w of the last two years in the timerange
    query = f"SELECT AVG(max_sol_w) AS avg_max_sol_w FROM (SELECT MAX(sol_w) AS max_sol_w FROM shelly_solar WHERE stamp BETWEEN '{start_date_last_year}' AND '{end_date_last_year}' OR stamp BETWEEN '{start_date_year_before_last_year}' AND '{end_date_year_before_last_year}') AS subquery"
    cursor.execute(query)
    results = cursor.fetchall()
    avg_max_sol_w_last_two_years = results[0][0]

    cursor.close()

    return avg_max_sol_w_last_two_years

def get_avg_daily_peak(days=10):
    """
    Average of the PER-DAY maximum sol_w over the last `days` full days.

    This is the seasonal-production signal the adaptive threshold rides on: it
    tracks how strong the daily PV peak has been recently, so it falls on its own
    as we head into autumn/winter. (The old version had no GROUP BY, so it
    returned the single highest sample in the window instead of the mean of the
    daily peaks - useless as a baseline.)

    Returns:
        float | None: mean daily-peak sol_w in W, or None if there is no data.
    """
    cursor = connection.cursor(prepared=True)
    # CURDATE() excludes today (partial day); use the last `days` COMPLETE days.
    query = ("SELECT AVG(daily_peak) FROM ("
             "SELECT MAX(sol_w) AS daily_peak FROM shelly_solar "
             "WHERE stamp >= CURDATE() - INTERVAL %s DAY AND stamp < CURDATE() "
             "GROUP BY DATE(stamp)) AS s")
    cursor.execute(query, (days,))
    row = cursor.fetchone()
    cursor.close()
    return float(row[0]) if row and row[0] is not None else None


# --- Adaptive solar-start threshold -----------------------------------------
# Start the pump only when PV is near its recent DAILY PEAK, so production can
# (almost) cover the compressor's ~3.3-4.8 kW draw instead of dribbling in at a
# fixed 1300 W in the early morning. The level is a fraction of the recent daily
# peak, so it self-lowers as the season fades - no manual retuning.
PEAK_FACTOR = 0.78          # fraction of the recent daily peak to require
PEAK_WINDOW_DAYS = 10       # trailing window the daily peak is averaged over
PROD_LEVEL_FLOOR = 800      # never require less (winter hot-water sanity)
PROD_LEVEL_CAP = 5000       # never require more than the pump can use (~4.8 kW)

# --- Afternoon fallback ------------------------------------------------------
# On a day whose peak underdelivers (thin overcast, worse than the 10-day avg the
# bar rides on), PV never reaches the full bar, so the pump would skip solar and
# grid-heat tonight. Instead: wait for the peak until PEAK_HOUR, then - only if
# the tank still WANTS solar heat (below SOLAR_TARGET_TEMP, which a normal sunny
# day has already blown past) - step the bar down hour by hour toward
# FALLBACK_MIN_LEVEL, grabbing the best remaining sun before the day closes.
# Stateless: the tank temp IS the "did we capture sun today" signal. The 50 C
# comfort floor still handles a genuinely dark day at night.
PEAK_HOUR = 13              # don't relax before this - wait for the real midday peak
FALLBACK_END_HOUR = 17      # by this hour the bar has fully relaxed
FALLBACK_MIN_LEVEL = 1500   # lowest the fallback drops to (below this it's not worth a 3 kW pump)
SOLAR_TARGET_TEMP = 58      # degC: below this in the afternoon we still want to top up on solar

def afternoon_fallback_level(full_level, tank_temp):
    """Relax the solar bar in the afternoon if the tank still wants solar heat,
    so we catch weak declining sun instead of grid-heating at night. Returns the
    (possibly lowered) bar; never raises it above full_level."""
    hour = datetime.now().hour
    if hour < PEAK_HOUR or tank_temp >= SOLAR_TARGET_TEMP:
        return full_level                       # wait for the peak, or tank already fine
    frac = min(1.0, (hour - PEAK_HOUR) / float(FALLBACK_END_HOUR - PEAK_HOUR))
    relaxed = full_level - frac * (full_level - FALLBACK_MIN_LEVEL)
    level = int(round(max(FALLBACK_MIN_LEVEL, min(full_level, relaxed))))
    if level < full_level:
        logging.info('startWP: afternoon fallback %02d:00 tank %.0fC<%dC -> bar %sW (was %sW)',
                     hour, tank_temp, SOLAR_TARGET_TEMP, level, full_level)
    return level

def compute_adaptive_prod_level(static_default):
    """Adaptive solar_prod_level = PEAK_FACTOR * recent daily peak, clamped.
    Falls back to the static default if there is no recent PV data."""
    peak = get_avg_daily_peak(PEAK_WINDOW_DAYS)
    if peak is None:
        logging.warning('startWP: no recent PV data, using static solar_prod_level %s', static_default)
        return static_default
    level = int(round(PEAK_FACTOR * peak))
    level = max(PROD_LEVEL_FLOOR, min(PROD_LEVEL_CAP, level))
    logging.info('startWP: adaptive solar_prod_level %sW (%.0f%% of %.0fW avg daily peak, last %sd)',
                 level, PEAK_FACTOR * 100, peak, PEAK_WINDOW_DAYS)
    return level

def log_decision(script, action, relay, tank, solar_total, netz_total, actual_usage, solar_prod_level, sun_present, heating, reason):
    """Persist one decision row so Grafana can show WHY the pump switched."""
    try:
        cur = connection.cursor(prepared=True)
        cur.execute('INSERT INTO wp_decision (ts, script, action, relay, tank, solar_total, netz_total, actual_usage, solar_prod_level, sun_present, heating, reason) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);',
                    (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), script, action, relay, tank,
                     solar_total, netz_total, actual_usage, solar_prod_level, sun_present, heating, reason[:255]))
        connection.commit()
        cur.close()
    except mysql.connector.Error as error:
        logging.error("Failed to insert wp_decision {}".format(error))

HOLIDAY_FLAG_URL = "http://192.168.137.227/rpc/Switch.GetStatus?id=0"
HOLIDAY_FILE = "/tmp/wp_holiday"

def holiday_mode():
    """Vacation override: 'do not heat at all'. Either manual switch enables it:
      - the .227 relay (wired to NOTHING - only hosts the tank temp addon),
        toggled with one tap in the Shelly app  -> output ON = holiday.
      - a local flag file `touch /tmp/wp_holiday`, an SSH/cron backup switch.
    Raises on a network error so the caller can skip the run (leave .68 as-is)
    rather than guess the flag state."""
    if os.path.exists(HOLIDAY_FILE):
        return True
    r = requests.get(HOLIDAY_FLAG_URL, timeout=10)
    return bool(r.json().get('output'))

def startWP(actual_temp, solar_total):
    sun_present = 1 if solar_total >= solar_prod_level else 0
    if   solar_total >= solar_prod_level and actual_usage < actual_use_limit:
         action, relay = 'enabled', 'on'
         msg = f'WP enabled - free solar power (solar {solar_total}W >= {solar_prod_level}W, usage {actual_usage}W < {actual_use_limit}W)'
    elif actual_temp < min_temp:
         action, relay = 'enabled', 'on'
         msg = f'WP enabled - tank {actual_temp}C below minimum {min_temp}C (grid start, never without hot water)'
    else:
        action, relay = 'no_start', None
        msg = f'no start - no surplus (solar {solar_total}W, usage {actual_usage}W) and tank {actual_temp}C >= {min_temp}C'
    print(msg)
    logging.info(msg)
    if relay == 'on':
        url = "http://192.168.137.68/relay/0?turn=on"
        try:
            response = requests.request("POST", url, headers={}, data={}, files={}, timeout=10)
            print(response.text)
        except requests.RequestException as e:
            # Relay unreachable: don't crash. Log it as unconfirmed (relay=NULL) so
            # wp_decision is honest, and let the next cron run retry the enable.
            relay = None
            logging.warning('startWP: .68 relay enable FAILED (%s); retry next run', e)
    log_decision('start', action, relay, actual_temp, solar_total, netz_total, actual_usage,
                 solar_prod_level, sun_present, None, msg)
    
# --- Holiday override --------------------------------------------------------
# One tap on the .227 relay in the Shelly app (or `touch /tmp/wp_holiday`) forces
# the pump fully OFF and skips ALL normal logic - even the hot-water floor - for
# vacations when nobody needs hot water. Toggle it back off to resume normal
# solar/tank control on the next cron tick.
try:
    holiday = holiday_mode()
except (requests.RequestException, ValueError, KeyError, TypeError) as e:
    logging.warning('startWP: could not read holiday flag, skipping run (relay unchanged): %s', e)
    sys.exit(0)

if holiday:
    tank = fetchTemp()
    relay = 'off'
    msg = 'HOLIDAY mode - pump forced off (Ferien override active)'
    try:
        requests.request("POST", "http://192.168.137.68/relay/0?turn=off", timeout=10)
    except requests.RequestException as e:
        relay = None
        msg = f'HOLIDAY mode - .68 off FAILED, may still be ON ({e}); retry next run'
    logging.info(msg)
    print(msg)
    log_decision('start', 'holiday', relay, tank, None, None, None,
                 solar_prod_level, None, None, msg)
    sys.exit(0)

actual_temp = fetchTemp()

# The Shelly meters live on the LAN and can blip. If we cannot read them, skip
# this run and leave the relay untouched (next cron run retries) rather than
# crashing the script on an un-guarded network call.
try:
    act_solar = fetchShelly('shelly-3em-solar')
    print(act_solar)
    response = json.loads(act_solar.content)
    solar_total = calcTotal(response, 'power')
    print('solar total: ', solar_total)

    act_netz = fetchShelly('shelly-3em-elektra')
    print(act_netz)
    response = json.loads(act_netz.content)
    netz_total = calcTotal(response, 'power')
    print('netz total: ', netz_total)
except (requests.RequestException, ValueError, KeyError, TypeError) as e:
    logging.warning('startWP: could not read meters, skipping run (relay unchanged): %s', e)
    sys.exit(0)

actual_usage = solar_total + netz_total
print('actual usage: ', actual_usage)


# Learn the start threshold from recent production instead of the fixed 1300 W.
solar_prod_level = compute_adaptive_prod_level(solar_prod_level)

avg_clouds_forecast, avg_clouds_current_forecast = fetchWeather()
if  avg_clouds_forecast > 70 and avg_clouds_current_forecast < 70:
    solar_prod_level = solar_prod_level - red_for_bad_weather
    print('solar_prod_level after reducation')
    print(solar_prod_level)

# Afternoon fallback: if the peak underdelivered and the tank still wants solar,
# relax the bar to grab the best remaining sun before grid-heating tonight.
solar_prod_level = afternoon_fallback_level(solar_prod_level, actual_temp)

startWP(actual_temp, solar_total)
