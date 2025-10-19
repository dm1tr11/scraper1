from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time
import csv

# --- Setup Chrome (headless) ---
options = Options()
options.add_argument("--headless=new")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

service = Service()
driver = webdriver.Chrome(service=service, options=options)
wait = WebDriverWait(driver, 12)

BASE_URL = "https://iisda.government.bg/ras/adm_structures/municipality_administrations"
driver.get(BASE_URL)
time.sleep(3)

emails = []  # We'll only store the emails


def get_municipalities():
    """Return all municipality links on the current page."""
    items = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "li.list-item a")))
    return [(i.text.strip(), i) for i in items]


def extract_email_from_current_page():
    """Click 'Информация' under 'Кмет на община' and get the email."""
    try:
        mayor_block = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//div[contains(@class,'node-title') and normalize-space(text())='Кмет на община']/..")
        ))
        info_icon = mayor_block.find_element(By.CSS_SELECTOR, "div.show-icon[title='Информация']")
        driver.execute_script("arguments[0].click();", info_icon)
        time.sleep(1.5)

        email_div = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//*[contains(text(),'Електронна поща')]")
        ))
        text = email_div.text.strip()
        if "@" in text:
            return text.split("Електронна поща:")[-1].strip()
        else:
            sibling = email_div.find_element(By.XPATH, "following-sibling::*[1]")
            email = sibling.text.strip()
            return email if "@" in email else None
    except Exception:
        return None


# --- Main scraping loop ---
for page in range(1, 10):
    print(f"\n--- Scraping page {page} ---")
    municipalities = get_municipalities()

    for name, link in municipalities:
        print(f"→ {name}")
        try:
            driver.execute_script("arguments[0].click();", link)
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.node-title")))

            email = extract_email_from_current_page()
            if email:
                emails.append(email)
            print(f"   ✓ Email: {email or 'N/A'}")

            driver.back()
            wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "li.list-item a")))
        except Exception as e:
            print(f"   ✗ Error on {name}: {e}")
            driver.get(BASE_URL)
            wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, "li.list-item a")))

    try:
        next_button = driver.find_element(By.CSS_SELECTOR, "a.next")
        driver.execute_script("arguments[0].click();", next_button)
        time.sleep(3)
    except:
        print("No more pages.")
        break

driver.quit()

# --- Save only emails to CSV ---
with open("bulgarian_mayors_emails.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["Email"])
    for email in emails:
        writer.writerow([email])

print(f"\n✅ Done. Saved {len(emails)} emails to bulgarian_mayors_emails.csv")
