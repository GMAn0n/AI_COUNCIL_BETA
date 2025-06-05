import json
import os
from typing import Optional, Dict, Any, List, Tuple, TypedDict # Added List, Tuple, TypedDict
import base64
import asyncio # Added asyncio for the main test block

import aiohttp # For async HTTP requests to Jupiter
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.hash import Hash as SolanaHash
from solders.transaction import VersionedTransaction
from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Confirmed
from spl.token.instructions import get_associated_token_address # type: ignore
# from solana.spl.token.client import Token as SplTokenClient # Not strictly needed for current balance check
from solana.exceptions import SolanaRpcException


# --- Global Cache/Config ---
SOLANA_CONFIG: Dict[str, Any] = {}

# --- Data Structures ---
class SolanaJupiterQuote(TypedDict):
    input_mint: str
    output_mint: str
    in_amount: int  # Smallest unit (e.g. lamports)
    out_amount: int # Smallest unit
    other_amount_threshold: int # Smallest unit, min out amount after slippage
    slippage_bps: int
    route_plan: List[Dict[str, Any]] # Detailed route plan from Jupiter
    request_id: str # ID of the quote request, needed for execution
    transaction_b64: str # Base64 encoded UNsigned VersionedTransaction
    prioritization_fee_lamports: Optional[int] # Optional priority fee in lamports
    raw_quote_response: Dict[str, Any] # The full raw JSON response from Jupiter /order

class SolanaSwapResult(TypedDict):
    success: bool
    signature: Optional[str] # Transaction signature if successful or if it made it to chain but failed
    error_message: Optional[str]
    input_amount_processed: Optional[int] # Actual input amount processed, in smallest unit
    output_amount_processed: Optional[int] # Actual output amount received, in smallest unit
    raw_execute_response: Optional[Dict[str, Any]] # Full raw JSON response from Jupiter /execute

# Base URL for Jupiter's Lite API (Ultra)
JUPITER_ULTRA_API_BASE = "https://lite-api.jup.ag/ultra/v1"


# --- Configuration ---
def _load_solana_config(config_path='config.json') -> bool:
    """Loads Solana config (RPC URLs, private key) from file and environment variables."""
    global SOLANA_CONFIG
    if SOLANA_CONFIG.get("loaded_flag"):
        return bool(SOLANA_CONFIG.get('solana_rpc_url_mainnet') or
                    SOLANA_CONFIG.get('solana_rpc_url_devnet') or
                    SOLANA_CONFIG.get('solana_private_key_b58'))

    SOLANA_CONFIG["loaded_flag"] = True
    try:
        config_data = {}
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config_data = json.load(f)
        else:
            print(f"Info (_load_solana_config): Config file '{config_path}' not found. Relying solely on env vars.")

        solana_settings = config_data.get("solana_settings", config_data)

        SOLANA_CONFIG['solana_rpc_url_mainnet'] = os.getenv('SOLANA_RPC_URL_MAINNET', solana_settings.get('solana_rpc_url_mainnet'))
        SOLANA_CONFIG['solana_rpc_url_devnet'] = os.getenv('SOLANA_RPC_URL_DEVNET', solana_settings.get('solana_rpc_url_devnet'))
        SOLANA_CONFIG['solana_private_key_b58'] = os.getenv('SOLANA_PRIVATE_KEY_B58', solana_settings.get('solana_private_key_b58'))

        if not SOLANA_CONFIG.get('solana_rpc_url_mainnet') and not SOLANA_CONFIG.get('solana_rpc_url_devnet'):
            print("Warning (_load_solana_config): Solana RPC URLs not found in env vars or config.")
        if not SOLANA_CONFIG.get('solana_private_key_b58'):
            print("Warning (_load_solana_config): Solana private key (solana_private_key_b58) not found. Wallet ops will fail.")
        return True
    except Exception as e:
        print(f"Error (_load_solana_config): Loading Solana config from '{config_path}': {e}")
        return False

