"""
This module provides utilities for interacting with the Solana blockchain, including:
- Connecting to Solana RPC nodes (AsyncClient).
- Loading Solana keypairs from base58 private keys.
- Fetching SOL (native) and SPL token balances.
- Executing token swaps via the Jupiter Ultra API (fetching quotes, signing, and executing).

Requires configuration in 'config.json' (ideally under a 'solana_settings' key)
for RPC URLs and private key. Environment variables are prioritized for sensitive data.
Uses 'aiohttp' for asynchronous calls to the Jupiter API.
"""
import json
import os
from typing import Optional, Dict, Any, List, Tuple, TypedDict
import base64
import asyncio

import aiohttp # For async HTTP requests to Jupiter
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.hash import Hash as SolanaHash # Explicit import for clarity if needed, though blockhash is often already this type
from solders.transaction import VersionedTransaction
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from spl.token.instructions import get_associated_token_address # type: ignore
from solana.exceptions import SolanaRpcException


# --- Global Cache/Config ---
SOLANA_CONFIG: Dict[str, Any] = {} # Caches loaded Solana configuration

# --- Data Structures ---
class SolanaJupiterQuote(TypedDict):
    """
    Represents a quote received from the Jupiter API /order endpoint.
    Fields:
        input_mint (str): Mint address of the input token.
        output_mint (str): Mint address of the output token.
        in_amount (int): Amount of input token (in smallest atomic unit).
        out_amount (int): Expected amount of output token (in smallest atomic unit).
        other_amount_threshold (int): Minimum output amount after slippage (atomic units).
        slippage_bps (int): Slippage tolerance in basis points (e.g., 50 for 0.5%).
        route_plan (List[Dict[str, Any]]): Detailed route plan from Jupiter.
        request_id (str): Unique ID for this quote request, needed for execution.
        transaction_b64 (str): Base64 encoded UNsigned VersionedTransaction for the swap.
        prioritization_fee_lamports (Optional[int]): Optional priority fee in lamports.
        raw_quote_response (Dict[str, Any]): The full raw JSON response from Jupiter.
    """
    input_mint: str
    output_mint: str
    in_amount: int
    out_amount: int
    other_amount_threshold: int
    slippage_bps: int
    route_plan: List[Dict[str, Any]]
    request_id: str
    transaction_b64: str
    prioritization_fee_lamports: Optional[int]
    raw_quote_response: Dict[str, Any]

class SolanaSwapResult(TypedDict):
    """
    Represents the result of an attempted Jupiter swap execution.
    Fields:
        success (bool): True if the swap was successfully executed and confirmed.
        signature (Optional[str]): Transaction signature if submitted (even if failed on-chain).
        error_message (Optional[str]): Description of error if success is False.
        input_amount_processed (Optional[int]): Actual input amount processed by Jupiter (atomic).
        output_amount_processed (Optional[int]): Actual output amount received (atomic).
        raw_execute_response (Optional[Dict[str, Any]]): Full raw JSON from Jupiter /execute.
    """
    success: bool
    signature: Optional[str]
    error_message: Optional[str]
    input_amount_processed: Optional[int]
    output_amount_processed: Optional[int]
    raw_execute_response: Optional[Dict[str, Any]]

JUPITER_ULTRA_API_BASE = "https://lite-api.jup.ag/ultra/v1"


