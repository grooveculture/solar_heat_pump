import requests
from lxml import html
import requests
from bs4 import BeautifulSoup
import pandas as pd

# Login credentials
payload = {
    "username": "danielschaerer@protonmail.com",
    "password": "N^F7YQw3NBvR*eTybXTE6c"
}

# Start a session
session_requests = requests.session()

# Send a POST request to the login URL
login_url = "https://kundencenter.elektra.ch/de/services/login.php"
result = session_requests.post(
    login_url,
    data=payload,
    headers=dict(referer=login_url)
)
print(payload)
print(result)
response = requests.get(login_url)
soup = BeautifulSoup(response.text, 'lxml')
print(soup.div)


# Scrape content from the invoices section
invoices_url = "https://kundencenter.elektra.ch/de/services/verbrauch.php"
result = session_requests.get(
    invoices_url,
    headers=dict(referer=invoices_url)
)
soup = BeautifulSoup(response.text, 'html.parser')
print(soup)
""" tree = html.fromstring(result.content)
element = tree.xpath('//td[@data-title="Rechnungsnr."]/a/text()')
print(element[0]) """

#give it a try

url = 'https://kundencenter.elektra.ch/de/services/verbrauch.php'


# Navigate to the desired page
page_url = 'https://kundencenter.elektra.ch/de/services/verbrauch.php'
response = session_requests.get(page_url)

# Find the desired class
class_name = 'class_name'
class_element = response.html.find(f'.{class_name}')[0]
print(class_element)
