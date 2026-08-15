import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from supabase import create_client, Client
import math

# ---------------------------------------------------------
# 1. DATABASE & PAGE SETUP
# ---------------------------------------------------------
st.set_page_config(page_title="B.Com Advanced Trading & F&O Terminal", layout="wide")

@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"].strip().strip('"').strip("'")
    key = st.secrets["SUPABASE_KEY"].strip().strip('"').strip("'")
    return create_client(url, key)

try:
    supabase = init_supabase()
except Exception:
    st.error("⚠️ Database connection setup failed. Please check your Secrets in Streamlit.")
    st.stop()

if "user" not in st.session_state:
    st.session_state.user = None

# ---------------------------------------------------------
# 2. BLACK-SCHOLES OPTIONS ENGINE & OI SIMULATOR
# ---------------------------------------------------------
def norm_cdf(x):
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

def calculate_option_premium(spot: float, strike: float, opt_type: str, index_name: str) -> float:
    if spot <= 0 or strike <= 0:
        return 0.0
    T = 7.0 / 365.0
    r = 0.07
    sigma = 0.18 if "BANK" in index_name else (0.13 if "SENSEX" in index_name else 0.14)
    d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if opt_type == "CE":
        price = spot * norm_cdf(d1) - strike * math.exp(-r * T) * norm_cdf(d2)
        intrinsic = max(0.0, spot - strike)
    else:
        price = strike * math.exp(-r * T) * norm_cdf(-d2) - spot * norm_cdf(-d1)
        intrinsic = max(0.0, strike - spot)

    return round(max(price, intrinsic, 10.50), 2)

def generate_simulated_oi(spot: float, strike: float, opt_type: str) -> int:
    """Generates realistic Open Interest (OI) buildup based on strike distance."""
    if spot <= 0:
        return 10000
    dist_pct = abs(spot - strike) / spot
    base_oi = math.exp(-dist_pct * 25) * 180000
    
    # OTM options usually have higher OI writing
    is_otm = (opt_type == "CE" and strike >= spot) or (opt_type == "PE" and strike <= spot)
    multiplier = 1.35 if is_otm else 0.75
    
    # Pseudo-random deterministic noise based on strike
    noise = (int(strike) * 17) % 25000
    total_oi = int((base_oi * multiplier) + noise)
    return max(8500, total_oi)

@st.cache_data(ttl=15)
def get_spot_price(symbol: str) -> float:
    try:
        df = yf.Ticker(symbol).history(period="5d")
        if not df.empty:
            return float(df['Close'].iloc[-1])
    except Exception:
        pass
    return 0.0

def get_current_price(ticker_symbol: str) -> float:
    if ticker_symbol.startswith("OPT:"):
        _, idx_code, strike_str, opt_type = ticker_symbol.split(":")
        spot_ticker = "^NSEI" if idx_code == "NIFTY" else ("^NSEBANK" if idx_code == "BANKNIFTY" else "^BSESN")
        spot = get_spot_price(spot_ticker)
        return calculate_option_premium(spot, float(strike_str), opt_type, idx_code)
    else:
        try:
            df = yf.Ticker(ticker_symbol).history(period="5d")
            if not df.empty:
                return float(df['Close'].iloc[-1])
        except Exception:
            pass
        return 0.0

# ---------------------------------------------------------
# 3. AUTHENTICATION (LOGIN / REGISTER)
# ---------------------------------------------------------
st.sidebar.title("👤 Student Portal")

