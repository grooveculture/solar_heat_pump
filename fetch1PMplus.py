#!/usr/bin/python3
import requests
import json
import mysql.connector
import logging
import fcntl
import os
import sys
import config
import datetime

def instance_already_running():
    lock_file_pointer = os.open(f"/tmp/fetch1PMplus.lock", os.O_WRONLY | os.O_CREAT)
    try:
        fcntl.lockf(lock_file_pointer, fcntl.LOCK_EX | fcntl.LOCK_NB)
        already_running = False
    except IOError:
        already_running = True
    return already_running

if instance_already_running():
    print('Process already running')
    sys.exit(0)

def insert_temperature(id, temp_type, ext_temp):
    try:
        # Get the current timestamp
        now = datetime.datetime.now()
        # Format the timestamp into a string
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

        cursor = connection.cursor(prepared=True)
        insert_query = 'INSERT INTO {table}(id, temp_speicher, createdAt, updatedAt) VALUES (%s, %s, %s, %s);'.format(
            table=temp_type)
        cursor.execute(insert_query, (id, ext_temp, timestamp, timestamp))
        connection.commit()
    except mysql.connector.Error as error:
        connection.rollback()
        logging.error("Failed to insert into MySQL table {}".format(error))
    finally:
        if connection.is_connected():
            cursor.close()


def insert_temp_speicher(id, ext_temp):
    insert_temperature(id, 'temp_speicher', ext_temp)


def insert_temp_vorlauf_boden(id, ext_temp):
    insert_temperature(id, 'temp_vorlauf_boden', ext_temp)


def insert_temp_vorlauf_radiator(id, ext_temp):
    insert_temperature(id, 'temp_vorlauf_radiator', ext_temp)


logging.basicConfig(filename='/home/dan/Documents/programming/IoT/dsnj-homie/fetch1PMplus.log', format='%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S', level=logging.INFO)

DB_NAME = ''
DB_USER = ''
DB_PASS = ''

# Read configuration
try:
    from config import *
except ImportError:
    pass

connection = mysql.connector.connect(host='localhost', database=DB_NAME, user=DB_USER, password=DB_PASS, auth_plugin='mysql_native_password')

# fetch all shellies to be checked
try:
    cursor = connection.cursor(prepared=False)
    cursor.execute('SELECT id, name, description FROM shelly_cfg WHERE description = \'shelly-1pm-plus-temp-wp\' ORDER BY id;')
    rows = cursor.fetchall()
except mysql.connector.Error as error:
    logging.error("Failed to read from MySQL table {}".format(error))
finally:
    if connection.is_connected():
        cursor.close()


for id,name,description in rows:
        try:
            status = requests.get('http://192.168.137.'+str(id)+'/rpc/Switch.GetStatus?id=0',timeout=3)
        except (requests.ConnectionError, requests.Timeout):
            # unavailable, let's skip it
            continue
        stats = json.loads(status.content)
        watt = stats['aenergy']['by_minute'][1]
        watt = watt * 60 / 1000
        watt = round(watt,1)
        onoff = stats['output']

        temp = stats['temperature']['tC']
        try:
            status = requests.get('http://192.168.137.'+str(id)+'/rpc/Wifi.GetStatus?id=0',timeout=3)
        except (requests.ConnectionError, requests.Timeout):
            # unavailable, let's skip it
            continue
        stats = json.loads(status.content)
        rssi = stats['rssi']

        try:
            cursor = connection.cursor(prepared=True)
            insert_query = 'INSERT INTO shelly_1pm (id, watt, onoff) VALUES (%s, %s, %s);'
            cursor.execute(insert_query, (id, watt, onoff))
            connection.commit()
        except mysql.connector.Error as error:
            connection.rollback()
            logging.error("Failed to insert into MySQL table {}".format(error))
        finally:
            if connection.is_connected():
                cursor.close()

        # additional data like temp, rssi (to keep main table fast and clean)
        try:
            cursor = connection.cursor(prepared=True)
            insert_query = 'INSERT INTO shelly_1pm_xtra (id, temp, rssi) VALUES (%s, %s, %s);'
            cursor.execute(insert_query, (id, temp, rssi))
            connection.commit()
        except mysql.connector.Error as error:
            connection.rollback()
            logging.error("Failed to insert into MySQL table {}".format(error))
        finally:
            if connection.is_connected():
                cursor.close()

def get_temperature(id, temp_type):
    try:
        status = requests.get(f'http://192.168.137.{str(id)}/rpc/Temperature.GetStatus?id={temp_type}', timeout=3)
    except (requests.ConnectionError, requests.Timeout):
        # unavailable, let's skip it
        return None

    stats = json.loads(status.content)
    return stats.get('tC')


# check if there's an addon and save first the speicher temp id=103 into the db
temp = get_temperature(id, 103)

if temp > 0:
    insert_temp_speicher(id, temp)

# check if there's an addon and save then the vorlauf bodenzeizung temp id=100 into the db
temp = get_temperature(id, 100)

if temp > 0:
    insert_temp_vorlauf_boden(id, temp)

# check if there's an addon and save then the vorlauf radiatoren temp id=101 into the db
temp = get_temperature(id, 101)

if temp > 0:
    insert_temp_vorlauf_radiator(id, temp)



connection.close()
