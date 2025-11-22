# bsc_trading_bot_wrapper.py
import os
import re
import json
import time
import requests
from dotenv import load_dotenv
from web3 import Web3

# =========================================================
#  ADVANCED MULTI-USER BSC TRADING BOT (Wrapper fee integration)
#  - Each user connects own wallet (private key)
#  - RPC failover
#  - Settings: slippage + gas mode
#  - Token CA -> price, MC, holders, risk check
#  - Buy/Sell with presets (25/50/100%)
#  - Portfolio + PnL tracking
#  - Uses RouterWithFee wrapper contract so every swap executed through the bot pays a fee to feeReceiver
# =========================================================

# ---------- Load .env ----------
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
PRIMARY_RPC = os.getenv("BSC_RPC_URL")  # Node endpoint
WRAPPER_ADDRESS = os.getenv("WRAPPER_ADDRESS")  # set after deploy

if not TELEGRAM_TOKEN:
    raise Exception("TELEGRAM_TOKEN missing from .env")

if not WRAPPER_ADDRESS or WRAPPER_ADDRESS == "0x0000000000000000000000000000000000000000":
    raise Exception("WRAPPER_ADDRESS must be set to the deployed contract address in .env")

TG_BASE_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

# ---------- RPC Failover ----------
RPC_LIST = [
    PRIMARY_RPC,
    "https://rpc.ankr.com/bsc",
    "https://bsc-mainnet.public.blastapi.io/",
    "https://bsc-dataseed1.ninicoin.io/",
]

RPC_LIST = [r for r in RPC_LIST if r]


def get_web3():
    last_err = None
    for url in RPC_LIST:
        try:
            w3_local = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 8}))
            if w3_local.is_connected():
                print("Using RPC:", url)
                return w3_local
        except Exception as e:
            last_err = e
            print("RPC failed:", url, e)
    raise Exception(f"No working BSC RPC. Last error: {last_err}")


w3 = get_web3()

# PancakeSwap V2 Router + WBNB + BUSD (mainnet addresses)
PANCAKE_ROUTER = Web3.to_checksum_address("0x10ED43C718714eb63d5aA57B78B54704E256024E")
WBNB = Web3.to_checksum_address("0xBB4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c")
BUSD = Web3.to_checksum_address("0xe9e7cea3dedca5984780bafc599bd69add087d56")
USDT = Web3.to_checksum_address("0x55d398326f99059fF77548524699939b09a8Cb00")
USDC = Web3.to_checksum_address("0x8AC76a51cc950d9822D68b83fE1Ad97b32Cd580d")

# Router ABI (used only for price quoting)
ROUTER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
        ],
        "name": "getAmountsOut",
        "outputs": [{"internalType": "uint256[]", "name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function",
    }
]

router = w3.eth.contract(address=PANCAKE_ROUTER, abi=ROUTER_ABI)

print("Connected to BSC & router ready")

# ---------- Wrapper ABI (minimal) ----------
WRAPPER_ADDRESS = Web3.to_checksum_address(WRAPPER_ADDRESS)
WRAPPER_ABI = [
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"},
        ],
        "name": "swapExactETHForTokensSupportingFeeOnTransferTokens",
        "outputs": [],
        "stateMutability": "payable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"},
        ],
        "name": "swapExactTokensForETHSupportingFeeOnTransferTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [
            {"internalType": "uint256", "name": "amountIn", "type": "uint256"},
            {"internalType": "uint256", "name": "amountOutMin", "type": "uint256"},
            {"internalType": "address[]", "name": "path", "type": "address[]"},
            {"internalType": "address", "name": "to", "type": "address"},
            {"internalType": "uint256", "name": "deadline", "type": "uint256"},
        ],
        "name": "swapExactTokensForTokensSupportingFeeOnTransferTokens",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
]

wrapper = w3.eth.contract(address=WRAPPER_ADDRESS, abi=WRAPPER_ABI)

