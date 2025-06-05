"""
This module provides functions to fetch token security analysis and trading pair data
from external APIs like GoPlus Security and DexScreener.
It requires API keys to be configured in config.json for some services (e.g., GoPlus).
The `config.json` should be populated based on `config.json.example`.
API keys can also be supplied via environment variables (e.g., GOPLUS_API_KEY).
"""
import requests
import json
import time
import hashlib
import uuid
import os
from typing import Optional, List, Dict, Any, TypedDict
from web3 import Web3 # For address validation

# --- Data Structures ---
class LPTokenInfo(TypedDict):
    """
    Represents information about a liquidity pool (LP) token holder.
    Fields:
        address (str): Holder's address.
        balance (float): Amount of LP tokens held by this address.
        percent_of_total_lp (float): Percentage of total LP supply held by this address.
        is_contract (bool): True if the holder is a smart contract.
        tag (Optional[str]): A tag associated with the holder (e.g., "Uniswap V2 Pair").
        is_locked (bool): True if the LP tokens are known to be locked (e.g., in a vesting contract).
        locked_details (Optional[List[Dict[str, Any]]]): Details about the lock, if any.
    """
    address: str
    balance: float
    percent_of_total_lp: float
    is_contract: bool
    tag: Optional[str]
    is_locked: bool
    locked_details: Optional[List[Dict[str, Any]]]

class TokenSecurityReport(TypedDict):
    """
    Represents a comprehensive security report for a token, primarily from GoPlus.
    Fields are derived from GoPlus API response and include security flags, tax info,
    LP details, and custom warnings/remarks.
    """
    token_address: str  # The address of the token analyzed
    chain_id: str       # GoPlus-specific chain ID (numeric string, e.g., "1" for Ethereum)
    retrieved_at: int   # Unix timestamp (seconds) of when the report was fetched

    # Contract Security Flags (from GoPlus)
    is_open_source: Optional[bool]      # Is the contract source code verified?
    is_proxy: Optional[bool]            # Is the contract a proxy contract?
    is_mintable: Optional[bool]         # Can new tokens be minted?
    owner_address: Optional[str]        # Address of the contract owner.
    can_take_back_ownership: Optional[bool] # Can ownership be reclaimed if renounced?
    owner_can_change_balance: Optional[bool] # Can owner arbitrarily change user balances? (Highly risky)
    has_hidden_owner: Optional[bool]    # Is there a hidden owner mechanism?
    can_self_destruct: Optional[bool]   # Can the contract be self-destructed? (Risky if by malicious owner)

    # Trading & DEX Information (from GoPlus)
    is_in_dex: Optional[bool]           # Is the token listed on any DEX tracked by GoPlus?
    buy_tax: Optional[float]            # Buy tax percentage (e.g., 0.01 for 1%).
    sell_tax: Optional[float]           # Sell tax percentage.
    transfer_tax: Optional[float]       # Tax on token transfers between wallets.

    # Honeypot & Trading Flags (from GoPlus)
    cannot_buy: Optional[bool]          # Is buying disabled? (Usually a temporary state or scam)
    cannot_sell_all: Optional[bool]     # Are there restrictions on selling the entire balance?
    is_honeypot: Optional[bool]         # Is the token identified as a honeypot? (CRITICAL)

    is_trading_pausable: Optional[bool] # Can trading be paused by the owner?
    has_blacklist: Optional[bool]       # Does the contract have a blacklist function?
    has_whitelist: Optional[bool]       # Does the contract have a whitelist function?
    is_anti_whale: Optional[bool]       # Are there anti-whale mechanisms (e.g., max transaction amount)?
    has_trading_cooldown: Optional[bool] # Is there a cooldown period between trades?
    can_owner_modify_taxes: Optional[bool] # Can the owner change buy/sell taxes?

    # Liquidity Pool Information (from GoPlus)
    top_lp_holders: List[LPTokenInfo]           # Information on top LP token holders.
    total_lp_liquidity_usd: Optional[float] # Summed USD liquidity from all DEXs known to GoPlus.

    # Custom Generated Summary
    warnings: List[str]                 # List of human-readable warnings based on analysis.
    remarks: List[str]                  # List of human-readable remarks or positive notes.

    raw_goplus_response: Dict[str, Any] # The raw JSON data for this token from GoPlus.

