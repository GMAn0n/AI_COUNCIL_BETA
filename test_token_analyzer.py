"""
test_token_analyzer.py: Test script for token_analyzer.py.

This script allows manual testing of fetching token security reports from GoPlus Security
and trading pair data from DexScreener. It's essential for verifying that the
`token_analyzer.py` module is functioning correctly with the respective APIs.

**Setup Requirements:**
1.  **`config.json` File:**
    *   Ensure a `config.json` file exists in the project root (you can copy from
        `config.json.example`).
    *   **GoPlus API Key:** For `fetch_token_security_report` tests to work, you MUST add
        your GoPlus Security API key to `config.json` under:
        `"token_analysis_apis": { "goplus_security": { "api_key": "YOUR_ACTUAL_KEY" } }`
        Alternatively, set the `GOPLUS_API_KEY` environment variable (which takes precedence).
        Obtain a key from `https://gopluslabs.io/`.
    *   DexScreener API calls for public pair data do not strictly require an API key at present.

2.  **Internet Connection:** Required to make calls to external APIs.

**Running Tests:**
*   Execute this script from your terminal: `python test_token_analyzer.py`
*   The script will run predefined test cases and print formatted outputs.
*   Review the outputs to confirm data is fetched and parsed as expected.
*   A placeholder for user-defined tests is included for custom scenarios.
*   A manual test outline for `ai_agent.py` integration is also printed for reference.
"""
import json
import os
import time
from typing import List, Optional

from token_analyzer import fetch_token_security_report, fetch_pairs_for_token, TokenSecurityReport, PairReport

# --- Helper Functions for Printing Test Outputs ---

def print_security_report(report: Optional[TokenSecurityReport]):
    """Prints a formatted summary of the TokenSecurityReport."""
    if not report:
        print("  No security report data or report is None.")
        return
    print(f"  Token Address: {report['token_address']} (Chain ID: {report['chain_id']})")
    print(f"  Retrieved: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(report['retrieved_at']))}")
    print(f"  Honeypot Risk: {report.get('is_honeypot')}")
    print(f"  Open Source: {report.get('is_open_source')}")
    print(f"  Buy Tax: {report.get('buy_tax')*100 if report.get('buy_tax') is not None else 'N/A'}%")
    print(f"  Sell Tax: {report.get('sell_tax')*100 if report.get('sell_tax') is not None else 'N/A'}%")
    print(f"  Owner Address: {report.get('owner_address', 'N/A')}")
    print(f"  Total LP USD: ${report.get('total_lp_liquidity_usd', 0):,.2f}")

    warnings = report.get('warnings', [])
    if warnings:
        print(f"  Warnings ({len(warnings)}):")
        for warning in warnings[:3]: # Print first 3 warnings for brevity
            print(f"    - {warning}")
        if len(warnings) > 3: print(f"    ... and {len(warnings)-3} more.")

    remarks = report.get('remarks', [])
    if remarks:
        print(f"  Remarks ({len(remarks)}):")
        for remark in remarks[:3]:
            print(f"    - {remark}")
        if len(remarks) > 3: print(f"    ... and {len(remarks)-3} more.")

    # LP Holders: Print summary of top few for brevity in tests
    lp_holders = report.get('top_lp_holders', [])
    print(f"  Top LP Holders ({len(lp_holders)} found):")
    for i, holder in enumerate(lp_holders[:2]): # Show first 2
        print(f"    Holder {i+1}: {holder['address']} ({holder['percent_of_total_lp']:.2f}%, Locked: {holder['is_locked']})")
    if len(lp_holders) > 2: print("    ...")
    # To see full raw response details, you'd inspect 'raw_goplus_response' in a debugger or print it.
    # print(f"  Raw GoPlus Keys: {list(report.get('raw_goplus_response', {}).keys())}")


