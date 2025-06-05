import requests
import json
import time
import hashlib
import uuid
import os # Added os for checking config file existence
from typing import Optional, List, Dict, Any, TypedDict
from web3 import Web3 # For address validation in fetch_token_security_report

# --- Data Structures ---
class LPTokenInfo(TypedDict):
    address: str
    balance: float # This was float in prompt, but GoPlus 'balance' is string. Converting.
    percent_of_total_lp: float # GoPlus 'percent' is string. Converting.
    is_contract: bool
    tag: Optional[str]
    is_locked: bool # GoPlus 'locked' is string '0' or '1'. Converting.
    locked_details: Optional[List[Dict[str, Any]]] # GoPlus 'locked_detail'

class TokenSecurityReport(TypedDict):
    token_address: str
    chain_id: str
    retrieved_at: int # Unix timestamp of when the report was fetched

    # From GoPlus 'token_security' endpoint
    is_open_source: Optional[bool]
    is_proxy: Optional[bool]
    is_mintable: Optional[bool] # 'is_mintable' or 'mintable' or similar
    owner_address: Optional[str]
    can_take_back_ownership: Optional[bool] # 'can_take_back_ownership'
    owner_can_change_balance: Optional[bool] # 'owner_change_balance'
    has_hidden_owner: Optional[bool] # 'hidden_owner'
    can_self_destruct: Optional[bool] # 'selfdestruct' / 'is_selfdestruct'

    is_in_dex: Optional[bool] # from 'dex' array presence
    buy_tax: Optional[float]
    sell_tax: Optional[float]
    transfer_tax: Optional[float] # 'transfer_tax' if available, or sum of buy/sell if it's about that

    cannot_buy: Optional[bool] # 'cannot_buy'
    cannot_sell_all: Optional[bool] # 'cannot_sell_all' / 'sell_limit'
    is_honeypot: Optional[bool]

    is_trading_pausable: Optional[bool] # 'transfer_pausable'
    has_blacklist: Optional[bool] # 'is_blacklisted'
    has_whitelist: Optional[bool] # 'is_whitelisted'
    is_anti_whale: Optional[bool] # 'is_anti_whale'
    has_trading_cooldown: Optional[bool] # 'trading_cooldown' / 'is_trading_cooldown'
    can_owner_modify_taxes: Optional[bool] # 'slippage_modifiable'

    top_lp_holders: List[LPTokenInfo]
    total_lp_liquidity_usd: Optional[float] # Summed from 'dex' array's 'liquidity' field

    warnings: List[str] # Custom generated warnings based on flags
    remarks: List[str]  # Custom generated remarks

    raw_goplus_response: Dict[str, Any] # Store the specific token's part of GoPlus response

class PairReport(TypedDict):
    pair_address: str
    base_token_address: str
    quote_token_address: str
    chain_id: str  # This will be the string chainId from DexScreener like 'ethereum'
    dex_id: Optional[str]
    price_usd: Optional[float]
    liquidity_usd: Optional[float]
    volume_h24: Optional[float]
    pair_created_at: Optional[int] # Unix timestamp (seconds)
    url: Optional[str]


# --- Global Cache/Config ---
ANALYZER_CONFIG: Dict[str, Any] = {}
GOPLUS_AUTH_TOKEN: Optional[str] = None
GOPLUS_TOKEN_EXPIRY: int = 0 # Unix timestamp when token expires
GOPLUS_API_BASE_URL = "https://api.gopluslabs.io/api/v1"
DEXSCREENER_API_BASE_URL = "https://api.dexscreener.com/latest"


# --- Helper Functions for Data Conversion ---
def _str_to_bool(s: Optional[Any], field_name: str = "") -> Optional[bool]:
    """Converts GoPlus string ('0' or '1') or boolean to Python bool."""
    if s is None:
        return None
    if isinstance(s, bool):
        return s
    if isinstance(s, str):
        if s == '1':
            return True
        elif s == '0':
            return False
    # print(f"Warning: Unexpected boolean-like value for '{field_name}': {s} (type: {type(s)})")
    return None # Or raise error, or return a default

