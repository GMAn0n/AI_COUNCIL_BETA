import asyncio
import json
import os
import time # For print formatting if needed
import aiohttp # Required for Jupiter swap functions that use it
from typing import Optional, List # For type hints

# Ensure solana_utils.py is accessible
from solana_utils import (
    _load_solana_config,
    get_solana_rpc_url,
    get_async_solana_client,
    load_solana_keypair,
    get_sol_balance,
    get_spl_token_balance,
    fetch_jupiter_quote,
    execute_jupiter_swap,
    SolanaJupiterQuote
)
from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solana.rpc.async_api import AsyncClient

# Devnet Mints (verify these are current for testing)
WSOL_DEVNET_MINT = "So11111111111111111111111111111111111111112" # Wrapped SOL Mint
USDC_DEVNET_MINT = "Gh9ZwEmdLJ8DscKNTkTqPbNwLNNBjuSzaG9Vp2KGtKJr" # Example Devnet USDC Mint

async def test_solana_connection_and_wallet_loading():
    print("\n--- Test: Solana Connection and Wallet Loading (test_solana_utils.py) ---")
    if not _load_solana_config():
        print("FAIL: Critical - Could not load Solana configuration. Aborting connection/wallet tests.")
        return None, None

    rpc_url = get_solana_rpc_url("devnet")
    if not rpc_url:
        print("FAIL: Devnet RPC URL not configured in config.json (solana_settings.solana_rpc_url_devnet or SOLANA_RPC_URL_DEVNET env).")
        return None, None

    client = await get_async_solana_client(network="devnet", rpc_url_override=rpc_url)
    if not client:
        print(f"FAIL: Could not connect to Solana devnet RPC at {rpc_url}.")
        return None, None
    print(f"PASS: Connected to Solana RPC: {rpc_url}")

    keypair = load_solana_keypair()
    if not keypair:
        print("FAIL: Could not load Solana keypair. Ensure solana_private_key_b58 is set in config.json (under solana_settings) or as SOLANA_PRIVATE_KEY_B58 env var.")
        return client, None
    print(f"PASS: Loaded Solana keypair. Pubkey: {keypair.pubkey()}")
    return client, keypair

async def test_solana_balance_functions(client: Optional[AsyncClient], keypair_to_test: Optional[Keypair]):
    print("\n--- Test: Solana Balance Functions (test_solana_utils.py) ---")
    if not client:
        print("SKIP: Solana client not available for balance tests.")
        return

    pubkey_to_check_str = ""
    if keypair_to_test:
        pubkey_to_check_str = str(keypair_to_test.pubkey())
        print(f"Using loaded keypair's public key for balance checks: {pubkey_to_check_str}")
    else:
        addr_input = input("Enter a Solana public key to check balances (or press Enter to skip balance tests): ").strip()
        if addr_input:
            pubkey_to_check_str = addr_input
        else:
            print("SKIP: No keypair loaded and no public key provided for balance tests.")
            return

    try:
        pubkey_to_check = Pubkey.from_string(pubkey_to_check_str)
    except ValueError:
        print(f"Invalid public key format entered: {pubkey_to_check_str}. Skipping balance tests.")
        return

    sol_bal = await get_sol_balance(client, pubkey_to_check)
    print(f"  SOL Balance for {pubkey_to_check}: {sol_bal if sol_bal is not None else 'Error or N/A'}")

    usdc_bal = await get_spl_token_balance(client, pubkey_to_check, USDC_DEVNET_MINT)
    print(f"  USDC (Devnet Mint: {USDC_DEVNET_MINT}) Balance for {pubkey_to_check}: {usdc_bal if usdc_bal is not None else 'Error or 0.0'}")

    random_mint_for_zero_balance_test = "RANDm111111111111111111111111111111111111111"
    zero_bal = await get_spl_token_balance(client, pubkey_to_check, random_mint_for_zero_balance_test)
    print(f"  Balance for likely non-held SPL Token ({random_mint_for_zero_balance_test}) for {pubkey_to_check}: {zero_bal} (expected 0.0)")


