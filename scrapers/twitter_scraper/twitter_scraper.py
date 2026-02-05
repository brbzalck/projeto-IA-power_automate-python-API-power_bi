import json
import time
from datetime import datetime, timedelta, timezone
import os
import yaml
from playwright.sync_api import sync_playwright

# ========================
# Paths
# ========================

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
OUTPUT_PATH = os.path.join(BASE_DIR, "output", "twitter_raw.json")
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")
COOKIES_PATH = os.path.join(os.path.dirname(__file__), "cookies.json")


# ========================
# Config loader
# ========================


def load_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ========================
# Cookies loader
# ========================


def load_cookies(context):
    if not os.path.exists(COOKIES_PATH):
        raise FileNotFoundError("twitter_cookies.json não encontrado")

    with open(COOKIES_PATH, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    # Corrige sameSite se necessário
    for c in cookies:
        if "sameSite" in c and c["sameSite"] not in ["Strict", "Lax", "None"]:
            c["sameSite"] = "Lax"

    context.add_cookies(cookies)


# ========================
# Main scraper
# ========================


def run_scrape():
    cfg = load_config()

    days_back = cfg.get("days_back", 1)

    until_date = datetime.now(timezone.utc).date()
    since_date = until_date - timedelta(days=days_back)

    since = since_date.strftime("%Y-%m-%d")
    until = until_date.strftime("%Y-%m-%d")

    search_url = cfg["search_url_template"].format(since=since, until=until)
    scroll_times = cfg.get("scroll_times", 30)
    scroll_pause = cfg.get("scroll_pause", 2)
    timeout = cfg.get("timeout", 60000)

    tweets_collected = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        load_cookies(context)

        page = context.new_page()

        try:
            page.goto(search_url, timeout=timeout, wait_until="domcontentloaded")
            # Espera extra garantida para o feed aparecer
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"[ERRO] Timeout ou falha ao carregar X: {e}")
            browser.close()
            return

        # Variável para controlar o "Fim da Página"
        last_height = page.evaluate("document.body.scrollHeight")
        consecutive_no_change = 0

        for i in range(scroll_times):
            # Coleta os artigos visíveis
            articles = page.query_selector_all("article")

            # Pequena otimização: se não achou articles, espera um pouco mais antes de desistir
            if not articles:
                time.sleep(1)
                articles = page.query_selector_all("article")

            for art in articles:
                try:
                    # Captura simples
                    text = art.inner_text()
                    tweets_collected.append(
                        {"text": text, "raw_html": art.inner_html()}
                    )
                except:
                    continue

            # Scroll
            page.mouse.wheel(0, 3000)
            time.sleep(scroll_pause)

            # CORREÇÃO 2: Verificação de "Fim da Linha" (Early Exit)
            new_height = page.evaluate("document.body.scrollHeight")

            if new_height == last_height:
                consecutive_no_change += 1
                # Se a altura não mudou por 3 tentativas seguidas, assumimos que acabou
                if consecutive_no_change >= 3:
                    print(
                        f"[INFO] Fim dos resultados detectado na rolagem {i+1}. Encerrando..."
                    )
                    break
            else:
                consecutive_no_change = 0  # Reset se a página cresceu

            last_height = new_height

        browser.close()

    # Remove duplicados por texto
    if tweets_collected:
        unique = {t["text"]: t for t in tweets_collected}.values()

        os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(list(unique), f, ensure_ascii=False, indent=2)

        print(f"[DONE] Saved {len(unique)} raw tweets -> {OUTPUT_PATH}")
    else:
        print("[AVISO] Nenhum tweet coletado. Verifique os Cookies ou a Busca.")


# ========================
# Entry point
# ========================

if __name__ == "__main__":
    run_scrape()
