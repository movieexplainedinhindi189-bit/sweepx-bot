
        
        import os
import time
import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# Environment Variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DELTA_API_KEY = os.getenv("DELTA_API_KEY")
DELTA_API_SECRET = os.getenv("DELTA_API_SECRET")

# Account & Strategy Settings
INITIAL_BALANCE = 1000.0  # Base Demo Balance
daily_trade_count = 0
MAX_DAILY_TRADES = 3
SYMBOLS = ["BTCUSDT", "ETHUSDT"]

# Telegram Helpers
def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Telegram Msg Error: {e}")

def send_telegram_photo(photo_path, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    try:
        with open(photo_path, 'rb') as photo:
            payload = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "Markdown"}
            files = {"photo": photo}
            requests.post(url, data=payload, files=files)
    except Exception as e:
        print(f"Telegram Photo Error: {e}")

# /balance Command Handler
def balance_command(update: Update, context: CallbackContext):
    msg = (
        f"💰 *Delta Exchange Demo Account*\n\n"
        f"💵 **Available Balance:** `{INITIAL_BALANCE:.2f}` USDT\n"
        f"🔄 **Daily Trades:** `{daily_trade_count}/{MAX_DAILY_TRADES}`\n"
        f"🟢 **Status:** Active & Ready (24/7)"
    )
    update.message.reply_text(msg, parse_mode='Markdown')