# --- Configuration ---
def _load_solana_config(config_path: str = 'config.json') -> bool:
    """
    Loads Solana configuration (RPC URLs, private key) from the specified config file
    and relevant environment variables. Prioritizes environment variables.
    Expected keys in config file (ideally under a 'solana_settings' object):
    - 'solana_rpc_url_mainnet', 'solana_rpc_url_devnet'
    - 'solana_private_key_b58' (Base58 encoded private key string)
    Corresponding environment variables:
    - SOLANA_RPC_URL_MAINNET, SOLANA_RPC_URL_DEVNET
    - SOLANA_PRIVATE_KEY_B58
    Returns True if loading was attempted (actual values might still be None if not set).
    """
    global SOLANA_CONFIG
    if SOLANA_CONFIG.get("loaded_flag"): # Avoid re-parsing if already attempted
        return True # Does not mean keys were found, just that loading was done.

    SOLANA_CONFIG["loaded_flag"] = True
    config_data = {}
    try:
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config_data = json.load(f)
        else:
            print(f"Info (_load_solana_config): Config file '{config_path}' not found. Will rely on environment variables for Solana settings.")

        # Look for a 'solana_settings' sub-object, otherwise use top-level config_data
        solana_specific_configs = config_data.get("solana_settings", config_data)

        SOLANA_CONFIG['solana_rpc_url_mainnet'] = os.getenv('SOLANA_RPC_URL_MAINNET', solana_specific_configs.get('solana_rpc_url_mainnet'))
        SOLANA_CONFIG['solana_rpc_url_devnet'] = os.getenv('SOLANA_RPC_URL_DEVNET', solana_specific_configs.get('solana_rpc_url_devnet'))
        SOLANA_CONFIG['solana_private_key_b58'] = os.getenv('SOLANA_PRIVATE_KEY_B58', solana_specific_configs.get('solana_private_key_b58'))

        if not SOLANA_CONFIG.get('solana_rpc_url_mainnet') and not SOLANA_CONFIG.get('solana_rpc_url_devnet'):
            print("Warning (_load_solana_config): No Solana RPC URLs found (mainnet or devnet) in environment variables or config file.")
        if not SOLANA_CONFIG.get('solana_private_key_b58'):
            print("Warning (_load_solana_config): `solana_private_key_b58` not found in environment variables or config. Wallet operations will fail.")
        return True
    except json.JSONDecodeError:
        print(f"Error (_load_solana_config): Could not decode JSON from config file '{config_path}'.")
        return False # Indicates a problem with config file format
    except Exception as e:
        print(f"Error (_load_solana_config): Unexpected error loading Solana config: {type(e).__name__} - {e}")
        return False

def get_solana_rpc_url(network: str = "mainnet-beta") -> Optional[str]:
    """
    Retrieves the RPC URL for the specified Solana network from the loaded configuration.
    Args:
        network (str): The desired network, e.g., "mainnet-beta" or "devnet".
    Returns:
        Optional[str]: The RPC URL string if found, else None.
    """
    if not SOLANA_CONFIG.get("loaded_flag"): _load_solana_config() # Ensure config is loaded

    # Construct key based on network name (e.g., 'solana_rpc_url_mainnet', 'solana_rpc_url_devnet')
    config_key = f"solana_rpc_url_{network.replace('-beta', '')}"
    url = SOLANA_CONFIG.get(config_key)
    if not url:
        print(f"Error: Solana RPC URL for network '{network}' (key: '{config_key}') not configured.")
    return url

# --- Client and Wallet ---
async def get_async_solana_client(network: str = "mainnet-beta", rpc_url_override: Optional[str] = None) -> Optional[AsyncClient]:
    """
    Creates and returns an asynchronous Solana client (AsyncClient).
    Args:
        network (str): Target Solana network (e.g., "mainnet-beta", "devnet"). Used if rpc_url_override is not provided.
        rpc_url_override (Optional[str]): Specific RPC URL to use, bypassing config lookup.
    Returns:
        Optional[AsyncClient]: Connected AsyncClient instance, or None on failure.
    """
    rpc_url = rpc_url_override if rpc_url_override else get_solana_rpc_url(network)
    if not rpc_url:
        print(f"Error (get_async_solana_client): RPC URL for network '{network}' is unavailable."); return None
    try:
        client = AsyncClient(rpc_url, commitment=Confirmed)
        if await client.is_connected(): # Pings /health endpoint
            print(f"Successfully connected to Solana RPC: {rpc_url} (Network: {network})")
            return client
        else:
            print(f"Failed to establish initial connection to Solana RPC: {rpc_url}"); await client.close(); return None
    except Exception as e:
        print(f"Error creating Solana async client for {rpc_url} (Network: {network}): {type(e).__name__} - {e}"); return None

