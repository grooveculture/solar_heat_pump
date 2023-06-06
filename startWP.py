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

min_temp = 45
solar_prod_level = 5100
actual_use_limit = 750
red_for_bad_weather = 3000

def instance_already_running():
    lock_file_pointer = os.open(f"/tmp/controlWP.lock", os.O_WRONLY | os.O_CREAT)
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

connection = mysql.connector.connect(host='localhost', database=DB_NAME, user=DB_USER, password=DB_PASS, auth_plugin='mysql_native_password')


#check weahter conditions 
#if weather is not good later today but 

def fetchShelly(description):
    cursor = connection.cursor(prepared=True)
    cursor.execute('SELECT id FROM shelly_cfg WHERE description = ?;', (description,))
    row = cursor.fetchone()
    cursor.close()
    return requests.get('http://192.168.137.'+str(row[0])+'/status')

def fetchTemp():
    cursor = connection.cursor(prepared=True)
    cursor.execute('SELECT temp FROM oventrop_temps ORDER BY id DESC LIMIT 1;')
    row = cursor.fetchone()
    cursor.close()
#   temp = requests.get(str(row[0]))
    print(row[0])
    return int(row[0])
#    return requests.get(+str(row[0]))


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

        # Convert the result to a float
        avg_clouds_all = float(avg_clouds_all)

    # Do something here
    print(f"The average value of clouds_all from {start_time} until {end_time} is {avg_clouds_all}.")

    cursor.close()
    return avg_clouds_all

def startWP(actual_temp, solar_total):
    if   solar_total >= solar_prod_level and actual_usage < actual_use_limit:
         print('we start the WP because there is free solar power')
         url = "http://192.168.137.144/relay/0?turn=on"
         payload={}
         files={}
         headers = {}
         response = requests.request("POST", url, headers=headers, data=payload, files=files)
         print(response.text)
    elif actual_temp < min_temp:
         print('we start the WP because the minimal temp is reached')
         url = "http://192.168.137.144/relay/0?turn=on"
         payload={}
         files={}
         headers = {}
         response = requests.request("POST", url, headers=headers, data=payload, files=files)
         print(response.text)
    else:
        print('wp does not need to be started')
    
actual_temp = fetchTemp()

act_solar = fetchShelly('shelly-3em-solar')
print(act_solar)
response = json.loads(act_solar.content)
print(response)
solar_total = calcTotal(response, 'power')
print('solar total: ', solar_total)

act_netz = fetchShelly('shelly-3em-elektra')
print(act_netz)
response = json.loads(act_netz.content)
print(response)
netz_total = calcTotal(response, 'power')
print('netz total: ', netz_total)
actual_usage = solar_total + netz_total
print('actual usage: ', actual_usage)

avg_clouds_forecast = fetchWeather()
if   avg_clouds_forecast > 60:
    solar_prod_level = solar_prod_level - red_for_bad_weather
    print('solar_prod_level after reducation')
    print(solar_prod_level)
   
startWP(actual_temp, solar_total)