def print_pair_reports(reports: Optional[List[PairReport]], token_address: str):
    """Prints a formatted summary of fetched PairReports."""
    if not reports:
        print(f"  No pair reports found or list is None for token {token_address}.")
        return
    print(f"  Pair Reports for {token_address} (Found: {len(reports)}, Displaying newest first):")
    for i, report_item in enumerate(reports): # `max_pairs` in fetch_pairs_for_token limits this
        created_at_str = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(report_item['pair_created_at'])) if report_item.get('pair_created_at') else 'N/A'
        print(f"    Pair {i+1}: {report_item.get('pair_address', 'N/A')}")
        print(f"      Base Token: {report_item.get('base_token_address', 'N/A')}")
        print(f"      Quote Token: {report_item.get('quote_token_address', 'N/A')}")
        print(f"      Chain: {report_item.get('chain_id', 'N/A')}, DEX: {report_item.get('dex_id', 'N/A')}")
        print(f"      Price USD: ${report_item.get('price_usd', 0):,.4f}")
        print(f"      Liquidity USD: ${report_item.get('liquidity_usd', 0):,.2f}")
        print(f"      Volume (24h): ${report_item.get('volume_h24', 0):,.2f}")
        print(f"      Pair Created At: {created_at_str}")
        print(f"      DexScreener URL: {report_item.get('url', 'N/A')}")
        if i >= 4 and len(reports) > 5 : # Limit printed pairs for very long lists
            print(f"    ... and {len(reports) - (i+1)} more pairs.")
            break


