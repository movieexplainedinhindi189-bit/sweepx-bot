import os
import time
import datetime
import hmac
import hashlib
import json
import requests
import pandas as pd
import matplotlib.pyplot as plt
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# --- 1. KEEP-ALIVE WEB SERVER FOR RENDER 24/7 RUNTIME ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"SweepX Dual Timeframe (1H Trend + 5M Entry) Active 24/7")

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), SimpleHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# --- 2. CONFIGURATION & SECRETS ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
DELTA_API_KEY = os.environ.get("DELTA_API_KEY")
DELTA_API_SECRET = os.environ.get("DELTA_API_SECRET")

DELTA_BASE_URL = "https://api.delta.exchange"
SYMBOLS = ["BTCUSDT", "ETHUSDT"] # ONLY BTC & ETH

daily_trade_count = 0
current_day = datetime.datetime.utcnow().day

# --- 3. AUTO NEWS SENTIMENT PREDICTOR ---
def get_market_news_sentiment():
    """Predicts market mood using Fear & Greed Index."""
    try:
        url = "https://api.alternative.me/fng/"
        res = requests.get(url, timeout=5).json()
        val = int(res['data'][0]['value'])
        sentiment_text = res['data'][0]['value_classification']
        
        if val >= 65:
            bias = "BULLISH"
        elif val <= 35:
            bias = "BEARISH"
        else:
            bias = "NEUTRAL"
        return bias, f"{sentiment_text} ({val})"
    except Exception:
        return "NEUTRAL", "Neutral (50)"

# --- 4. COINGLASS / LIQUIDITY & OPEN INTEREST TRACKER ---
def check_liquidity_bias(symbol):
    """Checks Taker Long/Short ratio to detect liquidity pools."""
    try:
        vol_url = f"https://fapi.binance.com/fapi/v1/takerlongshortRatio?symbol={symbol}&period=15m&limit=1"
        vol_res = requests.get(vol_url, timeout=5).json()
        
        if vol_res and len(vol_res) > 0:
            buy_sell_ratio = float(vol_res[0]['buySellRatio'])
            if buy_sell_ratio > 1.15:
                return "SHORT_LIQUIDITY_ABOVE", f"Buyers Dominant (Ratio: {buy_sell_ratio:.2f})"
            elif buy_sell_ratio < 0.85:
                return "LONG_LIQUIDITY_BELOW", f"Sellers Dominant (Ratio: {buy_sell_ratio:.2f})"
        
        return "BALANCED", "Equal Liquidity On Both Sides"
    except Exception:
        return "BALANCED", "Liquidity Neutral"

# --- 5. DELTA EXCHANGE SIGNED API REQUESTS ---
def delta_request(method, path, payload=None):
    if not DELTA_API_KEY or not DELTA_API_SECRET:
        print("Delta API Credentials Missing!")
        return None
    
    timestamp = str(int(time.time()))
    body_str = json.dumps(payload) if payload else ""
    query_str = ""
    
    signature_data = method + timestamp + path + query_str + body_str
    signature = hmac.new(
        DELTA_API_SECRET.encode('utf-8'),
        signature_data.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    headers = {
        'api-key': DELTA_API_KEY,
        'timestamp': timestamp,
        'signature': signature,
        'Content-Type': 'application/json'
    }

    url = f"{DELTA_BASE_URL}{path}"
    try:
        if method == "GET":
            res = requests.get(url, headers=headers, timeout=10)
        elif method == "POST":
            res = requests.post(url, headers=headers, data=body_str, timeout=10)
        return res.json()
    except Exception as e:
        print(f"Delta API Request Error: {e}")
        return None

def get_wallet_balance():
    res = delta_request("GET", "/v2/wallet/balances")
    if res and res.get("success"):
        for asset in res.get("result", []):
            if asset.get("asset_symbol") == "USDT":
                return float(asset.get("balance", 0.0))
    return 100.0

def place_order_with_sl_tp(symbol, side, current_price, sl_price, tp_price, risk_pct=0.02):
    balance = get_wallet_balance()
    risk_amount = balance * risk_pct
    price_risk = abs(current_price - sl_price)
    
    if price_risk == 0:
        price_risk = current_price * 0.01
        
    position_size = round(risk_amount / price_risk, 3)
    if position_size <= 0:
        position_size = 1

    payload = {
        "product_symbol": symbol,
        "size": position_size,
        "order_type": "market_order",
        "side": side,
        "stop_loss_order": {
            "stop_price": str(round(sl_price, 2)),
            "order_type": "market_order"
        },
        "take_profit_order": {
            "stop_price": str(round(tp_price, 2)),
            "order_type": "market_order"
        }
    }
    return delta_request("POST", "/v2/orders", payload), position_size, risk_amount

# --- 6. TELEGRAM NOTIFICATIONS WITH CHART ---
def send_telegram_msg(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})