def load_solana_keypair(private_key_b58_str: Optional[str] = None) -> Optional[Keypair]:
    """
    Loads a Solana Keypair from a base58 encoded private key string.
    Args:
        private_key_b58_str (Optional[str]): The base58 encoded private key. If None,
                                             attempts to load from config/environment.
    Returns:
        Optional[Keypair]: Loaded Keypair object, or None on failure.
    """
    if not private_key_b58_str:
        if not SOLANA_CONFIG.get("loaded_flag"): _load_solana_config() # Ensure config loaded
        private_key_b58_str = SOLANA_CONFIG.get('solana_private_key_b58')

    if not private_key_b58_str:
        print("Error (load_solana_keypair): No Solana private key provided or found in config/env."); return None

    # Check for placeholder key and warn, but still attempt to load for structural tests if needed.
    if private_key_b58_str == "YOUR_B58_PRIVATE_KEY_HERE_FOR_TESTING_ONLY_NEVER_COMMIT_REAL_KEYS" or \
       private_key_b58_str == "YOUR_SOLANA_WALLET_PRIVATE_KEY_B58_ENCODED_HERE_NEVER_COMMIT_REAL_KEYS":
        print("Warning (load_solana_keypair): Using a placeholder private key string. This will not work for on-chain transactions requiring a signature.");

    try:
        keypair = Keypair.from_base58_string(private_key_b58_str)
        print(f"Successfully loaded Solana keypair. Public Key: {keypair.pubkey()}"); return keypair
    except Exception as e:
        print(f"Error loading Solana keypair from base58 string: {type(e).__name__} - {e}")
        print("  Ensure the private key is a valid base58 encoded string representing a 64-byte Ed25519 secret key."); return None

# --- Balance Functions ---
async def get_sol_balance(client: AsyncClient, pubkey: Pubkey) -> Optional[float]:
    """Fetches the native SOL balance for a given public key."""
    if not client or not pubkey: print("Error (get_sol_balance): Client or Pubkey not provided."); return None
    try:
        resp = await client.get_balance(pubkey, commitment=Confirmed)
        sol_balance = resp.value / 1_000_000_000  # LAMPORTS_PER_SOL
        print(f"SOL balance for {pubkey}: {sol_balance:.9f} SOL"); return sol_balance
    except Exception as e: print(f"Error getting SOL balance for {pubkey}: {type(e).__name__} - {e}"); return None

async def get_spl_token_balance(client: AsyncClient, owner_pk: Pubkey, mint_addr_str: str) -> Optional[float]:
    """
    Fetches SPL token balance for an owner and mint. Derives ATA.
    Returns 0.0 if ATA doesn't exist.
    """
    if not all([client, owner_pk, mint_addr_str]): print("Error (get_spl_token_balance): Missing client, owner_pk, or mint_addr_str."); return None
    try: mint_pk = Pubkey.from_string(mint_addr_str)
    except ValueError: print(f"Error (get_spl_token_balance): Invalid SPL mint address format: {mint_addr_str}"); return None

    ata_pk = get_associated_token_address(owner_pk, mint_pk)
    try:
        resp = await client.get_token_account_balance(ata_pk, commitment=Confirmed)
        # value is TokenAmount(amount=str, decimals=int, ui_amount=float, ui_amount_string=str)
        ui_amount = resp.value.ui_amount
        if ui_amount is not None: # ui_amount is already decimal adjusted float
            print(f"SPL Token {mint_addr_str} balance for {owner_pk} (ATA {ata_pk}): {ui_amount}"); return ui_amount
        # Fallback if ui_amount is None (should be rare for this call)
        # amount_raw = int(resp.value.amount); decimals = resp.value.decimals
        # balance = amount_raw / (10**decimals)
        # print(f"SPL Token {mint_addr_str} balance (manual calc): {balance}"); return balance
        print(f"Warning (get_spl_token_balance): ui_amount not available for {mint_addr_str} at {ata_pk}. Raw: {resp.value.amount}"); return None
    except SolanaRpcException as e:
        if "could not find account" in str(e).lower() or "account does not exist" in str(e).lower():
            print(f"Info (get_spl_token_balance): ATA {ata_pk} for mint {mint_addr_str} (owner {owner_pk}) not found. Assuming 0 balance."); return 0.0
        print(f"RPC error getting SPL balance (Mint: {mint_addr_str}, Owner: {owner_pk}): {e}"); return None
    except Exception as e: print(f"Unexpected error getting SPL balance (Mint: {mint_addr_str}, Owner: {owner_pk}): {type(e).__name__} - {e}"); return None

