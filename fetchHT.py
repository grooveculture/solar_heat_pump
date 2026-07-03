#!/usr/bin/python3
import requests
import json
import mysql.connector
import logging
import fcntl
import os
import sys
import time

def instance_already_running():
    lock_file_pointer = os.open(f"/tmp/fetchHT.lock", os.O_WRONLY | os.O_CREAT)
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

logging.basicConfig(filename='/home/dan/Documents/programming/IoT/dsnj-homie/fetchHT.log', format='%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S', level=logging.INFO)

DB_NAME = ''
DB_USER = ''
DB_PASS = ''

# Read configuration
try:
    from config import *
except ImportError:
    pass

connection = mysql.connector.connect(host='localhost', database=DB_NAME, user=DB_USER, password=DB_PASS)

# fetch all shellies to be checked
try:
    cursor = connection.cursor(prepared=False)
    cursor.execute('SELECT id FROM shelly_cfg WHERE type = \'HT\' ORDER BY id;')
    rows = cursor.fetchall()
except mysql.connector.Error as error:
    logging.error("Failed to read from MySQL table {}".format(error))
finally:
    if connection.is_connected():
        cursor.close()

tocheck = []
for id, in rows:
    tocheck += [id]

elapsed_time = time.time() - start_time
max_time = 57
while elapsed_time < max_time:
    for id in tocheck:
        elapsed_time = time.time() - start_time
        if elapsed_time >= max_time:
            break
        try:
            status = requests.get('http://192.168.137.'+str(id)+'/status',timeout=1)
        except (requests.ConnectionError, requests.Timeout):
            # sensor unavailable, let's skip it
            continue

        # parse sensor data 
        stats = json.loads(status.content)
        tocheck.remove(id)
        temp = stats['tmp']['tC']
        temp = round(temp,1)
        humidity = stats['hum']['value']

        # check if this has been recently logged (maybe it was just logged during prev run)
        try:
            cursor = connection.cursor(prepared=True)
            cursor.execute('SELECT id FROM shelly_ht WHERE time >= NOW() - INTERVAL 2 MINUTE AND id = %s;', (id,))
            row = cursor.fetchone()
            if row is None:
                # all good, this hasn't been logged in a while
                pass
            else:
                # skip it, we recently logged it
                break
        except mysql.connector.Error as error:
            logging.error("Failed to read from MySQL table {}".format(error))
        finally:
            if connection.is_connected():
                cursor.close()

        # all good, log it
        try:
            cursor = connection.cursor(prepared=True)
            insert_query = 'INSERT INTO shelly_ht (id, temp, humidity) VALUES (%s, %s, %s);'
            cursor.execute(insert_query, (id, temp, humidity))
            connection.commit()
        except mysql.connector.Error as error:
            connection.rollback()
            logging.error("Failed to insert into MySQL table {}".format(error))
        finally:
            if connection.is_connected():
                cursor.close()

    # rewind, let's go again!
