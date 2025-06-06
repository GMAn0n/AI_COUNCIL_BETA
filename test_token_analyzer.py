"""
test_token_analyzer.py: Test script for token_analyzer.py.

This script allows manual testing of fetching token security reports from GoPlus Security
and trading pair data from DexScreener for both EVM and Solana tokens.
It's essential for verifying that `token_analyzer.py` functions correctly with the APIs.

**Setup Requirements:**
1.  **`config.json` File:**
    *   Ensure `config.json` exists (copy from `config.json.example`).
    *   **GoPlus API Key:** For security tests, a valid GoPlus API key MUST be in
        `config.json` (under `token_analysis_apis.goplus_security.api_key`)
        OR as `GOPLUS_API_KEY` environment variable (takes precedence).
        Get key from `https://gopluslabs.io/`.
    *   DexScreener public API for pairs doesn't currently require a key for basic use.

2.  **Internet Connection:** Required for all API calls.
3.  **Dependencies:** `requests`, `aiohttp` (used by `token_analyzer.py`).

**Running Tests:**
*   Execute: `python test_token_analyzer.py`
*   Review output for successful data fetching/parsing and any errors.
    The script will attempt to fetch data for pre-defined EVM and Solana tokens.
*   A manual test outline for `ai_agent.py` integration is also printed for reference,
    which guides on testing the AI agents' ability to request and use this analysis.
"""
import json
import os
import time
import asyncio
from typing import List, Optional

from token_analyzer import fetch_token_security_report, fetch_pairs_for_token, TokenSecurityReport, PairReport

# Devnet Mints for Solana testing (verify these are current from reliable sources like official devnet faucet info)
WSOL_DEVNET_MINT = "So11111111111111111111111111111111111111112" # Wrapped SOL (same mint on all networks)
USDC_DEVNET_MINT = "Gh9ZwEmdLJ8DscKNTkTqPbNwLNNBjuSzaG9Vp2KGtKJr" # Example Devnet USDC Mint (official devnet versions may vary)

# --- Helper Functions for Printing Test Outputs ---
def print_security_report(report: Optional[TokenSecurityReport]):
    """Prints a formatted summary of the TokenSecurityReport."""
    if not report:
        print("  No security report data or report is None.")
        return
    print(f"  Token Address: {report['token_address']} (Chain ID for API: '{report['chain_id']}')")
    print(f"  Retrieved At: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(report['retrieved_at']))}")

    is_solana_report = report['chain_id'].lower() == 'solana'

    # Print fields relevant to the chain type
    if is_solana_report:
        print(f"  Solana Derived Honeypot/Major Risk: {report.get('is_honeypot')}") # This is our derived field for Solana
        print(f"  Solana Transfer Tax: {report.get('transfer_tax')*100 if report.get('transfer_tax') is not None else 'N/A'}%")
        print(f"  Is Mintable (Solana): {report.get('is_mintable')}")
        print(f"  Is Freezable/Pausable (Solana): {report.get('is_trading_pausable')}") # Mapped from 'freezable'
        print(f"  Owner Address (Solana - e.g., Mint/Freeze Authority): {report.get('owner_address', 'N/A')}")
    else: # EVM
        print(f"  EVM Honeypot: {report.get('is_honeypot')}")
        print(f"  EVM Buy Tax: {report.get('buy_tax')*100 if report.get('buy_tax') is not None else 'N/A'}%")
        print(f"  EVM Sell Tax: {report.get('sell_tax')*100 if report.get('sell_tax') is not None else 'N/A'}%")
        print(f"  Is Open Source (EVM): {report.get('is_open_source')}")
        print(f"  Owner Address (EVM): {report.get('owner_address', 'N/A')}")

    print(f"  Total LP USD (from GoPlus): ${report.get('total_lp_liquidity_usd', 0):,.2f}")

    warnings = report.get('warnings', [])
    if warnings:
        print(f"  Warnings ({len(warnings)}):")
        for warning in warnings[:3]: print(f"    - {warning}") # Print first 3 for brevity
        if len(warnings) > 3: print(f"    ... and {len(warnings)-3} more warnings.")

    remarks = report.get('remarks', [])
    if remarks:
        print(f"  Remarks ({len(remarks)}):")
        for remark in remarks[:3]: print(f"    - {remark}")
        if len(remarks) > 3: print(f"    ... and {len(remarks)-3} more remarks.")

    lp_holders = report.get('top_lp_holders', [])
    print(f"  Top LP Holders ({len(lp_holders)} found):")
    for i, holder in enumerate(lp_holders[:2]): # Show first 2 for test summary brevity
        print(f"    Holder {i+1}: Address: {holder['address']} ({holder['percent_of_total_lp']:.2f}%, Locked: {holder['is_locked']})")
    if len(lp_holders) > 2: print("    ... (more LP holders in full report)")
    # For full details, inspect 'raw_goplus_response' or print more LP holders.

