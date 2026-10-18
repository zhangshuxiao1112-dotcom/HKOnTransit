"""Optional real-browser smoke check against a locally running server.

Install playwright and its Chromium binary in your own environment, start
./run.sh, then run: python tests/browser_smoke.py
This test uses real APIs; third-party service availability can affect results.
"""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    for width, height in ((1400, 900), (390, 844)):
        page = browser.new_page(viewport={"width": width, "height": height})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://127.0.0.1:8000", wait_until="domcontentloaded")
        page.locator('[data-screen="boarding"]').click()
        page.wait_for_function("document.querySelector('#stopSelect').options.length > 1", timeout=40000)
        page.locator('#lookupEta').click()
        page.wait_for_function("document.querySelector('#etaHealth').textContent !== 'Checking…'", timeout=15000)
        assert page.locator('html').get_attribute('lang') == 'en'
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors, errors
        page.close()
    browser.close()
