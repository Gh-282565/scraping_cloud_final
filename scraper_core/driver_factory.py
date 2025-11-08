import os, sys, traceback
import undetected_chromedriver as uc
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities

def make_uc_driver():
    print("[DRIVER] init UC...", flush=True)
    try:
        opts = uc.ChromeOptions()
        # Headless & stabilità
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        # Anti-automation & UA
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--disable-features=IsolateOrigins,site-per-process")
        opts.add_argument("--lang=en-US,en")
        opts.add_argument("--no-default-browser-check")
        opts.add_argument("--no-first-run")
        opts.add_argument(
            "--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        )

        # Non aspettare risorse terze: evita appesi infiniti
        caps = DesiredCapabilities.CHROME.copy()
        caps["pageLoadStrategy"] = "eager"

        driver = uc.Chrome(
            options=opts,
            browser_executable_path=os.getenv("CHROME_BIN", "/usr/bin/chromium"),
            driver_executable_path=os.getenv("CHROMEDRIVER", "/usr/bin/chromedriver"),
            use_subprocess=False,
            headless=True,
            desired_capabilities=caps,
        )
        # Timeout hard
        driver.set_page_load_timeout(25)
        driver.set_script_timeout(25)

        print("[DRIVER] UC OK", flush=True)
        return driver
    except Exception as e:
        print("[DRIVER][ERR] UC failed:", e, file=sys.stderr, flush=True)
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        raise