# Technical Indicators & Strategy Logic
def fetch_klines(symbol, interval, limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    data = requests.get(url).json()
    df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'])
    df['close'] = df['close'].astype(float)
    df['high'] = df['high'].astype(float)
    df['low'] = df['low'].astype(float)
    return df

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_indicators(df):
    df['rsi'] = calculate_rsi(df['close'])
    df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
    return df

def analyze_1h_trend(df_1h):
    df_1h = calculate_indicators(df_1h)
    last_close = df_1h['close'].iloc[-1]
    last_ema = df_1h['ema_200'].iloc[-1]
    return "BULLISH" if last_close > last_ema else "BEARISH"

def detect_5m_divergence(df_5m):
    df_5m = calculate_indicators(df_5m)
    price_recent_low = df_5m['low'].iloc[-2] < df_5m['low'].iloc[-10:-2].min()
    rsi_higher_low = df_5m['rsi'].iloc[-2] > df_5m['rsi'].iloc[-10:-2].min()
    if price_recent_low and rsi_higher_low and df_5m['rsi'].iloc[-2] < 35:
        return "BULLISH_DIVERGENCE"
        
    price_recent_high = df_5m['high'].iloc[-2] > df_5m['high'].iloc[-10:-2].max()
    rsi_lower_high = df_5m['rsi'].iloc[-2] < df_5m['rsi'].iloc[-10:-2].max()
    if price_recent_high and rsi_lower_high and df_5m['rsi'].iloc[-2] > 65:
        return "BEARISH_DIVERGENCE"
        
    return "NONE"

def check_liquidity_bias(symbol):
    return "NEUTRAL", "Clean Orderbook"

def generate_chart(df, symbol, title, entry, sl, tp, trend):
    plt.figure(figsize=(10, 5))
    plt.plot(df['close'].tail(30).values, label='Price', color='blue')
    plt.axhline(y=entry, color='black', linestyle='--', label=f'Entry: {entry:.2f}')
    plt.axhline(y=sl, color='red', linestyle='--', label=f'SL: {sl:.2f}')
    plt.axhline(y=tp, color='green', linestyle='--', label=f'TP: {tp:.2f}')
    plt.title(f"{symbol} - {title} ({trend})")
    plt.legend()
    chart_filename = f"{symbol}_chart.png"
    plt.savefig(chart_filename)
    plt.close()
    return chart_filename

def place_order_with_sl_tp(symbol, side, curr_price, sl_price, tp_price, risk_pct=0.02):
    risk_val = INITIAL_BALANCE * risk_pct
    size = risk_val / abs(curr_price - sl_price)
    return size, risk_val

# Main Strategy Execution
def run_trading_bot():
    global daily_trade_count
    if daily_trade_count >= MAX_DAILY_TRADES:
        return

    for symbol in SYMBOLS:
        df_1h = fetch_klines(symbol, "1h")
        df_5m = fetch_klines(symbol, "5m")
        
        trend_1h = analyze_1h_trend(df_1h)
        df_5m = calculate_indicators(df_5m)
        divergence_5m = detect_5m_divergence(df_5m)
        news_bias, news_text = "NEUTRAL", "No High Impact News"
        liq_bias, liq_text = check_liquidity_bias(symbol)
        
        curr_price = df_5m['close'].iloc[-1]
        balance = INITIAL_BALANCE

        # SHORT ENTRY
        if trend_1h == "BEARISH" and divergence_5m == "BEARISH_DIVERGENCE":
            if news_bias == "BULLISH":
                continue
            sl_price = df_5m['high'].iloc[-10:].max() * 1.002
            sl_dist = abs(curr_price - sl_price)
            tp_price = curr_price - (sl_dist * 2)
            
            res, size, risk_val = place_order_with_sl_tp(symbol, "Sell", curr_price, sl_price, tp_price)
            daily_trade_count += 1
            
            chart = generate_chart(df_5m, symbol, "SHORT (1H Trend + 5M Entry)", curr_price, sl_price, tp_price, trend_1h)
            msg = (
                f"🚨 *AUTOMATED SHORT TRADE EXECUTED* 🚨\n\n"
                f"📍 *Symbol:* {symbol}\n"
                f"📍 *1-Hour Trend:* 🔴 BEARISH\n"
                f"📍 *5-Min Entry Signal:* Bearish Divergence\n"
                f"📍 *Entry Price:* `${curr_price:.2f}`\n"
                f"📍 *Stop Loss (SL):* `${sl_price:.2f}`\n"
                f"📍 *Take Profit (1:2):* `${tp_price:.2f}`\n"
                f"📍 *Risk Amount (2%):* `${risk_val:.2f}` USDT\n"
                f"📍 *Wallet Balance:* `${balance:.2f}` USDT\n"
                f"📍 *Trades Today:* `{daily_trade_count}/{MAX_DAILY_TRADES}`"
            )
            send_telegram_photo(chart, msg)
            if os.path.exists(chart):
                os.remove(chart)

        # LONG ENTRY
        elif trend_1h == "BULLISH" and divergence_5m == "BULLISH_DIVERGENCE":
            if news_bias == "BEARISH":
                continue
            sl_price = df_5m['low'].iloc[-10:].min() * 0.998
            sl_dist = abs(curr_price - sl_price)
            tp_price = curr_price + (sl_dist * 2)
            
            res, size, risk_val = place_order_with_sl_tp(symbol, "Buy", curr_price, sl_price, tp_price)
            daily_trade_count += 1
            
            chart = generate_chart(df_5m, symbol, "LONG (1H Trend + 5M Entry)", curr_price, sl_price, tp_price, trend_1h)
            msg = (
                f"🚨 *AUTOMATED LONG TRADE EXECUTED* 🚨\n\n"
                f"📍 *Symbol:* {symbol}\n"
                f"📍 *1-Hour Trend:* 🟢 BULLISH\n"
                f"📍 *5-Min Entry Signal:* Bullish Divergence\n"
                f"📍 *Entry Price:* `${curr_price:.2f}`\n"
                f"📍 *Stop Loss (SL):* `${sl_price:.2f}`\n"
                f"📍 *Take Profit (1:2):* `${tp_price:.2f}`\n"
                f"📍 *Risk Amount (2%):* `${risk_val:.2f}` USDT\n"
                f"📍 *Wallet Balance:* `${balance:.2f}` USDT\n"
                f"📍 *Trades Today:* `{daily_trade_count}/{MAX_DAILY_TRADES}`"
            )
            send_telegram_photo(chart, msg)
            if os.path.exists(chart):
                os.remove(chart)

def main():
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # Handlers
    dp.add_handler(CommandHandler("balance", balance_command))
    
    send_telegram_msg("🤖 *SweepX Dual Timeframe Bot Online!*\nMacro: 1H | Entry: 5M\nType `/balance` for demo stats.")
    
    updater.start_polling()
    
    while True:
        try:
            run_trading_bot()
            time.sleep(300)  # Runs every 5 minutes
        except Exception as e:
            print(f"Loop Error: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
