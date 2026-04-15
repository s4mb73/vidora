"""
Diagnostic: force Instagram login with credentials and check explore page.
"""

import sys, time, hashlib, requests, urllib3
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
urllib3.disable_warnings()

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chromium.options import ChromiumOptions
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException
except ImportError:
    print("ERROR: pip install selenium")
    sys.exit(1)

ML_EMAIL     = "innoviteecom@gmail.com"
ML_PASS_FILE = "C:/vidora/pass.txt"
FOLDER_ID    = "3fcc8abd-1429-45ea-9383-1e71db538bc0"
PROFILE_ID   = "440c4445-407b-48d9-bbd1-c8e203477c3d"
MLX_API      = "https://api.multilogin.com"
MLX_LAUNCHER = "https://127.0.0.1:45001/api/v2"
LOCALHOST    = "http://127.0.0.1"

IG_USER_FILE = "C:/vidora/ig_user.txt"
IG_PASS_FILE = "C:/vidora/ig_pass.txt"
SCREENSHOT   = "C:/vidora/screenshots/explore_debug.png"


def signin():
    pw = open(ML_PASS_FILE, encoding='utf-8').read().strip()
    h = hashlib.md5(pw.encode()).hexdigest()
    r = requests.post(f"{MLX_API}/user/signin",
        json={"email": ML_EMAIL, "password": h},
        headers={"Content-Type": "application/json", "Accept": "application/json"})
    if r.status_code != 200:
        raise Exception(f"Multilogin login failed: {r.text}")
    print("  Multilogin: authenticated")
    return r.json()["data"]["token"]


def start_profile(token):
    r = requests.get(
        f"{MLX_LAUNCHER}/profile/f/{FOLDER_ID}/p/{PROFILE_ID}/start?automation_type=selenium",
        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
        verify=False)
    if r.status_code != 200:
        raise Exception(f"Failed to start profile: {r.text}")
    port = r.json()["data"]["port"]
    print(f"  Profile started on port {port}")
    return port


def stop_profile(token):
    try:
        requests.get(
            f"https://127.0.0.1:45001/api/v1/profile/stop/p/{PROFILE_ID}",
            headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
            verify=False)
        print("  Profile stopped")
    except Exception:
        pass


def connect_driver(port):
    options = ChromiumOptions()
    driver = webdriver.Remote(
        command_executor=f"{LOCALHOST}:{port}",
        options=options)
    print("  Selenium: connected")
    return driver