class PairReport(TypedDict):
    """
    Represents trading pair information, primarily from DexScreener.
    Fields:
        pair_address (str): Address of the liquidity pair contract.
        base_token_address (str): Address of the base token in the pair.
        quote_token_address (str): Address of the quote token in the pair.
        chain_id (str): DexScreener's string representation of the chain (e.g., "ethereum").
        dex_id (Optional[str]): Identifier for the DEX (e.g., "uniswap").
        price_usd (Optional[float]): Current price of the base token in USD.
        liquidity_usd (Optional[float]): Total liquidity of the pair in USD.
        volume_h24 (Optional[float]): Trading volume in the last 24 hours in USD.
        pair_created_at (Optional[int]): Unix timestamp (seconds) of when the pair was created.
        url (Optional[str]): URL to view the pair on DexScreener.
    """
    pair_address: str
    base_token_address: str
    quote_token_address: str
    chain_id: str
    dex_id: Optional[str]
    price_usd: Optional[float]
    liquidity_usd: Optional[float]
    volume_h24: Optional[float]
    pair_created_at: Optional[int]
    url: Optional[str]


# --- Global Cache/Config ---
ANALYZER_CONFIG: Dict[str, Any] = {} # Caches loaded configuration, e.g., API keys
GOPLUS_AUTH_TOKEN: Optional[str] = None # Caches GoPlus auth token
GOPLUS_TOKEN_EXPIRY: int = 0 # Unix timestamp when the GoPlus token expires
GOPLUS_API_BASE_URL = "https://api.gopluslabs.io/api/v1" # Base URL for GoPlus API
DEXSCREENER_API_BASE_URL = "https://api.dexscreener.com/latest" # Base URL for DexScreener API


# --- Helper Functions for Data Conversion ---
def _str_to_bool(s: Optional[Any], field_name: str = "") -> Optional[bool]:
    """Safely converts GoPlus string ('0' or '1') or boolean to Python bool."""
    if s is None: return None
    if isinstance(s, bool): return s
    if isinstance(s, str):
        if s == '1': return True
        elif s == '0': return False
    # print(f"Warning (token_analyzer._str_to_bool): Unexpected boolean-like value for '{field_name}': {s} (type: {type(s)})")
    return None

def _str_to_float(s: Optional[Any], field_name: str = "") -> Optional[float]:
    """Safely converts GoPlus string representation of a float to Python float."""
    if s is None or s == "": return None
    if isinstance(s, (float, int)): return float(s)
    if isinstance(s, str):
        try: return float(s)
        except ValueError:
            # print(f"Warning (token_analyzer._str_to_float): Could not convert string to float for '{field_name}': {s}")
            return None
    # print(f"Warning (token_analyzer._str_to_float): Unexpected float-like value for '{field_name}': {s} (type: {type(s)})")
    return None


# --- Configuration & Authentication for GoPlus API ---
def _load_analyzer_config(config_path: str = 'config.json') -> bool:
    """
    Loads API credentials and other settings from the config file.
    Prioritizes environment variables for API keys if available.
    Returns True if essential GoPlus API key is found, False otherwise.
    """
    global ANALYZER_CONFIG
    if ANALYZER_CONFIG.get('goplus_api_key_loaded'): # Check if already attempted loading
        return ANALYZER_CONFIG.get('goplus_api_key') is not None

    try:
        if not os.path.exists(config_path):
            print(f"Warning (_load_analyzer_config): Config file '{config_path}' not found. GoPlus features may be limited.")
            ANALYZER_CONFIG['goplus_api_key'] = os.getenv('GOPLUS_API_KEY') # Try env var even if file missing
            ANALYZER_CONFIG['goplus_api_key_loaded'] = True
            if not ANALYZER_CONFIG['goplus_api_key']:
                 print("Warning: GoPlus API key also not found in GOPLUS_API_KEY environment variable.")
                 return False
            print("Loaded GoPlus API key from environment variable.")
            return True

        with open(config_path, 'r') as f:
            config_data = json.load(f).get("token_analysis_apis", {}) # Look within this section

        ANALYZER_CONFIG['goplus_api_key'] = os.getenv('GOPLUS_API_KEY', config_data.get('goplus_security', {}).get('api_key'))
        ANALYZER_CONFIG['goplus_api_secret'] = os.getenv('GOPLUS_API_SECRET', config_data.get('goplus_security', {}).get('api_secret'))
        ANALYZER_CONFIG['goplus_api_key_loaded'] = True # Mark that loading was attempted

        if not ANALYZER_CONFIG['goplus_api_key']:
            print("Warning: `goplus_api_key` not found in config's `token_analysis_apis.goplus_security` section or GOPLUS_API_KEY env var. GoPlus features disabled.")
            return False
        return True
    except Exception as e:
        print(f"Error loading analyzer config from '{config_path}': {type(e).__name__} - {e}")
        ANALYZER_CONFIG['goplus_api_key'] = None
        ANALYZER_CONFIG['goplus_api_key_loaded'] = True # Still mark as attempted
        return False


