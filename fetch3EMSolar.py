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

def instance_already_running():
    lock_file_pointer = os.open(f"/tmp/fetchSolar.lock", os.O_WRONLY | os.O_CREAT)
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

logging.basicConfig(filename='/home/dan/Documents/programming/IoT/dsnj-homie/solar.log', format='%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S', level=logging.INFO)

DB_NAME = ''
DB_USER = ''
DB_PASS = ''

# Read configuration
try:
    from config import *
except ImportError:
    pass

connection = mysql.connector.connect(host='localhost', database=DB_NAME, user=DB_USER, password=DB_PASS, auth_plugin='mysql_native_password')

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
    total = float("{0:.2f}".format(total))
    return total

def calcDiff(current, previous):
    diff =  current - previous
    if diff < 0:
        diff = 0
    return diff

# read previous totals
cursor = connection.cursor(prepared=False)
cursor.execute('SELECT sol_wh_consumed_total, sol_wh_returned_total, elektra_wh_consumed_total, elektra_wh_returned_total FROM shelly_solar WHERE stamp = (SELECT MAX(stamp) FROM shelly_solar);')
row = cursor.fetchone()
print(row)
cursor.close()
sol_wh_consumed_prev = row[0]
sol_wh_returned_prev = row[1]
elektra_wh_consumed_prev = row[2]
elektra_wh_returned_prev = row[3]
    
# fetch current values
elapsed_time = time.time() - start_time
i = 0
sol_w_sum = 0
elektra_w_sum = 0
while elapsed_time < 55:
    sol_status = fetchShelly('shelly-3em-solar')
    elektra_status = fetchShelly('shelly-3em-elektra')
    sol_stats = json.loads(sol_status.content)
    elektra_stats = json.loads(elektra_status.content)
    # sum phases
    sol_w_sum += calcTotal(sol_stats,'power')
    elektra_w_sum += calcTotal(elektra_stats,'power')
    i += 1
    time.sleep(1)
    elapsed_time = time.time() - start_time

# cal averrage watt usage
sol_w = float("{0:.2f}".format(sol_w_sum/i))
elektra_w = float("{0:.2f}".format(elektra_w_sum/i))

sol_wh_consumed_total = calcTotal(sol_stats,'total')
sol_wh_returned_total = calcTotal(sol_stats,'total_returned')
elektra_wh_consumed_total = calcTotal(elektra_stats,'total')
elektra_wh_returned_total = calcTotal(elektra_stats,'total_returned')

# calc diffs
sol_wh_consumed_diff = calcDiff(sol_wh_consumed_total, sol_wh_consumed_prev)
sol_wh_returned_diff = calcDiff(sol_wh_returned_total, sol_wh_returned_prev)
elektra_wh_consumed_diff = calcDiff(elektra_wh_consumed_total, elektra_wh_consumed_prev)
elektra_wh_returned_diff = calcDiff(elektra_wh_returned_total, elektra_wh_returned_prev)

# insert data
try:
    cursor = connection.cursor(prepared=True)
    insert_query = 'INSERT INTO shelly_solar (sol_w, sol_wh_consumed_total, sol_wh_consumed_diff, sol_wh_returned_total, sol_wh_returned_diff, ' \
                                         'elektra_w, elektra_wh_consumed_total, elektra_wh_consumed_diff, elektra_wh_returned_total, elektra_wh_returned_diff) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);'
    cursor.execute(insert_query, (sol_w, sol_wh_consumed_total, sol_wh_consumed_diff, sol_wh_returned_total, sol_wh_returned_diff, elektra_w, elektra_wh_consumed_total, elektra_wh_consumed_diff, elektra_wh_returned_total, elektra_wh_returned_diff))
    connection.commit()
except mysql.connector.Error as error:
    connection.rollback()
    logging.error("Failed to insert into MySQL table {}".format(error))
finally:
    if connection.is_connected():
        cursor.close()


