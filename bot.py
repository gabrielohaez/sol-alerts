import os
import json
import time
import requests

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
SEEN_FILE = "seen.json"

MIN_LIQUIDITY_USD = 5000      # skip tokens with tiny liquidity
MAX_ALERTS_PER_RUN = 5        # avoid spamming the channel

PROFILES_URL = "https://api.dexscreener.com/token-profiles/latest/v1"
PAIRS_URL = "https://api.dexscreener.com/latest/dex/tokens/{addr}"


def load_seen():
    try:
        with open(SEEN_FILE) as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(sorted(seen)[-2000:], f)


def get_new_solana_tokens():
    r = requests.get(PROFILES_URL, timeout=20)
    r.raise_for_status()
    return [d for d in r.json() if d.get("chainId") == "solana"]


def get_best_pair(addr):
    r = requests.get(PAIRS_URL.format(addr=addr), timeout=20)
    r.raise_for_status()
    pairs = r.json().get("pairs") or []
    pairs = [p for p in pairs if p.get("chainId") == "solana"]
    if not pairs:
        return None
    return max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd", 0) or 0)


def fmt_usd(n):
    if n is None:
        return "n/a"
    if n >= 1_000_000:
        return f"${n/1_000_000:.2f}M"
    if n >= 1_000:
        return f"${n/1_000:.1f}K"
    return f"${n:.0f}"


def red_flags(pair, profile):
    flags = []
    liq = (pair.get("liquidity") or {}).get("usd") or 0
    if liq < 10000:
        flags.append("Low liquidity")
    txns = (pair.get("txns") or {}).get("h24") or {}
    buys, sells = txns.get("buys", 0), txns.get("sells", 0)
    if buys + sells > 20 and sells > buys * 2:
        flags.append("Heavy selling")
    if not profile.get("links"):
        flags.append("No website or socials listed")
    return flags


def build_message(pair, profile):
    base = pair.get("baseToken") or {}
    name = base.get("name", "Unknown")
    sym = base.get("symbol", "?")
    addr = base.get("address", "")
    liq = (pair.get("liquidity") or {}).get("usd")
    mc = pair.get("marketCap") or pair.get("fdv")
    vol = (pair.get("volume") or {}).get("h24")
    chg = (pair.get("priceChange") or {}).get("h1")
    url = pair.get("url", f"https://dexscreener.com/solana/{addr}")
    flags = red_flags(pair, profile)

    lines = [
        f"NEW SOLANA TOKEN: {name} (${sym})",
        "",
        f"Liquidity: {fmt_usd(liq)}",
        f"Market cap: {fmt_usd(mc)}",
        f"24h volume: {fmt_usd(vol)}",
        f"1h change: {chg if chg is not None else 'n/a'}%",
        "",
        f"Contract: {addr}",
        f"Chart: {url}",
        f"Rug check: https://rugcheck.xyz/tokens/{addr}",
        "",
    ]
    if flags:
        lines.append("Flags: " + ", ".join(flags))
    else:
        lines.append("Flags: none detected (still do your own research)")
    lines.append("")
    lines.append("Not financial advice. Most new tokens fail.")
    return "\n".join(lines)


def send(text):
    r = requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": "true"},
        timeout=20,
    )
    r.raise_for_status()


def main():
    seen = load_seen()
    sent = 0
    for profile in get_new_solana_tokens():
        addr = profile.get("tokenAddress")
        if not addr or addr in seen:
            continue
        seen.add(addr)
        try:
            pair = get_best_pair(addr)
        except Exception:
            continue
        if not pair:
            continue
        liq = (pair.get("liquidity") or {}).get("usd") or 0
        if liq < MIN_LIQUIDITY_USD:
            continue
        send(build_message(pair, profile))
        sent += 1
        time.sleep(2)
        if sent >= MAX_ALERTS_PER_RUN:
            break
    save_seen(seen)
    print(f"Done. Sent {sent} alerts.")


if __name__ == "__main__":
    main()