# ---------- Updated ERC20 ABI (includes optional fee getters) ----------
ERC20_ABI = [
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "symbol",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "totalSupply",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "owner", "type": "address"},
            {"name": "spender", "type": "address"},
        ],
        "name": "allowance",
        "outputs": [{"name": "remaining", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "value", "type": "uint256"},
        ],
        "name": "approve",
        "outputs": [{"name": "success", "type": "bool"}],
        "type": "function",
    },
    # fee-related getters (optional)
    {
        "constant": True,
        "inputs": [],
        "name": "feeBasisPoints",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "feeReceiver",
        "outputs": [{"name": "", "type": "address"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [{"name": "account", "type": "address"}],
        "name": "isExcludedFromFee",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "feePercentTimes100",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
]

# ---------- User storage ----------
USERS_FILE = "users.json"


def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def save_users(users_dict):
    with open(USERS_FILE, "w") as f:
        json.dump(users_dict, f, indent=2)


users = load_users()

# in-memory state
user_states = {}
pending_trades = {}

# ---------- helpers for user profile ----------
def ensure_profile(user_id):
    uid = str(user_id)
    if uid not in users:
        return None
    profile = users[uid]
    if "settings" not in profile:
        profile["settings"] = {"slippage": 0.03, "gas_mode": "standard"}
    if "positions" not in profile:
        profile["positions"] = {}
    return profile


def get_user_account(user_id):
    uid = str(user_id)
    if uid not in users:
        return None, None
    profile = ensure_profile(user_id)
    pk = profile["private_key"]
    acct = w3.eth.account.from_key(pk)
    return acct, pk


def get_user_settings(user_id):
    profile = ensure_profile(user_id)
    if not profile:
        return {"slippage": 0.03, "gas_mode": "standard"}
    return profile["settings"]


def get_user_positions(user_id):
    profile = ensure_profile(user_id)
    if not profile:
        return {}
    return profile["positions"]


# ---------- Telegram helpers ----------
def send_request(method, payload):
    try:
        r = requests.post(f"{TG_BASE_URL}/{method}", json=payload, timeout=30)
        return r.json()
    except Exception as e:
        print("Telegram error:", e)
        return None


def send_message(chat_id, text, buttons=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    return send_request("sendMessage", payload)


def edit_message(chat_id, message_id, text, buttons=None):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown",
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    return send_request("editMessageText", payload)


def get_main_menu(has_wallet: bool):
    if has_wallet:
        return [
            [
                {"text": "💼 Wallet", "callback_data": "wallet"},
                {"text": "🪙 Trade", "callback_data": "trade_menu"},
            ],
            [
                {"text": "📊 Portfolio", "callback_data": "portfolio"},
                {"text": "⚙ Settings", "callback_data": "settings"},
            ],
            [
                {"text": "❓ Help", "callback_data": "help"},
                {"text": "🔐 Disconnect", "callback_data": "disconnect"},
            ],
        ]
    else:
        return [
            [{"text": "🔐 Connect Wallet", "callback_data": "connect_wallet"}],
            [{"text": "❓ Help", "callback_data": "help"}],
        ]


# ---------- Web3 helpers ----------
def get_token_contract(token_address: str):
    return w3.eth.contract(
        address=Web3.to_checksum_address(token_address),
        abi=ERC20_ABI,
    )


def get_bnb_price_usd():
    try:
        one_bnb = w3.to_wei(1, "ether")
        path = [WBNB, BUSD]
        amounts = router.functions.getAmountsOut(one_bnb, path).call()
        return amounts[-1] / (10**18)
    except Exception as e:
        print("BNB price error:", e)
        return None


def format_number(value, decimals=4):
    if value is None:
        return "Unknown"
    try:
        v = float(value)
    except Exception:
        return str(value)
    if v == 0:
        return "0"
    if abs(v) >= 1_000_000_000:
        return f"{v/1_000_000_000:.2f}B"
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"{v/1_000:.2f}K"
    return f"{v:.{decimals}f}"


def get_holders_count_from_bscscan(token_address: str):
    try:
        url = f"https://bscscan.com/token/{token_address}"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            return "Unknown"
        m = re.search(r"Holders:\s*([\d,]+)", resp.text)
        if m:
            return m.group(1)
    except Exception as e:
        print("Holders fetch error:", e)
    return "Unknown"


def get_path_for_buy(token_address: str):
    token = Web3.to_checksum_address(token_address)
    if token == WBNB:
        raise Exception("Cannot buy WBNB with BNB")

    # Try direct path
    try:
        router.functions.getAmountsOut(w3.to_wei(1, "ether"), [WBNB, token]).call()
        return [WBNB, token]
    except:
        pass

    # Try via BUSD
    try:
        router.functions.getAmountsOut(w3.to_wei(1, "ether"), [WBNB, BUSD, token]).call()
        return [WBNB, BUSD, token]
    except:
        pass

    # Try via USDT
    try:
        router.functions.getAmountsOut(w3.to_wei(1, "ether"), [WBNB, USDT, token]).call()
        return [WBNB, USDT, token]
    except:
        pass

    # Try via USDC
    try:
        router.functions.getAmountsOut(w3.to_wei(1, "ether"), [WBNB, USDC, token]).call()
        return [WBNB, USDC, token]
    except:
        pass

    raise Exception("No valid path found for this token")


def get_token_info(token_address: str):
    token_address = Web3.to_checksum_address(token_address)
    token = get_token_contract(token_address)

    symbol = token.functions.symbol().call()
    decimals = token.functions.decimals().call()
    total_supply_raw = token.functions.totalSupply().call()
    total_supply = total_supply_raw / (10**decimals)

    price_usd = None
    tokens_per_bnb = None
    mc_usd = None

    try:
        one_bnb = w3.to_wei(1, "ether")
        path = get_path_for_buy(token_address)
        amt_out = router.functions.getAmountsOut(one_bnb, path).call()[-1]
        tokens_per_bnb = amt_out / (10**decimals)
        bnb_price = get_bnb_price_usd()
        if bnb_price is not None and tokens_per_bnb > 0:
            price_usd = bnb_price / tokens_per_bnb
            mc_usd = price_usd * total_supply
    except Exception as e:
        print("Token price calc error:", e)

    holders = get_holders_count_from_bscscan(token_address)

    # try to read fee info if token exposes it
    fee_percent = 0.0
    fee_receiver = None
    try:
        fee_bp = None
        try:
            fee_bp = token.functions.feeBasisPoints().call()
        except Exception:
            try:
                fee_bp = token.functions.feePercentTimes100().call()
            except Exception:
                fee_bp = None

        if fee_bp is not None:
            fee_percent = float(fee_bp) / 100.0
            try:
                fee_receiver = token.functions.feeReceiver().call()
            except Exception:
                fee_receiver = None
    except Exception as e:
        print("Fee read error:", e)

    return {
        "address": token_address,
        "symbol": symbol,
        "decimals": decimals,
        "total_supply": total_supply,
        "price_usd": price_usd,
        "tokens_per_bnb": tokens_per_bnb,
        "market_cap_usd": mc_usd,
        "holders": holders,
        "fee_percent": fee_percent,
        "fee_receiver": fee_receiver,
    }


def basic_risk_check(token_address: str):
    try:
        amount_in_bnb = 0.01
        amount_in_wei = w3.to_wei(amount_in_bnb, "ether")
        token_addr = Web3.to_checksum_address(token_address)

        path_buy = get_path_for_buy(token_addr)
        token_out = router.functions.getAmountsOut(amount_in_wei, path_buy).call()[-1]

        path_sell = list(reversed(path_buy))
        bnb_back = router.functions.getAmountsOut(token_out, path_sell).call()[-1]
        bnb_back_float = float(w3.from_wei(bnb_back, "ether"))

        effective_loss = 1 - (bnb_back_float / amount_in_bnb)
        loss_pct = max(effective_loss * 100, 0)

        if loss_pct < 5:
            level = "🟢 Low tax / normal"
        elif loss_pct < 25:
            level = "🟡 Medium tax / degen"
        else:
            level = "🔴 High tax / possible honeypot"

        return f"{level}\nEstimated roundtrip loss on 1 trade: ~{loss_pct:.2f}%"
    except Exception as e:
        return f"⚠ Risk check failed (illiquid or blocked): {e}"


def get_user_gas_price(user_id):
    base = w3.eth.gas_price
    settings = get_user_settings(user_id)
    mode = settings.get("gas_mode", "standard")
    mult_map = {
        "standard": 1.0,
        "fast": 1.2,
        "turbo": 1.5,
    }
    m = mult_map.get(mode, 1.0)
    return int(base * m)


def get_amount_out(amount_bnb, token_address: str):
    """
    Returns estimated raw token amount (integer, token units) for amount_bnb BNB
    Uses router.getAmountsOut (conservative for no-fee tokens).
    """
    amount_wei = w3.to_wei(amount_bnb, "ether")
    path = get_path_for_buy(token_address)
    try:
        amounts = router.functions.getAmountsOut(amount_wei, path).call()
        out_raw = amounts[-1]
        return out_raw
    except Exception as e:
        print("get_amount_out error:", e)
        raise


def swap_bnb_for_token(user_id, amount_bnb, token_address):
    acct, pk = get_user_account(user_id)
    if not acct:
        raise Exception("Wallet not connected")

    settings = get_user_settings(user_id)
    slippage = settings.get("slippage", 0.03)

    amount_in_wei = w3.to_wei(amount_bnb, "ether")
    path = get_path_for_buy(token_address)

    # estimate expected_out using router
    expected_out = router.functions.getAmountsOut(amount_in_wei, path).call()[-1]
    amount_out_min = int(expected_out * (1 - slippage))
    deadline = int(time.time()) + 600

    tx = wrapper.functions.swapExactETHForTokensSupportingFeeOnTransferTokens(
        amount_out_min, path, acct.address, deadline
    ).build_transaction(
        {
            "from": acct.address,
            "value": amount_in_wei,
            "gas": 600000,
            "gasPrice": get_user_gas_price(user_id),
            "nonce": w3.eth.get_transaction_count(acct.address),
            "chainId": 56,
        }
    )

    signed = w3.eth.account.sign_transaction(tx, pk)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.to_hex(tx_hash), expected_out


def approve_token_if_needed_for_wrapper(user_id, user_addr, user_pk, token_address, amount_wei):
    token = get_token_contract(token_address)
    current = token.functions.allowance(user_addr, WRAPPER_ADDRESS).call()
    if current >= amount_wei:
        return None

    max_uint = 2**256 - 1
    tx = token.functions.approve(WRAPPER_ADDRESS, max_uint).build_transaction(
        {
            "from": user_addr,
            "gas": 150_000,
            "gasPrice": get_user_gas_price(user_id),
            "nonce": w3.eth.get_transaction_count(user_addr),
            "chainId": 56,
        }
    )
    signed = w3.eth.account.sign_transaction(tx, user_pk)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return tx_hash


def swap_token_for_bnb(user_id, token_address, amount_tokens):
    acct, pk = get_user_account(user_id)
    if not acct:
        raise Exception("Wallet not connected")

    token = get_token_contract(token_address)
    decimals = token.functions.decimals().call()
    amount_in_wei = int(amount_tokens * (10**decimals))

    # ensure wrapper approved
    approve_hash = approve_token_if_needed_for_wrapper(user_id, acct.address, pk, token_address, amount_in_wei)
    if approve_hash:
        # Wait for approval to be mined
        w3.eth.wait_for_transaction_receipt(approve_hash, timeout=120)

    settings = get_user_settings(user_id)
    slippage = settings.get("slippage", 0.03)

    path = list(reversed(get_path_for_buy(token_address)))
    expected_out = router.functions.getAmountsOut(amount_in_wei, path).call()[-1]
    amount_out_min = int(expected_out * (1 - slippage))
    deadline = int(time.time()) + 600

    tx = wrapper.functions.swapExactTokensForETHSupportingFeeOnTransferTokens(
        amount_in_wei, amount_out_min, path, acct.address, deadline
    ).build_transaction(
        {
            "from": acct.address,
            "gas": 800000,
            "gasPrice": get_user_gas_price(user_id),
            "nonce": w3.eth.get_transaction_count(acct.address),
            "chainId": 56,
        }
    )
    signed = w3.eth.account.sign_transaction(tx, pk)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.to_hex(tx_hash), expected_out


# ---------- Portfolio / positions ----------
def update_position_buy(user_id, token_addr, symbol, tokens_bought, price_usd):
    profile = ensure_profile(user_id)
    if not profile:
        return
    positions = profile["positions"]
    t = token_addr
    old = positions.get(t)
    if old:
        old_amount = old["amount"]
        old_avg = old["avg_price_usd"]
        new_amount = old_amount + tokens_bought
        if new_amount <= 0:
            positions.pop(t, None)
        else:
            new_avg = (old_amount * old_avg + tokens_bought * price_usd) / new_amount
            positions[t] = {"symbol": symbol, "amount": new_amount, "avg_price_usd": new_avg}
    else:
        positions[t] = {"symbol": symbol, "amount": tokens_bought, "avg_price_usd": price_usd}
    save_users(users)


def update_position_sell(user_id, token_addr, tokens_sold):
    profile = ensure_profile(user_id)
    if not profile:
        return
    positions = profile["positions"]
    t = token_addr
    old = positions.get(t)
    if not old:
        return
    new_amount = old["amount"] - tokens_sold
    if new_amount <= 0:
        positions.pop(t, None)
    else:
        old["amount"] = new_amount
        positions[t] = old
    save_users(users)


# ---------- Callback handler ----------
def handle_callback(cb):
    chat_id = cb["message"]["chat"]["id"]
    user_id = cb["from"]["id"]
    msg_id = cb["message"]["message_id"]
    data = cb["data"]
    uid = str(user_id)
    has_wallet = uid in users

    # connect / disconnect / basics
    if data == "connect_wallet":
        user_states[user_id] = {"step": "await_pk", "data": {}}
        edit_message(
            chat_id,
            msg_id,
            "🔐 Send your PRIVATE KEY.\n\n⚠ Use a fresh wallet. You are responsible for your funds.",
        )
        return

    if data == "disconnect":
        if uid in users:
            del users[uid]
            save_users(users)
        user_states.pop(user_id, None)
        edit_message(chat_id, msg_id, "Wallet disconnected.", get_main_menu(False))
        return

    if data == "wallet":
        if not has_wallet:
            edit_message(chat_id, msg_id, "No wallet connected.", get_main_menu(False))
            return
        acct, _ = get_user_account(user_id)
        bnb_balance = w3.from_wei(w3.eth.get_balance(acct.address), "ether")
        text = f"💼 *Wallet*\n\nAddress:\n`{acct.address}`\n\nBNB Balance: *{bnb_balance}*"
        edit_message(chat_id, msg_id, text, get_main_menu(True))
        return

    if data == "help":
        text = (
            "🤖 *BSC Multi-User Trading Bot*\n\n"
            "1️⃣ Connect wallet (fresh wallet only)\n"
            "2️⃣ Tap Trade → Buy or Sell\n"
            "3️⃣ Paste token contract address\n"
            "4️⃣ Bot shows price / MC / holders / risk\n"
            "5️⃣ Proceed → choose % or custom amount → confirm\n\n"
            "⚠ Only run this bot on your own server. Trades through this bot pay a fee to the operator."
        )
        edit_message(chat_id, msg_id, text, get_main_menu(has_wallet))
        return

    if data == "trade_menu":
        if not has_wallet:
            edit_message(chat_id, msg_id, "Connect a wallet first.", get_main_menu(False))
            return
        buttons = [
            [
                {"text": "🟢 Buy (BNB → Token)", "callback_data": "buy_flow"},
                {"text": "🔴 Sell (Token → BNB)", "callback_data": "sell_flow"},
            ],
            [{"text": "⬅️ Back", "callback_data": "back_main"}],
        ]
        edit_message(chat_id, msg_id, "Choose trade type:", buttons)
        return

    if data == "back_main":
        edit_message(chat_id, msg_id, "Main menu:", get_main_menu(has_wallet))
        return

    # settings menu
    if data == "settings":
        settings = get_user_settings(user_id) if has_wallet else {"slippage": 0.03, "gas_mode": "standard"}
        slip = settings["slippage"] * 100
        mode = settings["gas_mode"]
        text = (
            "⚙ *Settings*\n\n"
            f"Slippage: *{slip:.1f}%*\n"
            f"Gas mode: *{mode}*\n\n"
            "Adjust below:"
        )
        buttons = [
            [
                {"text": "Slippage 1%", "callback_data": "set_slip_1"},
                {"text": "3%", "callback_data": "set_slip_3"},
                {"text": "5%", "callback_data": "set_slip_5"},
            ],
            [
                {"text": "Gas: standard", "callback_data": "set_gas_standard"},
                {"text": "fast", "callback_data": "set_gas_fast"},
                {"text": "turbo", "callback_data": "set_gas_turbo"},
            ],
            [{"text": "⬅️ Back", "callback_data": "back_main"}],
        ]
        edit_message(chat_id, msg_id, text, buttons)
        return

    if data.startswith("set_slip_"):
        if not has_wallet:
            edit_message(chat_id, msg_id, "Connect wallet first.", get_main_menu(False))
            return
        profile = ensure_profile(user_id)
        if data == "set_slip_1":
            profile["settings"]["slippage"] = 0.01
        elif data == "set_slip_3":
            profile["settings"]["slippage"] = 0.03
        elif data == "set_slip_5":
            profile["settings"]["slippage"] = 0.05
        save_users(users)
        # refresh settings menu
        handle_callback({"message": cb["message"], "from": cb["from"], "data": "settings"})
        return

    if data.startswith("set_gas_"):
        if not has_wallet:
            edit_message(chat_id, msg_id, "Connect wallet first.", get_main_menu(False))
            return
        profile = ensure_profile(user_id)
        if data == "set_gas_standard":
            profile["settings"]["gas_mode"] = "standard"
        elif data == "set_gas_fast":
            profile["settings"]["gas_mode"] = "fast"
        elif data == "set_gas_turbo":
            profile["settings"]["gas_mode"] = "turbo"
        save_users(users)
        handle_callback({"message": cb["message"], "from": cb["from"], "data": "settings"})
        return

    # portfolio
    if data == "portfolio":
        if not has_wallet:
            edit_message(chat_id, msg_id, "Connect wallet first.", get_main_menu(False))
            return
        positions = get_user_positions(user_id)
        if not positions:
            edit_message(chat_id, msg_id, "📊 No tracked positions yet.", get_main_menu(True))
            return

        total_value = 0.0
        lines = ["📊 *Portfolio*"]
        for t, p in positions.items():
            symbol = p["symbol"]
            amount = p["amount"]
            avg = p["avg_price_usd"]
            try:
                info = get_token_info(t)
                price = info["price_usd"]
                if price is None:
                    lines.append(f"\n{symbol} ({t}):\nAmount: {format_number(amount)}\nPrice: Unknown")
                    continue
                val = amount * price
                pnl_pct = (price - avg) / avg * 100 if avg > 0 else 0
                total_value += val
                lines.append(
                    f"\n*{symbol}*\nCA: `{t}`\n"
                    f"Amount: {format_number(amount)}\n"
                    f"Avg: ${format_number(avg)}\n"
                    f"Now: ${format_number(price)}\n"
                    f"Value: ${format_number(val)}\n"
                    f"PnL: {pnl_pct:+.2f}%"
                )
            except Exception as e:
                lines.append(f"\n{symbol} ({t}): error fetching price: {e}")
        lines.append(f"\n*Total est. value:* ${format_number(total_value)}")
        edit_message(chat_id, msg_id, "\n".join(lines), get_main_menu(True))
        return

    # trade flows
    if data == "buy_flow":
        user_states[user_id] = {"step": "await_buy_token", "data": {}}
        edit_message(chat_id, msg_id, "🟢 Send *token contract address* to BUY:", None)
        return

    if data == "sell_flow":
        user_states[user_id] = {"step": "await_sell_token", "data": {}}
        edit_message(chat_id, msg_id, "🔴 Send *token contract address* to SELL:", None)
        return

    if data == "buy_proceed":
        state = user_states.get(user_id)
        if not state or state.get("step") != "await_buy_proceed":
            edit_message(chat_id, msg_id, "No token selected for BUY.", get_main_menu(has_wallet))
            return
        state["step"] = "await_buy_amount"
        token_addr = state["data"]["token"]
        # ask amount with presets
        buttons = [
            [
                {"text": "25% BNB", "callback_data": "buy_pct_25"},
                {"text": "50%", "callback_data": "buy_pct_50"},
                {"text": "100%", "callback_data": "buy_pct_100"},
            ],
        ]
        send_message(
            chat_id,
            "Enter BNB amount to BUY (e.g. `0.01`) or use presets below:",
            buttons,
        )
        return

    if data == "sell_proceed":
        state = user_states.get(user_id)
        if not state or state.get("step") != "await_sell_proceed":
            edit_message(chat_id, msg_id, "No token selected for SELL.", get_main_menu(has_wallet))
            return
        state["step"] = "await_sell_amount"
        token_addr = state["data"]["token"]
        acct, _ = get_user_account(user_id)
        balance_info = ""
        try:
            token = get_token_contract(token_addr)
            decimals = token.functions.decimals().call()
            symbol = token.functions.symbol().call()
            bal_raw = token.functions.balanceOf(acct.address).call()
            bal_human = bal_raw / (10**decimals)
            balance_info = f"\nYour balance: {format_number(bal_human)} {symbol}"
        except Exception:
            pass
        buttons = [
            [
                {"text": "25% tokens", "callback_data": "sell_pct_25"},
                {"text": "50%", "callback_data": "sell_pct_50"},
                {"text": "100%", "callback_data": "sell_pct_100"},
            ],
        ]
        send_message(
            chat_id,
            "Enter TOKEN amount to SELL (in normal units) or use presets." + balance_info,
            buttons,
        )
        return

    # refresh & risk check
    if data in ("buy_refresh", "sell_refresh", "buy_risk", "sell_risk"):
        state = user_states.get(user_id)
        if not state or "data" not in state or "token" not in state["data"]:
            edit_message(chat_id, msg_id, "No token in context.", get_main_menu(has_wallet))
            return
        token_addr = state["data"]["token"]
        try:
            info = get_token_info(token_addr)
        except Exception as e:
            edit_message(chat_id, msg_id, f"Error reading token info: {e}", get_main_menu(has_wallet))
            return

        state["data"]["info"] = info
        base = (
            "📊 TOKEN OVERVIEW (BUY)\n\n"
            if data.startswith("buy_")
            else "📊 TOKEN OVERVIEW (SELL)\n\n"
        )
        text = (
            f"{base}"
            f"Symbol: {info['symbol']}\n"
            f"Address:\n`{info['address']}`\n\n"
            f"Price: {format_number(info['price_usd'])} USD\n"
            f"Market Cap: {format_number(info['market_cap_usd'])} USD\n"
            f"Total Supply: {format_number(info['total_supply'])} {info['symbol']}\n"
            f"Holders: {info['holders']}\n"
        )

        if data.endswith("risk"):
            risk = basic_risk_check(token_addr)
            text += f"\n*Risk check:*\n{risk}\n"

        # if token exposes fee, show it
        if info.get("fee_percent", 0.0) > 0:
            text += f"\nToken fee: ~{info['fee_percent']:.2f}% (to: {info.get('fee_receiver')})\n"

        text += "\nPress Proceed to continue."

        buttons = [
            [
                {"text": "🔄 Refresh", "callback_data": data.split("_")[0] + "_refresh"},
                {"text": "🧪 Risk", "callback_data": data.split("_")[0] + "_risk"},
            ],
            [
                {"text": "✅ Proceed", "callback_data": data.split("_")[0] + "_proceed"},
                {"text": "❌ Cancel", "callback_data": "cancel_trade"},
            ],
        ]
        edit_message(chat_id, msg_id, text, buttons)
        return

    # presets buy %
    if data in ("buy_pct_25", "buy_pct_50", "buy_pct_100"):
        state = user_states.get(user_id)
        if not state or state.get("step") != "await_buy_amount":
            send_message(chat_id, "No token context for preset. Start /start again.")
            return
        token_addr = state["data"]["token"]
        acct, _ = get_user_account(user_id)
        bal_wei = w3.eth.get_balance(acct.address)
        bal_bnb = float(w3.from_wei(bal_wei, "ether"))
        pct = {"buy_pct_25": 0.25, "buy_pct_50": 0.5, "buy_pct_100": 1.0}[data]
        amount = bal_bnb * pct
        if amount <= 0:
            send_message(chat_id, "BNB balance too low for this preset.")
            return
        # directly show confirmation
        prepare_buy_confirmation(user_id, chat_id, token_addr, amount)
        user_states.pop(user_id, None)
        return

    # presets sell %
    if data in ("sell_pct_25", "sell_pct_50", "sell_pct_100"):
        state = user_states.get(user_id)
        if not state or state.get("step") != "await_sell_amount":
            send_message(chat_id, "No token context for preset. Start /start again.")
            return
        token_addr = state["data"]["token"]
        acct, _ = get_user_account(user_id)
        token = get_token_contract(token_addr)
        decimals = token.functions.decimals().call()
        symbol = token.functions.symbol().call()
        bal_raw = token.functions.balanceOf(acct.address).call()
        bal_human = bal_raw / (10**decimals)
        pct = {"sell_pct_25": 0.25, "sell_pct_50": 0.5, "sell_pct_100": 1.0}[data]
        amount = bal_human * pct
        if amount <= 0:
            send_message(chat_id, f"{symbol} balance too low for this preset.")
            return
        prepare_sell_confirmation(user_id, chat_id, token_addr, amount)
        user_states.pop(user_id, None)
        return

    if data == "confirm_buy":
        trade = pending_trades.get(user_id)
        if not trade or trade.get("type") != "buy":
            edit_message(chat_id, msg_id, "No pending BUY trade.", get_main_menu(has_wallet))
            return
        token = trade["token"]
        amount_bnb = trade["amount"]
        try:
            info = get_token_info(token)
            tx, expected_out = swap_bnb_for_token(user_id, amount_bnb, token)
            decimals = info["decimals"]
            tokens_bought = expected_out / (10**decimals)
            price = info["price_usd"] or 0
            update_position_buy(user_id, token, info["symbol"], tokens_bought, price)
            bscscan = f"https://bscscan.com/tx/{tx}"
            edit_message(
                chat_id,
                msg_id,
                f"✅ BUY submitted!\n\nTx: `{tx}`\n{bscscan}",
                get_main_menu(has_wallet),
            )
        except Exception as e:
            edit_message(chat_id, msg_id, f"❌ BUY failed: `{e}`", get_main_menu(has_wallet))
        finally:
            pending_trades.pop(user_id, None)
        return

    if data == "confirm_sell":
        trade = pending_trades.get(user_id)
        if not trade or trade.get("type") != "sell":
            edit_message(chat_id, msg_id, "No pending SELL trade.", get_main_menu(has_wallet))
            return
        token = trade["token"]
        amount_tokens = trade["amount"]
        try:
            info = get_token_info(token)
            tx, expected_out = swap_token_for_bnb(user_id, token, amount_tokens)
            update_position_sell(user_id, token, amount_tokens)
            bnb_received = float(w3.from_wei(expected_out, "ether"))
            bscscan = f"https://bscscan.com/tx/{tx}"
            edit_message(
                chat_id,
                msg_id,
                f"✅ SELL submitted!\n\nEst. BNB: {bnb_received}\n\nTx: `{tx}`\n{bscscan}",
                get_main_menu(has_wallet),
            )
        except Exception as e:
            edit_message(chat_id, msg_id, f"❌ SELL failed: `{e}`", get_main_menu(has_wallet))
        finally:
            pending_trades.pop(user_id, None)
        return

    if data == "cancel_trade":
        pending_trades.pop(user_id, None)
        user_states.pop(user_id, None)
        edit_message(chat_id, msg_id, "Trade cancelled.", get_main_menu(has_wallet))
        return


# ---------- helper to build confirmations ----------
def prepare_buy_confirmation(user_id, chat_id, token_addr, amount_bnb):
    try:
        out_raw = get_amount_out(amount_bnb, token_addr)
        token = get_token_contract(token_addr)
        decimals = token.functions.decimals().call()
        symbol = token.functions.symbol().call()
        out_human = out_raw / (10**decimals)
        try:
            info = get_token_info(token_addr)
        except Exception:
            info = {"fee_percent": 0.0, "fee_receiver": None}
    except Exception as e:
        send_message(chat_id, f"Error quoting price: `{e}`")
        return

    pending_trades[user_id] = {"type": "buy", "token": token_addr, "amount": amount_bnb}

    fee_line = ""
    if info.get("fee_percent", 0.0) > 0:
        fee_line = f"\nToken fee: ~{info['fee_percent']:.2f}% (sent to {info.get('fee_receiver')})"

    buttons = [
        [
            {"text": "✅ Confirm BUY", "callback_data": "confirm_buy"},
            {"text": "❌ Cancel", "callback_data": "cancel_trade"},
        ]
    ]
    send_message(
        chat_id,
        f"🟢 *BUY CONFIRMATION*\n\nToken: *{symbol}*\nCA: `{token_addr}`\n"
        f"Amount: *{amount_bnb}* BNB\nEst. received (router quote): *{out_human}* {symbol}"
        f"{fee_line}\n\nConfirm?",
        buttons,
    )


def prepare_sell_confirmation(user_id, chat_id, token_addr, amount_tokens):
    try:
        token = get_token_contract(token_addr)
        decimals = token.functions.decimals().call()
        symbol = token.functions.symbol().call()
        amount_in_wei = int(amount_tokens * (10**decimals))
        path = list(reversed(get_path_for_buy(token_addr)))
        out_raw = router.functions.getAmountsOut(amount_in_wei, path).call()[-1]
        # note: tokens with transfer tax may cause actual received to differ
        out_bnb = float(w3.from_wei(out_raw, "ether"))
    except Exception as e:
        send_message(chat_id, f"Error quoting sell: `{e}`")
        return

    pending_trades[user_id] = {"type": "sell", "token": token_addr, "amount": amount_tokens}

    fee_line = ""
    try:
        info = get_token_info(token_addr)
        if info.get("fee_percent", 0.0) > 0:
            fee_line = f"\nToken fee: ~{info['fee_percent']:.2f}% (sent to {info.get('fee_receiver')})"
    except Exception:
        pass

    buttons = [
        [
            {"text": "✅ Confirm SELL", "callback_data": "confirm_sell"},
            {"text": "❌ Cancel", "callback_data": "cancel_trade"},
        ]
    ]
    send_message(
        chat_id,
        f"🔴 *SELL CONFIRMATION*\n\nToken: *{symbol}*\nCA: `{token_addr}`\n"
        f"Amount: *{amount_tokens}* {symbol}\nEst. received (router quote): *{out_bnb}* BNB"
        f"{fee_line}\n\nConfirm?",
        buttons,
    )


# ---------- Message handler ----------
def handle_message(msg):
    chat_id = msg["chat"]["id"]
    user_id = msg["from"]["id"]
    text = msg.get("text", "").strip()
    uid = str(user_id)
    has_wallet = uid in users

    state = user_states.get(user_id)

    # awaiting private key
    if state and state.get("step") == "await_pk":
        if not text.startswith("0x") or len(text) < 60:
            send_message(chat_id, "❌ Invalid private key format. Try again or /start.")
            return
        try:
            acct = w3.eth.account.from_key(text)
        except Exception:
            send_message(chat_id, "❌ Could not parse this private key.")
            return

        users[uid] = {
            "private_key": text,
            "address": acct.address,
            "settings": {"slippage": 0.03, "gas_mode": "standard"},
            "positions": {},
        }
        save_users(users)
        user_states.pop(user_id, None)
        send_message(
            chat_id,
            f"✅ Wallet connected!\nAddress:\n`{acct.address}`",
            get_main_menu(True),
        )
        return

    # awaiting BUY token CA -> show token info
    if state and state.get("step") == "await_buy_token":
        try:
            token_addr = Web3.to_checksum_address(text)
        except Exception:
            send_message(chat_id, "❌ Invalid contract address. Send again.")
            return

        try:
            info = get_token_info(token_addr)
        except Exception as e:
            send_message(chat_id, f"Error reading token info: `{e}`")
            user_states.pop(user_id, None)
            return

        user_states[user_id] = {
            "step": "await_buy_proceed",
            "data": {"token": info["address"], "info": info},
        }

        fee_line = ""
        if info.get("fee_percent", 0.0) > 0:
            fee_line = f"\nToken fee: ~{info['fee_percent']:.2f}% (to: {info.get('fee_receiver')})"

        info_text = (
            "📊 *TOKEN OVERVIEW (BUY)*\n\n"
            f"Symbol: *{info['symbol']}*\n"
            f"Address:\n`{info['address']}`\n\n"
            f"Price: *{format_number(info['price_usd'])}* USD\n"
            f"Market Cap: *{format_number(info['market_cap_usd'])}* USD\n"
            f"Total Supply: *{format_number(info['total_supply'])}* {info['symbol']}\n"
            f"Holders: *{info['holders']}*"
            f"{fee_line}\n\n"
            "Press buttons to refresh, check risk, or proceed."
        )

        buttons = [
            [
                {"text": "🔄 Refresh", "callback_data": "buy_refresh"},
                {"text": "🧪 Risk", "callback_data": "buy_risk"},
            ],
            [
                {"text": "✅ Proceed", "callback_data": "buy_proceed"},
                {"text": "❌ Cancel", "callback_data": "cancel_trade"},
            ],
        ]
        send_message(chat_id, info_text, buttons)
        return

    # awaiting BUY amount (custom)
    if state and state.get("step") == "await_buy_amount":
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError()
        except Exception:
            send_message(chat_id, "❌ Invalid amount. Send a positive number.")
            return

        token_addr = state["data"]["token"]
        prepare_buy_confirmation(user_id, chat_id, token_addr, amount)
        user_states.pop(user_id, None)
        return

    # awaiting SELL token CA -> show info
    if state and state.get("step") == "await_sell_token":
        try:
            token_addr = Web3.to_checksum_address(text)
        except Exception:
            send_message(chat_id, "❌ Invalid contract address. Send again.")
            return

        try:
            info = get_token_info(token_addr)
        except Exception as e:
            send_message(chat_id, f"Error reading token info: `{e}`")
            user_states.pop(user_id, None)
            return

        acct, _ = get_user_account(user_id) if has_wallet else (None, None)
        balance_line = ""
        if acct:
            try:
                token = get_token_contract(token_addr)
                decimals = token.functions.decimals().call()
                bal_raw = token.functions.balanceOf(acct.address).call()
                bal_human = bal_raw / (10**decimals)
                balance_line = f"\nYour balance: *{format_number(bal_human)}* {info['symbol']}"
            except Exception:
                pass

        user_states[user_id] = {
            "step": "await_sell_proceed",
            "data": {"token": info["address"], "info": info},
        }

        fee_line = ""
        if info.get("fee_percent", 0.0) > 0:
            fee_line = f"\nToken fee: ~{info['fee_percent']:.2f}% (to: {info.get('fee_receiver')})"

        info_text = (
            "📊 *TOKEN OVERVIEW (SELL)*\n\n"
            f"Symbol: *{info['symbol']}*\n"
            f"Address:\n`{info['address']}`\n\n"
            f"Price: *{format_number(info['price_usd'])}* USD\n"
            f"Market Cap: *{format_number(info['market_cap_usd'])}* USD\n"
            f"Total Supply: *{format_number(info['total_supply'])}* {info['symbol']}\n"
            f"Holders: *{info['holders']}*"
            f"{balance_line}{fee_line}\n\n"
            "Press buttons to refresh, check risk, or proceed."
        )

        buttons = [
            [
                {"text": "🔄 Refresh", "callback_data": "sell_refresh"},
                {"text": "🧪 Risk", "callback_data": "sell_risk"},
            ],
            [
                {"text": "✅ Proceed", "callback_data": "sell_proceed"},
                {"text": "❌ Cancel", "callback_data": "cancel_trade"},
            ],
        ]
        send_message(chat_id, info_text, buttons)
        return

    # awaiting SELL amount (custom)
    if state and state.get("step") == "await_sell_amount":
        try:
            amount = float(text)
            if amount <= 0:
                raise ValueError()
        except Exception:
            send_message(chat_id, "❌ Invalid amount. Send a positive number.")
            return

        token_addr = state["data"]["token"]
        prepare_sell_confirmation(user_id, chat_id, token_addr, amount)
        user_states.pop(user_id, None)
        return

    # no active state
    if text == "/start":
        send_message(
            chat_id,
            "Welcome to the *BSC Multi-User Trading Bot*.\nUse the menu below.",
            get_main_menu(has_wallet),
        )
        return

    send_message(chat_id, "Use the menu buttons below.", get_main_menu(has_wallet))


# ---------- Long polling main loop ----------
def main():
    last_update_id = 0
    print("Trading bot started.")
    while True:
        try:
            resp = requests.get(
                f"{TG_BASE_URL}/getUpdates",
                params={"offset": last_update_id + 1, "timeout": 50},
                timeout=60,
            )
            data = resp.json()
            for upd in data.get("result", []):
                last_update_id = upd["update_id"]
                if "callback_query" in upd:
                    handle_callback(upd["callback_query"])
                elif "message" in upd:
                    handle_message(upd["message"])
        except Exception as e:
            print("Loop error:", e)
            time.sleep(3)


if __name__ == "__main__":
    main() 