if not st.session_state.user:
    auth_mode = st.sidebar.radio("Action", ["Login", "Register"])
    roll_no = st.sidebar.text_input("Roll Number:").strip().upper()
    pin = st.sidebar.text_input("4-Digit PIN:", type="password")
    
    if auth_mode == "Register":
        name = st.sidebar.text_input("Full Name:")
        if st.sidebar.button("Register Account"):
            if roll_no and pin and name:
                try:
                    res = supabase.table("students").insert({
                        "roll_no": roll_no, 
                        "name": name, 
                        "pin": pin, 
                        "cash": 100000.0
                    }).execute()
                    if res.data:
                        st.sidebar.success("🎉 Registered! Switch to Login to sign in.")
                    else:
                        st.sidebar.error("Roll Number already registered.")
                except Exception:
                    st.sidebar.error("Database registration failed.")
            else:
                st.sidebar.warning("Fill in all fields.")

    elif auth_mode == "Login":
        if st.sidebar.button("Login"):
            try:
                res = supabase.table("students").select("*").eq("roll_no", roll_no).eq("pin", pin).execute()
                if res.data:
                    st.session_state.user = res.data[0]
                    st.rerun()
                else:
                    st.sidebar.error("Invalid Roll Number or PIN.")
            except Exception:
                st.sidebar.error("Connection error.")
    st.stop()

else:
    try:
        user_data = supabase.table("students").select("*").eq("id", st.session_state.user["id"]).execute().data[0]
        st.session_state.user = user_data
    except Exception:
        pass
        
    st.sidebar.write(f"**Logged in as:** {st.session_state.user['name']} ({st.session_state.user['roll_no']})")
    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.rerun()

# Risk Parameter Sidebar
st.sidebar.markdown("---")
st.sidebar.subheader("🛡️ Risk Controls")
max_alloc_pct = st.sidebar.slider("Max Capital per Trade (% of Cash):", min_value=10, max_value=100, value=30, step=5)

# ---------------------------------------------------------
# 4. APP TABS
# ---------------------------------------------------------
main_tab1, main_tab2, main_tab3 = st.tabs([
    "📊 Pro Stock Terminal", 
    "⚡ F&O Options Desk (NSE & BSE)", 
    "🏆 Live Class Leaderboard"
])

student_id = st.session_state.user["id"]
current_cash = float(st.session_state.user["cash"])
max_trade_budget = current_cash * (max_alloc_pct / 100.0)

