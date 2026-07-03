import mysql.connector
from datetime import datetime, timedelta
import mysql.connector
import logging
import fcntl
import os
import sys
import time
import config
from datetime import datetime, timedelta

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


def fetchWeather():
    cursor = connection.cursor(prepared=True)

    # Get the current time and 15:00 on the current or next day
    current_time = datetime.now()
    if current_time.hour < 15:
        end_time = current_time.replace(hour=15, minute=0, second=0, microsecond=0)
    else:
        end_time = (current_time + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)

    # Calculate the average value of the clouds_all column from the current time until 15:00
    query = f"SELECT AVG(clouds_all) FROM weather_data WHERE dt_txt >= '{current_time}' AND dt_txt <= '{end_time}'"
    cursor.execute(query)
    result = cursor.fetchone()
    if result:
        avg_clouds_all = result[0]

        # Convert the result to a float
        avg_clouds_all = float(avg_clouds_all)

    # Do something here
    print(f"The average value of clouds_all from the current time until 15:00 or if already past then next day at 15:00 is {avg_clouds_all}.")

    cursor.close()
    return avg_clouds_all

fetchWeather()




