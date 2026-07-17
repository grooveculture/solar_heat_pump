#!/usr/bin/python3
import requests
import json
import mysql.connector
import logging
import fcntl
import os
import sys
import time
import config
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# Decision thresholds (kept in sync with startWP.py so the two never fight).
# ---------------------------------------------------------------------------
comfort_floor = 50        # degC: at/above this the tank counts as "warm enough" to allow switching off
solar_prod_level = 1300   # W of PV production that counts as real sun (summer)
red_for_bad_weather = 1000
rise_threshold = 0.3      # degC rise over ~6 min => a compressor is actively heating
pump_power_level = 3000   # W of total house draw that means the compressor is running.
                          # Measured: pump pulls ~3.3-4.8 kW, standby ~0.3 kW, cooking ~2.4 kW,
                          # so 3000 sits safely above cooking and below the running pump.


def is_winter():
    return datetime.now().month in [11, 12, 1, 2]  # Nov, Dec, Jan, Feb


# Winter parameters (mirror startWP.py)
if is_winter():
    solar_prod_level = 1000
    red_for_bad_weather = 750


def instance_already_running():
    lock_file_pointer = os.open("/tmp/stopWP.lock", os.O_WRONLY | os.O_CREAT)
    try:
        fcntl.lockf(lock_file_pointer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        already_running = False
    except IOError:
        already_running = True
    return already_running


if instance_already_running():
    print('Process already running')
    sys.exit(0)

logging.basicConfig(filename='/home/dan/Documents/programming/IoT/dsnj-homie/controlWP.log',
                    format='%(asctime)s %(levelname)s: %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S', level=logging.INFO)

DB_NAME = ''
DB_USER = ''
DB_PASS = ''

# Read configuration
try:
    from config import *
except ImportError:
    pass

connection = mysql.connector.connect(host='localhost', database=DB_NAME, user=DB_USER, password=DB_PASS, auth_plugin='mysql_native_password')

WP_OFF_URL = "http://192.168.137.68/relay/0?turn=off"


def fetchShelly(description):
    cursor = connection.cursor(prepared=True)
    cursor.execute('SELECT id FROM shelly_cfg WHERE description = ?;', (description,))
    row = cursor.fetchone()
    cursor.close()
    return requests.get('http://192.168.137.'+str(row[0])+'/status', timeout=10)


def calcTotal(state, field):
    total  = state['emeters'][0][field]
    total += state['emeters'][1][field]
    total += state['emeters'][2][field]
    return float("{0:.2f}".format(total))


def fetchTemp():
    cursor = connection.cursor(prepared=True)
    cursor.execute('SELECT temp_speicher FROM temp_speicher ORDER BY createdAt DESC LIMIT 1;')
    row = cursor.fetchone()
    cursor.close()
    return float(row[0])


def isRising(table, threshold):
    """True when the given temperature series is climbing over the last ~6 min.
    The column is called temp_speicher in every temp_* table (see fetch1PMplus.py)."""
    cursor = connection.cursor(prepared=True)
    cursor.execute(f'SELECT temp_speicher FROM {table} ORDER BY createdAt DESC LIMIT 3;')
    rows = cursor.fetchall()
    cursor.close()
    if len(rows) < 3:
        return False  # not enough history -> can't prove it is heating
    return (float(rows[0][0]) - float(rows[2][0])) >= threshold


def isHeating(actual_usage):
    """SAFETY: True if the DHW compressor appears to be running, so we must NOT
    drop the enable and abort it mid-cycle. Two independent signals, either is
    enough ("if it's clearly the pump, don't stop"):

      1. tank temp_speicher is climbing (proven heating; immune to cooking, which
         never warms the tank). The Vorlauf (space-heating flow) sensors were
         dropped - they drift on their own in summer and gave false readings that
         kept the pump enabled overnight.
      2. total house draw >= pump_power_level. The compressor pulls ~3.3-4.8 kW,
         far above standby (~0.3 kW) and cooking (~2.4 kW), so a high draw at
         night means the pump. This catches the run ~4 min BEFORE the tank starts
         to climb (measured 2026-07-04), covering the thermal lag at start-up.

    When neither holds, the pump is clearly idle and stopWP is free to disable."""
    return isRising('temp_speicher', rise_threshold) or actual_usage >= pump_power_level


def fetchWeather():
    """Average forecast cloudiness for the rest of the solar window and the current
    value, used to lower the sun bar when it is clear now but turns bad later."""
    cursor = connection.cursor(prepared=True)
    current_time = datetime.now()
    if current_time.hour < 15:
        start = current_time
        end = current_time.replace(hour=15, minute=0, second=0, microsecond=0)
    else:
        start = (current_time + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        end = (current_time + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)

    cursor.execute(f"SELECT AVG(clouds_all) FROM weather_data WHERE dt_txt >= '{start}' AND dt_txt <= '{end}'")
    r = cursor.fetchone()
    avg_clouds = float(r[0]) if r and r[0] is not None else 0.0

    cursor.execute("SELECT clouds_all FROM weather_data ORDER BY dt DESC LIMIT 1")
    r = cursor.fetchone()
    cur_clouds = float(r[0]) if r and r[0] is not None else 0.0

    cursor.close()
    return avg_clouds, cur_clouds


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


def turnOff():
    url = WP_OFF_URL
    payload = {}
    files = {}
    headers = {}
    return requests.request("POST", url, headers=headers, data=payload, files=files, timeout=10)


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


# --- Holiday override --------------------------------------------------------
# One tap on the .227 relay in the Shelly app (or `touch /tmp/wp_holiday`) forces
# the pump fully OFF and skips ALL normal logic - even the comfort floor - for
# vacations when nobody needs hot water. Toggle it back off to resume normal
# control on the next cron tick.
try:
    holiday = holiday_mode()
except (requests.RequestException, ValueError, KeyError, TypeError) as e:
    logging.warning('stopWP: could not read holiday flag, skipping run (relay unchanged): %s', e)
    sys.exit(0)

if holiday:
    tank = fetchTemp()
    relay = 'off'
    msg = 'HOLIDAY mode - pump forced off (Ferien override active)'
    try:
        turnOff()
    except requests.RequestException as e:
        relay = None
        msg = f'HOLIDAY mode - .68 off FAILED, may still be ON ({e}); retry next run'
    logging.info(msg)
    print(msg)
    log_decision('stop', 'holiday', relay, tank, None, None, None,
                 solar_prod_level, None, None, msg)
    connection.close()
    sys.exit(0)

# --- gather the current state ------------------------------------------------
# The Shelly meters are on the LAN and can blip. If we cannot read them we CANNOT
# make a safe stop decision, so we skip this run and leave the relay untouched
# (the next cron run, ~15 min later, retries). A transient blip must never crash
# the script - that used to leave .68 enabled and let the pump grid-heat overnight.
try:
    act_solar = fetchShelly('shelly-3em-solar')
    solar_total = calcTotal(json.loads(act_solar.content), 'power')
    print('solar total: ', solar_total)

    act_netz = fetchShelly('shelly-3em-elektra')
    netz_total = calcTotal(json.loads(act_netz.content), 'power')
    print('netz total: ', netz_total)
except (requests.RequestException, ValueError, KeyError, TypeError) as e:
    logging.warning('stopWP: could not read meters, skipping run (relay unchanged): %s', e)
    sys.exit(0)

actual_usage = solar_total + netz_total
print('actual usage: ', actual_usage)

tank = fetchTemp()
heating = isHeating(actual_usage)
print('tank: ', tank, ' heating: ', heating)

# Lower the sun bar when it is clear now but the forecast turns bad later -
# same "grab it while we can" adjustment startWP uses, so both agree on "sun".
avg_clouds, cur_clouds = fetchWeather()
if avg_clouds > 70 and cur_clouds < 70:
    solar_prod_level = solar_prod_level - red_for_bad_weather
    print('solar_prod_level after reduction: ', solar_prod_level)

sun_present = solar_total >= solar_prod_level

# --- decide ------------------------------------------------------------------
# SAFETY FIRST: never abort a running compressor. If it is actively heating we
# keep the enable ON no matter what - a bit of grid is always better than
# short-cycling the pump.
# Otherwise keep it enabled while the sun feeds it, or while the tank is below
# the comfort floor (never leave the house without hot water). Only when it is
# idle, sunless and the tank is warm do we drop the .68 enable, so the pump's
# own thermostat cannot top the tank up on grid power in the evening.
if heating:
    action, relay = 'kept_on', None
    msg = f'kept ON - compressor running, never abort mid-cycle (tank {tank}C, usage {actual_usage}W)'
elif sun_present:
    action, relay = 'kept_on', None
    msg = f'kept ON - sun present (solar {solar_total}W >= {solar_prod_level}W)'
elif tank < comfort_floor:
    action, relay = 'kept_on', None
    msg = f'kept ON - tank {tank}C below comfort floor {comfort_floor}C'
else:
    action, relay = 'disabled', 'off'
    msg = f'WP disabled - idle, no sun (solar {solar_total}W), tank {tank}C warm, usage {actual_usage}W'
    try:
        turnOff()
    except requests.RequestException as e:
        # Relay unreachable: don't crash. .68 may still be ON; log it as unconfirmed
        # (relay=NULL) so wp_decision is honest, and let the next cron run retry.
        relay = None
        msg = f'WP disable FAILED - .68 relay unreachable, may still be ON ({e}); retry next run'

logging.info(msg)
print(msg)

log_decision('stop', action, relay, tank, solar_total, netz_total, actual_usage,
             solar_prod_level, 1 if sun_present else 0, 1 if heating else 0, msg)

connection.close()
