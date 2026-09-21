"""
signal_check.py
----------------
SMA kesisim sinyali olustugunda Telegram'a bildirim gonderen basit script.
GERCEK ISLEM YAPMAZ - sadece "AL sinyali" / "SAT sinyali" mesaji atar.

GitHub Actions uzerinde zamanlanmis olarak (ör. her 15 dakikada bir)
calistirilmak icin tasarlandi. Her calistirmada Binance'in herkese acik
fiyat API'sinden son mumlari ceker, en son kapanan mumda golden-cross /
death-cross olusmus mu diye bakar. Calistirmalar arasinda durum TUTMAZ
(stateless) - bu yuzden calistirma sikligi INTERVAL'a yakin olmali,
yoksa arada olusan bir sinyal kacabilir.

Ortam degiskenleri:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   (zorunlu)
    SYMBOL, INTERVAL, FAST_SMA, SLOW_SMA   (opsiyonel, varsayilanlari var)
"""

import os
import sys

import requests

SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
INTERVAL = os.getenv("INTERVAL", "15m")
FAST_SMA = int(os.getenv("FAST_SMA", "9"))
SLOW_SMA = int(os.getenv("SLOW_SMA", "21"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8252437697:AAEz1kWw9Zn0ST-hneFVN7oL76jZxFnkPEQ")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "8252437697")


def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("UYARI: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID tanimli degil, mesaj gonderilemedi.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(
        url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=15
    )
    if resp.status_code != 200:
        print(f"Telegram gonderim hatasi: {resp.status_code} {resp.text}")


def fetch_closes(symbol: str, interval: str, limit: int) -> list:
    # data-api.binance.vision: Binance'in herkese acik piyasa verisi icin
    # ayirdigi, bulut/CI sunucularindan (ör. GitHub Actions) da erisilebilen
    # adres. api.binance.com bazi bulut IP araliklarini engelleyebiliyor.
    url = "https://data-api.binance.vision/api/v3/klines"
    resp = requests.get(
        url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=15
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Binance API hatasi {resp.status_code}: {resp.text[:300]}")
    rows = resp.json()
    return [float(r[4]) for r in rows]


def sma(values: list, period: int) -> float:
    return sum(values[-period:]) / period


def check_signal(closed: list, fast: int, slow: int):
    """closed: en son mum SONA gelecek sekilde sirali kapanis fiyatlari."""
    prev_fast = sma(closed[:-1], fast)
    prev_slow = sma(closed[:-1], slow)
    curr_fast = sma(closed, fast)
    curr_slow = sma(closed, slow)

    if prev_fast <= prev_slow and curr_fast > curr_slow:
        return "BUY", curr_fast, curr_slow
    if prev_fast >= prev_slow and curr_fast < curr_slow:
        return "SELL", curr_fast, curr_slow
    return None, curr_fast, curr_slow


def main():
    send_telegram("Test mesaji - bot calisiyor!")
    limit = SLOW_SMA + 3
    try:
        closes = fetch_closes(SYMBOL, INTERVAL, limit)
    except Exception as e:
        print(f"HATA: Fiyat verisi cekilemedi -> {e}")
        sys.exit(1)

    closed = closes[:-1] if len(closes) > SLOW_SMA + 1 else closes
    if len(closed) < SLOW_SMA + 1:
        print("HATA: Yeterli mum verisi yok.")
        sys.exit(1)

    price = closed[-1]
    signal, fast_sma, slow_sma = check_signal(closed, FAST_SMA, SLOW_SMA)

    print(
        f"{SYMBOL} ({INTERVAL}) fiyat={price:.2f} "
        f"SMA{FAST_SMA}={fast_sma:.2f} SMA{SLOW_SMA}={slow_sma:.2f} sinyal={signal}"
    )

    if signal == "BUY":
        send_telegram(
            f"\U0001F7E2 AL sinyali - {SYMBOL}\n"
            f"Fiyat: {price:.2f}\n"
            f"SMA{FAST_SMA}: {fast_sma:.2f}  >  SMA{SLOW_SMA}: {slow_sma:.2f}\n"
            f"(Bu bir yatirim tavsiyesi degildir)"
        )
    elif signal == "SELL":
        send_telegram(
            f"\U0001F534 SAT sinyali - {SYMBOL}\n"
            f"Fiyat: {price:.2f}\n"
            f"SMA{FAST_SMA}: {fast_sma:.2f}  <  SMA{SLOW_SMA}: {slow_sma:.2f}\n"
            f"(Bu bir yatirim tavsiyesi degildir)"
        )
    else:
        print("Sinyal yok, bildirim gonderilmedi.")


if __name__ == "__main__":
    main()