def get_solana_rpc_url(network: str = "mainnet-beta") -> Optional[str]:
    """Gets the RPC URL for the specified Solana network."""
    if not SOLANA_CONFIG.get("loaded_flag"): _load_solana_config()
    key = f"solana_rpc_url_{network.replace('-beta', '')}" # mainnet-beta -> mainnet
    url = SOLANA_CONFIG.get(key)
    if not url: print(f"Error: Solana RPC URL for '{network}' not configured.")
    return url

# --- Client and Wallet ---
async def get_async_solana_client(network: str = "mainnet-beta", rpc_url_override: Optional[str] = None) -> Optional[AsyncClient]:
    """Creates and returns an AsyncClient for the specified Solana network."""
    rpc_url = rpc_url_override if rpc_url_override else get_solana_rpc_url(network)
    if not rpc_url:
        print(f"Cannot create Solana client: RPC URL for '{network}' is unavailable.")
        return None
    try:
        client = AsyncClient(rpc_url, commitment=Confirmed)
        if await client.is_connected():
            print(f"Successfully connected to Solana RPC: {rpc_url} (Network: {network})")
            return client
        else:
            print(f"Failed initial connection to Solana RPC: {rpc_url}"); await client.close(); return None
    except Exception as e:
        print(f"Error creating Solana async client for {rpc_url} (Network: {network}): {e}"); return None

def load_solana_keypair(private_key_b58_str: Optional[str] = None) -> Optional[Keypair]:
    """Loads a Solana Keypair from a base58 encoded private key string."""
    if not private_key_b58_str:
        if not SOLANA_CONFIG.get("loaded_flag"): _load_solana_config()
        private_key_b58_str = SOLANA_CONFIG.get('solana_private_key_b58')

    if not private_key_b58_str:
        print("Error: No Solana private key provided or found."); return None
    if private_key_b58_str == "YOUR_B58_PRIVATE_KEY_HERE_FOR_TESTING_ONLY_NEVER_COMMIT_REAL_KEYS":
        print("Warning: Using placeholder private key. This will not work for on-chain txns."); # Still load for structure tests
    try:
        keypair = Keypair.from_base58_string(private_key_b58_str)
        print(f"Loaded Solana keypair. Pubkey: {keypair.pubkey()}"); return keypair
    except Exception as e:
        print(f"Error loading Solana keypair from base58: {e}. Ensure it's a valid b58 encoded 64-byte key."); return None

# --- Balance Functions ---
async def get_sol_balance(client: AsyncClient, pubkey: Pubkey) -> Optional[float]:
    """Fetches native SOL balance for a public key."""
    if not client or not pubkey: print("Error: Client or Pubkey missing for SOL balance."); return None
    try:
        resp = await client.get_balance(pubkey, commitment=Confirmed)
        sol_bal = resp.value / 1_000_000_000
        print(f"SOL balance for {pubkey}: {sol_bal:.9f} SOL"); return sol_bal
    except Exception as e: print(f"Error getting SOL balance for {pubkey}: {e}"); return None

async def get_spl_token_balance(client: AsyncClient, owner_pk: Pubkey, mint_addr: str) -> Optional[float]:
    """Fetches SPL token balance for an owner and mint address."""
    if not all([client, owner_pk, mint_addr]): print("Error: Missing params for SPL balance."); return None
    try: mint_pk = Pubkey.from_string(mint_addr)
    except ValueError: print(f"Error: Invalid SPL mint address: {mint_addr}"); return None

    try:
        ata_pk = get_associated_token_address(owner_pk, mint_pk)
        resp = await client.get_token_account_balance(ata_pk, commitment=Confirmed)
        ui_amt_str = resp.value.ui_amount_string
        if ui_amt_str is not None:
            balance = float(ui_amt_str)
            print(f"SPL Token {mint_addr} balance for {owner_pk} (ATA {ata_pk}): {balance}"); return balance
        print(f"Warning: ui_amount_string missing for token {mint_addr} at ATA {ata_pk}. Raw: {resp.value.amount}"); return None
    except SolanaRpcException as e:
        if "could not find account" in str(e).lower() or "account does not exist" in str(e).lower():
            print(f"Info: ATA {ata_pk} for mint {mint_addr} (owner {owner_pk}) not found. Assuming 0 balance."); return 0.0
        print(f"RPC error getting SPL balance (Mint: {mint_addr}, Owner: {owner_pk}): {e}"); return None
    except Exception as e: print(f"Unexpected error getting SPL balance (Mint: {mint_addr}, Owner: {owner_pk}): {e}"); return None