# =========================================================
# TAB 1: PRO STOCK TERMINAL
# =========================================================
with main_tab1:
    ticker_input = st.sidebar.text_input("Stock Ticker (e.g. RELIANCE.NS, TCS.NS, AAPL):", value="RELIANCE.NS").upper()
    time_frame = st.sidebar.selectbox("Timeframe:", ["1mo", "3mo", "6mo", "1y"], index=2)

    st.sidebar.markdown("**Technical Indicators:**")
    show_sma = st.sidebar.checkbox("20 SMA", value=True)
    show_ema = st.sidebar.checkbox("50 EMA", value=True)
    show_bb = st.sidebar.checkbox("Bollinger Bands", value=True)
    show_rsi = st.sidebar.checkbox("RSI (14)", value=True)
    show_macd = st.sidebar.checkbox("MACD", value=True)

    try:
        stock = yf.Ticker(ticker_input)
        df = stock.history(period=time_frame)
        info = stock.info
        current_price = float(df['Close'].iloc[-1])
    except Exception:
        st.error(f"Failed to fetch stock data for: {ticker_input}")
        st.stop()

    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    df['EMA_50'] = df['Close'].ewm(span=50, adjust=False).mean()
    std_20 = df['Close'].rolling(window=20).std()
    df['BB_Upper'] = df['SMA_20'] + (2 * std_20)
    df['BB_Lower'] = df['SMA_20'] - (2 * std_20)

    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / loss)))

    ema_12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema_26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema_12 - ema_26
    df['MACD_Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_Hist'] = df['MACD'] - df['MACD_Signal']

    st.subheader(f"📊 Fundamental Analysis: {info.get('longName', ticker_input)}")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Current Price", f"₹{current_price:.2f}")
    c2.metric("Trailing P/E", f"{info.get('trailingPE', 'N/A')}")
    c3.metric("P/B Ratio", f"{info.get('priceToBook', 'N/A')}")
    c4.metric("Debt-to-Equity", f"{info.get('debtToEquity', 'N/A')}")
    c5.metric("52W High", f"₹{info.get('fiftyTwoWeekHigh', 'N/A')}")

    rows = 1
    row_heights = [0.6]
    if show_rsi:
        rows += 1
        row_heights.append(0.2)
    if show_macd:
        rows += 1
        row_heights.append(0.2)

    st.subheader("📉 Technical Chart with Custom Indicators")
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.04, row_heights=row_heights)
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Candlestick"), row=1, col=1)
    
    if show_sma:
        fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], mode='lines', name='20 SMA', line=dict(color='orange', width=1.5)), row=1, col=1)
    if show_ema:
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_50'], mode='lines', name='50 EMA', line=dict(color='cyan', width=1.5)), row=1, col=1)
    if show_bb:
        fig.add_trace(go.Scatter(x=df.index, y=df['BB_Upper'], mode='lines', name='BB Upper', line=dict(color='gray', dash='dash')), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['BB_Lower'], mode='lines', name='BB Lower', line=dict(color='gray', dash='dash')), row=1, col=1)

    curr_row = 2
    if show_rsi:
        fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], mode='lines', name='RSI (14)', line=dict(color='purple')), row=curr_row, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=curr_row, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=curr_row, col=1)
        curr_row += 1

    if show_macd:
        fig.add_trace(go.Scatter(x=df.index, y=df['MACD'], mode='lines', name='MACD', line=dict(color='blue')), row=curr_row, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MACD_Signal'], mode='lines', name='Signal', line=dict(color='orange')), row=curr_row, col=1)
        colors = ['green' if val >= 0 else 'red' for val in df['MACD_Hist']]
        fig.add_trace(go.Bar(x=df.index, y=df['MACD_Hist'], name='Histogram', marker_color=colors), row=curr_row, col=1)

    fig.update_layout(height=520, xaxis_rangeslider_visible=False, template="plotly_dark", margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)

    col_tr, col_po = st.columns([1.2, 1.5])
    with col_tr:
        st.subheader("💳 Order & Risk Management")
        trade_type = st.radio("Order Type:", ["BUY", "SELL"], key="stock_order_type", horizontal=True)
        qty = st.number_input("Shares Quantity:", min_value=1, value=5, step=1, key="stock_qty")
        total_cost = qty * current_price
        
        st.caption(f"📍 **Order Value:** ₹{total_cost:,.2f} | **Max Allowed per Order ({max_alloc_pct}%):** ₹{max_trade_budget:,.2f}")

        st.markdown("---")
        st.markdown("🎯 **Target & Stop-Loss Risk Calculator**")
        c_tp, c_sl = st.columns(2)
        target_price = c_tp.number_input("Target Price (₹):", min_value=0.0, value=round(current_price * 1.05, 2))
        stop_loss_price = c_sl.number_input("Stop Loss Price (₹):", min_value=0.0, value=round(current_price * 0.97, 2))

        potential_profit = (target_price - current_price) * qty
        potential_loss = (current_price - stop_loss_price) * qty
        rr_ratio = (target_price - current_price) / max(0.01, (current_price - stop_loss_price)) if trade_type == "BUY" else 0.0

        st.write(f"🟢 **Potential Profit:** ₹{potential_profit:,.2f}")
        st.write(f"🔴 **Potential Loss:** ₹{potential_loss:,.2f}")
        st.write(f"⚖️ **Risk-to-Reward Ratio:** 1 : {rr_ratio:.2f}")

        existing_pos = supabase.table("portfolio").select("*").eq("student_id", student_id).eq("ticker", ticker_input).execute().data

        if st.button("Submit Stock Order"):
            if trade_type == "BUY":
                if total_cost > max_trade_budget:
                    st.error(f"⚠️ Order Rejected! Exceeds Max Trade Limit of ₹{max_trade_budget:,.2f}.")
                elif current_cash >= total_cost:
                    new_cash = current_cash - total_cost
                    supabase.table("students").update({"cash": new_cash}).eq("id", student_id).execute()
                    if existing_pos:
                        prev_qty = existing_pos[0]["qty"]
                        prev_avg = float(existing_pos[0]["avg_price"])
                        new_qty = prev_qty + qty
                        new_avg = ((prev_qty * prev_avg) + total_cost) / new_qty
                        supabase.table("portfolio").update({"qty": new_qty, "avg_price": new_avg}).eq("id", existing_pos[0]["id"]).execute()
                    else:
                        supabase.table("portfolio").insert({"student_id": student_id, "ticker": ticker_input, "qty": qty, "avg_price": current_price}).execute()
                    st.success("Buy order executed!")
                    st.rerun()
                else:
                    st.error("Insufficient Cash Balance!")
            elif trade_type == "SELL":
                if existing_pos and existing_pos[0]["qty"] >= qty:
                    new_cash = current_cash + total_cost
                    supabase.table("students").update({"cash": new_cash}).eq("id", student_id).execute()
                    if existing_pos[0]["qty"] == qty:
                        supabase.table("portfolio").delete().eq("id", existing_pos[0]["id"]).execute()
                    else:
                        new_qty = existing_pos[0]["qty"] - qty
                        supabase.table("portfolio").update({"qty": new_qty}).eq("id", existing_pos[0]["id"]).execute()
                    st.success("Sell order executed!")
                    st.rerun()
                else:
                    st.error("Insufficient quantity!")

    with col_po:
        st.subheader("💼 Equity Holdings")
        st.write(f"**Available Cash:** ₹{current_cash:,.2f}")
        port_data = supabase.table("portfolio").select("*").eq("student_id", student_id).execute().data
        stock_positions = [p for p in port_data if not p["ticker"].startswith("OPT:")]

        display_list = []
        for row in stock_positions:
            p_price = get_current_price(row["ticker"])
            mkt_val = row["qty"] * p_price
            pnl = mkt_val - (row["qty"] * float(row["avg_price"]))
            display_list.append({
                "Ticker": row["ticker"],
                "Qty": row["qty"],
                "Avg Price": f"₹{float(row['avg_price']):.2f}",
                "Current Price": f"₹{p_price:.2f}",
                "Unrealized P&L": f"₹{pnl:,.2f}"
            })
        if display_list:
            st.table(pd.DataFrame(display_list))
        else:
            st.info("No equity stock holdings.")

# =========================================================
# TAB 2: OPTIONS TRADING DESK (NSE & BSE)
# =========================================================
with main_tab2:
    st.subheader("⚡ Index Options Desk (NSE & BSE F&O)")

    col_opt1, col_opt2 = st.columns([1, 1.2])

    with col_opt1:
        st.markdown("### 🎯 Select Contract")
        chosen_index = st.selectbox("Select Index:", ["NIFTY 50", "BANK NIFTY", "BSE SENSEX"])
        
        # Configure Ticker, Lot Size, and Step per Index
        if chosen_index == "NIFTY 50":
            idx_symbol, idx_code, lot_size, step = "^NSEI", "NIFTY", 25, 100
        elif chosen_index == "BANK NIFTY":
            idx_symbol, idx_code, lot_size, step = "^NSEBANK", "BANKNIFTY", 15, 100
        else:  # BSE SENSEX
            idx_symbol, idx_code, lot_size, step = "^BSESN", "SENSEX", 10, 100

        spot_price = get_spot_price(idx_symbol)
        st.metric(f"Live {chosen_index} Spot Price", f"₹{spot_price:,.2f}")

        base_strike = round(spot_price / step) * step
        strikes = [base_strike + (i * step) for i in range(-5, 6)]

        selected_strike = st.selectbox("Select Strike Price:", strikes, index=5)
        opt_type = st.radio("Option Type:", ["Call Option (CE)", "Put Option (PE)"], horizontal=True)
        opt_code = "CE" if "Call" in opt_type else "PE"

        opt_ticker = f"OPT:{idx_code}:{selected_strike}:{opt_code}"
        premium = calculate_option_premium(spot_price, float(selected_strike), opt_code, idx_code)
        single_oi = generate_simulated_oi(spot_price, float(selected_strike), opt_code)

        c_p1, c_p2 = st.columns(2)
        c_p1.info(f"💡 **Premium:** ₹{premium:.2f} / share\n\n📦 **1 Lot** = {lot_size} shares")
        c_p2.metric("Contract Open Interest (OI)", f"{single_oi:,} contracts")

    with col_opt2:
        st.markdown("### 💳 Order Execution")
        opt_trade_action = st.radio("Action:", ["BUY", "SELL"], key="opt_action", horizontal=True)
        num_lots = st.number_input("Number of Lots:", min_value=1, value=1, step=1)
        total_shares = num_lots * lot_size
        total_premium_cost = total_shares * premium

        st.metric("Total Premium Required", f"₹{total_premium_cost:,.2f}")
        st.caption(f"📍 **Max Allowed per Order ({max_alloc_pct}%):** ₹{max_trade_budget:,.2f}")

        existing_opt_pos = supabase.table("portfolio").select("*").eq("student_id", student_id).eq("ticker", opt_ticker).execute().data

        if st.button("Submit Options Order"):
            if opt_trade_action == "BUY":
                if total_premium_cost > max_trade_budget:
                    st.error(f"⚠️ Order Rejected! Exceeds Max Trade Allocation of ₹{max_trade_budget:,.2f}.")
                elif current_cash >= total_premium_cost:
                    new_cash = current_cash - total_premium_cost
                    supabase.table("students").update({"cash": new_cash}).eq("id", student_id).execute()

                    if existing_opt_pos:
                        prev_qty = existing_opt_pos[0]["qty"]
                        prev_avg = float(existing_opt_pos[0]["avg_price"])
                        new_qty = prev_qty + total_shares
                        new_avg = ((prev_qty * prev_avg) + total_premium_cost) / new_qty
                        supabase.table("portfolio").update({"qty": new_qty, "avg_price": new_avg}).eq("id", existing_opt_pos[0]["id"]).execute()
                    else:
                        supabase.table("portfolio").insert({"student_id": student_id, "ticker": opt_ticker, "qty": total_shares, "avg_price": premium}).execute()

                    st.success(f"Bought {num_lots} Lot(s) of {opt_ticker}!")
                    st.rerun()
                else:
                    st.error("Insufficient Cash Balance!")

            elif opt_trade_action == "SELL":
                if existing_opt_pos and existing_opt_pos[0]["qty"] >= total_shares:
                    new_cash = current_cash + total_premium_cost
                    supabase.table("students").update({"cash": new_cash}).eq("id", student_id).execute()

                    if existing_opt_pos[0]["qty"] == total_shares:
                        supabase.table("portfolio").delete().eq("id", existing_opt_pos[0]["id"]).execute()
                    else:
                        new_qty = existing_opt_pos[0]["qty"] - total_shares
                        supabase.table("portfolio").update({"qty": new_qty}).eq("id", existing_opt_pos[0]["id"]).execute()

                    st.success(f"Sold {num_lots} Lot(s) of {opt_ticker}!")
                    st.rerun()
                else:
                    st.error("Insufficient option contracts in portfolio!")

    # ---------------------------------------------------------
    # OPEN INTEREST (OI) & PCR ANALYSIS CHART
    # ---------------------------------------------------------
    st.markdown("---")
    st.subheader(f"📊 Open Interest (OI) Analysis & Put-Call Ratio: {chosen_index}")
    
    oi_data = []
    tot_call_oi, tot_put_oi = 0, 0
    for s_price in strikes:
        c_oi = generate_simulated_oi(spot_price, float(s_price), "CE")
        p_oi = generate_simulated_oi(spot_price, float(s_price), "PE")
        tot_call_oi += c_oi
        tot_put_oi += p_oi
        oi_data.append({"Strike": str(s_price), "Call OI (Resistance)": c_oi, "Put OI (Support)": p_oi})

    pcr = tot_put_oi / max(1, tot_call_oi)
    pcr_sentiment = "🟢 Bullish (Strong Put Writing)" if pcr > 1.1 else ("🔴 Bearish (Strong Call Writing)" if pcr < 0.85 else "🟡 Neutral")

    m_pcr1, m_pcr2, m_pcr3 = st.columns(3)
    m_pcr1.metric("Total Call Open Interest", f"{tot_call_oi:,}")
    m_pcr2.metric("Total Put Open Interest", f"{tot_put_oi:,}")
    m_pcr3.metric("Put-Call Ratio (PCR)", f"{pcr:.2f}", delta=pcr_sentiment)

    df_oi = pd.DataFrame(oi_data)
    fig_oi = go.Figure()
    fig_oi.add_trace(go.Bar(x=df_oi["Strike"], y=df_oi["Call OI (Resistance)"], name="Call OI (Call Writers / Resistance)", marker_color="crimson"))
    fig_oi.add_trace(go.Bar(x=df_oi["Strike"], y=df_oi["Put OI (Support)"], name="Put OI (Put Writers / Support)", marker_color="mediumseagreen"))
    fig_oi.update_layout(barmode="group", height=380, template="plotly_dark", title="Open Interest Build-Up across Strike Prices", margin=dict(l=10, r=10, t=40, b=10))
    st.plotly_chart(fig_oi, use_container_width=True)

    st.markdown("---")
    st.subheader("📜 Open Options Positions")
    port_data = supabase.table("portfolio").select("*").eq("student_id", student_id).execute().data
    opt_positions = [p for p in port_data if p["ticker"].startswith("OPT:")]

    opt_display = []
    for row in opt_positions:
        cur_prem = get_current_price(row["ticker"])
        mkt_val = row["qty"] * cur_prem
        pnl = mkt_val - (row["qty"] * float(row["avg_price"]))
        opt_display.append({
            "Contract Symbol": row["ticker"],
            "Total Shares": row["qty"],
            "Avg Premium Paid": f"₹{float(row['avg_price']):.2f}",
            "Live Premium": f"₹{cur_prem:.2f}",
            "Current Value": f"₹{mkt_val:,.2f}",
            "Unrealized P&L": f"₹{pnl:,.2f}"
        })

    if opt_display:
        st.table(pd.DataFrame(opt_display))
    else:
        st.info("No active option contracts.")

# =========================================================
# TAB 3: LIVE CLASS LEADERBOARD
# =========================================================
with main_tab3:
    st.subheader("🏆 Live Classroom Standings")
    if st.button("🔄 Refresh Standings"):
        st.rerun()

    all_students = supabase.table("students").select("*").execute().data
    all_portfolios = supabase.table("portfolio").select("*").execute().data

    unique_tickers = list(set([p["ticker"] for p in all_portfolios]))
    price_map = {t: get_current_price(t) for t in unique_tickers}

    leaderboard = []
    for s in all_students:
        s_cash = float(s["cash"])
        s_holdings = [p for p in all_portfolios if p["student_id"] == s["id"]]
        s_asset_val = sum([p["qty"] * price_map.get(p["ticker"], 0.0) for p in s_holdings])
        total_val = s_cash + s_asset_val
        ret_pct = ((total_val - 100000.0) / 100000.0) * 100

        leaderboard.append({
            "Student Name": s["name"],
            "Roll Number": s["roll_no"],
            "Cash Balance (₹)": f"₹{s_cash:,.2f}",
            "Holdings Value (₹)": f"₹{s_asset_val:,.2f}",
            "Total Net Worth (₹)": total_val,
            "Return (%)": f"{ret_pct:+.2f}%"
        })

    if leaderboard:
        df_lb = pd.DataFrame(leaderboard).sort_values(by="Total Net Worth (₹)", ascending=False).reset_index(drop=True)
        df_lb.index += 1
        df_lb["Total Net Worth (₹)"] = df_lb["Total Net Worth (₹)"].apply(lambda x: f"₹{x:,.2f}")
        st.dataframe(df_lb, use_container_width=True)
