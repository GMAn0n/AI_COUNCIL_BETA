"""
evm_utils.py: Utilities for interacting with EVM-compatible blockchains.

This module provides functions to connect to EVM networks, load wallets,
interact with ERC20 tokens (check balance, approve spending), and execute
trades on decentralized exchanges (DEXs) like Uniswap V2.

IMPORTANT SECURITY CONSIDERATIONS:
1.  PRIVATE KEY MANAGEMENT: This script handles private keys which grant
    full control over your crypto assets.
    - **NEVER hardcode private keys directly in scripts for production.**
    - **NEVER commit files containing private keys (e.g., `config.json` with a real key)
      to version control systems like Git.**
    - **STRONGLY PREFER using environment variables or dedicated secrets management
      services (e.g., HashiCorp Vault, AWS Secrets Manager, OS keyring) for
      storing and accessing private keys in any sensitive environment.**
    - The `config.json.example` file is a template. If you create `config.json`
      and use it for private keys (e.g., for testnet purposes), ensure it is
      added to your `.gitignore` file to prevent accidental public exposure.

2.  AUTOMATED TRADING RISKS: If these utilities are part of an automated
    trading system:
    - Automated systems can have bugs, be exploited, or react unexpectedly to
      market conditions, potentially leading to significant financial loss.
    - **ALWAYS begin testing on a TESTNET** (e.g., Sepolia for Ethereum,
      Polygon Mumbai) to thoroughly validate your logic and configurations.
    - Use a **dedicated, isolated wallet with limited funds** specifically for
      the bot, especially if deploying to a mainnet. Only fund it with amounts
      you are entirely prepared to lose.
    - Understand the smart contracts you are interacting with (DEX routers,
      token contracts). Verify their legitimacy and be aware of their specific
      mechanisms (e.g., fees on transfer for some tokens).
    - Be mindful of network conditions like slippage, gas fees, and congestion,
      as these can significantly impact trade outcomes.

3.  NO LIABILITY: The authors or contributors of this software provide it "as-is",
    without any warranty of any kind, express or implied. They are NOT
    responsible for any financial losses or other damages you may incur through
    the use of this software. Use this software entirely at your own risk.
"""
import json
import os
import time
from web3 import Web3
from datetime import datetime