# --- Jupiter Swap Functions ---
async def fetch_jupiter_quote(
    input_mint_str: str, output_mint_str: str, amount_atomic: int,
    user_public_key_str: str, slippage_bps: int = 100, # Default 1% (100 bps)
    session: Optional[aiohttp.ClientSession] = None
) -> Optional[SolanaJupiterQuote]:
    """
    Fetches a swap quote from Jupiter /order API using aiohttp.
    Args:
        input_mint_str (str): Mint address of the input token.
        output_mint_str (str): Mint address of the output token.
        amount_atomic (int): Amount of input token in its smallest atomic unit.
        user_public_key_str (str): The user's public key (wallet address) initiating the swap.
        slippage_bps (int): Slippage tolerance in basis points (e.g., 100 for 1%).
        session (Optional[aiohttp.ClientSession]): Optional existing aiohttp session.
    Returns:
        Optional[SolanaJupiterQuote]: Parsed quote data, or None on failure.
    """
    url = f"{JUPITER_ULTRA_API_BASE}/order"
    params = {"inputMint":input_mint_str,"outputMint":output_mint_str,"amount":amount_atomic,"taker":user_public_key_str,"slippageBps":slippage_bps}
    print(f"Fetching Jupiter quote: GET {url} with params {params}")

    close_session_after = False
    if session is None: session = aiohttp.ClientSession(); close_session_after = True

    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            resp.raise_for_status(); data = await resp.json()
        # print(f"Jupiter Quote Raw Response: {json.dumps(data, indent=2)}") # Verbose
        if not data or "transaction" not in data or not data["transaction"]:
            print(f"Error: 'transaction' field missing/null in Jupiter /order response. Data: {data}"); return None
        return SolanaJupiterQuote(
            input_mint=data.get("inputMint"), output_mint=data.get("outputMint"),
            in_amount=int(data.get("inAmount",0)), out_amount=int(data.get("outAmount",0)),
            other_amount_threshold=int(data.get("otherAmountThreshold",0)),
            slippage_bps=data.get("slippageBps",slippage_bps), route_plan=data.get("routePlan",[]),
            request_id=data.get("requestId"), transaction_b64=data["transaction"],
            prioritization_fee_lamports=data.get("prioritizationFeeLamports"), raw_quote_response=data )
    except Exception as e:
        error_body = "";
        if isinstance(e, aiohttp.ClientResponseError) and hasattr(e, 'response') and e.response:
            try: error_body = await e.response.text()
            except Exception: pass
        print(f"Error fetching Jupiter quote: {type(e).__name__} - {e}. Body: {error_body}"); return None
    finally:
        if close_session_after and session: await session.close()