# --- Jupiter Swap Functions ---
async def fetch_jupiter_quote(
    input_mint_str: str, output_mint_str: str, amount_atomic: int,
    user_public_key_str: str, slippage_bps: int = 50, # Default 0.5%
    session: Optional[aiohttp.ClientSession] = None
) -> Optional[SolanaJupiterQuote]:
    """Fetches a swap quote from Jupiter /order API."""
    url = f"{JUPITER_ULTRA_API_BASE}/order"
    params = {
        "inputMint": input_mint_str, "outputMint": output_mint_str,
        "amount": amount_atomic, "taker": user_public_key_str,
        "slippageBps": slippage_bps
    }
    print(f"Fetching Jupiter quote: GET {url} with params {params}")
    try:
        async def _do_fetch(s):
            async with s.get(url, params=params, timeout=aiohttp.ClientTimeout(total=20)) as resp: # Increased timeout
                resp.raise_for_status(); return await resp.json()
        data = await _do_fetch(session) if session else await _do_fetch(aiohttp.ClientSession())

        print(f"Jupiter Quote Raw Response: {json.dumps(data, indent=2)}") # Pretty print for debug
        if not data or "transaction" not in data or not data["transaction"]:
            print(f"Error: 'transaction' field missing/null in Jupiter /order response. Data: {data}"); return None

        return SolanaJupiterQuote(
            input_mint=data.get("inputMint"), output_mint=data.get("outputMint"),
            in_amount=int(data.get("inAmount",0)), out_amount=int(data.get("outAmount",0)),
            other_amount_threshold=int(data.get("otherAmountThreshold",0)),
            slippage_bps=data.get("slippageBps",slippage_bps), route_plan=data.get("routePlan",[]),
            request_id=data.get("requestId"), transaction_b64=data["transaction"],
            prioritization_fee_lamports=data.get("prioritizationFeeLamports"),
            raw_quote_response=data
        )
    except Exception as e:
        error_body = ""
        if isinstance(e, aiohttp.ClientResponseError) and e.response: error_body = await e.response.text()
        print(f"Error fetching Jupiter quote: {type(e).__name__} - {e}. Body: {error_body}"); return None

