"""
This module provides functions to fetch token security analysis and trading pair data
from external APIs like GoPlus Security and DexScreener.
It requires API keys to be configured in config.json for some services (e.g., GoPlus).
The `config.json` should be populated based on `config.json.example`.
API keys can also be supplied via environment variables (e.g., GOPLUS_API_KEY).
"""
import requests
import aiohttp # Async requests for actual data fetching
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
    Fields are derived from GoPlus API responses.
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
    LP details, and custom warnings/remarks. This structure aims to be a common format
    for both EVM and Solana tokens, though some fields might be specific to one type.
    """
    token_address: str
    chain_id: str       # API-specific chain ID (e.g., "1" for ETH GoPlus, "solana" for Solana GoPlus)
    retrieved_at: int

    is_open_source: Optional[bool]
    is_proxy: Optional[bool]
    is_mintable: Optional[bool]
    owner_address: Optional[str]
    can_take_back_ownership: Optional[bool]
    owner_can_change_balance: Optional[bool]
    has_hidden_owner: Optional[bool]
    can_self_destruct: Optional[bool]

    is_in_dex: Optional[bool]
    buy_tax: Optional[float]
    sell_tax: Optional[float]
    transfer_tax: Optional[float]

    cannot_buy: Optional[bool]
    cannot_sell_all: Optional[bool]
    is_honeypot: Optional[bool]

    is_trading_pausable: Optional[bool]
    has_blacklist: Optional[bool]
    has_whitelist: Optional[bool]
    is_anti_whale: Optional[bool]
    has_trading_cooldown: Optional[bool]
    can_owner_modify_taxes: Optional[bool]

    top_lp_holders: List[LPTokenInfo]
    total_lp_liquidity_usd: Optional[float]

    warnings: List[str]
    remarks: List[str]

    raw_goplus_response: Dict[str, Any]

class PairReport(TypedDict):
    """
    Represents trading pair information, primarily from DexScreener.
    """
    pair_address: str
    base_token_address: str
    quote_token_address: str
    chain_id: str  # DexScreener's string chainId (e.g., "ethereum", "solana")
    dex_id: Optional[str]
    price_usd: Optional[float]
    liquidity_usd: Optional[float]
    volume_h24: Optional[float]
    pair_created_at: Optional[int] # Unix timestamp (seconds)
    url: Optional[str]

# --- Global Cache/Config ---
ANALYZER_CONFIG: Dict[str, Any] = {}
GOPLUS_AUTH_TOKEN: Optional[str] = None
GOPLUS_TOKEN_EXPIRY: int = 0
GOPLUS_API_BASE_URL = "https://api.gopluslabs.io/api/v1"
DEXSCREENER_API_BASE_URL = "https://api.dexscreener.com/latest"

# --- Helper Functions ---
def _str_to_bool(s: Optional[Any], field_name: str = "") -> Optional[bool]:
    if s is None: return None
    if isinstance(s, bool): return s
    if isinstance(s, str):
        if s == '1': return True
        elif s == '0': return False
    return None

def _str_to_float(s: Optional[Any], field_name: str = "") -> Optional[float]:
    if s is None or s == "": return None
    if isinstance(s, (float, int)): return float(s)
    if isinstance(s, str):
        try: return float(s)
        except ValueError: return None
    return None

# --- GoPlus API ---
def _load_analyzer_config(config_path: str = 'config.json') -> bool:
    global ANALYZER_CONFIG
    if ANALYZER_CONFIG.get('goplus_api_key_loaded'):
        return ANALYZER_CONFIG.get('goplus_api_key') is not None
    try:
        config_data = {}
        if os.path.exists(config_path):
            with open(config_path, 'r') as f: config_data = json.load(f)
        else: print(f"Info: Config file '{config_path}' not found. Using env vars for GoPlus key.")

        goplus_conf = config_data.get("token_analysis_apis", {}).get("goplus_security", {})
        if not goplus_conf and "goplus_api_key" in config_data :
             goplus_conf = config_data

        ANALYZER_CONFIG['goplus_api_key'] = os.getenv('GOPLUS_API_KEY', goplus_conf.get('api_key'))
        ANALYZER_CONFIG['goplus_api_key_loaded'] = True
        if not ANALYZER_CONFIG['goplus_api_key']:
            print("Warning: GoPlus API key not found in config or GOPLUS_API_KEY env var. GoPlus analysis disabled.")
            return False
        return True
    except Exception as e:
        print(f"Error loading GoPlus API key from '{config_path}': {e}")
        ANALYZER_CONFIG['goplus_api_key_loaded'] = True; ANALYZER_CONFIG['goplus_api_key'] = None
        return False

async def _get_goplus_auth_token(force_refresh: bool = False, session: Optional[aiohttp.ClientSession] = None) -> Optional[str]:
    global GOPLUS_AUTH_TOKEN, GOPLUS_TOKEN_EXPIRY, ANALYZER_CONFIG
    if not _load_analyzer_config(): # Ensure config is attempted to be loaded
        print("GoPlus API key not available (config load failed). Cannot get auth token.")
        return None

    api_key = ANALYZER_CONFIG.get('goplus_api_key')
    if not api_key:
        print("Error: GoPlus API key is missing after config load attempt.")
        return None

    current_time = int(time.time())
    if GOPLUS_AUTH_TOKEN and current_time < GOPLUS_TOKEN_EXPIRY and not force_refresh:
        return GOPLUS_AUTH_TOKEN

    req_time_str = str(current_time); nonce = uuid.uuid4().hex.lower()
    data_to_sign = f"{api_key}{nonce}{req_time_str}"
    signature = hashlib.sha256(data_to_sign.encode('utf-8')).hexdigest()
    payload = {"app_key": api_key, "sign": signature, "time": req_time_str, "nonce": nonce}
    url = f"{GOPLUS_API_BASE_URL}/token"

    close_session_after = False
    if session is None:
        session = aiohttp.ClientSession()
        close_session_after = True

    try:
        print(f"Requesting new GoPlus auth token (async) from {url}...")
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            resp.raise_for_status(); data = await resp.json()

        if data.get('code') == 1 and data.get('result', {}).get('access_token'):
            GOPLUS_AUTH_TOKEN = data['result']['access_token']
            expires_in = int(data['result'].get('expires_in', 3600))
            GOPLUS_TOKEN_EXPIRY = current_time + expires_in - 60
            print("Successfully obtained GoPlus auth token (async).")
            return GOPLUS_AUTH_TOKEN
        else:
            print(f"Error getting GoPlus auth token (async): {data.get('message')} (Code: {data.get('code')})")
            return None
    except Exception as e:
        error_body = ""
        if isinstance(e, aiohttp.ClientResponseError) and hasattr(e, 'response') and e.response:
            try: error_body = await e.response.text()
            except Exception: pass
        print(f"Request error getting GoPlus auth token (async): {type(e).__name__} - {e}. Body: {error_body}"); return None
    finally:
        if close_session_after and session:
            await session.close()

async def fetch_token_security_report(token_address: str, chain_id_str: str) -> Optional[TokenSecurityReport]:
    """
    Fetches and parses token security report from GoPlus API for EVM or Solana.
    `chain_id_str` is GoPlus specific (e.g., "1" for ETH, "solana" for Solana).
    """
    is_sol_addr_format = len(token_address) > 30 and len(token_address) < 50 and not token_address.startswith("0x")
    if not Web3.is_address(token_address) and not is_sol_addr_format :
        print(f"Error (fetch_token_security_report): Invalid token address format: {token_address}"); return None

    async with aiohttp.ClientSession() as session:
        auth_token = await _get_goplus_auth_token(session=session)
        if not auth_token: print("Failed to get GoPlus auth token for security report."); return None

        is_solana_chain = chain_id_str.lower() == "solana"
        if is_solana_chain: url = f"{GOPLUS_API_BASE_URL}/solana/token_security?token_addresses={token_address}"
        else: url = f"{GOPLUS_API_BASE_URL}/token_security/{chain_id_str}?contract_addresses={token_address}"

        headers = {"Authorization": f"Bearer {auth_token}"}
        print(f"Fetching security report for {'Solana' if is_solana_chain else 'EVM'} token {token_address} on chain '{chain_id_str}' from {url}")

        try:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=20)) as response:
                response.raise_for_status(); response_data = await response.json()

            if response_data.get('code') != 1:
                print(f"GoPlus API error for {token_address} on {chain_id_str}: {response_data.get('message')} (Code: {response_data.get('code')})"); return None

            raw_data_map = response_data.get('result', {})
            data = None
            if is_solana_chain:
                # For Solana, GoPlus returns a list if one address is queried, or a dict if multiple.
                # The API doc implies ?token_addresses= (plural) but examples show single.
                # Let's robustly handle both list-of-one and direct-dict-for-one.
                if isinstance(raw_data_map, list) and len(raw_data_map) > 0: data = raw_data_map[0]
                elif isinstance(raw_data_map, dict) and token_address in raw_data_map : data = raw_data_map[token_address]
                elif isinstance(raw_data_map, dict) and not raw_data_map: # Empty result dict
                     print(f"Empty result for Solana token {token_address} in GoPlus response."); return None
                elif isinstance(raw_data_map, dict) and len(raw_data_map) == 1: # If it's a dict with one key, that's our data
                    data = list(raw_data_map.values())[0]
                else: print(f"Unexpected data structure for Solana token {token_address} in GoPlus response: {type(raw_data_map)}"); return None
            else:
                data = raw_data_map.get(token_address.lower())
            if not data: print(f"No specific data for token {token_address} in GoPlus result."); return None

            warnings_list: List[str] = []; remarks_list: List[str] = []

            if is_solana_chain:
                remarks_list.append(f"Solana Token. Name: {data.get('metadata',{}).get('name','N/A')}, Symbol: {data.get('metadata',{}).get('symbol','N/A')}")
                if _str_to_bool(data.get('creator',{}).get('malicious_address'),'sol_creator_malicious'): warnings_list.append("CRITICAL: Creator address flagged as malicious.")
                is_mintable = _str_to_bool(data.get('mintable',{}).get('status'),'sol_mintable_status')
                if is_mintable:
                    mint_auth = data.get('mintable',{}).get('authority',{}).get('address','N/A')
                    remarks_list.append(f"Token is mintable. Mint authority: {mint_auth}") # Remark, not warning unless malicious
                    if _str_to_bool(data.get('mintable',{}).get('authority',{}).get('malicious_address'),'sol_mint_auth_malicious'): warnings_list.append("CRITICAL: Mint authority flagged as malicious.")
                is_freezable = _str_to_bool(data.get('freezable',{}).get('status'),'sol_freezable_status')
                if is_freezable:
                    freeze_auth = data.get('freezable',{}).get('authority',{}).get('address','N/A')
                    warnings_list.append(f"Token accounts freezable. Freeze authority: {freeze_auth}")
                    if _str_to_bool(data.get('freezable',{}).get('authority',{}).get('malicious_address'),'sol_freeze_auth_malicious'): warnings_list.append("CRITICAL: Freeze authority flagged as malicious.")
                can_change_balance = _str_to_bool(data.get('balance_mutable_authority',{}).get('status'),'sol_bal_mutable_status')
                if can_change_balance: warnings_list.append("CRITICAL: Token balance can be changed by authority.")
                is_closable = _str_to_bool(data.get('closable',{}).get('status'),'sol_closable_status')
                if is_closable: warnings_list.append("CRITICAL: Token program can be closed by authority (assets may be lost).")
                tf_rate = data.get('transfer_fee', {}).get('current_fee_rate'); transfer_tax = (_str_to_float(tf_rate) / 10000.0) if tf_rate is not None else None
                if transfer_tax is not None and transfer_tax > 0.1: warnings_list.append(f"High transfer tax: {transfer_tax*100:.2f}%")
                is_honeypot_sol = (is_closable or can_change_balance or
                                   _str_to_bool(data.get('creator',{}).get('malicious_address')) or
                                   _str_to_bool(data.get('mintable',{}).get('authority',{}).get('malicious_address')) or
                                   _str_to_bool(data.get('freezable',{}).get('authority',{}).get('malicious_address')) or
                                   (_str_to_bool(data.get('transfer_hook',{}).get('status')) and _str_to_bool(data.get('transfer_hook',{}).get('malicious_address'))) or
                                   (data.get('default_account_state') == '2' and not data.get('freezable',{}).get('authority',{}).get('address')))
                if is_honeypot_sol: warnings_list.append("CRITICAL: Derived high rug risk (honeypot-like) from Solana flags.")
                lp_holders_sol: List[LPTokenInfo] = []
                total_lp_usd_sol: Optional[float] = sum(_str_to_float(d.get('tvl'),'sol_dex_tvl') or 0.0 for d in data.get('dex',[]))
                if data.get('dex') and data['dex'][0].get('lp_holders'):
                    for lp_h in data['dex'][0]['lp_holders']:
                        lp_holders_sol.append(LPTokenInfo(address=lp_h.get('token_account',''),balance=_str_to_float(lp_h.get('balance'))or 0.0,
                                                       percent_of_total_lp=_str_to_float(lp_h.get('percent'))or 0.0,is_contract=False,
                                                       tag=lp_h.get('tag'),is_locked=_str_to_bool(lp_h.get('is_locked'))or False,locked_details=lp_h.get('locked_detail')))
                if total_lp_usd_sol is not None and total_lp_usd_sol < 5000: warnings_list.append(f"Low liquidity in largest pool: ${total_lp_usd_sol:,.2f} USD.")

                return TokenSecurityReport(token_address=token_address, chain_id=chain_id_str, retrieved_at=int(time.time()),
                    is_open_source=None, is_proxy=None, is_mintable=is_mintable, owner_address=data.get('mintable',{}).get('authority',{}).get('address'),
                    can_take_back_ownership=None, owner_can_change_balance=can_change_balance, has_hidden_owner=None, can_self_destruct=is_closable,
                    is_in_dex=bool(data.get('dex')), buy_tax=None, sell_tax=None, transfer_tax=transfer_tax,
                    cannot_buy=None, cannot_sell_all=None, is_honeypot=is_honeypot_sol, is_trading_pausable=is_freezable,
                    has_blacklist=None, has_whitelist=None, is_anti_whale=None, has_trading_cooldown=None,
                    can_owner_modify_taxes=_str_to_bool(data.get('transfer_fee_upgradable',{}).get('status')),
                    top_lp_holders=lp_holders_sol, total_lp_liquidity_usd=total_lp_usd_sol,
                    warnings=warnings_list, remarks=remarks_list, raw_goplus_response=data )
            else: # EVM Logic (preserved and slightly formatted for consistency)
                is_open_source_evm = _str_to_bool(data.get('is_open_source'),'is_open_source')
                if is_open_source_evm is False: warnings_list.append("Contract source code is not verified (EVM).")
                is_honeypot_evm = _str_to_bool(data.get('is_honeypot'),'is_honeypot')
                if is_honeypot_evm: warnings_list.append("CRITICAL: Token flagged as HONEYPOT (EVM).") # Corrected typo
                buy_tax_evm=_str_to_float(data.get('buy_tax'),'buy_tax'); sell_tax_evm=_str_to_float(data.get('sell_tax'),'sell_tax')
                if buy_tax_evm is not None and buy_tax_evm > 0.10: warnings_list.append(f"High buy tax (EVM): {buy_tax_evm*100:.1f}%")
                if sell_tax_evm is not None and sell_tax_evm > 0.10: warnings_list.append(f"High sell tax (EVM): {sell_tax_evm*100:.1f}%")
                if _str_to_bool(data.get('slippage_modifiable'),'slippage_modifiable'): warnings_list.append("Owner can modify taxes (EVM).")
                if _str_to_bool(data.get('cannot_sell_all'),'cannot_sell_all'): warnings_list.append("Token has sell limits (EVM).")
                if _str_to_bool(data.get('transfer_pausable'),'transfer_pausable'): warnings_list.append("Trading can be paused (EVM).")
                parsed_evm_lp_holders: List[LPTokenInfo]=[]
                for lp_h_item in data.get('lp_holders',[]):
                    parsed_evm_lp_holders.append(LPTokenInfo(address=lp_h_item.get('address',''),balance=_str_to_float(lp_h_item.get('balance'))or 0.0,
                        percent_of_total_lp=_str_to_float(lp_h_item.get('percent'))or 0.0,is_contract=_str_to_bool(lp_h_item.get('is_contract'))or False,
                        tag=lp_h_item.get('tag'),is_locked=_str_to_bool(lp_h_item.get('locked'))or False,locked_details=lp_h_item.get('locked_detail')))
                if parsed_evm_lp_holders:
                    locked_lp_pct_evm=sum(h['percent_of_total_lp']for h in parsed_evm_lp_holders if h['is_locked'])
                    if locked_lp_pct_evm<0.80 and any(h['percent_of_total_lp']>0.05 for h in parsed_evm_lp_holders if not h['is_locked']): remarks_list.append(f"LP Lock (EVM): {locked_lp_pct_evm*100:.2f}% of top LP locked.")
                total_lp_usd_evm=sum(_str_to_float(d.get('liquidity'))or 0.0 for d in data.get('dex',[]))
                if total_lp_usd_evm < 5000 and total_lp_usd_evm > 0 : warnings_list.append(f"Low total DEX liquidity (EVM): ${total_lp_usd_evm:,.2f} USD.")
                elif total_lp_usd_evm == 0 and _str_to_bool(data.get('is_in_dex')): warnings_list.append("Token in DEX but GoPlus reports $0 total liquidity (EVM).")
                return TokenSecurityReport(token_address=token_address, chain_id=chain_id_str, retrieved_at=int(time.time()),
                    is_open_source=is_open_source_evm, is_proxy=_str_to_bool(data.get('is_proxy')), is_mintable=_str_to_bool(data.get('is_mintable')),
                    owner_address=data.get('owner_address'), can_take_back_ownership=_str_to_bool(data.get('can_take_back_ownership')),
                    owner_can_change_balance=_str_to_bool(data.get('owner_change_balance')), has_hidden_owner=_str_to_bool(data.get('hidden_owner')),
                    can_self_destruct=_str_to_bool(data.get('selfdestruct')), is_in_dex=_str_to_bool(data.get('is_in_dex')),
                    buy_tax=buy_tax_evm, sell_tax=sell_tax_evm, transfer_tax=_str_to_float(data.get('transfer_tax')),
                    cannot_buy=_str_to_bool(data.get('cannot_buy')), cannot_sell_all=_str_to_bool(data.get('cannot_sell_all')),
                    is_honeypot=is_honeypot_evm, is_trading_pausable=_str_to_bool(data.get('transfer_pausable')),
                    has_blacklist=_str_to_bool(data.get('is_blacklisted')), has_whitelist=_str_to_bool(data.get('is_whitelisted')),
                    is_anti_whale=_str_to_bool(data.get('is_anti_whale')), has_trading_cooldown=_str_to_bool(data.get('trading_cooldown')),
                    can_owner_modify_taxes=_str_to_bool(data.get('slippage_modifiable')), top_lp_holders=parsed_evm_lp_holders,
                    total_lp_liquidity_usd=total_lp_usd_evm, warnings=warnings_list,remarks=remarks_list,raw_goplus_response=data)
        except Exception as e:
            error_body = ""
            if isinstance(e, aiohttp.ClientResponseError) and hasattr(e, 'response') and e.response :
                try: error_body = await e.response.text()
                except Exception: pass
            print(f"Error fetching/processing GoPlus report for {token_address} on {chain_id_str}: {type(e).__name__} - {e}. Body: {error_body}"); return None


def fetch_pairs_for_token(token_address: str, dexscreener_chain_name: str, max_pairs: int = 10) -> List[PairReport]:
    """Fetches trading pair info from DexScreener API."""
    # Basic address validation (lenient for this specific check as DexScreener might use non-standard identifiers for some custom chains)
    if not token_address or len(token_address) < 30: # Very basic check
        print(f"Warning (fetch_pairs_for_token): Potentially invalid token address format: {token_address}"); # Don't return, let API try

    url = f"{DEXSCREENER_API_BASE_URL}/dex/search?q={token_address}"
    parsed_pairs: List[PairReport] = []
    try:
        print(f"Fetching DexScreener pairs for {token_address} (chain '{dexscreener_chain_name}')...")
        response = requests.get(url, timeout=15) # Using synchronous requests here
        response.raise_for_status(); response_data = response.json()
        raw_pairs = response_data.get("pairs", [])
        if not raw_pairs: print(f"No pairs by DexScreener search for '{token_address}'."); return []

        for pair_data in raw_pairs:
            if pair_data.get('chainId', '').lower() != dexscreener_chain_name.lower(): continue
            base_token, quote_token = pair_data.get('baseToken',{}), pair_data.get('quoteToken',{})
            # Ensure the token we are searching for is part of this pair
            # This check is important because DexScreener search `q=` can be broad.
            if not (base_token.get('address','').lower() == token_address.lower() or \
                    quote_token.get('address','').lower() == token_address.lower()):
                continue

            liquidity, volume = pair_data.get('liquidity',{}), pair_data.get('volume',{})
            created_at_ms = pair_data.get('pairCreatedAt')
            created_at_s = int(created_at_ms/1000) if isinstance(created_at_ms,(int,float)) else None
            parsed_pairs.append(PairReport(
                pair_address=pair_data.get('pairAddress','N/A'),base_token_address=base_token.get('address','N/A'),
                quote_token_address=quote_token.get('address','N/A'),chain_id=pair_data.get('chainId','N/A'),
                dex_id=pair_data.get('dexId'),price_usd=_str_to_float(pair_data.get('priceUsd'),'priceUsd'),
                liquidity_usd=_str_to_float(liquidity.get('usd'),'liq_usd'),volume_h24=_str_to_float(volume.get('h24'),'vol_h24'),
                pair_created_at=created_at_s,url=pair_data.get('url')))

        parsed_pairs.sort(key=lambda p:p['pair_created_at']if p['pair_created_at']is not None else 0,reverse=True)
        print(f"Found & filtered {len(parsed_pairs)} pairs for {token_address} on '{dexscreener_chain_name}'. Returning top {max_pairs}.")
        return parsed_pairs[:max_pairs]
    except Exception as e: print(f"Error processing DexScreener pairs for {token_address}: {type(e).__name__} - {e}"); return []

# --- Example Usage (for direct testing of this module) ---
if __name__ == '__main__':
    import asyncio # Required for run_tests
    # Helper functions to print reports (simplified for this file, more detailed in test_token_analyzer.py)
    def _print_sec_report_summary(report: Optional[TokenSecurityReport]):
        if not report: print("  No security report."); return
        print(f"  Report for: {report['token_address']} on {report['chain_id']}")
        print(f"    Honeypot: {report.get('is_honeypot')}, Buy Tax: {report.get('buy_tax')}, Sell Tax: {report.get('sell_tax')}")
        print(f"    Warnings: {len(report.get('warnings',[]))} - Top: {report.get('warnings',[])[:2]}")

    def _print_pair_report_summary(reports: List[PairReport], token: str):
        if not reports: print(f"  No pair reports for {token}."); return
        print(f"  Pairs for {token} (found {len(reports)}):")
        for p in reports[:2]: print(f"    - Pair: {p['pair_address']}, Liq: ${p.get('liquidity_usd',0):,.0f}, Price: ${p.get('price_usd',0):.4f}")

    async def run_tests():
        print("Starting token_analyzer.py example usage (async)...")
        if not os.path.exists('config.json'):
            print("`config.json` not found. Creating dummy. API calls will fail without real keys.")
            with open('config.json', 'w') as f_dummy:
                json.dump({"token_analysis_apis":{"goplus_security":{"api_key":"YOUR_GOPLUS_KEY"}}},f_dummy,indent=2)

        # Test GoPlus Security for EVM (WETH on Ethereum)
        # evm_sec_report = await fetch_token_security_report("0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "1")
        # _print_sec_report_summary(evm_sec_report)

        # Test GoPlus Security for Solana (WSOL on Solana)
        # sol_sec_report = await fetch_token_security_report("So11111111111111111111111111111111111111112", "solana")
        # _print_sec_report_summary(sol_sec_report)

        # Test DexScreener (PEPE on Ethereum) - This call is synchronous
        # pepe_pairs = fetch_pairs_for_token("0x6982508145454Ce325dDbE47a25d4ec3d2311933", "ethereum", max_pairs=3)
        # _print_pair_report_summary(pepe_pairs, "PEPE_ETH")

        print("\nToken analyzer example usage complete. Uncomment specific tests and ensure API keys are set for full functionality.")

    asyncio.run(run_tests())
```
