"""
test_evm_utils.py: Test script for EVM utility functions in `evm_utils.py`.

This script provides a command-line interface to manually test each function
in `evm_utils.py`. It is crucial for verifying that your EVM environment,
configuration (`config.json`), and the utility functions themselves are working
as expected, especially before integrating them into a larger application like
the AI agent system.

**IMPORTANT SETUP INSTRUCTIONS:**

1.  **Create `config.json`:**
    *   If you haven't already, copy `config.json.example` to `config.json`
        in the same directory as these scripts.
    *   **CRITICALLY IMPORTANT**: Fill `config.json` with **VALID data for a
        TESTNET** (e.g., Sepolia for Ethereum tests, Polygon Mumbai for Polygon tests).
        *   `rpc_urls`: Provide correct RPC URLs for your chosen testnet(s).
                       (e.g., from Infura, Alchemy, QuickNode, or your own testnet node).
        *   `chain_ids`: Ensure these match the `rpc_urls`.
        *   `private_key`: This MUST be a private key for a **TESTNET wallet** that
                           you control. This wallet needs to be funded with the
                           testnet's native currency (e.g., Sepolia ETH, Mumbai MATIC)
                           to cover gas fees for on-chain tests.
                           **ABSOLUTELY DO NOT USE A MAINNET PRIVATE KEY OR A KEY
                           ASSOCIATED WITH REAL FUNDS FOR THESE TESTS.**
                           For enhanced security, `evm_utils.py` prioritizes loading
                           the private key from the `EVM_PRIVATE_KEY` environment variable.
                           If set, it will override the `private_key` in `config.json`.
        *   `dex_routers`: Correct addresses of DEX routers on your chosen testnet(s)
                           (e.g., Uniswap V2 compatible routers).
        *   `token_addresses`: Correct contract addresses of ERC20 tokens (like WETH,
                           USDC, DAI testnet versions) on your testnet(s). Ensure the
                           test wallet has balances of these tokens if you intend to
                           test trades or approvals involving them.

2.  **Understanding On-Chain Tests:**
    *   Functions in this script prefixed with `test_approve_token` and
        `test_execute_trade` WILL attempt to send REAL transactions to the
        configured testnet if you confirm at the prompt.
    *   These transactions will spend testnet gas and interact with testnet
        smart contracts.
    *   Always double-check your `config.json` and environment to ensure you are
        interacting with the intended testnet and wallet.

3.  **Running the Tests:**
    *   You can run this script directly from your terminal:
        `python test_evm_utils.py`
    *   The script will guide you through available tests. For tests that perform
        on-chain actions, you will be prompted for confirmation.
    *   Examine the output carefully to ensure functions behave as expected and
        to debug any configuration or connectivity issues.

**NEVER RUN AUTOMATED TESTS OR THIS SCRIPT POINTING TO A MAINNET WALLET
WITH SIGNIFICANT REAL FUNDS WITHOUT EXTREME CAUTION, THOROUGH UNDERSTANDING
OF THE CODE, AND ACCEPTANCE OF ALL RISKS INVOLVED.**
This script is for development and testing convenience.
"""

import json
import time
import os # For environment variable access
from web3 import Web3

# Assuming evm_utils.py is in the same directory or Python path
from evm_utils import (
    load_config,
    connect_to_network,
    load_wallet,
    get_token_balance,
    approve_token,
    execute_trade,
    MINIMAL_ERC20_ABI # Used for some internal test logic if needed
)

# --- Test Functions ---

def test_load_config(config_path='config.json'):
    """Tests the load_config function from evm_utils.py."""
    print(f"\n--- Test: Load Configuration (from '{config_path}') ---")
    try:
        config = load_config(config_path)
        if config:
            print("Configuration loaded successfully:")
            # Print a subset for brevity, or specific keys you want to check
            print(f"  Networks found: {list(config.get('rpc_urls', {}).keys())}")
            print(f"  Default network (if set): {config.get('default_network')}")
            # Avoid printing sensitive content like private_key from config here.
            # The evm_utils.load_wallet function handles private_key loading with warnings.
            return config
        else:
            print("Failed to load config, or config is empty/invalid.")
            return None
    except Exception as e:
        print(f"An error occurred during config loading test: {type(e).__name__} - {e}")
        return None
    finally:
        print("--- Test Load Configuration Complete ---")