async def execute_jupiter_swap(
    quote: SolanaJupiterQuote, signer_keypair: Keypair,
    solana_client: AsyncClient, session: Optional[aiohttp.ClientSession] = None
) -> SolanaSwapResult:
    """Executes a Jupiter swap using the provided quote and signer."""
    if not quote.get("transaction_b64"):
        return SolanaSwapResult(success=False,error_message="No transaction in quote.",signature=None,raw_execute_response=None,input_amount_processed=None,output_amount_processed=None)
    try:
        print("Fetching recent blockhash for signing..."); blockhash_resp = await solana_client.get_latest_blockhash(commitment=Confirmed)
        if not blockhash_resp.value or not blockhash_resp.value.blockhash:
            return SolanaSwapResult(success=False,error_message="Failed to get recent blockhash.",signature=None,raw_execute_response=None,input_amount_processed=None,output_amount_processed=None)
        recent_blockhash = blockhash_resp.value.blockhash # This is already a solders.hash.Hash object
        print(f"Recent blockhash: {recent_blockhash}")

        tx_bytes = base64.b64decode(quote["transaction_b64"])
        versioned_tx = VersionedTransaction.from_bytes(tx_bytes); print("Transaction deserialized.")
        versioned_tx.sign([signer_keypair], recent_blockhash); print("Transaction signed.")
        signed_tx_b64 = base64.b64encode(versioned_tx.serialize()).decode('utf-8'); print("Signed tx serialized.")

        url = f"{JUPITER_ULTRA_API_BASE}/execute"
        payload = {"requestId": quote["request_id"], "signedTransaction": signed_tx_b64}
        print(f"Executing Jupiter swap: POST {url} for requestId {quote['request_id']}")

        async def _do_post(s):
            async with s.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=90)) as resp: # Longer timeout for execution
                resp.raise_for_status(); return await resp.json()
        exec_data = await _do_post(session) if session else await _do_post(aiohttp.ClientSession())
        print(f"Jupiter Execute Raw Response: {json.dumps(exec_data, indent=2)}")

        if exec_data.get("status") == "Success":
            return SolanaSwapResult(success=True,signature=exec_data.get("signature"),error_message=None,
                                    input_amount_processed=int(exec_data.get("inputAmountResult",0)) if exec_data.get("inputAmountResult") else None,
                                    output_amount_processed=int(exec_data.get("outputAmountResult",0)) if exec_data.get("outputAmountResult") else None,
                                    raw_execute_response=exec_data)
        else:
            err_msg_detail = exec_data.get("error","Unknown error from Jupiter /execute")
            if isinstance(err_msg_detail,dict):err_msg_detail=json.dumps(err_msg_detail)
            return SolanaSwapResult(success=False,signature=exec_data.get("signature"),
                                    error_message=f"Jupiter swap execution failed: {err_msg_detail} (Code: {exec_data.get('code')})",
                                    raw_execute_response=exec_data,input_amount_processed=None,output_amount_processed=None)
    except Exception as e:
        error_body = ""
        if isinstance(e, aiohttp.ClientResponseError) and e.response: error_body = await e.response.text()
        print(f"Error executing Jupiter swap: {type(e).__name__} - {e}. Body: {error_body}")
        return SolanaSwapResult(success=False,error_message=f"Exception: {type(e).__name__} - {e}. Body: {error_body}",signature=None,raw_execute_response=None,input_amount_processed=None,output_amount_processed=None)

# --- Main Test Block ---
async def basic_main_test(): # Renamed from previous main_test
    print("="*70 + "\nSolana Utilities Basic Tests\n" + "="*70)
    if not _load_solana_config(): print("Failed to load Solana config. Basic tests may fail."); return
    rpc_url = get_solana_rpc_url("devnet")
    if not rpc_url: print("Devnet RPC URL not configured. Skipping basic client tests."); return
    client = await get_async_solana_client(network="devnet", rpc_url_override=rpc_url)
    if not client: print("Failed to connect to Solana Devnet for basic tests."); return

    keypair = load_solana_keypair()
    if keypair:
        await get_sol_balance(client, keypair.pubkey())
        # Example Devnet USDC mint: Gh9ZwEmdLJ8DscKNTkTqPbNwLNNBjuSzaG9Vp2KGtKJr (verify this is still valid)
        devnet_usdc_mint = "Gh9ZwEmdLJ8DscKNTkTqPbNwLNNBjuSzaG9Vp2KGtKJr"
        await get_spl_token_balance(client, keypair.pubkey(), devnet_usdc_mint)
    else: print("Keypair not loaded (check config/env for SOLANA_PRIVATE_KEY_B58), skipping balance tests.")
    await client.close(); print("Basic tests Solana client closed.")

