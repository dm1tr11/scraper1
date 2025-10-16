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

# ========== Configuration ==========
HEADLESS = True   # set False while debugging
MAX_PAGE_ITER = 20  # safety cap
PAGE_WAIT_SECONDS = 5
# ===================================

email_re = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", re.UNICODE)

def find_emails_in_html(html):
    found = set(email_re.findall(html))
    return sorted(found)

def setup_driver():
    options = webdriver.ChromeOptions()
    if HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/117.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)
    driver.set_page_load_timeout(60)
    return driver

def collect_municipality_links_from_page(driver):
    """Collects links to all municipality detail pages from current listing page."""
    soup = BeautifulSoup(driver.page_source, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        text = (a.get_text() or "").strip()
        if "Общинска администрация" in text or ("общинска администрация" in text.lower()):
            href = a["href"]
            full = urljoin(BASE, href)
            links.append((text, full))
    seen = set()
    dedup = []
    for text, url in links:
        if url not in seen:
            seen.add(url)
            dedup.append((text, url))
    return dedup

def click_next_page(driver):
    """Clicks the 'Следваща' button to go to the next page."""
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
    except Exception as e:
        print("Could not click Next:", e)
        return False

def extract_mayor_from_municipality(driver, url):
    """
    Opens the municipality page, clicks 'Информация',
    and extracts mayor name and email (under 'Електронна поща:').
    """
    result = {"municipality": "", "mayor": "", "emails": [], "url": url}

    try:
        driver.get(url)
        time.sleep(1.5)
    except Exception:
        driver.get(url)

    soup = BeautifulSoup(driver.page_source, "lxml")

    # Municipality title
    header = soup.find("h1")
    if header:
        result["municipality"] = header.get_text(strip=True)

    # --- Click the "Информация" button ---
    try:
        info_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//a[normalize-space(text())='Информация']"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", info_button)
        time.sleep(0.5)
        info_button.click()
        time.sleep(2.0)  # wait for info content to load
    except Exception as e:
        print(f"  Could not click 'Информация' for {result['municipality']}: {e}")

    # If it opened a new tab, switch to it
    try:
        if len(driver.window_handles) > 1:
            driver.switch_to.window(driver.window_handles[-1])
            time.sleep(1.0)
    except Exception:
        pass

    # Re-parse the new page content
    soup = BeautifulSoup(driver.page_source, "lxml")

    # Extract email under 'Електронна поща:'
    email_text = ""
    label = soup.find(string=lambda s: s and "Електронна поща" in s)
    if label:
        parent = label.parent
        mailto = None
        if parent:
            mailto = parent.find_next("a", href=lambda h: h and "mailto:" in h)
        if mailto:
            email_text = mailto["href"].replace("mailto:", "").split("?")[0].strip()
        else:
            # Look for nearby plain text email
            text_after = parent.find_next(text=email_re)
            if text_after:
                email_text = text_after.strip()
            else:
                sib = parent.find_next_sibling(text=email_re)
                if sib:
                    email_text = sib.strip()

    # Try to extract mayor's name if present
    mayor_label = soup.find(string=lambda s: s and "Кмет на община" in s)
    if mayor_label:
        td = mayor_label.find_parent("td")
        if td:
            nxt = td.find_next_sibling("td")
            if nxt:
                result["mayor"] = nxt.get_text(strip=True)

    if email_text:
        result["emails"] = [email_text]

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
            print(f"Collecting links on listing page {page}...")
            try:
                wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "a")))
            except Exception:
                pass
            page_links = collect_municipality_links_from_page(driver)
            existing = set(u for _, u in all_municipality_links)
            new_count = 0
            for txt, url in page_links:
                if url not in existing:
                    all_municipality_links.append((txt, url))
                    existing.add(url)
                    new_count += 1
            print(f"  Found {len(page_links)} candidate links on this page, {new_count} new")

            if page >= LAST_PAGE:
                print(f"Reached page {page}.")
                break

            clicked = click_next_page(driver)
            if not clicked:
                print("No 'Следваща' found or could not click — assuming last page.")
                break
            page += 1
            time.sleep(PAGE_WAIT_SECONDS)

        print(f"Total municipality links collected: {len(all_municipality_links)}")

        unique_links = []
        seen = set()
        for txt, url in all_municipality_links:
            if url not in seen:
                seen.add(url)
                unique_links.append((txt, url))

        print(f"Visiting {len(unique_links)} municipality pages to extract mayor emails...")
        results = []
        counter = 0
        for txt, url in unique_links:
            counter += 1
            print(f"[{counter}/{len(unique_links)}] {txt} -> {url}")
            try:
                info = extract_mayor_from_municipality(driver, url)
                if not info["municipality"]:
                    info["municipality"] = txt
                results.append(info)
            except Exception as e:
                print("  ERROR extracting:", e)
            time.sleep(0.6)

        print(f"Saving results to {OUTPUT_CSV}...")
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["municipality", "mayor_name", "emails", "source_url"])
            for r in results:
                writer.writerow([r["municipality"], r["mayor"], "; ".join(r["emails"]), r["url"]])

        print("Done.")
        total_with_emails = sum(1 for r in results if r["emails"])
        print(f"  {len(results)} pages visited, {total_with_emails} with at least one email found.")
        print(f"CSV file saved as: {OUTPUT_CSV}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
