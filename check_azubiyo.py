from bs4 import BeautifulSoup

with open("www.azubiyo.de_ausbildung_berlin_.html", encoding="utf-8") as f:
    html = f.read()

print("__NEXT_DATA__:", "__NEXT_DATA__" in html)
print("__NUXT__:", "__NUXT__" in html)
print("JobPosting:", "JobPosting" in html)
print("application/ld+json:", "application/ld+json" in html)

print("\nScript types:\n")

soup = BeautifulSoup(html, "html.parser")

for script in soup.find_all("script"):
    if script.get("type"):
        print(script.get("type"))