if __name__ == "__main__":
    print("="*70)
    print("Token Analyzer Test Suite")
    print("="*70)
    print("This script tests fetching and parsing data from GoPlus Security and DexScreener.")
    print("A `config.json` file (copied from `config.json.example`) is needed.")
    print("A valid GoPlus API key in `config.json` or `GOPLUS_API_KEY` env var is required for security tests.")
    print("Internet access is required for all API calls.")

    # Ensure a dummy config exists if a real one is missing, to prevent FileNotFoundError
    # during token_analyzer._load_analyzer_config if it's called by test setup.
    # The actual API calls will still fail gracefully if the key within is invalid/placeholder.
    if not os.path.exists('config.json'):
        print("\nWARNING: `config.json` not found. Creating a dummy one.")
        print("         API calls requiring keys (like GoPlus) will likely fail or use placeholders.")
        print("         Please create a real `config.json` from `config.json.example` and add your API keys.")
        try:
            with open('config.json', 'w') as f_dummy:
                json.dump({
                    "token_analysis_apis": {
                        "goplus_security": {
                            "api_key": "YOUR_GOPLUS_API_KEY_PLACEHOLDER",
                            "api_secret": "YOUR_GOPLUS_SECRET_PLACEHOLDER"
                        }
                    }
                }, f_dummy, indent=2)
        except Exception as e:
            print(f"Could not create dummy config.json: {e}")


    # --- Test Cases ---
    # GoPlus uses numeric chain IDs (as strings). DexScreener uses string chain names.
    # These are mapped in ai_agent.py's CHAIN_NAME_TO_ID_MAP, but token_analyzer.py functions
    # expect the direct API-specific chain identifiers.

    # Case 1: WETH on Ethereum (generally safe, well-known token)
    print("\n--- Test Case 1: WETH on Ethereum ---")
    weth_addr = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    goplus_eth_id = "1"          # GoPlus chain_id for Ethereum
    dexscreener_eth_name = "ethereum" # DexScreener chain name for Ethereum

    print(f"\nFetching GoPlus Security report for WETH ({weth_addr}) on chain ID '{goplus_eth_id}'...")
    sec_report_weth = fetch_token_security_report(weth_addr, goplus_eth_id)
    print_security_report(sec_report_weth)

    print(f"\nFetching DexScreener pairs for WETH ({weth_addr}) on chain '{dexscreener_eth_name}'...")
    pair_reports_weth = fetch_pairs_for_token(weth_addr, dexscreener_eth_name)
    print_pair_reports(pair_reports_weth, weth_addr)

    # Case 2: WBNB on BSC (Binance Smart Chain)
    print("\n--- Test Case 2: WBNB on BSC ---")
    wbnb_addr = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
    goplus_bsc_id = "56"         # GoPlus chain_id for BSC
    dexscreener_bsc_name = "bsc"   # DexScreener chain name for BSC

    print(f"\nFetching GoPlus Security report for WBNB ({wbnb_addr}) on chain ID '{goplus_bsc_id}'...")
    sec_report_wbnb = fetch_token_security_report(wbnb_addr, goplus_bsc_id)
    print_security_report(sec_report_wbnb)

    print(f"\nFetching DexScreener pairs for WBNB ({wbnb_addr}) on chain '{dexscreener_bsc_name}'...")
    pair_reports_wbnb = fetch_pairs_for_token(wbnb_addr, dexscreener_bsc_name)
    print_pair_reports(pair_reports_wbnb, wbnb_addr)

    # Case 3: User-defined token for testing specific flags or new tokens
    # Encourage users to find a token on a testnet (e.g., Sepolia, Mumbai) for this.
    print("\n--- Test Case 3: User-Defined Token (Example: PEPE on Ethereum) ---")
    # Example: PEPE on Ethereum
    user_token_addr = "0x6982508145454Ce325dDbE47a25d4ec3d2311933"
    user_goplus_chain = "1" # Ethereum
    user_dexscreener_chain = "ethereum"

    # To test with your own token, uncomment and modify the lines below:
    # user_token_addr = "YOUR_TOKEN_ADDRESS_HERE"
    # user_goplus_chain = "YOUR_GOPLUS_CHAIN_ID_HERE" # e.g., "11155111" for Sepolia
    # user_dexscreener_chain = "YOUR_DEXSCREENER_CHAIN_NAME_HERE" # e.g., "ethereum" for Sepolia on DexScreener

    if user_token_addr != "YOUR_TOKEN_ADDRESS_HERE": # Basic check if user might have updated it
        print(f"\nFetching GoPlus Security report for {user_token_addr} on chain ID '{user_goplus_chain}'...")
        sec_report_user = fetch_token_security_report(user_token_addr, user_goplus_chain)
        print_security_report(sec_report_user)

        print(f"\nFetching DexScreener pairs for {user_token_addr} on chain '{user_dexscreener_chain}'...")
        pair_reports_user = fetch_pairs_for_token(user_token_addr, user_dexscreener_chain)
        print_pair_reports(pair_reports_user, user_token_addr)
    else:
        print("  Skipping User-Defined Test Case 3 - Modify script with a token address and chain details to run.")

    # Case 4: Non-existent or invalid token address
    print("\n--- Test Case 4: Non-Existent or Invalid Token Address ---")
    invalid_addr = "0x000000000000000000000000000000000000DEAD" # Common burn/dead address

    print(f"\nFetching GoPlus Security for invalid/dead token ({invalid_addr}) on chain ID '{goplus_eth_id}'...")
    sec_report_invalid = fetch_token_security_report(invalid_addr, goplus_eth_id)
    if not sec_report_invalid or not sec_report_invalid.get('raw_goplus_response'): # Expecting no substantial data
        print("  Correctly returned no significant data or failed for invalid/dead token security.")
    else:
        print("  Unexpectedly received data for invalid/dead token security:")
        print_security_report(sec_report_invalid)

    print(f"\nFetching DexScreener pairs for invalid/dead token ({invalid_addr}) on chain '{dexscreener_eth_name}'...")
    pair_reports_invalid = fetch_pairs_for_token(invalid_addr, dexscreener_eth_name)
    if not pair_reports_invalid:
        print("  Correctly found no pairs for invalid/dead token.")
    else:
        print("  Unexpectedly found pairs for invalid/dead token:")
        print_pair_reports(pair_reports_invalid, invalid_addr)

    # Case 5: Invalid Chain ID for GoPlus
    print("\n--- Test Case 5: Invalid Chain ID for GoPlus ---")
    print(f"Fetching security for WETH ({weth_addr}) on invalid GoPlus chain ID '99999'...")
    sec_report_bad_chain = fetch_token_security_report(weth_addr, "99999")
    if not sec_report_bad_chain:
        print("  Correctly failed or returned no data for invalid GoPlus chain ID.")
    else:
        print("  Unexpectedly received data with invalid GoPlus chain ID:")
        print_security_report(sec_report_bad_chain)

    print("\n\n" + "="*70)
    print("MANUAL TEST OUTLINE FOR AI_AGENT.PY INTEGRATION")
    print("="*70)
    manual_tests = """
    **General Setup:**
    1. Ensure `config.json` is fully configured for a TESTNET (RPC, Chain IDs, Private Key, DEX Routers, Token Addresses).
    2. CRITICAL: Ensure `goplus_api_key` is correctly set in `config.json` (under `token_analysis_apis.goplus_security`)
       OR as `GOPLUS_API_KEY` environment variable for security analysis features to work.
    3. Fund your testnet wallet with native gas tokens and some test ERC20 tokens if needed.
    4. Run `python ai_agent.py`.

    **Test Scenarios (Monitor `ai_agent.py` console output):**

    A. Agent Requests Token Analysis:
    ---------------------------------
    1. Trigger: During an agent's turn, its response should include a line like:
       `ANALYZE_TOKEN: 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 ethereum` (for WETH on Ethereum)
       (Use an address and chain name appropriate for your `config.json` setup, e.g., a token on Sepolia).
    2. Observe:
       - `ai_agent.py` log showing: "Agent requested analysis for 0xC02... on ethereum".
       - `token_analyzer.py` logs showing: "Fetching GoPlus security report..." and "Fetching DexScreener pairs...".
       - `ai_agent.py` log showing: "Security report for 0xC02... updated." and "Pair reports for 0xC02... updated."
    3. Verify:
       - In the *next* agent's turn, the `Current Context` block in its prompt should contain an
         `available_token_analyses_summary` section with entries for "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2".
         This summary should include `security_summary` (honeypot, taxes, warnings) and `pair_info_summary` (count, liquidity).
       - The full reports should be internally stored in `AgentGroup.context["token_analysis_reports"]`.

    B. Agent Uses Analysis in Trade Proposal (Safe Token):
    ----------------------------------------------------
    1. Prerequisite: Analysis for a "safe" token (e.g., WETH, USDC on your testnet) is already in the context from a previous `ANALYZE_TOKEN` command.
    2. Trigger: An agent proposes a trade involving this safe token as the *output* (token being bought). Example:
       `TRADE: USDT_TEST 0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2 10 ethereum uniswap_v2` (Buying WETH with test USDT)
    3. Observe:
       - `AgentGroup.propose_trade` logs. Since WETH is likely on the `SAFE_OUTPUT_TOKENS_BY_CHAIN` list (or should be for this test),
         the system pre-check might be skipped or pass silently if the token is considered safe.
    4. Verify:
       - The trade proposal IS ADDED to the `MultisigWallet`'s pending transactions queue (check logs).

    C. System Rejects Trade for Known Risky Token (Honeypot):
    ---------------------------------------------------------
    1. Setup:
       - Find a known honeypot token address on your TESTNET. This can be difficult.
         Alternatively, simulate this by manually editing `token_analyzer.py`'s `fetch_token_security_report`
         to temporarily return `is_honeypot: True` for a specific test address.
       - Have an agent analyze this token: `ANALYZE_TOKEN: <honeypot_test_address> <your_test_chain_name>`
    2. Trigger: An agent proposes to buy this honeypot token:
       `TRADE: WETH_TEST <honeypot_test_address> 0.01 <your_test_chain_name> <your_dex_key>`
    3. Observe:
       - `AgentGroup.propose_trade` log should show: "SYSTEM REJECTED TRADE: Token <honeypot_test_address> is a confirmed honeypot."
    4. Verify:
       - The trade proposal IS NOT ADDED to the `MultisigWallet`'s pending transactions.

    D. System Rejects Trade for High-Tax Token:
    --------------------------------------------
    1. Setup:
       - Find/create a test token with buy or sell tax > 25%.
       - Analyze it: `ANALYZE_TOKEN: <high_tax_token_addr> <chain_name>`
    2. Trigger: Agent proposes to buy this token.
    3. Observe: `AgentGroup.propose_trade` log: "SYSTEM REJECTED TRADE: Excessive taxes for token..."
    4. Verify: Trade NOT added to multisig queue.

    E. Agent Proposes Trade for Unanalyzed, Non-Safe Token:
    -------------------------------------------------------
    1. Trigger: Agent proposes to buy an obscure token address (NOT on `SAFE_OUTPUT_TOKENS_BY_CHAIN` for that network)
       for which NO analysis has been previously requested.
       `TRADE: WETH_TEST 0xObscureTokenAddress... 0.01 <your_test_chain_name> <your_dex_key>`
    2. Observe:
       - `AgentGroup.propose_trade` log: "WARNING: No analysis summary for OUTPUT token 0xObscure... Proposing without system pre-check."
    3. Verify:
       - The trade IS ADDED to the `MultisigWallet` queue (as the system doesn't have info to block it yet).

    F. Agent Voting on a Trade (Considering Analysis):
    --------------------------------------------------
    1. Setup: A trade for a token (e.g., TokenX) is in the `MultisigWallet` queue. `TokenX` has an analysis report
       in `available_token_analyses_summary` which shows some non-critical warnings (e.g., "Owner can mint new tokens")
       but is not a honeypot or excessively taxed.
    2. Observe:
       - When other agents vote on this proposal, their console log output (from `AIAgent.vote_on_transaction`)
         should include reasoning that mentions consulting the analysis for TokenX and how the warnings (or lack thereof)
         influenced their APPROVE/REJECT decision.
    """
    print(manual_tests)

    print("\nToken analyzer test script finished.")
    print("Remember: For GoPlus tests to pass, a valid API key is essential.")
    print("For DexScreener, ensure the token address and chain name are correct for the platform.")
    print("Always prioritize testing on dedicated testnets.")