def test_connect_to_network(network_name, config_path='config.json'):
    """Tests the connect_to_network function."""
    print(f"\n--- Test: Connect to Network ('{network_name}') ---")
    w3_instance = None
    try:
        w3_instance = connect_to_network(network_name, config_path=config_path)
        if w3_instance and w3_instance.is_connected():
            print(f"Successfully connected to '{network_name}'.")
            print(f"  Chain ID: {w3_instance.eth.chain_id}")
            print(f"  Latest Block: {w3_instance.eth.block_number}")
        else:
            print(f"Failed to connect to '{network_name}' or connection is invalid.")
    except Exception as e:
        print(f"An error occurred while testing connect_to_network for '{network_name}': {type(e).__name__} - {e}")
    finally:
        print("--- Test Connect to Network Complete ---")
        return w3_instance


def test_load_wallet_from_config(network_name, config_path='config.json'):
    """Tests the load_wallet function using the private key from config or environment."""
    print(f"\n--- Test: Load Wallet for Network ('{network_name}') ---")
    print("    (This test uses the private key specified in config.json or EVM_PRIVATE_KEY env var)")
    wallet_account = None
    try:
        w3 = connect_to_network(network_name, config_path=config_path)
        if not w3:
            print(f"Cannot test load_wallet: Connection to '{network_name}' failed.")
            return None

        # The load_wallet function itself prints extensive warnings.
        wallet_account = load_wallet(w3, network_name, config_path=config_path)
        if wallet_account:
            print(f"Wallet loaded successfully via load_wallet for network '{network_name}'.")
            print(f"  Wallet Address: {wallet_account.address}")
        else:
            print(f"Failed to load wallet for network '{network_name}' using config/env private key.")
    except Exception as e:
        print(f"An error occurred during load_wallet test for '{network_name}': {type(e).__name__} - {e}")
    finally:
        print("--- Test Load Wallet Complete ---")
        return wallet_account


def test_get_token_balance_interactive(w3, network_name, default_wallet_address, config_path='config.json'):
    """Interactively tests get_token_balance for a specified token."""
    print(f"\n--- Test: Get Token Balance (on '{network_name}') ---")
    if not w3 or not w3.is_connected():
        print(f"Web3 not connected for '{network_name}'. Cannot get token balance.")
        return

    token_symbol = input(f"Enter token symbol to check balance for (e.g., ETH, MATIC, WETH, USDC) on '{network_name}': ").strip().upper()
    wallet_addr_to_check = input(f"Enter wallet address to check (or press Enter for default: {default_wallet_address}): ").strip()
    if not wallet_addr_to_check:
        wallet_addr_to_check = default_wallet_address

    if not Web3.is_address(wallet_addr_to_check):
        print(f"Invalid wallet address format: {wallet_addr_to_check}")
        print("--- Test Get Token Balance Aborted ---")
        return

    print(f"Fetching balance of {token_symbol} for {wallet_addr_to_check} on {network_name}...")
    balance = get_token_balance(w3, wallet_addr_to_check, token_symbol, network_name, config_path=config_path)

    if balance is not None:
        print(f"RESULT: Balance of {token_symbol} for {wallet_addr_to_check} on {network_name}: {balance} {token_symbol}")
    else:
        print(f"RESULT: Failed to get balance for {token_symbol}, or balance is zero/not found in config.")
    print("--- Test Get Token Balance Complete ---")