def _str_to_float(s: Optional[Any], field_name: str = "") -> Optional[float]:
    """Converts GoPlus string representation of float to Python float."""
    if s is None or s == "": # Check for empty string too
        return None
    if isinstance(s, (float, int)): # Already a number
        return float(s)
    if isinstance(s, str):
        try:
            return float(s)
        except ValueError:
            # print(f"Warning: Could not convert string to float for '{field_name}': {s}")
            return None
    # print(f"Warning: Unexpected float-like value for '{field_name}': {s} (type: {type(s)})")
    return None


# --- Configuration & Authentication for GoPlus API ---
def _load_analyzer_config(config_path='config.json') -> bool:
    """Loads GoPlus API credentials from config file if not already loaded."""
    global ANALYZER_CONFIG
    if ANALYZER_CONFIG.get('goplus_api_key'): # Check if already loaded
        return True

    try:
        # This function might be called by other modules, ensure path is relative to project root if needed
        # For now, assumes config.json is in the same dir as this script or project root.
        if not os.path.exists(config_path): # Check if config file exists before trying to open
            print(f"Warning: Config file '{config_path}' not found. GoPlus functionality will be disabled.")
            ANALYZER_CONFIG['goplus_api_key'] = None # Explicitly set to None if file not found
            return False

        with open(config_path, 'r') as f:
            config_data = json.load(f)

        # Prioritize environment variables for sensitive keys
        ANALYZER_CONFIG['goplus_api_key'] = os.getenv('GOPLUS_API_KEY', config_data.get('goplus_api_key'))
        # GoPlus API secret is not directly used in the documented signing method for /token endpoint,
        # but it's good practice to load it if present for other potential uses or API versions.
        ANALYZER_CONFIG['goplus_api_secret'] = os.getenv('GOPLUS_API_SECRET', config_data.get('goplus_api_secret'))

        if not ANALYZER_CONFIG['goplus_api_key']:
            print("Warning: `goplus_api_key` not found in config or GOPLUS_API_KEY environment variable. GoPlus features disabled.")
            return False
        return True
    except FileNotFoundError: # Should be caught by os.path.exists, but as a fallback
        print(f"Error: Config file '{config_path}' not found.")
        ANALYZER_CONFIG['goplus_api_key'] = None
        return False
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{config_path}'. Check for syntax errors.")
        ANALYZER_CONFIG['goplus_api_key'] = None
        return False
    except Exception as e:
        print(f"Error loading analyzer config from '{config_path}': {e}")
        ANALYZER_CONFIG['goplus_api_key'] = None
        return False


def _get_goplus_auth_token(force_refresh=False) -> Optional[str]:
    """
    Retrieves GoPlus API authentication token, obtaining a new one if expired or forced.
    The signature is sha256(app_key + Lowercase(nonce) + request_time).
    """
    global GOPLUS_AUTH_TOKEN, GOPLUS_TOKEN_EXPIRY

    if not _load_analyzer_config() or not ANALYZER_CONFIG.get('goplus_api_key'):
        print("GoPlus API key not available. Cannot get auth token.")
        return None

    api_key = ANALYZER_CONFIG['goplus_api_key']
    current_time_seconds = int(time.time())

    if GOPLUS_AUTH_TOKEN and current_time_seconds < GOPLUS_TOKEN_EXPIRY and not force_refresh:
        # print("Using cached GoPlus auth token.") # For debugging
        return GOPLUS_AUTH_TOKEN

    # Generate parameters for new token request
    request_time_str = str(current_time_seconds)
    nonce = uuid.uuid4().hex.lower() # Random string, lowercase as per some interpretations

    data_to_sign = f"{api_key}{nonce}{request_time_str}"
    signature = hashlib.sha256(data_to_sign.encode('utf-8')).hexdigest()

    auth_payload = {
        "app_key": api_key,
        "sign": signature,
        "time": request_time_str, # API docs specify 'time'
        "nonce": nonce
    }

    auth_url = f"{GOPLUS_API_BASE_URL}/token"
    try:
        print(f"Requesting new GoPlus auth token from {auth_url}...")
        response = requests.post(auth_url, json=auth_payload, timeout=10) # 10s timeout
        response.raise_for_status() # Raises HTTPError for bad responses (4XX or 5XX)

        data = response.json()
        if data.get('code') == 1 and data.get('result', {}).get('access_token'): # GoPlus success code is 1
            GOPLUS_AUTH_TOKEN = data['result']['access_token']
            # expires_in is typically in seconds (e.g., 3600 for 1 hour)
            expires_in_seconds = int(data['result'].get('expires_in', 3600))
            GOPLUS_TOKEN_EXPIRY = current_time_seconds + expires_in_seconds - 60 # Subtract 60s buffer for clock skew
            print("Successfully obtained new GoPlus auth token.")
            return GOPLUS_AUTH_TOKEN
        else:
            print(f"Error getting GoPlus auth token from API: {data.get('message')} (Code: {data.get('code')})")
            return None
    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error getting GoPlus auth token: {http_err} - Response: {http_err.response.text}")
        return None
    except requests.exceptions.RequestException as req_err:
        print(f"Request error (e.g., network issue) getting GoPlus auth token: {req_err}")
        return None
    except Exception as e:
        print(f"Unexpected error getting GoPlus auth token: {type(e).__name__} - {e}")
        return None

