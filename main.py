import os
import time
import requests
import pandas as pd
import json

# Fetch Environment Variables
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

SYMBOLS = ["BTCUSDT", "ETHUSDT"]
STATE_FILE = "bot_state.json"

def send_telegram_message(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram tokens not configured!")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

def fetch_klines(symbol, interval, limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=10).json()
        df = pd.DataFrame(res, columns=[
            'time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'qav', 'num_trades', 'taker_base', 'taker_quote', 'ignore'
        ])
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        return df
    except Exception as e:
        print(f"Error fetching data for {symbol}: {e}")
        return None

def calculate_rsi(df, period=14):
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def check_liquidity_sweep(df):
    recent_high = df['high'].iloc[-20:-2].max()
    recent_low = df['low'].iloc[-20:-2].min()
    current_high = df['high'].iloc[-1]
    current_low = df['low'].iloc[-1]
    
    if current_high > recent_high:
        return "BULLISH_SWEEP"
    elif current_low < recent_low:
        return "BEARISH_SWEEP"
    return None

def process_bot():
    print("Checking market conditions...")
    for symbol in SYMBOLS:
        df_1h = fetch_klines(symbol, "1h")
        df_15m = fetch_klines(symbol, "15m")
        
        if df_1h is None or df_15m is None:
            continue
            
        sweep = check_liquidity_sweep(df_1h)
        df_15m['rsi'] = calculate_rsi(df_15m)
        current_rsi = df_15m['rsi'].iloc[-1]
        current_price = df_15m['close'].iloc[-1]
        
        if sweep == "BULLISH_SWEEP" and current_rsi < 35:
            msg = (
                f"🚨 *SweepX Signal Detected!*\n\n"
                f"• *Symbol:* {symbol}\n"
                f"• *Type:* LONG (Bullish Liquidity Sweep)\n"
                f"• *Price:* ${current_price:.2f}\n"
                f"• *RSI (15M):* {current_rsi:.2f}\n"
                f"• *Risk:* 1.5% | *R:R Target:* 1:2\n"
                f"• *Status:* Breakeven Trailing Active"
            )
            send_telegram_message(msg)
            
        elif sweep == "BEARISH_SWEEP" and current_rsi > 65:
            msg = (
                f"🚨 *SweepX Signal Detected!*\n\n"
                f"• *Symbol:* {symbol}\n"
                f"• *Type:* SHORT (Bearish Liquidity Sweep)\n"
                f"• *Price:* ${current_price:.2f}\n"
                f"• *RSI (15M):* {current_rsi:.2f}\n"
                f"• *Risk:* 1.5% | *R:R Target:* 1:2\n"
                f"• *Status:* Breakeven Trailing Active"
            )
            send_telegram_message(msg)

if __name__ == "__main__":
    send_telegram_message("🚀 *SweepX Bot Render par Live Ho Gaya Hai!* 24/7 Monitoring Active.")
    while True:
        try:
            process_bot()
            time.sleep(300) # Check every 5 minutes
        except Exception as e:
            print(f"Error in main loop: {e}")
            time.sleep(60)
          