def test_approve_token_interactive(w3, wallet, network_name, config, config_path='config.json'):
    """Interactively tests the approve_token function (ON-CHAIN)."""
    print(f"\n--- Test: Approve Token for Spending (ON-CHAIN on '{network_name}') ---")
    print("="*60)
    print("WARNING: THIS WILL ATTEMPT AN ON-CHAIN TRANSACTION.")
    print("Ensure you are on a TESTNET and the wallet has gas (e.g., SepoliaETH).")
    print("="*60)

    if not w3 or not wallet:
        print("Web3 connection or wallet not available. Cannot run approve test.")
        return

    token_symbol = input(f"Enter ERC20 token symbol to approve (from your config for '{network_name}', e.g., WETH, USDC_TEST): ").strip().upper()

    # Check if native token, which doesn't need approval
    native_sym = config.get('token_addresses', {}).get(network_name, {}).get('NATIVE', 'ETH')
    if token_symbol == native_sym:
        print(f"{token_symbol} is the native token for this network and does not require approval. Test skipped.")
        print("--- Test Approve Token Complete ---")
        return

    if not config.get('token_addresses',{}).get(network_name,{}).get(token_symbol):
        print(f"Token {token_symbol} not found in config for network {network_name}. Cannot proceed.")
        print("--- Test Approve Token Complete ---")
        return

    spender_dex_key = input(f"Enter DEX key for spender (from config's 'dex_routers' for '{network_name}', e.g., uniswap_v2, quickswap): ").strip().lower()
    spender_address = config.get('dex_routers', {}).get(network_name, {}).get(spender_dex_key)

    if not spender_address:
        print(f"DEX router for key '{spender_dex_key}' not found in config for '{network_name}'.")
        print("--- Test Approve Token Complete ---")
        return

    amount_str = input(f"Enter amount of {token_symbol} to approve (e.g., 0.01, 100, or 'max' for maximum): ").strip().lower()

    approve_amount_float = None
    if amount_str != 'max':
        try:
            approve_amount_float = float(amount_str)
            if approve_amount_float <= 0:
                print("Approval amount must be positive.")
                print("--- Test Approve Token Complete ---")
                return
        except ValueError:
            print(f"Invalid amount: '{amount_str}'. Must be a number or 'max'.")
            print("--- Test Approve Token Complete ---")
            return

    print(f"\nConfirmation for ON-CHAIN Approval:")
    print(f"  Network : {network_name}")
    print(f"  Wallet  : {wallet.address}")
    print(f"  Token   : {token_symbol}")
    print(f"  Spender : {spender_dex_key} ({spender_address})")
    print(f"  Amount  : {amount_str} {token_symbol}")

    if input("Proceed with this ON-CHAIN approval? (yes/no): ").lower() != 'yes':
        print("Approval test cancelled by user.")
        print("--- Test Approve Token Complete ---")
        return

    print(f"Attempting to approve {amount_str} of {token_symbol} for spender {spender_address}...")
    success, tx_hash_or_msg = approve_token(
        w3, wallet, token_symbol, spender_address, network_name,
        amount_to_approve=approve_amount_float, # Pass None for 'max'
        config_path=config_path
    )

    if success:
        print(f"Approval call SUCCEEDED or allowance was sufficient. Result/TxHash: {tx_hash_or_msg}")
        # Optional: Verify allowance after a short delay
        time.sleep(config.get("blockchain_read_delay_seconds", 10)) # Wait for potential block confirmation
        token_address_str = config.get('token_addresses',{}).get(network_name,{}).get(token_symbol)
        if token_address_str:
            token_contract = w3.eth.contract(address=Web3.to_checksum_address(token_address_str), abi=MINIMAL_ERC20_ABI)
            current_allowance = token_contract.functions.allowance(wallet.address, Web3.to_checksum_address(spender_address)).call()
            decimals = token_contract.functions.decimals().call()
            print(f"  VERIFIED: Current allowance of {token_symbol} for {spender_dex_key} is now: {current_allowance / (10**decimals)}")
    else:
        print(f"Approval call FAILED. Details: {tx_hash_or_msg}")
    print("--- Test Approve Token Complete ---")