# --- Main Analysis Function ---
def fetch_token_security_report(token_address: str, chain_id_str: str) -> Optional[TokenSecurityReport]:
    """
    Fetches and parses a token security report from GoPlus API for a given token and chain.
    """
    if not Web3.is_address(token_address): # Basic address validation
        print(f"Error: Invalid token address format: {token_address}")
        return None

    auth_token = _get_goplus_auth_token()
    if not auth_token:
        print("Failed to obtain GoPlus auth token. Cannot fetch security report.")
        return None

    # Construct the API URL for token security
    api_url = f"{GOPLUS_API_BASE_URL}/token_security/{chain_id_str}?contract_addresses={token_address}"
    headers = {"Authorization": f"Bearer {auth_token}"}

    try:
        print(f"Fetching security report for token {token_address} on chain {chain_id_str}...")
        response = requests.get(api_url, headers=headers, timeout=20) # Increased timeout for API
        response.raise_for_status() # Check for HTTP errors

        response_json = response.json()
        if response_json.get('code') != 1: # GoPlus API success code is typically 1
            print(f"GoPlus API returned an error for {token_address} on chain {chain_id_str}: {response_json.get('message')} (Code: {response_json.get('code')})")
            return None

        # Data for the specific token is nested under its address (lowercase) in the 'result' field
        token_data_raw = response_json.get('result', {}).get(token_address.lower())
        if not token_data_raw:
            print(f"No security data found for token {token_address} in GoPlus response for chain {chain_id_str}.")
            return None

        # Initialize lists for custom warnings and remarks
        warnings_list: List[str] = []
        remarks_list: List[str] = []

        # --- Parse Contract Security aspects ---
        is_open_source = _str_to_bool(token_data_raw.get('is_open_source'), 'is_open_source')
        if is_open_source is False: # Note: None means unknown, False means explicitly not open source
            warnings_list.append("Contract source code is not verified on the explorer.")

        is_honeypot = _str_to_bool(token_data_raw.get('is_honeypot'), 'is_honeypot')
        if is_honeypot:
            warnings_list.append("CRITICAL: GoPlus flags this token as a HODNEYPOT.")

        buy_tax_val = _str_to_float(token_data_raw.get('buy_tax'), 'buy_tax')
        sell_tax_val = _str_to_float(token_data_raw.get('sell_tax'), 'sell_tax')
        if buy_tax_val is not None and buy_tax_val > 0.10: # Tax > 10%
            warnings_list.append(f"High buy tax detected: {buy_tax_val*100:.1f}%")
        if sell_tax_val is not None and sell_tax_val > 0.10: # Tax > 10%
            warnings_list.append(f"High sell tax detected: {sell_tax_val*100:.1f}%")

        if _str_to_bool(token_data_raw.get('slippage_modifiable'), 'slippage_modifiable'):
            warnings_list.append("Owner can modify transaction taxes (slippage).")
        if _str_to_bool(token_data_raw.get('cannot_sell_all'), 'cannot_sell_all'):
            warnings_list.append("Token has sell limits (cannot sell all at once).")
        if _str_to_bool(token_data_raw.get('transfer_pausable'), 'transfer_pausable'):
            warnings_list.append("Token trading can be paused by owner.")

        # --- Parse LP Holders & Liquidity ---
        lp_holders_raw = token_data_raw.get('lp_holders', [])
        parsed_lp_holders_list: List[LPTokenInfo] = []
        for lp_holder_item in lp_holders_raw:
            parsed_lp_holders_list.append(LPTokenInfo(
                address=lp_holder_item.get('address','N/A'),
                balance=_str_to_float(lp_holder_item.get('balance'), 'lp_holder_balance') or 0.0,
                percent_of_total_lp=(_str_to_float(lp_holder_item.get('percent'), 'lp_holder_percent') or 0.0), # Already a percentage from GoPlus
                is_contract=_str_to_bool(lp_holder_item.get('is_contract'), 'lp_holder_is_contract') or False,
                tag=lp_holder_item.get('tag'),
                is_locked=_str_to_bool(lp_holder_item.get('locked'), 'lp_holder_locked') or False, # GoPlus 'locked' is '0' or '1'
                locked_details=lp_holder_item.get('locked_detail') # This is usually a list of dicts
            ))

        # Analyze LP lock status (example heuristic)
        if parsed_lp_holders_list:
            total_locked_lp_percent = sum(h['percent_of_total_lp'] for h in parsed_lp_holders_list if h['is_locked'])
            if total_locked_lp_percent < 0.80 and len(parsed_lp_holders_list) > 0 : # If less than 80% of listed top LP is locked
                 remarks_list.append(f"LP Lock: {total_locked_lp_percent*100:.2f}% of tracked top LP is locked. Review details.")
            elif total_locked_lp_percent >= 0.80:
                remarks_list.append(f"LP Lock: Significant portion of tracked LP ({total_locked_lp_percent*100:.2f}%) appears to be locked.")

        # Sum total USD liquidity from all DEX entries
        total_lp_liquidity_usd_val = sum(
            _str_to_float(dex_item.get('liquidity'), 'dex_liquidity') or 0.0
            for dex_item in token_data_raw.get('dex', [])
        )
        if total_lp_liquidity_usd_val < 10000: # Example threshold for low liquidity warning
            warnings_list.append(f"Low total DEX liquidity: ${total_lp_liquidity_usd_val:,.2f} USD.")

        # --- Construct the Report ---
        final_report = TokenSecurityReport(
            token_address=token_address,
            chain_id=chain_id_str,
            retrieved_at=int(time.time()),
            is_open_source=is_open_source,
            is_proxy=_str_to_bool(token_data_raw.get('is_proxy'), 'is_proxy'),
            is_mintable=_str_to_bool(token_data_raw.get('is_mintable'), 'is_mintable'), # GoPlus uses 'is_mintable'
            owner_address=token_data_raw.get('owner_address'),
            can_take_back_ownership=_str_to_bool(token_data_raw.get('can_take_back_ownership'), 'can_take_back_ownership'),
            owner_can_change_balance=_str_to_bool(token_data_raw.get('owner_change_balance'), 'owner_change_balance'),
            has_hidden_owner=_str_to_bool(token_data_raw.get('hidden_owner'), 'hidden_owner'),
            can_self_destruct=_str_to_bool(token_data_raw.get('selfdestruct'), 'selfdestruct'), # GoPlus uses 'selfdestruct'
            is_in_dex=_str_to_bool(token_data_raw.get('is_in_dex'), 'is_in_dex'),
            buy_tax=buy_tax_val,
            sell_tax=sell_tax_val,
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
            top_lp_holders=parsed_lp_holders_list,
            total_lp_liquidity_usd=total_lp_liquidity_usd_val,
            warnings=warnings_list,
            remarks=remarks_list,
            raw_goplus_response=token_data_raw # Store the relevant part of the response
        )
        return final_report

    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error fetching security report for {token_address} on {chain_id_str}: {http_err} - Response: {http_err.response.text if http_err.response else 'No response body'}")
        return None
    except requests.exceptions.RequestException as req_err:
        print(f"Request error (e.g., network issue) fetching security report for {token_address} on {chain_id_str}: {req_err}")
        return None
    except Exception as e: # Catch-all for other unexpected errors like JSON parsing issues
        print(f"Unexpected error processing security report for {token_address} on {chain_id_str}: {type(e).__name__} - {e}")
        # import traceback; traceback.print_exc() # Uncomment for detailed debugging
        return None


