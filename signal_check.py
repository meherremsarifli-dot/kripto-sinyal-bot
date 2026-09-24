"""
signal_check.py  (v2: trend + ATR stop + 1:3R)
------------------------------------------------
GERCEK ISLEM YAPMAZ - sadece Telegram'a bildirim gonderir.

Strateji (BTC 2020-2026 gercek verisiyle test edildi):
  1) Sadece ANA TREND YUKARIYKEN: fiyat > SMA200 ve SMA50 > SMA200
  2) Giris: fiyat geri cekilmeden sonra SMA21'in tekrar USTUNE kapatir
  3) Stop  = giris - 2 x ATR(14)      -> bu mesafe 1R
     Hedef = giris + 3 x stop mesafesi -> +3R (1:3R)
  4) Tek islem: acik (sanal) islem kapanmadan yeni AL gonderilmez

Her calistirmada son ~1000 mumu ceker ve stratejiyi bastan oynatir.
Boylece dosya/durum tutmadan acik islemi bilir ve SADECE son kapanan
mumdaki olaylari (yeni AL / hedef / stop) bildirir. Bu yuzden workflow
her mum kapanisinda BIR kez calismali (4h: gunde 6 kez).

Ortam degiskenleri:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID   (zorunlu)
    SYMBOL (BTCUSDT), INTERVAL (4h), RISK_PCT (1)
    SEND_STATUS=true -> durum mesaji da gonder (elle calistirinca)
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import requests

SYMBOL = os.getenv("SYMBOL", "BTCUSDT")
INTERVAL = os.getenv("INTERVAL", "4h")
RISK_PCT = float(os.getenv("RISK_PCT", "1"))
SEND_STATUS = os.getenv("SEND_STATUS", "false").lower() == "true"

TREND_SLOW, TREND_FAST, ENTRY_SMA = 200, 50, 21
ATR_PERIOD, ATR_MULT, REWARD_RISK = 14, 2.0, 3.0

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TR_TZ = timezone(timedelta(hours=3))  # Turkiye saati


def send_telegram(message: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("UYARI: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID tanimli degil, mesaj gonderilemedi.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": message}, timeout=15)
    if resp.status_code != 200:
        print(f"Telegram gonderim hatasi: {resp.status_code} {resp.text}")


def fetch_klines(symbol: str, interval: str, limit: int = 1000) -> list:
    # data-api.binance.vision: GitHub Actions'tan erisilebilen resmi adres
    url = "https://data-api.binance.vision/api/v3/klines"
    resp = requests.get(url, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"Binance API hatasi {resp.status_code}: {resp.text[:300]}")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    return [r for r in resp.json() if int(r[6]) < now_ms]  # sadece KAPANMIS mumlar


def sma(values: list, n: int) -> list:
    out, total = [None] * len(values), 0.0
    for i, v in enumerate(values):
        total += v
        if i >= n:
            total -= values[i - n]
        if i >= n - 1:
            out[i] = total / n
    return out


def atr(highs: list, lows: list, closes: list, n: int) -> list:
    """Wilder ATR (TradingView'deki ATR ile ayni hesap)."""
    tr = [highs[0] - lows[0]] + [
        max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        for i in range(1, len(closes))
    ]
    out = [None] * len(closes)
    out[n - 1] = sum(tr[:n]) / n
    for i in range(n, len(tr)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def replay(highs, lows, closes):
    """Stratejiyi mum mum oynatir. Donus: (acik_islem, olaylar)."""
    s21, s50, s200 = sma(closes, ENTRY_SMA), sma(closes, TREND_FAST), sma(closes, TREND_SLOW)
    a = atr(highs, lows, closes, ATR_PERIOD)
    pos, events = None, []
    for i in range(TREND_SLOW, len(closes)):
        if pos is not None:
            # once stop'a bak (ayni mumda ikisi de olduysa stop sayilir - temkinli)
            if lows[i] <= pos["stop"]:
                events.append((i, "STOP", pos))
                pos = None
            elif highs[i] >= pos["target"]:
                events.append((i, "TARGET", pos))
                pos = None
            continue
        uptrend = closes[i] > s200[i] and s50[i] > s200[i]
        crossed_up = closes[i - 1] <= s21[i - 1] and closes[i] > s21[i]
        if uptrend and crossed_up and a[i] > 0:
            risk = ATR_MULT * a[i]
            pos = {"i": i, "entry": closes[i], "stop": closes[i] - risk,
                   "target": closes[i] + REWARD_RISK * risk}
            events.append((i, "ENTRY", pos))
    uptrend_now = closes[-1] > s200[-1] and s50[-1] > s200[-1]
    return pos, events, uptrend_now


def pct(a: float, b: float) -> float:
    return (b / a - 1) * 100


def fmt_time(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, TR_TZ).strftime("%d.%m.%Y %H:%M")


def entry_message(p: dict, close_ms: int) -> str:
    stop_pct = -pct(p["entry"], p["stop"])
    size_pct = RISK_PCT / stop_pct * 100
    msg = (
        f"\U0001F7E2 AL KURULUMU (1:3R) - {SYMBOL} {INTERVAL}\n"
        f"Mum kapanışı: {fmt_time(close_ms)} (TR)\n\n"
        f"Giriş (şu anki fiyat civarı): {p['entry']:.2f}\n"
        f"\U0001F6D1 Stop:  {p['stop']:.2f}  (-%{stop_pct:.1f} = -1R)\n"
        f"\U0001F3AF Hedef: {p['target']:.2f}  (+%{stop_pct * REWARD_RISK:.1f} = +3R)\n\n"
    )
    if size_pct <= 100:
        msg += (
            f"\U0001F4D0 %{RISK_PCT:g} risk için pozisyon: sermayenin %{size_pct:.0f} kadarı\n"
            f"Örnek: 1000$ sermaye -> {10 * size_pct:.0f}$'lık alım. "
            f"Stop olursa -{10 * RISK_PCT:.0f}$, hedef gelirse +{10 * RISK_PCT * REWARD_RISK:.0f}$\n\n"
        )
    else:
        msg += (
            f"⚠️ Stop çok yakın: %{RISK_PCT:g} risk için sermayeden büyük pozisyon gerekir. "
            f"Spot'ta en fazla sermayen kadar al (risk %{stop_pct:.1f} olur) ya da bu kurulumu atla.\n\n"
        )
    msg += (
        "Stop ve hedefi girişle birlikte borsaya gir (OCO emri). "
        "Mesajı geç gördüysen ve fiyat girişten %1'den fazla yukarı kaçtıysa bu işlemi atla.\n"
        "(Yatırım tavsiyesi değildir)"
    )
    return msg


def exit_message(kind: str, p: dict) -> str:
    if kind == "TARGET":
        return (
            f"✅ HEDEF GELDİ: +3R - {SYMBOL} {INTERVAL}\n"
            f"Giriş {p['entry']:.2f} -> Hedef {p['target']:.2f} (+%{pct(p['entry'], p['target']):.1f})"
        )
    return (
        f"❌ STOP: -1R - {SYMBOL} {INTERVAL}\n"
        f"Giriş {p['entry']:.2f} -> Stop {p['stop']:.2f} (-%{-pct(p['entry'], p['stop']):.1f})\n"
        "1:3R'de bu normal: işlemlerin çoğu stopla biter, kârı az sayıdaki +3R'ler getirir."
    )


def status_message(price, pos, events, uptrend, open_times) -> str:
    lines = [f"\U0001F4CA Durum - {SYMBOL} {INTERVAL}", f"Fiyat: {price:.2f}"]
    lines.append(
        "Ana trend: YUKARI ✅ (AL kurulumu aranıyor)" if uptrend
        else "Ana trend: YUKARI DEĞİL ⛔ (trend dönene kadar AL gelmez, bilinçli)"
    )
    if pos:
        lines.append(f"Açık işlem: VAR - giriş {pos['entry']:.2f}, stop {pos['stop']:.2f}, hedef {pos['target']:.2f}")
    else:
        lines.append("Açık işlem: yok")
    closed = [(i, k) for i, k, p in events if k != "ENTRY"][-3:]
    if closed:
        lines.append("Son işlemler: " + ", ".join(
            f"{'+3R' if k == 'TARGET' else '-1R'} ({fmt_time(open_times[i])[:5]})" for i, k in reversed(closed)))
    lines.append("Bot çalışıyor ✅")
    return "\n".join(lines)


def main():
    try:
        rows = fetch_klines(SYMBOL, INTERVAL)
    except Exception as e:
        print(f"HATA: Fiyat verisi cekilemedi -> {e}")
        sys.exit(1)
    if len(rows) < TREND_SLOW + 50:
        print("HATA: Yeterli mum verisi yok.")
        sys.exit(1)

    open_times = [int(r[0]) for r in rows]
    highs = [float(r[2]) for r in rows]
    lows = [float(r[3]) for r in rows]
    closes = [float(r[4]) for r in rows]
    last = len(closes) - 1
    last_close_ms = int(rows[-1][6]) + 1

    pos, events, uptrend = replay(highs, lows, closes)
    print(f"{SYMBOL} {INTERVAL} son mum {fmt_time(last_close_ms)} TR, fiyat={closes[-1]:.2f}, "
          f"trend={'YUKARI' if uptrend else 'degil'}, acik islem={'var' if pos else 'yok'}")

    sent = False
    for i, kind, p in events:
        if i == last:  # sadece son kapanan mumdaki olaylar -> tekrar bildirim olmaz
            send_telegram(entry_message(p, last_close_ms) if kind == "ENTRY" else exit_message(kind, p))
            print(f"Bildirim gonderildi: {kind}")
            sent = True

    close_dt = datetime.fromtimestamp(last_close_ms / 1000, timezone.utc)
    weekly = close_dt.weekday() == 0 and close_dt.hour == 8 and close_dt.minute == 0  # Pzt 11:00 TR
    if SEND_STATUS or weekly:
        send_telegram(status_message(closes[-1], pos, events, uptrend, open_times))
        print("Durum mesaji gonderildi.")
    elif not sent:
        print("Yeni olay yok, bildirim gonderilmedi.")


if __name__ == "__main__":
    main()