def send_telegram_photo(photo_path, caption):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    with open(photo_path, 'rb') as photo:
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "Markdown"}, files={"photo": photo})

def generate_chart(df_5m, symbol, signal_type, entry, sl, tp, trend_1h):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), gridspec_kw={'height_ratios': [2.5, 1]}, sharex=True)
    plt.style.use('dark_background')
    fig.patch.set_facecolor('#0d1117')
    ax1.set_facecolor('#161b22')
    ax2.set_facecolor('#161b22')

    ax1.plot(df_5m['close'], label=f'{symbol} Price (5m)', color='#58a6ff', linewidth=1.8)
    ax1.plot(df_5m['sma50'], label='50 SMA', color='#e3b341', linestyle='--')
    
    ax1.axhline(y=sl, color='#f85149', linestyle=':', label=f'SL: ${sl:.2f}')
    ax1.axhline(y=tp, color='#3fb950', linestyle=':', label=f'TP (1:2): ${tp:.2f}')
    
    ax1.set_title(f"SweepX MTF — {symbol} [{signal_type}] | 1H Trend: {trend_1h}")
    ax1.grid(True, color='#21262d', linestyle=':')
    ax1.legend(loc='upper left')

    ax2.plot(df_5m['rsi'], label='RSI 5m', color='#d2a8ff', linewidth=1.5)
    ax2.axhline(y=70, color='#f85149', linestyle='--', alpha=0.5)
    ax2.axhline(y=30, color='#3fb950', linestyle='--', alpha=0.5)
    ax2.grid(True, color='#21262d', linestyle=':')
    ax2.legend(loc='upper left')

    chart_path = "signal_chart.png"
    plt.tight_layout()
    plt.savefig(chart_path, dpi=200, bbox_inches='tight')
    plt.close()
    return chart_path

# --- 7. TECHNICAL ANALYSIS ENGINE (MULTI-TIMEFRAME) ---
def fetch_klines(symbol, interval, limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=10).json()
        df = pd.DataFrame(res, columns=['time', 'open', 'high', 'low', 'close', 'vol', 'ct', 'qa', 'nt', 'tb', 'tq', 'ig'])
        df['high'] = df['high'].astype(float)
        df['low'] = df['low'].astype(float)
        df['close'] = df['close'].astype(float)
        return df
    except Exception as e:
        print(f"Data Fetch Error ({symbol} - {interval}): {e}")
        return None

def calculate_indicators(df):
    df['sma50'] = df['close'].rolling(window=50).mean()
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    return df

def analyze_1h_trend(df_1h):
    """Analyzes overall trend direction on 1 Hour candles."""
    df_1h = calculate_indicators(df_1h)
    last_close = df_1h['close'].iloc[-1]
    sma50 = df_1h['sma50'].iloc[-1]
    ema20 = df_1h['ema20'].iloc[-1]
    rsi = df_1h['rsi'].iloc[-1]

    if last_close > sma50 and ema20 > sma50 and rsi > 45:
        return "BULLISH"
    elif last_close < sma50 and ema20 < sma50 and rsi < 55:
        return "BEARISH"
    return "SIDEWAYS"

def detect_5m_divergence(df_5m):
    """Detects entry divergence on 5 Minute candles."""
    price_high_now = df_5m['high'].iloc[-1]
    price_high_prev = df_5m['high'].iloc[-15:-2].max()
    rsi_now = df_5m['rsi'].iloc[-1]
    rsi_prev = df_5m['rsi'].iloc[-15:-2].max()
    
    price_low_now = df_5m['low'].iloc[-1]
    price_low_prev = df_5m['low'].iloc[-15:-2].min()
    rsi_low_now = df_5m['rsi'].iloc[-1]
    rsi_low_prev = df_5m['rsi'].iloc[-15:-2].min()

    # Bearish Divergence
    if (price_high_now > price_high_prev) and (rsi_now < rsi_prev) and (rsi_now > 60):
        return "BEARISH_DIVERGENCE"
        
    # Bullish Divergence
    if (price_low_now < price_low_prev) and (rsi_low_now > rsi_low_prev) and (rsi_low_now < 40):
        return "BULLISH_DIVERGENCE"
        
    return None