def test_execute_trade_interactive(w3, wallet, network_name, config, config_path='config.json'):
    """Interactively tests the execute_trade function (ON-CHAIN)."""
    print(f"\n--- Test: Execute Trade (ON-CHAIN on '{network_name}') ---")
    print("="*60)
    print("WARNING: THIS WILL ATTEMPT AN ON-CHAIN SWAP TRANSACTION.")
    print("Ensure you are on a TESTNET, the wallet has gas, and necessary token balances/approvals.")
    print("="*60)

    if not w3 or not wallet:
        print("Web3 connection or wallet not available. Cannot run trade test.")
        return

    dex_key = input(f"Enter DEX key (from config's 'dex_routers' for '{network_name}', e.g., uniswap_v2): ").strip().lower()
    if not config.get('dex_routers', {}).get(network_name, {}).get(dex_key):
        print(f"DEX key '{dex_key}' not found in config for '{network_name}'.")
        print("--- Test Execute Trade Aborted ---"); return

    input_token_sym = input(f"Enter INPUT token symbol (the token you want to SELL, e.g., WETH, USDC_TEST, or native like ETH): ").strip().upper()
    output_token_sym = input(f"Enter OUTPUT token symbol (the token you want to BUY, e.g., UNI_TEST, WETH): ").strip().upper()
    amount_in_str = input(f"Enter amount of {input_token_sym} to sell: ").strip()

    try:
        amount_in_float = float(amount_in_str)
        if amount_in_float <= 0:
            print("Trade amount must be positive."); print("--- Test Execute Trade Aborted ---"); return
    except ValueError:
        print(f"Invalid amount: '{amount_in_str}'."); print("--- Test Execute Trade Aborted ---"); return

    # Display current balances before trade for context
    print("\nChecking pre-trade balances (may take a moment)...")
    input_bal = get_token_balance(w3, wallet.address, input_token_sym, network_name, config_path)
    output_bal = get_token_balance(w3, wallet.address, output_token_sym, network_name, config_path)
    print(f"  Pre-trade {input_token_sym} balance: {input_bal if input_bal is not None else 'Error/Not found'}")
    print(f"  Pre-trade {output_token_sym} balance: {output_bal if output_bal is not None else 'Error/Not found'}")

    if input_bal is None or input_bal < amount_in_float:
        confirm_low_balance = input(f"Warning: Your balance of {input_token_sym} ({input_bal}) seems insufficient for trading {amount_in_float} {input_token_sym}. Proceed anyway? (yes/no): ")
        if confirm_low_balance.lower() != 'yes':
            print("Trade test cancelled by user due to low balance concern."); print("--- Test Execute Trade Complete ---"); return


    print(f"\nConfirmation for ON-CHAIN Trade:")
    print(f"  Network : {network_name}")
    print(f"  Wallet  : {wallet.address}")
    print(f"  DEX     : {dex_key}")
    print(f"  Action  : SELL {amount_in_float} {input_token_sym} FOR {output_token_sym}")

    if input("Proceed with this ON-CHAIN trade? (yes/no): ").lower() != 'yes':
        print("Trade test cancelled by user."); print("--- Test Execute Trade Complete ---"); return

    print(f"\nAttempting to execute trade: {amount_in_float} {input_token_sym} for {output_token_sym} via {dex_key}...")

    # The execute_trade function itself prints a detailed pre-trade summary.
    tx_hash, success, message = execute_trade(
        w3, wallet, network_name, dex_key,
        input_token_sym, output_token_sym, amount_in_float,
        config_path=config_path
    )

    if success:
        print(f"Trade execution SUCCEEDED! Message: {message}, Tx Hash: {tx_hash}")
    else:
        print(f"Trade execution FAILED. Message: {message}, Tx Hash (if any): {tx_hash}")

    # Display balances after trade attempt
    print("\nChecking post-trade balances (please wait for potential block confirmations)...")
    time.sleep(config.get("blockchain_read_delay_seconds", 15)) # Longer delay after trade
    input_bal_post = get_token_balance(w3, wallet.address, input_token_sym, network_name, config_path)
    output_bal_post = get_token_balance(w3, wallet.address, output_token_sym, network_name, config_path)
    print(f"  Post-trade {input_token_sym} balance: {input_bal_post if input_bal_post is not None else 'Error/Not found'}")
    print(f"  Post-trade {output_token_sym} balance: {output_bal_post if output_bal_post is not None else 'Error/Not found'}")

    print("--- Test Execute Trade Complete ---")


