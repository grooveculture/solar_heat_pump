import mysql.connector
import logging

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

mycursor = connection.cursor()

kundennummer = input("Enter kundennummer: ")
rechnungsdatum = input("Enter rechnungsdatum (YYYY-MM-DD): ")
rechnungsbetrag = input("Enter rechnungsbetrag: ")
rechnungsnummer = input("Enter rechnungsnummer: ")
tarif = input("Enter tarif: ")
status = input("Enter status: ")

sql = "INSERT INTO stromrechnungen (kundennummer, rechnungsdatum, rechnungsbetrag, rechnungsnummer, tarif, status) VALUES (%s, %s, %s, %s, %s, %s)"
val = (kundennummer, rechnungsdatum, rechnungsbetrag, rechnungsnummer, tarif, status)

mycursor.execute(sql, val)

connection.commit()

print(mycursor.rowcount, "record inserted.")