def print_pair_reports(reports: Optional[List[PairReport]], token_address: str):
    """Prints a formatted summary of fetched DexScreener PairReports."""
    if not reports:
        print(f"  No pair reports found or list is None for token {token_address}.")
        return
    print(f"  DexScreener Pair Reports for {token_address} (Found: {len(reports)}, Displaying up to 5 newest):")
    for i, report_item in enumerate(reports[:5]): # Limiting to 5 for test output brevity
        created_at_str = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(report_item['pair_created_at'])) if report_item.get('pair_created_at') else 'N/A'
        print(f"    Pair {i+1}: {report_item.get('pair_address', 'N/A')}")
        print(f"      Base: {report_item.get('base_token_address', 'N/A')} | Quote: {report_item.get('quote_token_address', 'N/A')}")
        print(f"      Chain: {report_item.get('chain_id', 'N/A')}, DEX: {report_item.get('dex_id', 'N/A')}")
        print(f"      Price USD: ${report_item.get('price_usd', 0):,.4f if report_item.get('price_usd') is not None else 'N/A'}")
        print(f"      Liquidity USD: ${report_item.get('liquidity_usd', 0):,.2f if report_item.get('liquidity_usd') is not None else 'N/A'}")
        print(f"      Volume (24h): ${report_item.get('volume_h24', 0):,.2f if report_item.get('volume_h24') is not None else 'N/A'}")
        print(f"      Pair Created At: {created_at_str}")
        # print(f"      DexScreener URL: {report_item.get('url', 'N/A')}") # URL can be long
    if len(reports) > 5: print(f"    ... and {len(reports) - 5} more pairs not shown in this summary.")

# --- Async Test Functions ---
async def test_evm_token_full_analysis(token_address: str, goplus_chain_id: str, dexscreener_chain_name: str, token_symbol: str):
    """Helper to fetch and print combined analysis for a specified EVM token."""
    print(f"\n--- Full Analysis for EVM Token: {token_symbol} ({token_address}) ---")
    print(f"  GoPlus Chain ID for API: '{goplus_chain_id}', DexScreener Chain Name for API: '{dexscreener_chain_name}'")

    security_report = await fetch_token_security_report(token_address, goplus_chain_id)
    print_security_report(security_report)

    # fetch_pairs_for_token is currently synchronous, run in default executor if called from async context
    pair_reports = await asyncio.to_thread(fetch_pairs_for_token, token_address, dexscreener_chain_name)
    print_pair_reports(pair_reports, token_address)

async def test_solana_token_full_analysis(mint_address: str, goplus_chain_id: str, dexscreener_chain_name: str, token_symbol: str):
    """Helper to fetch and print combined analysis for a specified Solana token."""
    print(f"\n--- Full Analysis for Solana Token: {token_symbol} ({mint_address}) ---")
    print(f"  GoPlus Chain ID for API: '{goplus_chain_id}', DexScreener Chain Name for API: '{dexscreener_chain_name}'")

    security_report = await fetch_token_security_report(mint_address, goplus_chain_id)
    print_security_report(security_report)

    pair_reports = await asyncio.to_thread(fetch_pairs_for_token, mint_address, dexscreener_chain_name)
    print_pair_reports(pair_reports, mint_address)