# Minimal ABI for ERC20 token interactions (balanceOf, decimals, approve, allowance)
MINIMAL_ERC20_ABI = [
    {"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"balance","type":"uint256"}],"type":"function"},
    {"constant":True,"inputs":[],"name":"decimals","outputs":[{"name":"","type":"uint8"}],"type":"function"},
    {"constant":False,"inputs":[{"name":"_spender","type":"address"},{"name":"_value","type":"uint256"}],"name":"approve","outputs":[{"name":"","type":"bool"}],"type":"function"},
    {"constant":True,"inputs":[{"name":"_owner","type":"address"},{"name":"_spender","type":"address"}],"name":"allowance","outputs":[{"name":"remaining","type":"uint256"}],"type":"function"},
]

# Minimal ABI for Uniswap V2 compatible router (for swaps and getting amounts)
UNISWAP_V2_ROUTER_ABI = [
    {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactTokensForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"nonpayable","type":"function"},
    {"inputs":[{"internalType":"uint256","name":"amountOutMin","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"},{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"deadline","type":"uint256"}],"name":"swapExactETHForTokens","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"payable","type":"function"},
    {"inputs":[{"internalType":"uint256","name":"amountIn","type":"uint256"},{"internalType":"address[]","name":"path","type":"address[]"}],"name":"getAmountsOut","outputs":[{"internalType":"uint256[]","name":"amounts","type":"uint256[]"}],"stateMutability":"view","type":"function"}
]

def load_config(config_path='config.json'):
    """
    Loads configuration settings from a JSON file.

    Args:
        config_path (str): Path to the configuration file.

    Returns:
        dict or None: Loaded configuration as a dictionary, or None if loading fails.
    """
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        # print(f"Configuration loaded from {config_path}") # Can be noisy, uncomment for debugging
        return config
    except FileNotFoundError:
        print(f"Error: Configuration file '{config_path}' not found.")
        return None
    except json.JSONDecodeError as e:
        print(f"Error: Could not decode JSON from '{config_path}'. Invalid JSON format: {e}")
        return None
    except Exception as e:
        print(f"Error loading configuration from '{config_path}': {type(e).__name__} - {e}")
        return None


def connect_to_network(network_name, config_path='config.json'):
    """
    Connects to an EVM network using settings from the configuration file.

    Args:
        network_name (str): The key for the network in the config (e.g., "sepolia").
        config_path (str): Path to the configuration file.

    Returns:
        Web3 or None: A Web3 instance connected to the network, or None if connection fails.
    """
    config = load_config(config_path)
    if not config:
        return None

    rpc_urls = config.get('rpc_urls', {})
    chain_ids = config.get('chain_ids', {})

    if network_name not in rpc_urls:
        print(f"Error: RPC URL for network '{network_name}' not found in configuration.")
        return None
    if network_name not in chain_ids:
        print(f"Error: Chain ID for network '{network_name}' not found in configuration.")
        return None

    rpc_url = rpc_urls[network_name]
    expected_chain_id = chain_ids[network_name]

    try:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        if w3.is_connected():
            current_chain_id = w3.eth.chain_id
            if current_chain_id == expected_chain_id:
                print(f"Successfully connected to network: {network_name} (Chain ID: {current_chain_id})")
                return w3
            else:
                print(f"Error: Connected to network '{network_name}', but chain ID mismatch! Expected {expected_chain_id}, got {current_chain_id}.")
                return None
        else:
            print(f"Error: Failed to connect to network: {network_name} using RPC URL: {rpc_url}")
            return None
    except Exception as e:
        print(f"Error connecting to network '{network_name}': {type(e).__name__} - {e}")
        return None

def load_wallet(web3_instance, network_name, config_path='config.json'):
    """
    Loads a wallet account from a private key, typically stored in the configuration file.
    Includes prominent warnings about private key security.

    Args:
        web3_instance (Web3): Active Web3 instance.
        network_name (str): Name of the network (for logging purposes).
        config_path (str): Path to the configuration file.

    Returns:
        LocalAccount or None: The loaded wallet account object, or None if loading fails.
    """
    print("\n" + "="*80)
    print("SECURITY WARNING: ATTEMPTING TO LOAD WALLET FROM PRIVATE KEY IN CONFIGURATION FILE.")
    print("This method is suitable for DEVELOPMENT and TESTING with TESTNETS ONLY.")
    print("For PRODUCTION or MAINNET operations, consider these more secure options:")
    print("  1. Store the private key in an ENVIRONMENT VARIABLE.")
    print("  2. Use a dedicated SECRETS MANAGEMENT SYSTEM (e.g., HashiCorp Vault, OS Keyring).")
    print("NEVER commit your actual private key to any version control system (e.g., Git).")
    print("If `config.json` contains a real private key, ensure it's in your `.gitignore` file.")
    print("YOU ARE SOLELY RESPONSIBLE FOR THE SECURITY OF YOUR PRIVATE KEYS AND ANY ASSOCIATED FUNDS.")
    print("="*80 + "\n")

    if not web3_instance:
        print("Error: Web3 instance is not available. Cannot load wallet.")
        return None

    config = load_config(config_path)
    if not config:
        print("Error: Configuration not loaded. Cannot retrieve private key to load wallet.")
        return None

    private_key = os.getenv('EVM_PRIVATE_KEY') # Prioritize environment variable
    source = "environment variable"
    if not private_key:
        private_key = config.get('private_key')
        source = f"config file ('{config_path}')"
        if not private_key:
            print(f"Error: 'private_key' not found in configuration file ('{config_path}') or EVM_PRIVATE_KEY environment variable.")
            return None

    if private_key == "YOUR_PRIVATE_KEY_HERE_DO_NOT_COMMIT_THIS_FILE_WITH_REAL_KEYS":
        print("CRITICAL WARNING: Attempting to use the placeholder private key.")
        print("                 This key is for example purposes only and will not work for real transactions.")
        print("                 Replace it with a valid TESTNET private key (preferably via environment variable).")
        return None # Prevent loading of the placeholder key

    try:
        account = web3_instance.eth.account.from_key(private_key)
        print(f"Wallet loaded successfully from {source}.")
        print(f"Address: {account.address} (Network: {network_name})")
        return account
    except ValueError as ve:
        print(f"Error loading wallet from private key (source: {source}): {ve}.")
        print("Ensure the private key is a valid 64-character hexadecimal string (optionally 0x-prefixed).")
        return None
    except Exception as e:
        print(f"An unexpected error occurred while loading wallet (source: {source}): {type(e).__name__} - {e}")
        return None


def get_token_balance(web3_instance, wallet_address, token_symbol, network_name, config_path='config.json'):
    """
    Gets the balance of a specified token (native or ERC20) for a given wallet address.

    Args:
        web3_instance (Web3): Active Web3 instance.
        wallet_address (str): The address to check the balance for.
        token_symbol (str): The symbol of the token (e.g., "ETH", "MATIC", "USDC").
        network_name (str): The network key from the config.
        config_path (str): Path to the configuration file.

    Returns:
        Decimal or None: The token balance (adjusted for decimals), or None if an error occurs.
    """
    if not web3_instance:
        print("Error (get_token_balance): Web3 instance is not available.")
        return None
    if not wallet_address:
        print("Error (get_token_balance): Wallet address is not provided.")
        return None

    config = load_config(config_path)
    if not config: return None

    token_info_for_network = config.get('token_addresses', {}).get(network_name, {})
    native_currency_symbol = token_info_for_network.get("NATIVE", "ETH") # Default to ETH if not specified for network

    try:
        checksum_wallet_address = Web3.to_checksum_address(wallet_address)
    except ValueError:
        print(f"Error (get_token_balance): Invalid wallet address format: {wallet_address}")
        return None

    if token_symbol.upper() == native_currency_symbol.upper(): # Native currency balance
        try:
            balance_wei = web3_instance.eth.get_balance(checksum_wallet_address)
            balance_ether = Web3.from_wei(balance_wei, 'ether')
            # print(f"Native balance ({token_symbol}) for {checksum_wallet_address}: {balance_ether} {token_symbol.upper()}")
            return balance_ether
        except Exception as e:
            print(f"Error getting native token ({token_symbol}) balance for {checksum_wallet_address}: {e}")
            return None

    # ERC20 token balance
    token_address_str = token_info_for_network.get(token_symbol)
    if not token_address_str:
        print(f"Error (get_token_balance): Token symbol '{token_symbol}' not found in config for network '{network_name}'.")
        return None

    try:
        token_address = Web3.to_checksum_address(token_address_str)
        token_contract = web3_instance.eth.contract(address=token_address, abi=MINIMAL_ERC20_ABI)

        balance_raw = token_contract.functions.balanceOf(checksum_wallet_address).call()
        decimals = token_contract.functions.decimals().call()

        balance_adjusted = balance_raw / (10**decimals)
        # print(f"ERC20 balance ({token_symbol}) for {checksum_wallet_address}: {balance_adjusted} {token_symbol}")
        return balance_adjusted
    except ValueError: # For checksum address error
        print(f"Error (get_token_balance): Invalid token contract address for {token_symbol}: {token_address_str}")
        return None
    except Exception as e:
        print(f"Error getting ERC20 token ({token_symbol}) balance for {checksum_wallet_address}: {type(e).__name__} - {e}")
        return None


def approve_token(web3_instance, wallet_account, token_symbol, spender_address, network_name,
                  amount_to_approve=None, config_path='config.json'):
    """
    Approves a spender to spend a specified amount of an ERC20 token on behalf of the wallet owner.

    Args:
        web3_instance (Web3): Active Web3 instance.
        wallet_account (LocalAccount): Loaded wallet account of the approver.
        token_symbol (str): Symbol of the ERC20 token to approve.
        spender_address (str): Address of the contract/wallet to grant spending approval to.
        network_name (str): Network key from the config.
        amount_to_approve (float, optional): The amount of the token to approve (in standard units, not wei).
                                             If None, approves the maximum possible amount (effectively infinite).
        config_path (str): Path to the configuration file.

    Returns:
        tuple (bool, str or None): (True, transaction_hash) if successful or allowance already sufficient.
                                   (False, error_message_or_tx_hash) if failed.
    """
    if not web3_instance or not wallet_account:
        print("Error (approve_token): Web3 instance or wallet account is not available.")
        return False, "Web3 instance or wallet account missing."

    config = load_config(config_path)
    if not config: return False, "Configuration not loaded for approve_token."

    token_addresses_on_network = config.get('token_addresses', {}).get(network_name, {})
    chain_id = config.get('chain_ids', {}).get(network_name)

    if not chain_id:
        return False, f"Chain ID for network '{network_name}' not found."

    token_address_str = token_addresses_on_network.get(token_symbol)
    if not token_address_str:
         # Check if it's a native token, which doesn't need approval.
        native_sym = token_addresses_on_network.get('NATIVE', 'ETH')
        if token_symbol.upper() == native_sym.upper():
            print(f"Info (approve_token): {token_symbol} is the native token for {network_name} and does not require approval.")
            return True, "Native token, no approval needed."
        return False, f"Token symbol '{token_symbol}' not found in config for network '{network_name}'."

    try:
        token_address = Web3.to_checksum_address(token_address_str)
        spender_checksum_address = Web3.to_checksum_address(spender_address)
    except ValueError as ve:
        return False, f"Invalid address format for token or spender: {ve}"

    try:
        token_contract = web3_instance.eth.contract(address=token_address, abi=MINIMAL_ERC20_ABI)
        decimals = token_contract.functions.decimals().call()

        current_allowance_raw = token_contract.functions.allowance(wallet_account.address, spender_checksum_address).call()

        amount_raw_to_approve = 2**256 - 1 # Default to max approval
        display_amount = "maximum (infinite)"
        if amount_to_approve is not None:
            amount_raw_to_approve = int(float(amount_to_approve) * (10**decimals))
            display_amount = f"{amount_to_approve} {token_symbol}"
            if current_allowance_raw >= amount_raw_to_approve:
                print(f"Sufficient allowance ({current_allowance_raw / (10**decimals)} {token_symbol}) already exists for {spender_address} to spend {display_amount}.")
                return True, "Allowance already sufficient."

        print(f"Attempting to approve {display_amount} (raw: {amount_raw_to_approve}) for spender {spender_checksum_address} to spend {token_symbol} on {network_name}...")

        tx_params = {
            'from': wallet_account.address,
            'nonce': web3_instance.eth.get_transaction_count(wallet_account.address),
            'gasPrice': web3_instance.eth.gas_price,
            'chainId': chain_id
        }

        unsigned_approve_tx = token_contract.functions.approve(spender_checksum_address, amount_raw_to_approve).build_transaction(tx_params)

        try:
            estimated_gas = web3_instance.eth.estimate_gas(unsigned_approve_tx)
            unsigned_approve_tx['gas'] = int(estimated_gas * 1.25) # 25% buffer
        except Exception as e:
            print(f"Warning: Gas estimation failed for approval: {e}. Using fallback gas limit (300k).")
            unsigned_approve_tx['gas'] = 300000

        signed_tx = web3_instance.eth.account.sign_transaction(unsigned_approve_tx, wallet_account.key)
        tx_hash_bytes = web3_instance.eth.send_raw_transaction(signed_tx.rawTransaction)
        tx_hash = Web3.to_hex(tx_hash_bytes)
        print(f"Approval transaction sent. Hash: {tx_hash}")

        print(f"Waiting for approval transaction receipt (Tx: {tx_hash}, timeout ~2 mins)...")
        tx_receipt = web3_instance.eth.wait_for_transaction_receipt(tx_hash_bytes, timeout=120)

        if tx_receipt.status == 1:
            print(f"Approval successful for {token_symbol}. Tx: {tx_hash}")
            return True, tx_hash
        else:
            print(f"Approval transaction failed on-chain for {token_symbol}. Tx: {tx_hash}. Receipt: {tx_receipt}")
            return False, tx_hash
    except Exception as e:
        print(f"Error during token approval for {token_symbol}: {type(e).__name__} - {e}")
        return False, f"Exception during approval: {e}"


def execute_trade(web3_instance, wallet_account, network_name, dex_name,
                  input_token_symbol, output_token_symbol, amount_in,
                  config_path='config.json', slippage_tolerance=0.01):
    """
    Executes a trade on a DEX, handling native-to-ERC20, ERC20-to-native, and ERC20-to-ERC20 swaps.
    Includes pre-trade summary and attempts token approval if needed for ERC20 input.

    Args:
        web3_instance (Web3): Active Web3 instance.
        wallet_account (LocalAccount): Loaded wallet account executing the trade.
        network_name (str): Network key from the config.
        dex_name (str): DEX key from the config (e.g., "uniswap_v2").
        input_token_symbol (str): Symbol of the token to sell.
        output_token_symbol (str): Symbol of the token to buy.
        amount_in (float): Amount of the input_token to sell (in standard units).
        config_path (str): Path to the configuration file.
        slippage_tolerance (float): Allowed slippage (e.g., 0.01 for 1%).

    Returns:
        tuple (str or None, bool, str): (transaction_hash, success_status, message)
    """
    tx_hash_str = None

    if not web3_instance or not wallet_account:
        return tx_hash_str, False, "Web3 instance or wallet account missing for execute_trade."

    config = load_config(config_path)
    if not config: return tx_hash_str, False, "Configuration not loaded for execute_trade."

    # --- Configuration Validation ---
    chain_id = config.get('chain_ids', {}).get(network_name)
    if not chain_id: return tx_hash_str, False, f"Chain ID for network '{network_name}' not found."

    dex_router_address_str = config.get('dex_routers', {}).get(network_name, {}).get(dex_name)
    if not dex_router_address_str: return tx_hash_str, False, f"DEX router '{dex_name}' not found for network '{network_name}'."
    dex_router_address = Web3.to_checksum_address(dex_router_address_str)

    token_info_net = config.get('token_addresses', {}).get(network_name, {})
    native_sym = token_info_net.get("NATIVE", "ETH")
    weth_address_str = token_info_net.get("WETH") # WETH/WMATIC etc.

    is_input_native = (input_token_symbol.upper() == native_sym.upper())
    is_output_native = (output_token_symbol.upper() == native_sym.upper())

    input_token_address_str = token_info_net.get(input_token_symbol)
    output_token_address_str = token_info_net.get(output_token_symbol)

    if not is_input_native and not input_token_address_str:
        return tx_hash_str, False, f"Input ERC20 token '{input_token_symbol}' address not found for '{network_name}'."
    if not is_output_native and not output_token_address_str:
        return tx_hash_str, False, f"Output ERC20 token '{output_token_symbol}' address not found for '{network_name}'."
    if (is_input_native or is_output_native) and not weth_address_str:
        return tx_hash_str, False, f"WETH address not configured for '{network_name}', required for trades involving native currency."

    # --- Amount and Path Setup ---
    amount_in_wei = 0
    input_decimals = 18 # Default for native
    input_token_for_path = ""

    if is_input_native:
        amount_in_wei = Web3.to_wei(amount_in, 'ether')
        input_token_for_path = Web3.to_checksum_address(weth_address_str)
    else:
        input_address = Web3.to_checksum_address(input_token_address_str)
        input_contract = web3_instance.eth.contract(address=input_address, abi=MINIMAL_ERC20_ABI)
        try:
            input_decimals = input_contract.functions.decimals().call()
            amount_in_wei = int(float(amount_in) * (10**input_decimals))
        except Exception as e:
            return tx_hash_str, False, f"Could not get decimals for input token {input_token_symbol}: {e}"
        input_token_for_path = input_address

    if amount_in_wei <= 0: return tx_hash_str, False, "Input amount must be positive."

    output_token_for_path = ""
    if is_output_native:
        output_token_for_path = Web3.to_checksum_address(weth_address_str)
    else:
        output_token_for_path = Web3.to_checksum_address(output_token_address_str)

    path = [input_token_for_path, output_token_for_path]
    if input_token_for_path == output_token_for_path : # e.g. WETH -> WETH or Native -> WETH when WETH is output
        if not (is_input_native and output_token_symbol.upper() == "WETH"): # Allow ETH -> WETH wrapping style path
             if not (is_output_native and input_token_symbol.upper() == "WETH"): # Allow WETH -> ETH unwrapping style path
                return tx_hash_str, False, f"Trade path involves the same input and output token ({input_token_symbol}), this is usually wrapping/unwrapping or an error."


    print(f"Trade path: {input_token_symbol} -> {output_token_symbol} via [{' -> '.join(path)}]")
    dex_contract = web3_instance.eth.contract(address=dex_router_address, abi=UNISWAP_V2_ROUTER_ABI)

    # --- Estimate Output & Deadline ---
    try:
        amounts_out_list = dex_contract.functions.getAmountsOut(amount_in_wei, path).call()
        estimated_out_wei = amounts_out_list[-1]
        min_out_wei = int(estimated_out_wei * (1 - slippage_tolerance))
        if min_out_wei <= 0:
            return tx_hash_str, False, "Estimated minimum output is zero or less. Check liquidity or input amount."
    except Exception as e:
        return tx_hash_str, False, f"Could not estimate output (getAmountsOut failed for path {path}): {type(e).__name__} - {e}"

    deadline = int(time.time()) + (20 * 60) # 20 minutes

    # --- Approve ERC20 Input Token (if not native) ---
    if not is_input_native:
        print(f"ERC20 input: Ensuring {input_token_symbol} is approved for DEX router {dex_router_address}...")
        approve_ok, approve_msg_or_hash = approve_token(
            web3_instance, wallet_account, input_token_symbol, dex_router_address,
            network_name, amount_in, config_path
        )
        if not approve_ok:
            return approve_msg_or_hash, False, f"Approval for {input_token_symbol} failed: {approve_msg_or_hash}"
        print(f"Approval for {input_token_symbol} confirmed or already sufficient. Details: {approve_msg_or_hash}")

    # --- Prepare and Log Trade Details ---
    output_decimals = 18 # Default
    try:
        if not is_output_native:
            out_contract = web3_instance.eth.contract(address=output_token_for_path, abi=MINIMAL_ERC20_ABI)
            output_decimals = out_contract.functions.decimals().call()
    except Exception: pass # Use default if decimals fetch fails

    print("\n" + "="*80)
    print(f"         PENDING ON-CHAIN TRADE ON {network_name.upper()} VIA {dex_name.upper()}")
    print("="*80)
    print(f"  Trader Wallet   : {wallet_account.address}")
    print(f"  Input           : {amount_in:.8f} {input_token_symbol}")
    print(f"  Output Estimate : {(estimated_out_wei / (10**output_decimals)):.8f} {output_token_symbol}")
    print(f"  Min. Acceptable : {(min_out_wei / (10**output_decimals)):.8f} {output_token_symbol} (Slippage: {slippage_tolerance*100:.2f}%)")
    print(f"  Route Path      : {' -> '.join(path)}")
    print(f"  Deadline        : {datetime.fromtimestamp(deadline).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("="*80 + "\n")
    # Consider adding a brief `time.sleep(3)` here if user needs to see this before logs continue rapidly.

    # --- Build and Send Transaction ---
    tx_params = {'from': wallet_account.address, 'gasPrice': web3_instance.eth.gas_price,
                 'nonce': web3_instance.eth.get_transaction_count(wallet_account.address), 'chainId': chain_id}

    if is_input_native:
        swap_function_call = dex_contract.functions.swapExactETHForTokens(min_out_wei, path, wallet_account.address, deadline)
        tx_params['value'] = amount_in_wei
    else:
        swap_function_call = dex_contract.functions.swapExactTokensForTokens(amount_in_wei, min_out_wei, path, wallet_account.address, deadline)
        tx_params['value'] = 0 # For ERC20 token swaps, value is 0

    try:
        unsigned_tx = swap_function_call.build_transaction(tx_params)
        try:
            estimated_gas = web3_instance.eth.estimate_gas(unsigned_tx)
            unsigned_tx['gas'] = int(estimated_gas * 1.3) # 30% buffer for gas, adjust as needed
            print(f"Gas estimated: {estimated_gas}, using gas limit: {unsigned_tx['gas']}")
        except Exception as gas_est_ex:
            err_msg = f"Gas estimation failed: {type(gas_est_ex).__name__} - {gas_est_ex}."
            print(f"CRITICAL: {err_msg} This often indicates a pre-send revert condition (e.g., liquidity, bad path).")
            return tx_hash_str, False, err_msg

        signed_tx = web3_instance.eth.account.sign_transaction(unsigned_tx, wallet_account.key)
        tx_bytes = web3_instance.eth.send_raw_transaction(signed_tx.rawTransaction)
        tx_hash_str = Web3.to_hex(tx_bytes)
        print(f"Swap transaction sent. Hash: {tx_hash_str}")

        print(f"Waiting for swap transaction receipt (Tx: {tx_hash_str}, timeout ~5 mins)...")
        tx_receipt = web3_instance.eth.wait_for_transaction_receipt(tx_bytes, timeout=300) # Use tx_bytes here

        if tx_receipt.status == 1:
            msg = f"Swap successful. Tx: {tx_hash_str}"
            print(msg)
            # Actual amount out can be parsed from logs here if needed for more precision.
            return tx_hash_str, True, msg
        else:
            msg = f"Swap transaction failed on-chain. Status: {tx_receipt.get('status')}. Tx: {tx_hash_str}. Receipt: {tx_receipt}"
            print(msg)
            return tx_hash_str, False, msg

    except Exception as e:
        err_type = type(e).__name__
        err_detail = str(e).lower()
        # Common error substrings to make messages more user-friendly
        if "insufficient funds" in err_detail: specific_msg = "Insufficient funds for gas or token amount."
        elif "allowance" in err_detail: specific_msg = "Insufficient token allowance."
        elif "reverted" in err_detail or "execution reverted" in err_detail : specific_msg = "Transaction reverted (check slippage, deadline, liquidity, or token contract issues)."
        elif "nonce too low" in err_detail: specific_msg = "Nonce too low. Retry may be needed."
        elif "gas" in err_detail: specific_msg = "Gas issue (e.g., intrinsic gas too low, out of gas)."
        else: specific_msg = f"Trade execution error: {err_type} - {e}"

        print(f"Error: {specific_msg}")
        return tx_hash_str, False, specific_msg # tx_hash_str may or may not be set here

if __name__ == '__main__':
    print("\n" + "="*70)
    print(" evm_utils.py - Example Usage & Manual Testing Section")
    print("="*70)
    print("This section is for demonstrating and manually testing the functions above.")
    print("Ensure `config.json` is correctly set up for a TESTNET before running on-chain tests.")

    # --- Example Calls (uncomment and customize to test) ---
    # print("\n--- Running Examples ---")
    # test_config = load_config()
    # if test_config:
    #     default_network = test_config.get('default_network', 'sepolia') # Fallback to sepolia

    #     # Test Connection
    #     # w3_instance = connect_to_network(default_network)

    #     # Test Wallet Loading (Requires Web3 Instance)
    #     # if w3_instance:
    #     #     test_wallet = load_wallet(w3_instance, default_network)

    #     # Test Get Balance (Requires Web3 Instance & Wallet Address)
    #     # if w3_instance and test_wallet:
    #     #     native_sym = test_config.get('token_addresses',{}).get(default_network,{}).get('NATIVE','ETH')
    #     #     get_token_balance(w3_instance, test_wallet.address, native_sym, default_network)
    #     #     # Example for an ERC20 - replace "WETH" with a token in your config
    #     #     get_token_balance(w3_instance, test_wallet.address, "WETH", default_network)

    #     # Test Approve Token (ON-CHAIN - BE CAREFUL)
    #     # if w3_instance and test_wallet:
    #     #     print("\n--- Example: Approve Token (ON-CHAIN - requires user confirmation in test script) ---")
    #     #     # Customize: network, token symbol, spender (DEX router key from config), amount
    #     #     # test_approve_token(w3_instance, test_wallet, "UNI_TEST", "uniswap_v2", default_network, amount_to_approve=0.01)

    #     # Test Execute Trade (ON-CHAIN - BE CAREFUL)
    #     # if w3_instance and test_wallet:
    #     #     print("\n--- Example: Execute Trade (ON-CHAIN - requires user confirmation in test script) ---")
    #     #     # Customize: network, dex_name, input_token, output_token, amount_in
    #     #     # Example: Swap 0.0001 Native ETH for UNI_TEST token
    #     #     native_sym_trade = test_config.get('token_addresses',{}).get(default_network,{}).get('NATIVE','ETH')
    #     #     # test_execute_trade(w3_instance, test_wallet, default_network, "uniswap_v2",
    #     #     #                    native_sym_trade, "UNI_TEST", 0.0001)
    # else:
    #     print("Cannot run examples: `config.json` failed to load.")

    print("\n--- End of evm_utils.py example usage ---")
    pass
