import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from supabase import create_client, Client

# ---------------------------------------------------------
# 1. DATABASE & PAGE SETUP
# ---------------------------------------------------------
st.set_page_config(page_title="B.Com Investment Terminal", layout="wide")

@st.cache_resource
def init_supabase() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_supabase()

if "user" not in st.session_state:
    st.session_state.user = None

# ---------------------------------------------------------
# 2. AUTHENTICATION (LOGIN / REGISTER)
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
                res = supabase.table("students").insert({"roll_no": roll_no, "name": name, "pin": pin, "cash": 100000.0}).execute()
                if res.data:
                    st.sidebar.success("Registered! You can now log in.")
                else:
                    st.sidebar.error("Roll Number already registered.")
            else:
                st.sidebar.warning("Fill in all fields.")

    elif auth_mode == "Login":
        if st.sidebar.button("Login"):
            res = supabase.table("students").select("*").eq("roll_no", roll_no).eq("pin", pin).execute()
            if res.data:
                st.session_state.user = res.data[0]
                st.sidebar.success(f"Welcome {res.data[0]['name']}!")
                st.rerun()
            else:
                st.sidebar.error("Invalid Roll Number or PIN.")
    st.stop()
else:
    user_data = supabase.table("students").select("*").eq("id", st.session_state.user["id"]).execute().data[0]
    st.session_state.user = user_data
    st.sidebar.write(f"**Logged in as:** {st.session_state.user['name']} ({st.session_state.user['roll_no']})")
    if st.sidebar.button("Logout"):
        st.session_state.user = None
        st.rerun()

# ---------------------------------------------------------
# 3. APP NAVIGATION: TERMINAL vs LEADERBOARD
# ---------------------------------------------------------
main_tab1, main_tab2 = st.tabs(["📊 Trading Terminal", "🏆 Live Class Leaderboard"])

def get_current_price(ticker_symbol):
    try:
        data = yf.Ticker(ticker_symbol).history(period="1d")
        if not data.empty:
            return data['Close'].iloc[-1]
    except Exception:
        pass
    return 0.0

# TAB 1: TRADING TERMINAL
with main_tab1:
    ticker_input = st.sidebar.text_input("Enter Ticker (e.g. RELIANCE.NS, TCS.NS, AAPL):", value="RELIANCE.NS").upper()
    time_frame = st.sidebar.selectbox("Select Timeframe:", ["1mo", "3mo", "6mo", "1y"], index=2)

    try:
        stock = yf.Ticker(ticker_input)
        df = stock.history(period=time_frame)
        info = stock.info
        current_price = df['Close'].iloc[-1]
    except Exception:
        st.error(f"Failed to fetch data for ticker: {ticker_input}. Verify valid Yahoo Finance symbol.")
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
    fig.update_layout(height=450, xaxis_rangeslider_visible=False, template="plotly_dark")
    st.plotly_chart(fig, use_container_width=True)

    col_tr, col_po = st.columns([1, 1.5])
    student_id = st.session_state.user["id"]
    current_cash = float(st.session_state.user["cash"])

    with col_tr:
        st.subheader("💳 Execute Order")
        trade_type = st.radio("Order Type:", ["BUY", "SELL"], horizontal=True)
        qty = st.number_input("Shares Quantity:", min_value=1, value=5, step=1)
        total_cost = qty * current_price
        st.write(f"**Total Order Cost:** ₹{total_cost:,.2f}")

        existing_pos = supabase.table("portfolio").select("*").eq("student_id", student_id).eq("ticker", ticker_input).execute().data

        if st.button("Submit Order"):
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
                    
                    st.success("Buy order executed successfully!")
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
                    
                    st.success("Sell order executed successfully!")
                    st.rerun()
                else:
                    st.error("Insufficient share quantity in portfolio!")

    with col_po:
        st.subheader("💼 Your Portfolio")
        st.write(f"**Available Cash Balance:** ₹{current_cash:,.2f}")
        port_data = supabase.table("portfolio").select("*").eq("student_id", student_id).execute().data
        
        holdings_val = 0.0
        display_list = []
        for row in port_data:
            p_price = get_current_price(row["ticker"])
            mkt_val = row["qty"] * p_price
            pnl = mkt_val - (row["qty"] * float(row["avg_price"]))
            holdings_val += mkt_val
            display_list.append({
                "Ticker": row["ticker"],
                "Qty": row["qty"],
                "Avg Price": f"₹{float(row['avg_price']):.2f}",
                "Current Price": f"₹{p_price:.2f}",
                "Unrealized P&L": f"₹{pnl:,.2f}"
            })
        
        net_worth = current_cash + holdings_val
        st.metric("Total Net Worth", f"₹{net_worth:,.2f}", delta=f"₹{(net_worth - 100000.0):,.2f}")
        if display_list:
            st.table(pd.DataFrame(display_list))

# TAB 2: LIVE CLASS LEADERBOARD
with main_tab2:
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
        s_stock_val = sum([p["qty"] * price_map.get(p["ticker"], 0.0) for p in s_holdings])
        total_val = s_cash + s_stock_val
        ret_pct = ((total_val - 100000.0) / 100000.0) * 100

        leaderboard.append({
            "Student Name": s["name"],
            "Roll Number": s["roll_no"],
            "Cash (₹)": f"₹{s_cash:,.2f}",
            "Holdings Value (₹)": f"₹{s_stock_val:,.2f}",
            "Total Net Worth (₹)": total_val,
            "Return (%)": f"{ret_pct:+.2f}%"
        })

    if leaderboard:
        df_lb = pd.DataFrame(leaderboard).sort_values(by="Total Net Worth (₹)", ascending=False).reset_index(drop=True)
        df_lb.index += 1
        df_lb["Total Net Worth (₹)"] = df_lb["Total Net Worth (₹)"].apply(lambda x: f"₹{x:,.2f}")
        st.dataframe(df_lb, use_container_width=True)