async def execute_jupiter_swap(
    quote: SolanaJupiterQuote, signer_keypair: Keypair,
    solana_client: AsyncClient, session: Optional[aiohttp.ClientSession] = None
) -> SolanaSwapResult:
    """
    Executes a Jupiter swap using the provided quote and signer keypair.
    Args:
        quote (SolanaJupiterQuote): The quote received from `fetch_jupiter_quote`.
        signer_keypair (Keypair): The keypair of the wallet executing the swap.
        solana_client (AsyncClient): Connected Solana AsyncClient.
        session (Optional[aiohttp.ClientSession]): Optional existing aiohttp session.
    Returns:
        SolanaSwapResult: Dictionary containing success status, signature, and other details.
    """
    if not quote.get("transaction_b64"):
        return SolanaSwapResult(success=False,error_message="No transaction string in quote.",signature=None,raw_execute_response=None,input_amount_processed=None,output_amount_processed=None)
    try:
        print("Fetching recent blockhash for signing transaction...");
        blockhash_resp = await solana_client.get_latest_blockhash(commitment=Confirmed)
        if not blockhash_resp.value or not blockhash_resp.value.blockhash:
            return SolanaSwapResult(success=False,error_message="Failed to get recent blockhash.",signature=None,raw_execute_response=None,input_amount_processed=None,output_amount_processed=None)
        recent_blockhash = blockhash_resp.value.blockhash # This is a solders.hash.Hash object
        print(f"Using recent blockhash: {recent_blockhash}")

        tx_bytes = base64.b64decode(quote["transaction_b64"])
        versioned_tx = VersionedTransaction.from_bytes(tx_bytes); print("Transaction deserialized from quote.")
        versioned_tx.sign([signer_keypair], recent_blockhash); print("Transaction signed with signer's keypair.")
        signed_tx_b64 = base64.b64encode(versioned_tx.serialize()).decode('utf-8'); print("Signed transaction serialized to base64.")

        url = f"{JUPITER_ULTRA_API_BASE}/execute"
        payload = {"requestId": quote["request_id"], "signedTransaction": signed_tx_b64}
        print(f"Executing Jupiter swap via POST to {url} for requestId {quote['request_id']}")

        close_session_after = False
        if session is None: session = aiohttp.ClientSession(); close_session_after = True

        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=90)) as resp: # Increased timeout for execution
            resp.raise_for_status(); exec_data = await resp.json()
        # print(f"Jupiter Execute Raw Response: {json.dumps(exec_data, indent=2)}") # Verbose

        if exec_data.get("status") == "Success":
            return SolanaSwapResult(success=True,signature=exec_data.get("signature"),error_message=None,
                                    input_amount_processed=int(exec_data.get("inputAmountResult",0)) if exec_data.get("inputAmountResult") else None,
                                    output_amount_processed=int(exec_data.get("outputAmountResult",0)) if exec_data.get("outputAmountResult") else None,
                                    raw_execute_response=exec_data)
        else:
            err_msg_detail = exec_data.get("error","Unknown error from Jupiter /execute")
            if isinstance(err_msg_detail,dict):err_msg_detail=json.dumps(err_msg_detail)
            return SolanaSwapResult(success=False,signature=exec_data.get("signature"), error_message=f"Jupiter swap execution failed: {err_msg_detail} (Code: {exec_data.get('code')})",
                                    raw_execute_response=exec_data,input_amount_processed=None,output_amount_processed=None)
    except Exception as e:
        error_body = "";
        if isinstance(e, aiohttp.ClientResponseError) and hasattr(e, 'response') and e.response:
            try: error_body = await e.response.text()
            except Exception: pass
        print(f"Error executing Jupiter swap: {type(e).__name__} - {e}. Body: {error_body}")
        return SolanaSwapResult(success=False,error_message=f"Exception: {type(e).__name__} - {e}. Body: {error_body}",signature=None,raw_execute_response=None,input_amount_processed=None,output_amount_processed=None)
    finally:
        if close_session_after and session: await session.close()

# --- Main Test Block (Illustrative) ---
async def _basic_main_test():
    print("="*70 + "\nSolana Utilities Basic Tests (from _basic_main_test)\n" + "="*70)
    if not _load_solana_config(): print("Failed to load Solana config. Basic tests may fail or be skipped."); return

    rpc_url = get_solana_rpc_url("devnet")
    if not rpc_url: print("Devnet RPC URL not configured. Skipping basic client tests."); return

    client = await get_async_solana_client(network="devnet", rpc_url_override=rpc_url)
    if not client: print("Failed to connect to Solana Devnet for basic tests."); return

    keypair = load_solana_keypair() # Attempt to load keypair from config/env
    if keypair:
        await get_sol_balance(client, keypair.pubkey())
        # Example Devnet USDC mint: Gh9ZwEmdLJ8DscKNTkTqPbNwLNNBjuSzaG9Vp2KGtKJr (ensure this is a valid mint on your target devnet)
        devnet_usdc_mint = "Gh9ZwEmdLJ8DscKNTkTqPbNwLNNBjuSzaG9Vp2KGtKJr"
        await get_spl_token_balance(client, keypair.pubkey(), devnet_usdc_mint)
    else: print("Keypair not loaded (check config/env for SOLANA_PRIVATE_KEY_B58), skipping balance tests that require it.")

    await client.close(); print("Basic tests' Solana client closed.")

