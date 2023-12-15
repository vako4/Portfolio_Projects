import requests
from bs4 import BeautifulSoup

url = "https://en.wikipedia.org/wiki/List_of_most-followed_Instagram_accounts"

response = requests.get(url)

if response.status_code == 200:
    soup = BeautifulSoup(response.text, 'html.parser')

    table = soup.find('table', {'class': 'wikitable'})


    for row in table.find_all('tr')[1:]:
        columns = row.find_all('td')

        if columns:
            owner = columns[1].text.strip()
            followers = columns[3].text.strip()

            print(f"Owner: {owner}, Followers: {followers}")

else:
    print(f"Failed to retrieve the page. Status code: {response.status_code}")
