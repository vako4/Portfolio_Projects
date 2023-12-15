import requests
from bs4 import BeautifulSoup

URL = "https://web.archive.org/web/20200518073855/https://www.empireonline.com/movies/features/best-movies-2/"



response = requests.get(URL)
web_page = response.text

soup = BeautifulSoup(web_page, "html.parser")
titles = soup.find_all(name="h3", class_="title")

title_list = []
for i in titles:
    title = i.getText()
    only_title = title.split()[1:]
    full_title = " ".join(only_title)
    title_list.append(full_title)


new_list = list(reversed(title_list))
num = 1
for i in new_list:
    print(f"{num} {i}")
    num += 1