# --- 8. MAIN AUTOMATED TRADING LOOP ---
def run_trading_bot():
    global daily_trade_count, current_day
    
    now_day = datetime.datetime.utcnow().day
    if now_day != current_day:
        current_day = now_day
        daily_trade_count = 0
        send_telegram_msg("🔄 *Daily Trade Limit Reset:* 0/3 Trades executed today.")

    if daily_trade_count >= 3:
        return

    # Check News Sentiment
    news_bias, news_text = get_market_news_sentiment()

    for symbol in SYMBOLS:
        # Fetch 1 Hour Data for Macro Analysis
        df_1h = fetch_klines(symbol, "1h", limit=100)
        # Fetch 5 Min Data for Precision Entry
        df_5m = fetch_klines(symbol, "5m", limit=100)
        
        if df_1h is None or df_5m is None:
            continue
            
        trend_1h = analyze_1h_trend(df_1h)
        df_5m = calculate_indicators(df_5m)
        divergence_5m = detect_5m_divergence(df_5m)
        liq_bias, liq_text = check_liquidity_bias(symbol)
        
        curr_price = df_5m['close'].iloc[-1]
        balance = get_wallet_balance()

        # SHORT ENTRY RULE: 1H Trend is Bearish AND 5M gives Bearish Divergence
        if trend_1h == "BEARISH" and divergence_5m == "BEARISH_DIVERGENCE":
            if news_bias == "BULLISH":
                print("Skipping Short: Strong Bullish News Sentiment")
                continue

            sl_price = df_5m['high'].iloc[-10:].max() * 1.002
            sl_dist = abs(curr_price - sl_price)
            tp_price = curr_price - (sl_dist * 2)
            
            res, size, risk_val = place_order_with_sl_tp(symbol, "sell", curr_price, sl_price, tp_price, risk_pct=0.02)
            daily_trade_count += 1
            
            chart = generate_chart(df_5m, symbol, "SHORT (1H Trend + 5M Entry)", curr_price, sl_price, tp_price, trend_1h)
            msg = (
                f"🚨 *AUTOMATED SHORT TRADE EXECUTED* 🚨\n\n"
                f"• *Symbol:* {symbol}\n"
                f"• *1-Hour Trend:* 🔴 BEARISH\n"
                f"• *5-Min Entry Signal:* Bearish Divergence\n"
                f"• *Entry Price:* ${curr_price:.2f}\n"
                f"• *Stop Loss (SL):* ${sl_price:.2f}\n"
                f"• *Take Profit (1:2):* ${tp_price:.2f}\n"
                f"• *Risk Amount (2%):* ${risk_val:.2f} USDT\n"
                f"• *Wallet Balance:* ${balance:.2f} USDT\n"
                f"• *News Sentiment:* {news_text}\n"
                f"• *Liquidity Heatmap:* {liq_text}\n"
                f"• *Trades Today:* {daily_trade_count}/3\n\n"
                f"🤖 _Executed 24/7 by SweepX Dual Timeframe Engine_"
            )
            send_telegram_photo(chart, msg)
            if os.path.exists(chart):
                os.remove(chart)

        # LONG ENTRY RULE: 1H Trend is Bullish AND 5M gives Bullish Divergence
        elif trend_1h == "BULLISH" and divergence_5m == "BULLISH_DIVERGENCE":
            if news_bias == "BEARISH":
                print("Skipping Long: Strong Bearish News Sentiment")
                continue

            sl_price = df_5m['low'].iloc[-10:].min() * 0.998
            sl_dist = abs(curr_price - sl_price)
            tp_price = curr_price + (sl_dist * 2)
            
            res, size, risk_val = place_order_with_sl_tp(symbol, "buy", curr_price, sl_price, tp_price, risk_pct=0.02)
            daily_trade_count += 1
            
            chart = generate_chart(df_5m, symbol, "LONG (1H Trend + 5M Entry)", curr_price, sl_price, tp_price, trend_1h)
            msg = (
                f"🚨 *AUTOMATED LONG TRADE EXECUTED* 🚨\n\n"
                f"• *Symbol:* {symbol}\n"
                f"• *1-Hour Trend:* 🟢 BULLISH\n"
                f"• *5-Min Entry Signal:* Bullish Divergence\n"
                f"• *Entry Price:* ${curr_price:.2f}\n"
                f"• *Stop Loss (SL):* ${sl_price:.2f}\n"
                f"• *Take Profit (1:2):* ${tp_price:.2f}\n"
                f"• *Risk Amount (2%):* ${risk_val:.2f} USDT\n"
                f"• *Wallet Balance:* ${balance:.2f} USDT\n"
                f"• *News Sentiment:* {news_text}\n"
                f"• *Liquidity Heatmap:* {liq_text}\n"
                f"• *Trades Today:* {daily_trade_count}/3\n\n"
                f"🤖 _Executed 24/7 by SweepX Dual Timeframe Engine_"
            )
            send_telegram_photo(chart, msg)
            if os.path.exists(chart):
                os.remove(chart)

if __name__ == "__main__":
    send_telegram_msg("🤖 *SweepX Dual Timeframe Bot Online!*\n• Macro Analysis: 1-Hour Timeframe\n• Entry Signal: 5-Minute Timeframe\n• Pairs: BTC & ETH\n• Liquidity & Sentiment Filter: Active")
    while True:
        try:
            run_trading_bot()
            time.sleep(300) # Runs every 5 minutes
        except Exception as e:
            print(f"Loop Error: {e}")
            time.sleep(60)