async def _main_swap_test():
    print("\n" + "="*70 + "\nSolana Jupiter Swap Functionality Tests (from _main_swap_test)\n" + "="*70)
    if not _load_solana_config(): print("Failed to load Solana config. Swap tests cannot proceed."); return

    rpc_url = get_solana_rpc_url("devnet")
    if not rpc_url: print("Devnet RPC URL not configured. Skipping swap tests."); return

    signer = load_solana_keypair()
    if not signer or not hasattr(signer, 'pubkey') or signer.pubkey() is None:
        print("Failed to load Solana keypair or keypair is invalid. Swap tests require a valid signer.");
        print("Ensure SOLANA_PRIVATE_KEY_B58 is correctly set in config or environment."); return
    print(f"Using wallet for swaps: {signer.pubkey()}")

    sol_client = await get_async_solana_client(network="devnet", rpc_url_override=rpc_url)
    if not sol_client: print("Failed to connect to Solana Devnet RPC for swap tests."); return

    # Standard Mint Addresses for Devnet (use actual valid ones)
    WSOL_MINT = "So11111111111111111111111111111111111111112"
    USDC_DEVNET_MINT_EXAMPLE = "Gh9ZwEmdLJ8DscKNTkTqPbNwLNNBjuSzaG9Vp2KGtKJr"

    sol_amount_to_swap = 0.00001 # Very small amount for devnet testing
    sol_amount_lamports = int(sol_amount_to_swap * 1_000_000_000)

    print(f"\nAttempting Jupiter quote: {sol_amount_to_swap} SOL ({WSOL_MINT}) to USDC ({USDC_DEVNET_MINT_EXAMPLE})")

    async with aiohttp.ClientSession() as http_session:
        quote = await fetch_jupiter_quote(
            input_mint_str=WSOL_MINT, output_mint_str=USDC_DEVNET_MINT_EXAMPLE,
            amount_atomic=sol_amount_lamports, user_public_key_str=str(signer.pubkey()),
            slippage_bps=100, session=http_session
        )
        if quote:
            print("\n--- Jupiter Quote Received ---") # Basic print, details in function log
            print(f"  Input: {quote.get('in_amount')} {quote.get('input_mint')} -> Output Estimate: {quote.get('out_amount')} {quote.get('output_mint')}")
            if input("Proceed with DEVNET swap execution based on this quote? (yes/no): ").lower() == 'yes':
                swap_result = await execute_jupiter_swap(quote, signer, sol_client, session=http_session)
                print(f"\n--- Swap Execution Result --- \n{json.dumps(swap_result, indent=2)}")
            else: print("Swap execution cancelled by user.")
        else: print("\nFailed to get Jupiter quote. Check mint addresses, amount, or Jupiter API status.")

    await sol_client.close(); print("\nSwap tests' Solana client closed.")

async def run_all_solana_tests_main():
    """Main function to run all test suites defined in this file."""
    if not os.path.exists('config.json'):
        print("INFO: `config.json` not found. Creating a dummy for structural integrity.")
        try:
            with open('config.json', 'w') as f_dummy:
                json.dump({
                    "solana_settings": {
                        "solana_rpc_url_devnet": "https://api.devnet.solana.com",
                        "solana_private_key_b58": "YOUR_B58_PRIVATE_KEY_FOR_DEVNET_TESTING_HERE"
                    }
                }, f_dummy, indent=2)
        except Exception as e: print(f"Could not create dummy config.json: {e}")

    await _basic_main_test()
    await _main_swap_test()

if __name__ == '__main__':
    asyncio.run(run_all_solana_tests_main())
    print("\nAll Solana utility tests in solana_utils.py finished.")
```