async def run_all_analyzer_tests():
    """Runs all predefined test cases for token_analyzer.py."""
    print("="*70 + "\nToken Analyzer Test Suite\n" + "="*70)
    print("This script tests fetching data from GoPlus Security and DexScreener.")
    print("A valid GoPlus API key (in `config.json` or `GOPLUS_API_KEY` env var) is needed for full security tests.")

    if not os.path.exists('config.json'):
        print("\nINFO: `config.json` not found. Creating a dummy one with placeholders.")
        print("      API calls requiring keys (like GoPlus) will likely fail or use placeholders.")
        try:
            with open('config.json', 'w') as f_dummy:
                json.dump({
                    "token_analysis_apis": { "goplus_security": { "api_key": "YOUR_GOPLUS_API_KEY_PLACEHOLDER" }}
                }, f_dummy, indent=2)
        except Exception as e: print(f"Could not create dummy config.json: {e}")

    # Test Case 1: WETH on Ethereum (EVM)
    await test_evm_token_full_analysis(
        token_address="0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", goplus_chain_id="1",
        dexscreener_chain_name="ethereum", token_symbol="WETH (Ethereum)"
    )
    # Test Case 2: WBNB on BSC (EVM)
    await test_evm_token_full_analysis(
        token_address="0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c", goplus_chain_id="56",
        dexscreener_chain_name="bsc", token_symbol="WBNB (BSC)"
    )
    # Test Case 3: WSOL on Solana (Solana)
    await test_solana_token_full_analysis(
        mint_address=WSOL_DEVNET_MINT, goplus_chain_id="solana", # GoPlus uses "solana"
        dexscreener_chain_name="solana", token_symbol="WSOL (Solana Devnet)"
    )
    # Test Case 4: USDC on Solana Devnet (Solana)
    await test_solana_token_full_analysis(
        mint_address=USDC_DEVNET_MINT, goplus_chain_id="solana",
        dexscreener_chain_name="solana", token_symbol="USDC (Solana Devnet)"
    )
    # Test Case 5: Non-existent/Invalid Token (EVM example)
    await test_evm_token_full_analysis(
        token_address="0x000000000000000000000000000000000000DEAD", goplus_chain_id="1",
        dexscreener_chain_name="ethereum", token_symbol="InvalidEVMToken"
    )
    # Test Case 6: Non-existent/Invalid Token (Solana example)
    await test_solana_token_full_analysis(
        mint_address="1nc1der1111111111111111111111111111111111", goplus_chain_id="solana", # Invalid mint address
        dexscreener_chain_name="solana", token_symbol="InvalidSolanaToken"
    )

    print("\n\n" + "="*70 + "\nMANUAL TEST OUTLINE FOR AI_AGENT.PY INTEGRATION (Review for Solana specific cases)\n" + "="*70)
    # This manual test outline is for guiding user testing of the ai_agent.py integration.
    # It's not executed by this script but printed for user reference.
    manual_tests_summary = """
    **Key Scenarios for Manual Testing in `ai_agent.py`:**
    1.  **EVM Token Analysis Request & Usage:**
        - Agent requests analysis for an EVM token (e.g., WETH on Sepolia).
        - Verify context update and subsequent agent decisions based on this analysis.
    2.  **Solana Token Analysis Request & Usage:**
        - Agent requests analysis for a Solana token (e.g., WSOL on Devnet).
        - Verify context update and agent decisions using Solana-specific risk flags.
    3.  **System Rejection of Risky EVM Trade:**
        - Agent analyzes a known EVM honeypot/high-tax token.
        - Agent proposes to buy it; system should reject the trade pre-proposal.
    4.  **System Rejection of Risky Solana Trade:**
        - Agent analyzes a Solana token with high derived risk (e.g., malicious creator).
        - Agent proposes to buy it; system should reject.
    5.  **Trade Proposal for Unanalyzed Token (EVM & Solana):**
        - Agent proposes trade for an obscure token (not on safe lists, no prior analysis).
        - Verify trade is proposed to multisig WITH warnings about missing analysis.
        - Voting agents should react cautiously, potentially requesting analysis.
    6.  **Voting Based on Analysis (EVM & Solana):**
        - A trade for a token with some (non-critical) warnings is proposed.
        - Verify voting agents mention consulting the analysis in their reasoning.
    (Refer to the full outline printed by `test_token_analyzer.py` in previous versions for more detail if needed)
    """
    print(manual_tests_summary)
    print("\nToken analyzer test script finished.")

if __name__ == "__main__":
    asyncio.run(run_all_analyzer_tests())
```
