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
st.set_page_config(page_title="B.Com Investment Terminal & F&O Desk", layout="wide")

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
# 2. BLACK-SCHOLES OPTIONS PRICING ENGINE
# ---------------------------------------------------------
def norm_cdf(x):
    """Cumulative distribution function for standard normal distribution."""
    return (1.0 + math.erf(x / math.sqrt(2.0))) / 2.0

def calculate_option_premium(spot: float, strike: float, opt_type: str, index_name: str) -> float:
    """Calculates Black-Scholes option premium for Nifty/BankNifty."""
    if spot <= 0 or strike <= 0:
        return 0.0

    T = 7.0 / 365.0  # 7 days to weekly expiry
    r = 0.07          # 7% risk-free rate
    sigma = 0.18 if "BANK" in index_name else 0.14  # Implied Volatility

    d1 = (math.log(spot / strike) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    if opt_type == "CE":
        price = spot * norm_cdf(d1) - strike * math.exp(-r * T) * norm_cdf(d2)
        intrinsic = max(0.0, spot - strike)
    else:  # PE
        price = strike * math.exp(-r * T) * norm_cdf(-d2) - spot * norm_cdf(-d1)
        intrinsic = max(0.0, strike - spot)

    # Floor pricing for time value realism
    return round(max(price, intrinsic, 8.50), 2)

# ---------------------------------------------------------
# 3. PRICE FETCHING ENGINE
# ---------------------------------------------------------
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
    """Unified price lookup for both Equities and Options tickers."""
    if ticker_symbol.startswith("OPT:"):
        # Format: OPT:NIFTY:24500:CE
        _, idx_code, strike_str, opt_type = ticker_symbol.split(":")
        spot_ticker = "^NSEI" if idx_code == "NIFTY" else "^NSEBANK"
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
# 4. AUTHENTICATION (LOGIN / REGISTER)
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

# ---------------------------------------------------------
# 5. APP TABS
# ---------------------------------------------------------
main_tab1, main_tab2, main_tab3 = st.tabs([
    "📊 Stock Terminal", 
    "⚡ Options Desk (F&O)", 
    "🏆 Live Class Leaderboard"
])

student_id = st.session_state.user["id"]
current_cash = float(st.session_state.user["cash"])

# =========================================================
# TAB 1: STOCK TERMINAL
# =========================================================
with main_tab1:
    ticker_input = st.sidebar.text_input("Stock Ticker (e.g. RELIANCE.NS, TCS.NS, AAPL):", value="RELIANCE.NS").upper()
    time_frame = st.sidebar.selectbox("Select Timeframe:", ["1mo", "3mo", "6mo", "1y"], index=2)

    try:
        stock = yf.Ticker(ticker_input)
        df = stock.history(period=time_frame)
        info = stock.info
        current_price = float(df['Close'].iloc[-1])
    except Exception:
        st.error(f"Failed to fetch stock data for: {ticker_input}")
        st.stop()

    df['SMA_20'] = df['Close'].rolling(window=20).mean()
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    df['RSI'] = 100 - (100 / (1 + (gain / loss)))

    st.subheader(f"📊 Fundamental Analysis: {info.get('longName', ticker_input)}")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Current Price", f"₹{current_price:.2f}")
    c2.metric("Trailing P/E", f"{info.get('trailingPE', 'N/A')}")
    c3.metric("P/B Ratio", f"{info.get('priceToBook', 'N/A')}")
    c4.metric("Debt-to-Equity", f"{info.get('debtToEquity', 'N/A')}")
    c5.metric("52W High", f"₹{info.get('fiftyTwoWeekHigh', 'N/A')}")

    st.subheader("📉 Technical Chart (Candlesticks + RSI)")
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Candlestick"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['SMA_20'], mode='lines', name='20 SMA', line=dict(color='orange')), row=1, col=1)
    fig.add_trace(go.Scatter(x=df.index, y=df['RSI'], mode='lines', name='RSI', line=dict(color='purple')), row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)
    fig.update_layout(height=420, xaxis_rangeslider_visible=False, template="plotly_dark")
    st.plotly_chart(fig, use_container_width=True)

    col_tr, col_po = st.columns([1, 1.5])
    with col_tr:
        st.subheader("💳 Execute Stock Order")
        trade_type = st.radio("Order Type:", ["BUY", "SELL"], key="stock_order_type", horizontal=True)
        qty = st.number_input("Shares Quantity:", min_value=1, value=5, step=1, key="stock_qty")
        total_cost = qty * current_price
        st.write(f"**Total Order Cost:** ₹{total_cost:,.2f}")

        existing_pos = supabase.table("portfolio").select("*").eq("student_id", student_id).eq("ticker", ticker_input).execute().data

        if st.button("Submit Stock Order"):
            if trade_type == "BUY":
                if current_cash >= total_cost:
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
                    st.error("Insufficient Cash!")
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
# TAB 2: OPTIONS TRADING DESK (F&O)
# =========================================================
with main_tab2:
    st.subheader("⚡ Index Options Trading Desk")

    col_opt1, col_opt2 = st.columns([1, 1.2])

    with col_opt1:
        st.markdown("### 🎯 Select Contract")
        chosen_index = st.selectbox("Select Index:", ["NIFTY 50", "BANK NIFTY"])
        idx_symbol = "^NSEI" if chosen_index == "NIFTY 50" else "^NSEBANK"
        idx_code = "NIFTY" if chosen_index == "NIFTY 50" else "BANKNIFTY"
        lot_size = 25 if chosen_index == "NIFTY 50" else 15

        spot_price = get_spot_price(idx_symbol)
        st.metric(f"Live {chosen_index} Spot Price", f"₹{spot_price:,.2f}")

        # Generate realistic strike prices around spot
        step = 100
        base_strike = round(spot_price / step) * step
        strikes = [base_strike + (i * step) for i in range(-5, 6)]

        selected_strike = st.selectbox("Select Strike Price:", strikes, index=5)
        opt_type = st.radio("Option Type:", ["Call Option (CE)", "Put Option (PE)"], horizontal=True)
        opt_code = "CE" if "Call" in opt_type else "PE"

        opt_ticker = f"OPT:{idx_code}:{selected_strike}:{opt_code}"
        premium = calculate_option_premium(spot_price, float(selected_strike), opt_code, idx_code)

        st.info(f"💡 **Estimated Premium:** ₹{premium:.2f} per share | **1 Lot** = {lot_size} shares")

    with col_opt2:
        st.markdown("### 💳 Order Execution")
        opt_trade_action = st.radio("Action:", ["BUY", "SELL"], key="opt_action", horizontal=True)
        num_lots = st.number_input("Number of Lots:", min_value=1, value=1, step=1)
        total_shares = num_lots * lot_size
        total_premium_cost = total_shares * premium

        st.metric("Total Investment Required", f"₹{total_premium_cost:,.2f}")

        existing_opt_pos = supabase.table("portfolio").select("*").eq("student_id", student_id).eq("ticker", opt_ticker).execute().data

        if st.button("Submit Options Order"):
            if opt_trade_action == "BUY":
                if current_cash >= total_premium_cost:
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
                    st.error("Insufficient Cash for Option Premium!")

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
                    st.error("Insufficient option contracts in portfolio to sell!")

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