async def test_solana_jupiter_swap_cycle(client: Optional[AsyncClient], test_keypair: Optional[Keypair]):
    print("\n--- Test: Solana Jupiter Swap Cycle (Devnet SOL -> USDC) (test_solana_utils.py) ---")
    if not client or not test_keypair:
        print("SKIP: Solana client or keypair not available for swap tests. Ensure keypair is funded on Devnet.")
        return

    print(f"IMPORTANT: This test will attempt an ON-CHAIN DEVNET transaction from wallet {test_keypair.pubkey()}.")
    print(f"Ensure it has some Devnet SOL for transaction fees and a small amount to swap (e.g., 0.0001 SOL).")

    initial_sol = await get_sol_balance(client, test_keypair.pubkey())
    initial_usdc = await get_spl_token_balance(client, test_keypair.pubkey(), USDC_DEVNET_MINT)
    print(f"  Initial balances: SOL: {initial_sol if initial_sol is not None else 'N/A'}, Devnet USDC: {initial_usdc if initial_usdc is not None else 'N/A'}")

    if initial_sol is None or initial_sol < 0.0002:
        print(f"  WARNING: Insufficient SOL balance ({initial_sol}) for swap test. Test may fail.")
        if input("Proceed anyway? (yes/no): ").strip().lower() != 'yes': return

    user_prompt = input("Proceed with DEVNET SOL->USDC swap test? (yes/no): ").strip().lower()
    if user_prompt != 'yes':
        print("Swap test cancelled by user.")
        return

    sol_amount_to_swap_human = 0.0001
    sol_amount_lamports = int(sol_amount_to_swap_human * 1_000_000_000)

    print(f"  Attempting to get Jupiter quote: {sol_amount_to_swap_human} SOL ({WSOL_DEVNET_MINT}) to USDC ({USDC_DEVNET_MINT}) for wallet {test_keypair.pubkey()}")

    async with aiohttp.ClientSession() as http_session:
        quote = await fetch_jupiter_quote(
            input_mint_str=WSOL_DEVNET_MINT, output_mint_str=USDC_DEVNET_MINT,
            amount_atomic=sol_amount_lamports, user_public_key_str=str(test_keypair.pubkey()),
            slippage_bps=100, session=http_session # 1% slippage
        )

        if not quote:
            print("FAIL: Could not get Jupiter quote. Check API status, input parameters, and token mints."); return

        print(f"  PASS: Jupiter Quote Received. Expected out: {quote.get('out_amount')} of {quote.get('output_mint')} (atomic). RequestID: {quote.get('request_id')}")
        if quote.get('transaction_b64'): print(f"    Transaction (first 30 chars): {quote['transaction_b64'][:30]}...")
        else: print("FAIL: No transaction string in quote from Jupiter!"); return

        print("\n  Attempting to execute swap using received quote...")
        swap_result = await execute_jupiter_swap(quote, test_keypair, client, session=http_session)

        print("  --- Swap Execution Result ---")
        if swap_result and swap_result.get("success"):
            print(f"  PASS: Swap successful!"); print(f"    Signature: {swap_result.get('signature')}")
            print(f"    Input Processed (lamports): {swap_result.get('input_amount_processed')}")
            print(f"    Output Received (atomic USDC): {swap_result.get('output_amount_processed')}")
        elif swap_result:
            print(f"  FAIL: Swap failed."); print(f"    Error: {swap_result.get('error_message')}")
            if swap_result.get('signature'): print(f"    Failed Tx Signature (if any): {swap_result.get('signature')}")
        else: print("  FAIL: Swap execution function returned None or unexpected result.")

    print("\n  Checking post-swap balances (please wait a few seconds for blockchain state)...")
    await asyncio.sleep(10)
    final_sol = await get_sol_balance(client, test_keypair.pubkey())
    final_usdc = await get_spl_token_balance(client, test_keypair.pubkey(), USDC_DEVNET_MINT)
    print(f"  Final balances: SOL: {final_sol if final_sol is not None else 'N/A'}, USDC: {final_usdc if final_usdc is not None else 'N/A'}")
    if initial_sol is not None and final_sol is not None: print(f"  SOL change: {final_sol - initial_sol:.9f}")
    if initial_usdc is not None and final_usdc is not None: print(f"  USDC change: {final_usdc - initial_usdc}")


async def main_solana_tests():
    print("="*70 + "\n Solana Utilities Test Runner\n" + "="*70)
    print("This script will test Solana connection, wallet loading, balance fetching, and Jupiter swaps.")
    print("Ensure your `config.json` (or environment variables) are set for a Solana DEVNET,")
    print("and the specified devnet wallet (SOLANA_PRIVATE_KEY_B58) is funded with some SOL.")
    print("On-chain swap tests will require user confirmation.")

    if not os.path.exists('config.json'):
        print("\nINFO: `config.json` not found. Creating a dummy `config.json` with placeholder values.")
        try:
            with open('config.json', 'w') as f_dummy:
                json.dump({
                    "solana_settings": {
                        "solana_rpc_url_devnet": "https://api.devnet.solana.com",
                        "solana_private_key_b58": "YOUR_B58_PRIVATE_KEY_FOR_DEVNET_TESTING_HERE"
                    },
                    "token_analysis_apis": { "goplus_security": {"api_key": "YOUR_GOPLUS_KEY_PLACEHOLDER"}}
                }, f_dummy, indent=2)
        except Exception as e: print(f"Could not create dummy config.json: {e}")

    sol_client, test_kp = await test_solana_connection_and_wallet_loading()
    if sol_client:
        await test_solana_balance_functions(sol_client, test_kp)
        if test_kp: await test_solana_jupiter_swap_cycle(sol_client, test_kp)
        else: print("\nSKIP: Keypair not loaded, SKIPPING Jupiter swap cycle tests.")
        await sol_client.close(); print("\nSolana client closed after tests.")
    else: print("\nSolana client could not be initialized. Most tests skipped.")
    print("\n--- test_solana_utils.py finished ---")

if __name__ == "__main__":
    asyncio.run(main_solana_tests())
```
