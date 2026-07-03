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
    lock_file_pointer = os.open(f"/tmp/getWeatherData.lock", os.O_WRONLY | os.O_CREAT)
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

logging.basicConfig(filename='/home/dan/Documents/programming/IoT/dsnj-homie/weather.log', format='%(asctime)s %(levelname)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S', level=logging.INFO)

DB_NAME = ''
DB_USER = ''
DB_PASS = ''

# Read configuration
try:
    from config import *
except ImportError:
    pass

api_key = "275f22ed3a45dd80208edf6513536dff"
lat = "47.11"
lon = "7.52"

url = f"https://api.openweathermap.org/data/2.5/forecast?id=2661551&appid={api_key}&units=metric&cnt=16"

response = requests.get(url)
data = response.json()

print(json.dumps(data, indent=4))

cnx = mysql.connector.connect(host='localhost', database=DB_NAME, user=DB_USER, password=DB_PASS, auth_plugin='mysql_native_password')

cursor = cnx.cursor()

# Insert the data into the weather_data table
for item in data["list"]:
    dt = item["dt"]
    temp = item["main"]["temp"]
    feels_like = item["main"]["feels_like"]
    temp_min = item["main"]["temp_min"]
    temp_max = item["main"]["temp_max"]
    pressure = item["main"]["pressure"]
    sea_level = item["main"].get("sea_level")
    grnd_level = item["main"].get("grnd_level")
    humidity = item["main"]["humidity"]
    temp_kf = item["main"]["temp_kf"]
    weather_id = item["weather"][0]["id"]
    weather_main = item["weather"][0]["main"]
    weather_description = item["weather"][0]["description"]
    weather_icon = item["weather"][0]["icon"]
    clouds_all = item["clouds"]["all"]
    wind_speed = item["wind"]["speed"]
    wind_deg = item["wind"]["deg"]
    wind_gust = item["wind"].get("gust")
    visibility = item.get("visibility")
    pop = item.get("pop")
    sys_pod = item["sys"]["pod"]
    dt_txt = item["dt_txt"]

    insert_stmt = (
        "INSERT INTO weather_data (dt, temp, feels_like, temp_min, temp_max, pressure, sea_level, grnd_level, humidity, temp_kf, weather_id, weather_main, weather_description, weather_icon, clouds_all, wind_speed, wind_deg, wind_gust, visibility, pop, sys_pod, dt_txt) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
    )
    data = (dt,temp,feels_like,temp_min,temp_max,pressure,sea_level,grnd_level,humidity,temp_kf,
            weather_id,weather_main,weather_description,
            weather_icon,clouds_all,
            wind_speed,
            wind_deg,
            wind_gust,
            visibility,
            pop,
            sys_pod,
            dt_txt)
    
    cursor.execute(insert_stmt,data)

# Commit the changes and close the connection
cnx.commit()
cursor.close()
cnx.close()

print("Data inserted successfully!")