# --- DexScreener API Interaction ---
def fetch_pairs_for_token(token_address: str, chain_id_str: str, max_pairs: int = 10) -> List[PairReport]:
    """
    Fetches trading pair information for a given token address from DexScreener API,
    filtered by chain_id_str (DexScreener's string representation like 'ethereum').
    Sorts pairs by creation date (newest first) and returns up to max_pairs.
    """
    # DexScreener uses string chain IDs like 'ethereum', 'bsc', 'polygon', etc.
    # Ensure chain_id_str matches DexScreener's naming.
    url = f"{DEXSCREENER_API_BASE_URL}/dex/search?q={token_address}"
    # Alternative: f"{DEXSCREENER_API_BASE_URL}/dex/tokens/{token_address}/pairs"
    # The /tokens/{token_address}/pairs endpoint might be more direct if chain_id_str can be mapped.
    # However, search with post-filtering is also viable.

    parsed_pairs: List[PairReport] = []

    try:
        print(f"Fetching pairs for token {token_address} (filtering for chain '{chain_id_str}') from DexScreener...")
        response = requests.get(url, timeout=15) # 15s timeout
        response.raise_for_status() # Raises HTTPError for bad responses

        response_data = response.json()

        raw_pairs_data = response_data.get("pairs", [])
        if not raw_pairs_data:
            print(f"No pairs found by DexScreener search for query '{token_address}'.")
            return []

        processed_count = 0
        for pair_data in raw_pairs_data:
            # Primary filter: DexScreener's chainId must match the requested chain_id_str
            if pair_data.get('chainId', '').lower() != chain_id_str.lower():
                continue

            base_token = pair_data.get('baseToken', {})
            quote_token = pair_data.get('quoteToken', {})

            # Secondary filter: Ensure the token_address we are searching for is part of this pair
            if not (base_token.get('address','').lower() == token_address.lower() or \
                    quote_token.get('address','').lower() == token_address.lower()):
                continue

            liquidity_info = pair_data.get('liquidity', {}) # Contains 'usd', 'base', 'quote'
            volume_info = pair_data.get('volume', {})     # Contains 'h24', 'h6', 'h1', 'm5'

            # DexScreener pairCreatedAt is in milliseconds
            pair_created_at_ms = pair_data.get('pairCreatedAt')
            pair_created_at_timestamp_seconds = int(pair_created_at_ms / 1000) if isinstance(pair_created_at_ms, (int, float)) else None

            report = PairReport(
                pair_address=pair_data.get('pairAddress','N/A'),
                base_token_address=base_token.get('address','N/A'),
                quote_token_address=quote_token.get('address','N/A'),
                chain_id=pair_data.get('chainId','N/A'), # This is DexScreener's string chainId
                dex_id=pair_data.get('dexId'),
                price_usd=_str_to_float(pair_data.get('priceUsd'), 'priceUsd'),
                liquidity_usd=_str_to_float(liquidity_info.get('usd'), 'liquidity_usd'), # USD liquidity
                volume_h24=_str_to_float(volume_info.get('h24'), 'volume_h24'), # 24-hour volume in USD
                pair_created_at=pair_created_at_timestamp_seconds,
                url=pair_data.get('url')
            )
            parsed_pairs.append(report)
            processed_count +=1

        # Sort pairs by creation date (newest first) after all filtering
        # Handle None for pair_created_at by placing them at the end (or beginning if preferred)
        parsed_pairs.sort(key=lambda p: p['pair_created_at'] if p['pair_created_at'] is not None else 0, reverse=True)

        print(f"Found and filtered {len(parsed_pairs)} pairs for {token_address} on chain '{chain_id_str}' from DexScreener raw results.")
        return parsed_pairs[:max_pairs] # Return up to max_pairs

    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error fetching pairs for {token_address} from DexScreener: {http_err} - Response: {http_err.response.text if http_err.response else 'No response body'}")
        return []
    except requests.exceptions.RequestException as req_err: # Other request errors (network, timeout)
        print(f"Request error fetching pairs for {token_address} from DexScreener: {req_err}")
        return []
    except Exception as e: # Catch-all for other issues like JSON parsing
        print(f"Unexpected error processing DexScreener pairs for {token_address}: {type(e).__name__} - {e}")
        # import traceback; traceback.print_exc() # Uncomment for detailed debugging during development
        return []