if __name__ == "__main__":
    print("="*70)
    print("EVM UTILITIES INTERACTIVE TEST SUITE")
    print("="*70)
    print("This script allows manual testing of functions in `evm_utils.py`.")
    print("Please ensure `config.json` is correctly set up for a TESTNET, and your")
    print("TESTNET wallet (from `private_key` or `EVM_PRIVATE_KEY` env var) is funded.")
    print("="*70)

    # Load master config once
    master_config = test_load_config()
    if not master_config:
        print("\nCRITICAL: `config.json` could not be loaded. Cannot proceed with tests.")
        exit(1)

    available_networks = list(master_config.get('rpc_urls', {}).keys())
    if not available_networks:
        print("No networks found in config.json/rpc_urls. Add network configurations to test.")
        exit(1)

    print(f"\nAvailable networks for testing: {', '.join(available_networks)}")

    # Determine default network, prioritize 'default_network' from config if set.
    chosen_network = master_config.get('default_network')
    if chosen_network and chosen_network not in available_networks:
        print(f"Warning: 'default_network' ('{chosen_network}') from config is not in available networks. Using first available.")
        chosen_network = None
    if not chosen_network:
        chosen_network = available_networks[0]

    user_network_choice = input(f"Enter network to test (or press Enter for default '{chosen_network}'): ").strip().lower()
    if user_network_choice and user_network_choice in available_networks:
        test_network = user_network_choice
    elif user_network_choice: # User entered something not in available_networks
        print(f"Network '{user_network_choice}' not found in config. Using '{chosen_network}'.")
        test_network = chosen_network
    else: # User pressed enter
        test_network = chosen_network

    print(f"\n--- Will run subsequent tests against network: '{test_network}' ---")

    # Establish Web3 connection and load wallet for this network (used by multiple tests)
    w3 = test_connect_to_network(test_network)
    active_wallet = None
    if w3:
        active_wallet = test_load_wallet_from_config(test_network)
    else:
        print(f"Skipping wallet-dependent tests as connection to '{test_network}' failed.")

    # Loop for interactive test selection
    while True:
        print("\nAvailable tests:")
        print("  1. Get Token Balance")
        if w3 and active_wallet: # Only show on-chain tests if wallet is loaded
            print("  2. Approve Token for Spender (ON-CHAIN)")
            print("  3. Execute Trade (ON-CHAIN)")
        print("  --------------------")
        print("  L. Load/Reload Full Config (test_load_config)")
        print("  C. Change Test Network / Reconnect")
        print("  Q. Quit")

        choice = input("Enter your choice: ").strip().lower()

        if choice == '1':
            default_addr = active_wallet.address if active_wallet else ""
            test_get_token_balance_interactive(w3, test_network, default_addr)
        elif choice == '2' and w3 and active_wallet:
            test_approve_token_interactive(w3, active_wallet, test_network, master_config)
        elif choice == '3' and w3 and active_wallet:
            test_execute_trade_interactive(w3, active_wallet, test_network, master_config)
        elif choice == 'l':
            master_config = test_load_config() # Reload
        elif choice == 'c':
            user_network_choice = input(f"Enter new network to test from {available_networks} (current: '{test_network}'): ").strip().lower()
            if user_network_choice and user_network_choice in available_networks:
                test_network = user_network_choice
                print(f"\n--- Switched to network: '{test_network}' ---")
                w3 = test_connect_to_network(test_network) # Reconnect
                if w3: active_wallet = test_load_wallet_from_config(test_network) # Reload wallet for new network
                else: active_wallet = None; print(f"Connection to new network '{test_network}' failed.")
            else:
                print(f"Invalid network choice or choice not in {available_networks}.")
        elif choice == 'q':
            print("Exiting test suite.")
            break
        else:
            print("Invalid choice. Please try again.")

    print("\n--- EVM Utilities Test Script Finished ---")
    print("Reminder: Always ensure responsible private key management and use TESTNETS for development.")