def _get_goplus_auth_token(force_refresh: bool = False) -> Optional[str]:
    """
    Retrieves GoPlus API authentication token. Handles caching and refreshing.
    Signature generation: sha256(app_key + Lowercase(nonce) + request_time_unix_seconds_str).
    """
    global GOPLUS_AUTH_TOKEN, GOPLUS_TOKEN_EXPIRY

    if not _load_analyzer_config() or not ANALYZER_CONFIG.get('goplus_api_key'):
        print("GoPlus API key not configured. Cannot get auth token.")
        return None

    api_key = ANALYZER_CONFIG['goplus_api_key']
    current_time_seconds = int(time.time())

    if GOPLUS_AUTH_TOKEN and current_time_seconds < GOPLUS_TOKEN_EXPIRY and not force_refresh:
        return GOPLUS_AUTH_TOKEN

    request_time_str = str(current_time_seconds)
    nonce = uuid.uuid4().hex.lower()
    data_to_sign = f"{api_key}{nonce}{request_time_str}"
    signature = hashlib.sha256(data_to_sign.encode('utf-8')).hexdigest()

    auth_payload = {"app_key": api_key, "sign": signature, "time": request_time_str, "nonce": nonce}
    auth_url = f"{GOPLUS_API_BASE_URL}/token"

    try:
        print(f"Requesting new GoPlus auth token from {auth_url}...")
        response = requests.post(auth_url, json=auth_payload, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get('code') == 1 and data.get('result', {}).get('access_token'):
            GOPLUS_AUTH_TOKEN = data['result']['access_token']
            expires_in = int(data['result'].get('expires_in', 3600)) # Default 1 hour
            GOPLUS_TOKEN_EXPIRY = current_time_seconds + expires_in - 60 # 60s buffer
            print("Successfully obtained new GoPlus auth token.")
            return GOPLUS_AUTH_TOKEN
        else:
            print(f"Error from GoPlus /token API: {data.get('message')} (Code: {data.get('code')})")
            return None
    except Exception as e:
        print(f"Exception during GoPlus auth token request: {type(e).__name__} - {e}")
        return None

# --- Main Data Fetching Functions ---

def fetch_token_security_report(token_address: str, chain_id_str: str) -> Optional[TokenSecurityReport]:
    """
    Fetches a security report for a given token address on a specific chain using GoPlus API.

    Args:
        token_address (str): The contract address of the token.
        chain_id_str (str): The GoPlus-specific chain ID (e.g., "1" for Ethereum, "56" for BSC).

    Returns:
        Optional[TokenSecurityReport]: A dictionary containing the security report,
                                       or None if fetching or parsing fails.
    """
    if not Web3.is_address(token_address):
        print(f"Error (fetch_token_security_report): Invalid token address format: {token_address}")
        return None

    auth_token = _get_goplus_auth_token()
    if not auth_token:
        print("Error (fetch_token_security_report): Failed to obtain GoPlus auth token.")
        return None

    api_url = f"{GOPLUS_API_BASE_URL}/token_security/{chain_id_str}?contract_addresses={token_address}"
    headers = {"Authorization": f"Bearer {auth_token}"}

    try:
        print(f"Fetching GoPlus security report for {token_address} on chain {chain_id_str}...")
        response = requests.get(api_url, headers=headers, timeout=20)
        response.raise_for_status()
        response_json = response.json()

        if response_json.get('code') != 1:
            print(f"GoPlus API error for {token_address} (chain {chain_id_str}): {response_json.get('message')} (Code: {response_json.get('code')})")
            return None

        token_data_raw = response_json.get('result', {}).get(token_address.lower())
        if not token_data_raw:
            print(f"No data returned by GoPlus for token {token_address} on chain {chain_id_str}.")
            return None

        warnings_list: List[str] = []
        remarks_list: List[str] = []

        is_open_source = _str_to_bool(token_data_raw.get('is_open_source'), 'is_open_source')
        if is_open_source is False: warnings_list.append("Contract source code is not verified.")

        is_honeypot = _str_to_bool(token_data_raw.get('is_honeypot'), 'is_honeypot')
        if is_honeypot: warnings_list.append("CRITICAL: GoPlus flags token as a HONEYPOT.") # Corrected typo

        buy_tax = _str_to_float(token_data_raw.get('buy_tax'), 'buy_tax')
        sell_tax = _str_to_float(token_data_raw.get('sell_tax'), 'sell_tax')
        if buy_tax is not None and buy_tax > 0.10: warnings_list.append(f"High buy tax: {buy_tax*100:.1f}%")
        if sell_tax is not None and sell_tax > 0.10: warnings_list.append(f"High sell tax: {sell_tax*100:.1f}%")

        if _str_to_bool(token_data_raw.get('slippage_modifiable'), 'slippage_modifiable'): warnings_list.append("Owner can modify transaction taxes.")
        if _str_to_bool(token_data_raw.get('cannot_sell_all'), 'cannot_sell_all'): warnings_list.append("Token may have sell limits (cannot sell all at once).")
        if _str_to_bool(token_data_raw.get('transfer_pausable'), 'transfer_pausable'): warnings_list.append("Token trading can be paused by owner.")

        lp_holders_data = token_data_raw.get('lp_holders', [])
        parsed_lp_holders: List[LPTokenInfo] = [
            LPTokenInfo(
                address=lp_h.get('address','N/A'),
                balance=_str_to_float(lp_h.get('balance'), 'lp_h_balance') or 0.0,
                percent_of_total_lp=_str_to_float(lp_h.get('percent'), 'lp_h_percent') or 0.0,
                is_contract=_str_to_bool(lp_h.get('is_contract'), 'lp_h_is_contract') or False,
                tag=lp_h.get('tag'),
                is_locked=_str_to_bool(lp_h.get('locked'), 'lp_h_locked') or False,
                locked_details=lp_h.get('locked_detail')
            ) for lp_h in lp_holders_data
        ]

        if parsed_lp_holders:
            locked_lp_percent = sum(h['percent_of_total_lp'] for h in parsed_lp_holders if h['is_locked'])
            # Heuristic for LP lock warning/remark
            if locked_lp_percent < 0.80 and any(h['percent_of_total_lp'] > 0.05 for h in parsed_lp_holders if not h['is_locked']): # If significant LP is not locked
                 remarks_list.append(f"LP Lock: {locked_lp_percent*100:.2f}% of tracked top LP is locked. Some significant LPs might be unlocked.")
            elif locked_lp_percent >= 0.95 : # Most top LPs are locked
                remarks_list.append(f"LP Lock: High percentage ({locked_lp_percent*100:.2f}%) of tracked top LP is locked.")

        total_lp_usd = sum(_str_to_float(dex.get('liquidity'), 'dex_liquidity') or 0.0 for dex in token_data_raw.get('dex', []))
        if total_lp_usd < 5000 and total_lp_usd > 0: warnings_list.append(f"Very low total DEX liquidity: ${total_lp_usd:,.2f} USD.")
        elif total_lp_usd == 0 and _str_to_bool(token_data_raw.get('is_in_dex'),'is_in_dex'): warnings_list.append("Token is in DEX but GoPlus reports $0 total liquidity.")


        return TokenSecurityReport(
            token_address=token_address, chain_id=chain_id_str, retrieved_at=int(time.time()),
            is_open_source=is_open_source, is_proxy=_str_to_bool(token_data_raw.get('is_proxy'), 'is_proxy'),
            is_mintable=_str_to_bool(token_data_raw.get('is_mintable'), 'is_mintable'),
            owner_address=token_data_raw.get('owner_address'),
            can_take_back_ownership=_str_to_bool(token_data_raw.get('can_take_back_ownership'), 'can_take_back_ownership'),
            owner_can_change_balance=_str_to_bool(token_data_raw.get('owner_change_balance'), 'owner_change_balance'),
            has_hidden_owner=_str_to_bool(token_data_raw.get('hidden_owner'), 'hidden_owner'),
            can_self_destruct=_str_to_bool(token_data_raw.get('selfdestruct'), 'selfdestruct'),
            is_in_dex=_str_to_bool(token_data_raw.get('is_in_dex'), 'is_in_dex'),
            buy_tax=buy_tax, sell_tax=sell_tax,
            transfer_tax=_str_to_float(token_data_raw.get('transfer_tax'), 'transfer_tax'),
            cannot_buy=_str_to_bool(token_data_raw.get('cannot_buy'), 'cannot_buy'),
            cannot_sell_all=_str_to_bool(token_data_raw.get('cannot_sell_all'), 'cannot_sell_all'),
            is_honeypot=is_honeypot,
            is_trading_pausable=_str_to_bool(token_data_raw.get('transfer_pausable'), 'transfer_pausable'),
            has_blacklist=_str_to_bool(token_data_raw.get('is_blacklisted'), 'is_blacklisted'),
            has_whitelist=_str_to_bool(token_data_raw.get('is_whitelisted'), 'is_whitelisted'),
            is_anti_whale=_str_to_bool(token_data_raw.get('is_anti_whale'), 'is_anti_whale'),
            has_trading_cooldown=_str_to_bool(token_data_raw.get('trading_cooldown'), 'trading_cooldown'),
            can_owner_modify_taxes=_str_to_bool(token_data_raw.get('slippage_modifiable'), 'slippage_modifiable'),
            top_lp_holders=parsed_lp_holders, total_lp_liquidity_usd=total_lp_usd,
            warnings=warnings_list, remarks=remarks_list, raw_goplus_response=token_data_raw
        )
    except Exception as e:
        print(f"Unexpected error in fetch_token_security_report for {token_address} on {chain_id_str}: {type(e).__name__} - {e}")
        return None


def fetch_pairs_for_token(token_address: str, dexscreener_chain_name: str, max_pairs: int = 10) -> List[PairReport]:
    """
    Fetches trading pair information for a token from DexScreener API.

    Args:
        token_address (str): The contract address of the token.
        dexscreener_chain_name (str): DexScreener's string name for the chain (e.g., "ethereum", "bsc").
        max_pairs (int): Maximum number of pairs to return, sorted by newest first.

    Returns:
        List[PairReport]: A list of pair reports, or an empty list if an error occurs or no pairs found.
    """
    if not Web3.is_address(token_address):
        print(f"Error (fetch_pairs_for_token): Invalid token address format: {token_address}")
        return []

    # DexScreener search API is flexible with 'q'. Using token address directly is often effective.
    url = f"{DEXSCREENER_API_BASE_URL}/dex/search?q={token_address}"

    parsed_pairs: List[PairReport] = []
    try:
        print(f"Fetching DexScreener pairs for {token_address} (filtering for chain '{dexscreener_chain_name}')...")
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        response_data = response.json()

        raw_pairs = response_data.get("pairs", [])
        if not raw_pairs:
            print(f"No pairs found by DexScreener search for query '{token_address}'.")
            return []

        for pair_data in raw_pairs:
            if pair_data.get('chainId', '').lower() != dexscreener_chain_name.lower():
                continue # Filter by DexScreener's chain name

            base_token = pair_data.get('baseToken', {})
            quote_token = pair_data.get('quoteToken', {})

            # Ensure the searched token_address is part of this pair
            if not (base_token.get('address','').lower() == token_address.lower() or \
                    quote_token.get('address','').lower() == token_address.lower()):
                continue

            liquidity = pair_data.get('liquidity', {}) # Contains 'usd', 'base', 'quote'
            volume = pair_data.get('volume', {})     # Contains 'h24', 'h6', 'h1', 'm5'

            created_at_ms = pair_data.get('pairCreatedAt')
            created_at_s = int(created_at_ms / 1000) if isinstance(created_at_ms, (int, float)) else None

            parsed_pairs.append(PairReport(
                pair_address=pair_data.get('pairAddress','N/A'),
                base_token_address=base_token.get('address','N/A'),
                quote_token_address=quote_token.get('address','N/A'),
                chain_id=pair_data.get('chainId','N/A'),
                dex_id=pair_data.get('dexId'),
                price_usd=_str_to_float(pair_data.get('priceUsd'), 'priceUsd'),
                liquidity_usd=_str_to_float(liquidity.get('usd'), 'liquidity_usd'),
                volume_h24=_str_to_float(volume.get('h24'), 'volume_h24'),
                pair_created_at=created_at_s,
                url=pair_data.get('url')
            ))

        # Sort by creation date (newest first), handling None by placing them at the end
        parsed_pairs.sort(key=lambda p: p['pair_created_at'] if p['pair_created_at'] is not None else 0, reverse=True)

        print(f"Found and filtered {len(parsed_pairs)} pairs for {token_address} on chain '{dexscreener_chain_name}'. Returning top {max_pairs}.")
        return parsed_pairs[:max_pairs]

    except Exception as e:
        print(f"Error processing DexScreener pairs for {token_address}: {type(e).__name__} - {e}")
        return []


# --- Example Usage (for direct testing of this module) ---
if __name__ == '__main__':
    print("Starting token_analyzer.py example usage...")
    print("This requires `config.json` with a `goplus_api_key` for GoPlus security reports.")
    print("DexScreener calls do not require an API key for public endpoints used here.")

    if not os.path.exists('config.json'):
        print("`config.json` not found. Creating a dummy one with placeholder GoPlus API key.")
        print("Please replace placeholder with your actual GoPlus API key for security tests.")
        with open('config.json', 'w') as f_dummy:
            json.dump({"token_analysis_apis": { # Ensure structure matches what _load_analyzer_config expects
                           "goplus_security": {
                               "api_key": "YOUR_GOPLUS_API_KEY_HERE_PLACEHOLDER",
                               "api_secret":"YOUR_GOPLUS_SECRET_HERE_PLACEHOLDER"
                           }
                       }}, f_dummy, indent=2)

    # --- Test GoPlus Security Report ---
    # Example: WETH (Wrapped Ether) on Ethereum mainnet
    # test_goplus_token = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    # test_goplus_chain = "1" # GoPlus chain ID for Ethereum
    # print(f"\n--- Testing GoPlus Security for {test_goplus_token} on chain ID {test_goplus_chain} ---")
    # security_report = fetch_token_security_report(test_goplus_token, test_goplus_chain)
    # print_security_report(security_report) # Helper function from test_token_analyzer.py would be needed here or inline print

    # --- Test DexScreener Pair Fetching ---
    # Example: PEPE token on Ethereum mainnet
    print("\n--- Testing DexScreener for PEPE on Ethereum ---")
    test_dex_token = "0x6982508145454Ce325dDbE47a25d4ec3d2311933"
    test_dex_chain = "ethereum" # DexScreener chain name

    pair_reports_list = fetch_pairs_for_token(test_dex_token, test_dex_chain, max_pairs=5)
    if pair_reports_list:
        print(f"\nFound {len(pair_reports_list)} pairs for {test_dex_token} on {test_dex_chain}:")
        for i, pair in enumerate(pair_reports_list):
            print(f"  Pair {i+1}:")
            for key, val in pair.items():
                if key == 'pair_created_at' and val is not None:
                    print(f"    {key}: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(val))}")
                else:
                    print(f"    {key}: {val}")
    else:
        print(f"No pairs found for {test_dex_token} on {test_dex_chain} via DexScreener, or an error occurred.")

    print("\nToken analyzer example usage complete.")
    print("Uncomment GoPlus test and provide a valid API key in config.json to test security reports.")