def run_diagnostic(driver):
    ig_user = open(IG_USER_FILE, encoding='utf-8').read().strip()
    ig_pass = open(IG_PASS_FILE, encoding='utf-8').read().strip()

    if not ig_user or not ig_pass:
        print("\nPlease add Instagram credentials to ig_user.txt and ig_pass.txt")
        return

    # --- Step 1: check current session ---
    print(f"\n[1] Checking current session at instagram.com ...")
    driver.get("https://www.instagram.com/")
    time.sleep(7)
    print(f"    URL   : {driver.current_url}")
    print(f"    Title : {driver.title}")
    already_in = "accounts/login" not in driver.current_url
    print(f"    Status: {'LOGGED IN' if already_in else 'NOT LOGGED IN'}")

    # --- Step 2: force navigate to login page and log in fresh ---
    print(f"\n[2] Navigating to login page to sign in as {ig_user} ...")
    driver.get("https://www.instagram.com/accounts/login/")
    time.sleep(6)

    print(f"    URL   : {driver.current_url}")

    if "accounts/login" not in driver.current_url:
        # Was redirected away - already logged in with a session
        # Log out first so we can log in with our credentials
        print("    Redirected away from login - logging out first ...")
        driver.get("https://www.instagram.com/accounts/logout/?hl=en")
        time.sleep(5)
        driver.get("https://www.instagram.com/accounts/login/")
        time.sleep(6)
        print(f"    URL after logout+redirect: {driver.current_url}")

    wait = WebDriverWait(driver, 20)

    # --- Step 3: fill in login form ---
    print(f"\n[3] Filling login form ...")
    # Try multiple selectors - Instagram has changed field attributes before
    user_field = None
    for selector_type, selector in [
        (By.NAME,        "username"),
        (By.CSS_SELECTOR, "input[autocomplete='username']"),
        (By.CSS_SELECTOR, "input[type='text']"),
        (By.XPATH,        "//input[@placeholder[contains(.,'username') or contains(.,'email') or contains(.,'Mobile')]]"),
    ]:
        try:
            user_field = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((selector_type, selector))
            )
            print(f"    Found username field via: {selector}")
            break
        except TimeoutException:
            continue

    if user_field is None:
        print("    ERROR: could not find username field with any selector")
        print(f"    Current URL: {driver.current_url}")
        print(f"    Page title:  {driver.title}")
        # Print all input fields found on page for debugging
        inputs = driver.find_elements(By.TAG_NAME, "input")
        print(f"    Input fields on page ({len(inputs)}):")
        for inp in inputs:
            print(f"      type={inp.get_attribute('type')} name={inp.get_attribute('name')} "
                  f"autocomplete={inp.get_attribute('autocomplete')} "
                  f"placeholder={inp.get_attribute('placeholder')}")
        Path(SCREENSHOT).parent.mkdir(parents=True, exist_ok=True)
        driver.save_screenshot(SCREENSHOT)
        print(f"    Screenshot saved to {SCREENSHOT}")
        return

    user_field.clear()
    for ch in ig_user:
        user_field.send_keys(ch)
        time.sleep(0.05)

    # Small pause then find password field - try multiple selectors
    time.sleep(1)
    pass_field = None
    for selector_type, selector in [
        (By.NAME,         "password"),
        (By.CSS_SELECTOR, "input[type='password']"),
        (By.CSS_SELECTOR, "input[autocomplete='current-password']"),
    ]:
        try:
            pass_field = WebDriverWait(driver, 8).until(
                EC.element_to_be_clickable((selector_type, selector))
            )
            print(f"    Found password field via: {selector}")
            break
        except TimeoutException:
            continue

    if pass_field is None:
        print("    ERROR: could not find password field")
        inputs = driver.find_elements(By.TAG_NAME, "input")
        print(f"    Input fields on page ({len(inputs)}):")
        for inp in inputs:
            print(f"      type={inp.get_attribute('type')} name={inp.get_attribute('name')} "
                  f"autocomplete={inp.get_attribute('autocomplete')}")
        Path(SCREENSHOT).parent.mkdir(parents=True, exist_ok=True)
        driver.save_screenshot(SCREENSHOT)
        print(f"    Screenshot saved to {SCREENSHOT}")
        return

    pass_field.clear()
    for ch in ig_pass:
        pass_field.send_keys(ch)
        time.sleep(0.05)

    time.sleep(0.5)
    print(f"    Submitting ...")
    submitted = False
    for selector_type, selector in [
        (By.CSS_SELECTOR, "button[type='submit']"),
        (By.XPATH,        "//button[contains(text(),'Log in') or contains(text(),'Log In')]"),
        (By.XPATH,        "//div[@role='button'][contains(text(),'Log')]"),
    ]:
        try:
            btn = driver.find_element(selector_type, selector)
            btn.click()
            submitted = True
            print(f"    Clicked submit via: {selector}")
            break
        except Exception:
            continue

    if not submitted:
        # Last resort: press Enter in the password field
        from selenium.webdriver.common.keys import Keys
        pass_field.send_keys(Keys.RETURN)
        print("    Submitted via Enter key")

    # --- Step 4: wait for redirect ---
    try:
        wait.until(lambda d: "accounts/login" not in d.current_url)
        print(f"    Redirected to: {driver.current_url}")
    except TimeoutException:
        print("    ERROR: Still on login page after 20s")
        print(f"    URL: {driver.current_url}")
        Path(SCREENSHOT).parent.mkdir(parents=True, exist_ok=True)
        driver.save_screenshot(SCREENSHOT)
        print(f"    Screenshot saved to {SCREENSHOT} - check for wrong password / captcha")
        return

    time.sleep(3)

    # --- Handle 2FA / email verification code if prompted ---
    if "codeentry" in driver.current_url or "checkpoint" in driver.current_url or "challenge" in driver.current_url:
        code_file = Path("C:/vidora/ig_code.txt")
        code_file.write_text("", encoding="utf-8")  # clear any old code

        print(f"\n  *** VERIFICATION CODE REQUIRED ***")
        print(f"  Instagram sent a code to your email.")
        print(f"  1. Check your inbox")
        print(f"  2. Write ONLY the code into: C:\\vidora\\ig_code.txt")
        print(f"  Waiting up to 3 minutes...")

        code = None
        for _ in range(90):   # poll every 2s for up to 3 min
            time.sleep(2)
            val = code_file.read_text(encoding="utf-8").strip()
            if val:
                code = val
                break

        if not code:
            print("    ERROR: No code received within 3 minutes - aborting")
            Path(SCREENSHOT).parent.mkdir(parents=True, exist_ok=True)
            driver.save_screenshot(SCREENSHOT)
            return

        print(f"    Code received: {code} - submitting...")

        try:
            code_field = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "input[name='verificationCode'], input[placeholder='Code'], input[autocomplete='one-time-code'], input[type='text'], input[type='number']"))
            )
            code_field.clear()
            code_field.send_keys(code)
            time.sleep(0.5)

            # Try clicking Continue button
            submitted = False
            for xpath in ["//button[contains(text(),'Continue')]",
                          "//button[contains(text(),'Confirm')]",
                          "//button[contains(text(),'Submit')]"]:
                try:
                    driver.find_element(By.XPATH, xpath).click()
                    submitted = True
                    break
                except Exception:
                    pass
            if not submitted:
                from selenium.webdriver.common.keys import Keys
                code_field.send_keys(Keys.RETURN)

            time.sleep(5)
            print(f"    URL after code: {driver.current_url}")
        except Exception as e:
            print(f"    ERROR entering code: {e}")
            return

    # Dismiss "Save login info" / notification prompts
    for xpath in ["//button[contains(text(),'Not Now')]",
                  "//button[contains(text(),'Not now')]",
                  "//button[contains(text(),'Skip')]"]:
        try:
            driver.find_element(By.XPATH, xpath).click()
            time.sleep(2)
            break
        except Exception:
            pass

    print(f"\n[4] Login complete")
    print(f"    URL   : {driver.current_url}")
    print(f"    Title : {driver.title}")

    # --- Step 5: navigate to explore ---
    print(f"\n[5] Navigating to instagram.com/explore ...")
    driver.get("https://www.instagram.com/explore/")
    time.sleep(10)

    print(f"    URL   : {driver.current_url}")
    print(f"    Title : {driver.title}")

    # --- Step 6: screenshot ---
    Path(SCREENSHOT).parent.mkdir(parents=True, exist_ok=True)
    driver.save_screenshot(SCREENSHOT)
    print(f"\n[6] Screenshot saved to {SCREENSHOT}")

    # --- Step 7: show all links ---
    links = driver.find_elements(By.CSS_SELECTOR, "a[href]")
    ig_links = [a.get_attribute("href") for a in links if "instagram.com" in (a.get_attribute("href") or "")]
    print(f"\n[7] Links on explore page: {len(links)} total, {len(ig_links)} instagram.com links")
    print("    All instagram.com links:")
    for l in ig_links:
        print(f"      {l}")


def main():
    print("=" * 50)
    print("  Instagram Login Diagnostic")
    print("=" * 50)

    token = signin()
    port = start_profile(token)
    time.sleep(3)
    driver = None

    try:
        driver = connect_driver(port)
        run_diagnostic(driver)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback; traceback.print_exc()
    finally:
        if driver:
            try: driver.quit()
            except Exception: pass
        stop_profile(token)


if __name__ == "__main__":
    main()