async def main_swap_test():
    print("\n" + "="*70 + "\nSolana Jupiter Swap Functionality Tests\n" + "="*70)
    if not _load_solana_config(): print("Failed to load Solana config. Swap tests cannot proceed."); return

    # Using devnet for swap tests. Ensure your SOLANA_PRIVATE_KEY_B58 is for a devnet wallet with SOL.
    rpc_url = get_solana_rpc_url("devnet")
    if not rpc_url: print("Devnet RPC URL not configured. Skipping swap tests."); return

    signer = load_solana_keypair()
    if not signer or signer.pubkey() is None: # Check if keypair actually loaded
        print("Failed to load Solana keypair (SOLANA_PRIVATE_KEY_B58). Swap tests require a valid signer. Ensure it's correctly set in config or env."); return
    print(f"Using wallet for swaps: {signer.pubkey()}")

    sol_client = await get_async_solana_client(network="devnet", rpc_url_override=rpc_url)
    if not sol_client: print("Failed to connect to Solana Devnet RPC for swap tests."); return

    WSOL_MINT = "So11111111111111111111111111111111111111112"
    USDC_DEVNET_MINT = "Gh9ZwEmdLJ8DscKNTkTqPbNwLNNBjuSzaG9Vp2KGtKJr" # Verify this devnet USDC mint

    sol_amount_to_swap = 0.0001 # Very small amount for testing
    sol_amount_lamports = int(sol_amount_to_swap * 1_000_000_000)

    print(f"\nAttempting Jupiter quote: {sol_amount_to_swap} SOL ({WSOL_MINT}) to USDC ({USDC_DEVNET_MINT})")

    async with aiohttp.ClientSession() as http_session: # Use a single session for related API calls
        quote = await fetch_jupiter_quote(
            input_mint_str=WSOL_MINT, output_mint_str=USDC_DEVNET_MINT,
            amount_atomic=sol_amount_lamports, user_public_key_str=str(signer.pubkey()),
            slippage_bps=100, session=http_session # 1% slippage
        )
        if quote:
            print("\n--- Jupiter Quote Received ---")
            print(f"  Input: {quote['in_amount']} of {quote['input_mint']}")
            print(f"  Output Estimate: {quote['out_amount']} of {quote['output_mint']}")
            print(f"  Min Output (after slippage): {quote['other_amount_threshold']}")
            # print(f"  Route Plan (first step): {quote['route_plan'][0]['swapInfo'] if quote['route_plan'] else 'N/A'}") # Can be verbose
            print(f"  Transaction to sign (first 30 chars): {quote['transaction_b64'][:30]}...")

            if input("Proceed with executing this devnet swap? (yes/no): ").lower() == 'yes':
                print("\nAttempting to execute swap...")
                swap_result = await execute_jupiter_swap(quote, signer, sol_client, session=http_session)
                print("\n--- Swap Execution Result ---")
                if swap_result["success"]:
                    print(f"  SUCCESS! Signature: {swap_result['signature']}")
                    print(f"  Input Processed: {swap_result.get('input_amount_processed')} lamports")
                    print(f"  Output Received: {swap_result.get('output_amount_processed')} (smallest unit of USDC_DEVNET_MINT)")
                else:
                    print(f"  FAILED! Error: {swap_result['error_message']}")
                    if swap_result['signature']: print(f"  Failed Tx Signature: {swap_result['signature']}")
            else:
                print("Swap execution cancelled by user.")
        else:
            print("\nFailed to get Jupiter quote. Check token addresses, amounts, and API connectivity.")

    await sol_client.close(); print("\nSwap tests Solana client closed.")

async def run_all_tests():
    """Runs all defined async test suites."""
    # Ensure dummy config exists for structural run if no real config.json
    if not os.path.exists('config.json'):
        print("Creating dummy config.json for test run structure...")
        with open('config.json', 'w') as f_dummy:
            # Provide a more complete dummy structure if other parts of config are accessed by utilities
            json.dump({
                "solana_settings": {
                    "solana_rpc_url_mainnet": "https://api.mainnet-beta.solana.com",
                    "solana_rpc_url_devnet": "https://api.devnet.solana.com",
                    "solana_private_key_b58": "YOUR_B58_PRIVATE_KEY_FOR_DEVNET_TESTING_HERE"
                },
                "token_analysis_apis": { # For token_analyzer if its config load is called
                     "goplus_security": {"api_key": "YOUR_GOPLUS_KEY_PLACEHOLDER"}
                }
            }, f_dummy, indent=2)

    await basic_main_test()
    await main_swap_test()

if __name__ == '__main__':
    # This structure allows running specific tests if needed by modifying the call here,
    # or running all tests as configured.
    asyncio.run(run_all_tests())
    print("\nAll Solana utility tests finished.")
```
