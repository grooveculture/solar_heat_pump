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
solar_prod_level = 1300
actual_use_limit = 850
red_for_bad_weather = 1000

def is_winter():
    current_month = datetime.now().month
    return current_month in [11, 12, 1, 2]  # November, December, January, February

# Check if it's winter and adjust parameters
if is_winter():
    min_temp = 50  # Set minimum temperature for winter
    solar_prod_level = 1000  # Set solar production level for winter
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

def get_avg_max_sol_w_last_20_days():
    """
    Get the average of the maximum sol_w of the last 10 days.

    Returns:
        float: The average of the maximum sol_w of the last 10 days.
    """
    cursor = connection.cursor(prepared=True)

    # Calculate the start and end dates of the timerange for the last 20 days
    start_date = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S')
    end_date = (datetime.now()).strftime('%Y-%m-%d %H:%M:%S')

    # Get the maximum sol_w of the last 20 days
    query = f"SELECT AVG(max_sol_w) AS avg_max_sol_w FROM (SELECT MAX(sol_w) AS max_sol_w FROM shelly_solar WHERE stamp BETWEEN '{start_date}' AND '{end_date}') AS subquery"
    cursor.execute(query)
    results = cursor.fetchall()
    avg_max_sol_w_last_20_days = results[0][0]

    cursor.close()

    return avg_max_sol_w_last_20_days

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
        response = requests.request("POST", url, headers={}, data={}, files={}, timeout=10)
        print(response.text)
    log_decision('start', action, relay, actual_temp, solar_total, netz_total, actual_usage,
                 solar_prod_level, sun_present, None, msg)
    
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


test_solar_prod_level = get_avg_max_sol_w_last_two_years()

test_solar_prod_level_last_10_days = get_avg_max_sol_w_last_20_days()

avg_clouds_forecast, avg_clouds_current_forecast = fetchWeather()
if  avg_clouds_forecast > 70 and avg_clouds_current_forecast < 70:
    solar_prod_level = solar_prod_level - red_for_bad_weather
    print('solar_prod_level after reducation')
    print(solar_prod_level)
   
startWP(actual_temp, solar_total)
