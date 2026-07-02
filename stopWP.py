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
    return requests.get('http://192.168.137.'+str(row[0])+'/status')


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


def isHeating():
    """SAFETY: True if the compressor appears to be actively running, so we must
    NOT drop the enable and abort it mid-cycle. We treat it as running if ANY of
    the heated loops is climbing: the hot-water tank (DHW, summer) OR either
    heating flow / Vorlauf (space heating, winter). Stage-agnostic and immune to
    cooking, which never warms any of these. Errs on the side of 'running'."""
    return (isRising('temp_speicher', rise_threshold)
            or isRising('temp_vorlauf_boden', rise_threshold)
            or isRising('temp_vorlauf_radiator', rise_threshold))


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


def turnOff():
    url = WP_OFF_URL
    payload = {}
    files = {}
    headers = {}
    return requests.request("POST", url, headers=headers, data=payload, files=files)


# --- gather the current state ------------------------------------------------
act_solar = fetchShelly('shelly-3em-solar')
response = json.loads(act_solar.content)
solar_total = calcTotal(response, 'power')
print('solar total: ', solar_total)

act_netz = fetchShelly('shelly-3em-elektra')
response = json.loads(act_netz.content)
netz_total = calcTotal(response, 'power')
print('netz total: ', netz_total)

actual_usage = solar_total + netz_total
print('actual usage: ', actual_usage)

tank = fetchTemp()
heating = isHeating()
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
    msg = f'kept ON - compressor running, never abort mid-cycle (tank {tank}C)'
elif sun_present:
    msg = f'kept ON - sun present (solar {solar_total}W >= {solar_prod_level}W)'
elif tank < comfort_floor:
    msg = f'kept ON - tank {tank}C below comfort floor {comfort_floor}C'
else:
    turnOff()
    msg = f'WP disabled - idle, no sun (solar {solar_total}W), tank {tank}C warm, usage {actual_usage}W'

logging.info(msg)
print(msg)

connection.close()
