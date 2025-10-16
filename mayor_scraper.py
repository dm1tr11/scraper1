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
PAGE_WAIT_SECONDS = 5
email_re = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", re.UNICODE)

def setup_driver():
    options = webdriver.ChromeOptions()
    if HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64)")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver

def collect_municipality_links_from_page(driver):
    soup = BeautifulSoup(driver.page_source, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        text = (a.get_text() or "").strip()
        if "Общинска администрация" in text:
            href = a["href"]
            full = urljoin(BASE, href)
            links.append((text, full))
    # Deduplicate
    seen = set()
    dedup = []
    for txt, url in links:
        if url not in seen:
            seen.add(url)
            dedup.append((txt, url))
    return dedup

def click_next_page(driver):
    try:
        next_btn = WebDriverWait(driver, 5).until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(.,'Следваща')]"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", next_btn)
        time.sleep(0.5)
        next_btn.click()
        time.sleep(1.5)
        return True
    except Exception:
        return False

def extract_mayor_from_municipality(driver, url):
    result = {"municipality": "", "mayor": "", "emails": [], "url": url}
    driver.get(url)
    time.sleep(1.5)

    # Municipality name
    try:
        result["municipality"] = driver.find_element(By.CSS_SELECTOR, "h1").text.strip()
    except Exception:
        pass

    # Find the "Кмет на община" block
    try:
        mayor_node = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//div[contains(@class,'node-title') and contains(.,'Кмет на община')]/parent::div"))
        )
        # Extract mayor name if visible on page
        try:
            mayor_text = mayor_node.find_element(By.XPATH, ".//div[contains(@class,'node-title')]").text.strip()
            result["mayor"] = mayor_text
        except Exception:
            pass

        # Find and click the info icon inside that node
        info_icon = mayor_node.find_element(By.CSS_SELECTOR, "div.show-icon[title='Информация']")
        driver.execute_script("arguments[0].click();", info_icon)

        # Wait for the modal to load
        modal = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "div.modal-content"))
        )
        time.sleep(0.6)

        modal_html = modal.get_attribute("innerHTML")
        soup = BeautifulSoup(modal_html, "lxml")

        # Find email inside modal
        label = soup.find(string=lambda s: s and "Електронна поща" in s)
        if label:
            mailto = soup.find("a", href=lambda h: h and "mailto:" in h)
            if mailto:
                email = mailto["href"].replace("mailto:", "").strip()
                result["emails"].append(email)
            else:
                # fallback: regex search
                m = re.search(email_re, modal_html)
                if m:
                    result["emails"].append(m.group(0))

        # Close the modal
        try:
            close_btn = driver.find_element(By.CSS_SELECTOR, "button.btn-close, button.close")
            driver.execute_script("arguments[0].click();", close_btn)
        except Exception:
            driver.execute_script("document.querySelector('div.modal.show button')?.click();")
        time.sleep(0.4)

    except Exception as e:
        print(f"  [!] Could not extract modal info for {result['municipality']}: {e}")

    return result

def main():
    driver = setup_driver()
    wait = WebDriverWait(driver, 15)

    try:
        print("Opening start URL...")
        driver.get(START_URL)
        time.sleep(1.5)

        all_links = []
        page = 1
        while True:
            print(f"Scraping page {page}...")
            wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "a")))
            links = collect_municipality_links_from_page(driver)
            print(f"  Found {len(links)} links on this page.")
            all_links.extend(links)

            if not click_next_page(driver):
                break
            page += 1
            time.sleep(PAGE_WAIT_SECONDS)

        print(f"Total collected links: {len(all_links)}")

        results = []
        for i, (txt, url) in enumerate(all_links, 1):
            print(f"[{i}/{len(all_links)}] {txt}")
            info = extract_mayor_from_municipality(driver, url)
            if not info["municipality"]:
                info["municipality"] = txt
            results.append(info)
            time.sleep(0.5)

        print(f"Saving {len(results)} results to CSV...")
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["municipality", "mayor_name", "emails", "source_url"])
            for r in results:
                w.writerow([r["municipality"], r["mayor"], "; ".join(r["emails"]), r["url"]])

        print("Done.")
        print(f"{sum(1 for r in results if r['emails'])} municipalities with email found.")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
