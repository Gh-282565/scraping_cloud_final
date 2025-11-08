# scraper_core/driver_factory.py
import os, sys, traceback
import undetected_chromedriver as uc

def make_uc_driver():
    print("[DRIVER] init UC...", flush=True)
    try:
        opts = uc.ChromeOptions()
        # headless robusto per Render
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1920,1080")
        # opzionale: riduce rumorini/permessi
        opts.add_argument("--use-fake-ui-for-media-stream")
        opts.add_argument("--no-default-browser-check")
        opts.add_argument("--no-first-run")

        driver = uc.Chrome(
            options=opts,
            browser_executable_path=os.getenv("CHROME_BIN", "/usr/bin/chromium"),
            driver_executable_path=os.getenv("CHROMEDRIVER", "/usr/bin/chromedriver"),
            use_subprocess=False,
            headless=True,  # per compat vecchie versioni UC
        )
        print("[DRIVER] UC OK", flush=True)
        return driver
    except Exception as e:
        print("[DRIVER][ERR] UC failed:", e, file=sys.stderr, flush=True)
        print(traceback.format_exc(), file=sys.stderr, flush=True)
        raise

