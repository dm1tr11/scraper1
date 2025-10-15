#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Scrape mayor emails ("Кмет на община") from:
https://iisda.government.bg/ras/adm_structures/municipality_administrations

How it works:
 - Opens the main listing page with Selenium.
 - For each of the (9) pages it:
    - Collects the links to municipality detail pages visible on that page.
    - Opens each municipality page, searches for the official with title "Кмет на община",
      and extracts any email addresses found nearby (or any mailto links on the page).
 - Outputs results to CSV: municipality, mayor_name (if found), email (may be blank),
   source_url.
"""

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
HEADLESS = True   # set False while debugging to see the browser
MAX_PAGE_ITER = 20  # safety cap; site has 9 pages but we limit to avoid infinite loops
PAGE_WAIT_SECONDS = 5
# ===================================

email_re = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", re.UNICODE)

def find_emails_in_html(html):
    """Return list of unique emails found in html using regex."""
    found = set(email_re.findall(html))
    return sorted(found)

def setup_driver():
    options = webdriver.ChromeOptions()
    if HEADLESS:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # optional: run with a user-agent
    options.add_argument("user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/117.0 Safari/537.36")
    driver = webdriver.Chrome(options=options)  # ensure chromedriver is on PATH
    driver.set_page_load_timeout(60)
    return driver

def collect_municipality_links_from_page(driver):
    """
    On the listing page, collect links to municipality detail pages visible currently.
    The listing uses <a> links like "Общинска администрация - <name>".
    """
    soup = BeautifulSoup(driver.page_source, "lxml")
    links = []
    # find links that likely point to municipality detail pages:
    for a in soup.find_all("a", href=True):
        text = (a.get_text() or "").strip()
        # Heuristic: link text contains "Общинска администрация" or starts with municipality name
        if "Общинска администрация" in text or ("общинска администрация" in text.lower()):
            href = a["href"]
            full = urljoin(BASE, href)
            links.append((text, full))
        # also include links under the common listing format: "Община - X" style
        # (we include many candidates, dedupe later)
    # dedupe by URL
    seen = set()
    dedup = []
    for text, url in links:
        if url not in seen:
            seen.add(url)
            dedup.append((text, url))
    return dedup

def click_next_page(driver):
    """Click the link/button which says 'Следваща' (Next). Return True if clicked, False otherwise."""
    try:
        # Wait a short while and try to find an element with text 'Следваща'
        # There might be a link or button. Try multiple ways.
        wait = WebDriverWait(driver, 6)
        # try link first
        next_elem = None
        try:
            next_elem = driver.find_element(By.LINK_TEXT, "Следваща")
        except Exception:
            # try button-like element by xpath searching for exact text
            elems = driver.find_elements(By.XPATH, "//*[normalize-space(text())='Следваща']")
            if elems:
                next_elem = elems[0]
        if not next_elem:
            return False
        # scroll into view and click
        driver.execute_script("arguments[0].scrollIntoView(true);", next_elem)
        time.sleep(0.3)
        next_elem.click()
        return True
    except Exception as e:
        print("Could not click Next:", e)
        return False

def extract_mayor_from_municipality(driver, url):
    """
    Open municipality detail page and try to extract:
     - municipality name (from the page)
     - mayor name (label 'Кмет на община' usually appears)
     - mayor email(s)
    Returns a dict.
    """
    result = {"municipality": "", "mayor": "", "emails": [], "url": url}
    try:
        driver.get(url)
    except Exception:
        # try simple fallback navigation
        driver.get(url)
    # wait briefly for content
    time.sleep(1.0)
    soup = BeautifulSoup(driver.page_source, "lxml")

    # Municipality title heuristic: h1 or page header contains municipality name
    h1 = soup.find(["h1","h2"])
    if h1:
        result["municipality"] = h1.get_text(strip=True)

    # 1) Look for an element that contains the exact text "Кмет на община"
    mayor_elements = []
    for tag in soup.find_all(text=lambda t: t and "Кмет на община" in t):
        mayor_elements.append(tag)

    # If none found, look for "Кмет" (may catch other roles) and filter later
    if not mayor_elements:
        for tag in soup.find_all(text=lambda t: t and "Кмет" in t and "Общ." not in t):
            mayor_elements.append(tag)

    mayor_name = ""
    mayor_emails = set()

    # Strategy: for each matched text node, look at parent and siblings to find name and email
    for text_node in mayor_elements:
        parent = text_node.parent
        surrounding_html = "".join(str(x) for x in parent.find_all(recursive=True)) if parent else ""
        # try to find emails in the parent's HTML
        for e in find_emails_in_html(surrounding_html):
            mayor_emails.add(e)
        # try to extract a nearby name: often the name is in the next <td> or following <div>
        # look at next siblings
        # attempt: go up to parent's parent and search for the next <td> or strong/span following this node
        candidate = None
        if parent:
            # check next siblings
            sib = parent.find_next_sibling()
            if sib:
                candidate = sib.get_text(" ", strip=True)
            # check parent next sibling
            if not candidate and parent.parent:
                psib = parent.parent.find_next_sibling()
                if psib:
                    candidate = psib.get_text(" ", strip=True)
        if candidate:
            # sanitize candidate
            candidate = candidate.strip()
            if candidate and len(candidate) < 200:
                mayor_name = candidate
                break

    # 2) If no emails found yet, fallback: find any mailto: links on page
    if not mayor_emails:
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if href.startswith("mailto:"):
                # clean mailto: may contain name before email (mailto:email?subject=)
                addr = href.split(":",1)[1].split("?")[0]
                if email_re.match(addr):
                    mayor_emails.add(addr)

    # 3) Another fallback: search entire page text for emails
    if not mayor_emails:
        for e in find_emails_in_html(soup.get_text(" ")):
            mayor_emails.add(e)

    # 4) Try to find mayor name from structured blocks mentioning Кмет
    if not mayor_name:
        # search for elements that contain "Кмет" and contain another phrase that looks like a person's name
        # names usually are two words (First Last) with capital letters
        name_candidate_re = re.compile(r"[А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+){1,2}")
        for tag in soup.find_all(text=lambda t: t and "Кмет" in t):
            text = tag.strip()
            m = name_candidate_re.search(text)
            if m:
                mayor_name = m.group(0)
                break

    result["mayor"] = mayor_name
    result["emails"] = sorted(mayor_emails)
    return result

def main():
    driver = setup_driver()
    wait = WebDriverWait(driver, 15)

    try:
        print("Opening start URL...")
        driver.get(START_URL)
        time.sleep(1.2)

        all_municipality_links = []  # list of (link_text, url)

        # Iterate through pages by clicking "Следваща". On each page collect municipality links.
        page = 1
        while page <= MAX_PAGE_ITER:
            print(f"Collecting links on listing page {page} ...")
            # wait for page content to appear; we wait for any link under listing
            try:
                # a simple wait for presence of listings (we expect many <a>)
                wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "a")))
            except Exception:
                pass
            page_links = collect_municipality_links_from_page(driver)
            # append unique
            existing = set(u for _, u in all_municipality_links)
            new_count = 0
            for txt, url in page_links:
                if url not in existing:
                    all_municipality_links.append((txt, url))
                    existing.add(url)
                    new_count += 1
            print(f"  found {len(page_links)} candidate links on this page, {new_count} new")

            # try to click next
            clicked = click_next_page(driver)
            if not clicked:
                print("No 'Следваща' found or could not click — assuming last page.")
                break
            page += 1
            # wait for navigation to finish
            time.sleep(PAGE_WAIT_SECONDS)

        print(f"Total municipality links collected (candidates): {len(all_municipality_links)}")
        # If we got many duplicates or non-municipality links, we'll still visit each unique URL
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
                # If municipality label empty, use the link text as fallback
                if not info["municipality"]:
                    info["municipality"] = txt
                # if no emails found, leave empty list
                results.append(info)
            except Exception as e:
                print("  ERROR extracting:", e)
            # brief pause to be polite
            time.sleep(0.6)

        # Save to CSV
        print(f"Saving results to {OUTPUT_CSV} ...")
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["municipality", "mayor_name", "emails", "source_url"])
            for r in results:
                writer.writerow([r["municipality"], r["mayor"], "; ".join(r["emails"]), r["url"]])

        print("Done. Summary:")
        total_with_emails = sum(1 for r in results if r["emails"])
        print(f"  {len(results)} municipality pages visited, {total_with_emails} with at least one email found.")
        print(f"CSV file: {OUTPUT_CSV}")

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