# --- Example Usage ---
if __name__ == '__main__':
    print("Starting token_analyzer.py example usage...")
    print("This requires a `config.json` file with a valid `goplus_api_key` for successful API calls.")
    print("If `config.json` or the API key is missing, auth will fail, and no report will be fetched.")

    # Create a dummy config.json if it doesn't exist, to allow script to run without FileNotFoundError
    # The user still needs to populate it with a REAL GoPlus API key for the example to work.
    if not os.path.exists('config.json'):
        print("`config.json` not found. Creating a dummy one with placeholder API key.")
        print("Please replace 'YOUR_GOPLUS_API_KEY_HERE' with your actual GoPlus API key.")
        with open('config.json', 'w') as f_dummy:
            json.dump({"goplus_api_key": "YOUR_GOPLUS_API_KEY_HERE",
                       "goplus_api_secret":"YOUR_GOPLUS_SECRET_IF_ANY"}, f_dummy, indent=2)

    # --- Example: Fetch report for a known token (e.g., USDC on Ethereum) ---
    # Ensure your GoPlus API key has permissions for the desired chain.
    # Ethereum chain_id for GoPlus is "1"
    # BNB Chain (BSC) chain_id for GoPlus is "56"
    # Polygon chain_id for GoPlus is "137"

    # test_token_eth_usdc = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
    # test_chain_id_eth = "1"

    # print(f"\nAttempting to fetch report for USDC on Ethereum ({test_token_eth_usdc})...")
    # report_usdc_eth = fetch_token_security_report(test_token_eth_usdc, test_chain_id_eth)

    # if report_usdc_eth:
    #     print("\n--- Token Security Report (USDC on Ethereum) ---")
    #     for key, value in report_usdc_eth.items():
    #         if key == 'top_lp_holders' and isinstance(value, list):
    #             print(f"  {key}: [{len(value)} holders listed]")
    #             for i, item in enumerate(value[:2]): # Print details of first 2 LP holders
    #                 print(f"    Holder {i+1}: {item}")
    #         elif key == 'raw_goplus_response':
    #             print(f"  {key}: (Raw GoPlus JSON data stored, not printed in full)")
    #         else:
    #             print(f"  {key}: {value}")
    # else:
    #     print("\nFailed to retrieve token security report for USDC on Ethereum.")

    # print("\nToken analyzer example finished.")
    # print("To test thoroughly, uncomment the example call above and ensure `config.json` has a valid `goplus_api_key`.")
    # print("You may need to replace the example token address and chain ID with one relevant to your GoPlus API key's access.")

    print("\nRunning token_analyzer.py example for DexScreener...")
    # Example DexScreener call:
    # PEPE on Ethereum. DexScreener chainId for Ethereum is 'ethereum'.
    test_dexscreener_token = "0x6982508145454Ce325dDbE47a25d4ec3d2311933"
    test_dexscreener_chain_str = "ethereum"

    pairs = fetch_pairs_for_token(test_dexscreener_token, test_dexscreener_chain_str)
    if pairs:
        print(f"\n--- Pair Reports for {test_dexscreener_token} on {test_dexscreener_chain_str} (Newest First, Max 10) ---")
        for i, pair_report_item in enumerate(pairs): # Renamed 'pair' to 'pair_report_item'
            print(f"  Pair {i+1}:")
            print(f"    Address: {pair_report_item['pair_address']}")
            print(f"    Base Token: {pair_report_item['base_token_address']}")
            print(f"    Quote Token: {pair_report_item['quote_token_address']}")
            print(f"    Liquidity USD: {pair_report_item.get('liquidity_usd', 'N/A')}")
            created_at_ts = pair_report_item['pair_created_at']
            created_at_str = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(created_at_ts)) if created_at_ts else 'N/A'
            print(f"    Pair Created At: {created_at_str}")
            print(f"    DexScreener URL: {pair_report_item.get('url', 'N/A')}")
    else:
        print(f"\nNo pairs found or error fetching pairs for {test_dexscreener_token} on {test_dexscreener_chain_str}.")

    print("\nToken analyzer full example finished.")

[end of token_analyzer.py]
