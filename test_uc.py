from undetected_chromedriver import Chrome
b = Chrome()
b.get("https://example.com")
print("Titolo:", b.title)
b.quit()
