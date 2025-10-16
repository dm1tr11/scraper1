import re
import time
import csv
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

BASE = "https://iisda.government.bg"
START_URL = "https://iisda.government.bg/ras/adm_structures/municipality_administrations"
OUTPUT_CSV = "mayors_bulgaria.csv"

HEADLESS = True
MAX_PAGE_ITER = 20
PAGE_WAIT_SECONDS = 5

email_re = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", re.UNICODE)


def setup_driver():
    options = webdriver.ChromeOptions()
    if HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument(
        "user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/117.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver


def collect_municipality_links_from_page(driver):
    soup = BeautifulSoup(driver.page_source, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        text = (a.get_text() or "").strip()
        if "Общинска администрация" in text:
            full = urljoin(BASE, a["href"])
            links.append((text, full))
    seen = set()
    dedup = []
    for text, url in links:
        if url not in seen:
            seen.add(url)
            dedup.append((text, url))
    return dedup


def click_next_page(driver):
    try:
        next_elem = None
        try:
            next_elem = driver.find_element(By.LINK_TEXT, "Следваща")
        except Exception:
            elems = driver.find_elements(By.XPATH, "//*[normalize-space(text())='Следваща']")
            if elems:
                next_elem = elems[0]
        if not next_elem:
            return False
        driver.execute_script("arguments[0].scrollIntoView(true);", next_elem)
        time.sleep(0.3)
        next_elem.click()
        return True
    except Exception:
        return False


def extract_mayor_from_municipality(driver, url):
    """Open the municipality detail page and extract the mayor’s name and email."""
    result = {"municipality": "", "mayor": "", "emails": [], "url": url}

    driver.get(url)
    time.sleep(1.5)
    soup = BeautifulSoup(driver.page_source, "lxml")

    # Get the municipality name (header)
    header = soup.find("h1")
    if header:
        result["municipality"] = header.get_text(strip=True)

    # --- Find the “Кмет на община” row ---
    mayor_row = None
    for tr in soup.find_all("tr"):
        if tr.find(string=lambda s: s and "Кмет на община" in s):
            mayor_row = tr
            break

    mayor_name = ""
    mayor_email = ""

    if mayor_row:
        # Extract all cells
        cells = [td.get_text(" ", strip=True) for td in mayor_row.find_all("td")]
        row_html = str(mayor_row)

        # Mayor name: often in same row, next to title
        if len(cells) > 1:
            mayor_name = cells[1].strip()

        # Mayor email: check for mailto links or regex matches
        mailto = mayor_row.find("a", href=lambda h: h and "mailto:" in h)
        if mailto:
            mayor_email = mailto["href"].replace("mailto:", "").split("?")[0].strip()
        else:
            found = re.findall(email_re, row_html)
            if found:
                mayor_email = found[0]

    # If we didn’t find it in the table, fallback: scan the whole page
    if not mayor_email:
        found = re.findall(email_re, soup.get_text(" "))
        if found:
            mayor_email = found[0]

    result["mayor"] = mayor_name
    result["emails"] = [mayor_email] if mayor_email else []
    return result


def main():
    driver = setup_driver()
    wait = WebDriverWait(driver, 15)

    try:
        print("Opening start URL...")
        driver.get(START_URL)
        time.sleep(1.2)

        all_municipality_links = []
        page = 1
        LAST_PAGE = 9

        while page <= MAX_PAGE_ITER and page <= LAST_PAGE:
            print(f"Collecting links on listing page {page} ...")
            wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "a")))
            page_links = collect_municipality_links_from_page(driver)

            existing = set(u for _, u in all_municipality_links)
            for txt, url in page_links:
                if url not in existing:
                    all_municipality_links.append((txt, url))

            if page >= LAST_PAGE:
                break
            if not click_next_page(driver):
                break

            page += 1
            time.sleep(PAGE_WAIT_SECONDS)

        print(f"Total municipality links collected: {len(all_municipality_links)}")

        results = []
        for i, (txt, url) in enumerate(all_municipality_links, 1):
            print(f"[{i}/{len(all_municipality_links)}] {txt}")
            info = extract_mayor_from_municipality(driver, url)
            if not info["municipality"]:
                info["municipality"] = txt
            results.append(info)
            time.sleep(0.5)

        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["municipality", "mayor_name", "emails", "source_url"])
            for r in results:
                writer.writerow([r["municipality"], r["mayor"], "; ".join(r["emails"]), r["url"]])

        found = sum(1 for r in results if r["emails"])
        print(f"Done! {found}/{len(results)} mayors with email found.")
        print(f"Saved to {OUTPUT_CSV}")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
