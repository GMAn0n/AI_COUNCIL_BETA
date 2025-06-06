"""
ai_agent.py: Main script for AI agent group simulation, supporting EVM and Solana interactions.

This script orchestrates a group of AI agents that discuss cryptocurrency trends,
propose trades, vote on them, and can execute approved trades on EVM-compatible
blockchains (via `evm_utils.py`) or Solana (via `solana_utils.py`).
It also supports fetching token security and pair data via `token_analyzer.py`.

--------------------------------------------------------------------------------
Quick Start / How to Use:
--------------------------------------------------------------------------------
1.  **Configure Environment:**
    *   Copy `config.json.example` to `config.json`.
    *   **CRITICAL**: Fill `config.json` with your details, ESPECIALLY for
        TESTNETS (e.g., Sepolia for EVM, Solana Devnet for Solana). This includes:
        *   EVM `rpc_urls`, `chain_ids`, `private_key` (or `EVM_PRIVATE_KEY` env var).
        *   Solana `solana_settings.solana_rpc_url_mainnet`,
            `solana_settings.solana_rpc_url_devnet`,
            `solana_settings.solana_private_key_b58` (or `SOLANA_PRIVATE_KEY_B58` env var).
        *   `dex_routers` (EVM) and `token_addresses` (EVM & Solana mints).
        *   `token_analysis_apis.goplus_security.api_key` (for token analysis)
            (or `GOPLUS_API_KEY` env var).
    *   Set `GEMINI_API_KEY` environment variable for Google Gemini.

2.  **Install Dependencies:**
    *   `pip install google-generativeai web3 websockets requests python-dotenv solders solana spl-token aiohttp`
    *   (Consider a `requirements.txt` file).

3.  **Verify Utilities (Recommended):**
    *   Run `python test_evm_utils.py` for EVM setup.
    *   Run `python test_solana_utils.py` for Solana setup.
    *   Run `python test_token_analyzer.py` for GoPlus/DexScreener setup.

4.  **Run the AI Agent Simulation:**
    *   `python ai_agent.py`
    *   Agents discuss, can request token analysis (`ANALYZE_TOKEN: <ADDR> <CHAIN_NAME>`),
        and propose trades (`TRADE: <IN_TOKEN> <OUT_TOKEN> <AMOUNT> <NETWORK> <DEX/PLATFORM>`).
    *   Approved on-chain transactions will be attempted if `config.json` is correctly set up
        with funded TESTNET wallets.

--------------------------------------------------------------------------------
IMPORTANT SECURITY AND OPERATIONAL NOTES:
--------------------------------------------------------------------------------
1.  LIVE TRADING RISK: Mainnet configuration with real funds is STRONGLY DISCOURAGED.
    Automated systems can lead to financial loss.
2.  PRIVATE KEY SECURITY: Paramount. Use environment variables (`EVM_PRIVATE_KEY`,
    `SOLANA_PRIVATE_KEY_B58`) over `config.json` for private keys.
    Ensure `config.json` (if holding any keys) is in `.gitignore`.
3.  TESTNET FIRST: Always test thoroughly on testnets.
4.  ISOLATED WALLETS: For any mainnet tests, use dedicated wallets with limited funds.
5.  NO LIABILITY: Software provided "as-is". Authors/contributors are not liable for losses.
    USE AT YOUR OWN RISK.
--------------------------------------------------------------------------------

# /*-----------------------------------------------------------------------    # | Multi-Chain Capabilities & Token Analysis Features                    |
# |-----------------------------------------------------------------------|
# | This system integrates EVM and Solana blockchain interactions and     |
# | token analysis capabilities to help AI agents make more informed      |
# | decisions and avoid risky assets.                                     |
# |                                                                       |
# | **1. EVM Integration (`evm_utils.py`):**                             |
# |    - Connects to EVM networks (Ethereum, Polygon, BSC, etc.).         |
# |    - Loads EVM wallets from private keys.                             |
# |    - Fetches ERC20 token balances and native currency balances.       |
# |    - Approves ERC20 tokens for DEX spending.                          |
# |    - Executes trades on EVM DEXs (e.g., Uniswap V2 style).            |
# |                                                                       |
# | **2. Solana Integration (`solana_utils.py`):**                        |
# |    - Connects to Solana networks (Mainnet-beta, Devnet).              |
# |    - Loads Solana keypairs from base58 encoded private keys.          |
# |    - Fetches SOL (native) and SPL token balances.                     |
# |    - Executes swaps via Jupiter Aggregator API for optimal routing.   |
# |                                                                       |
# | **3. Token Analysis Features (`token_analyzer.py`):**                 |
# |    - GoPlus Security: For detailed smart contract security analysis   |
# |      (honeypots, taxes, LP status, vulnerabilities, etc.) for both    |
# |      EVM and Solana tokens. Requires a GoPlus API key.                |
# |    - DexScreener: For real-time trading pair data (liquidity, volume, |
# |      pair age, etc.) for both EVM and Solana tokens. Public API used. |
# |                                                                       |
# | **Agent Interaction & Workflow:**                                     |
# | - Agents can request analysis for a token (EVM or Solana):            |
# |   `ANALYZE_TOKEN: <TOKEN_ADDRESS_OR_MINT> <CHAIN_NAME>`               |
# |   (e.g., `ANALYZE_TOKEN: 0x... ethereum` or `ANALYZE_TOKEN: So1... solana`)|
# | - Analysis summaries are added to `available_token_analyses_summary`  |
# |   in the agent context. Agents are prompted to check this.            |
# | - Trade proposals follow specific formats:                            |
# |   EVM: `TRADE: <IN_TOKEN> <OUT_TOKEN> <AMOUNT> <NETWORK> <DEX>`       |
# |   Solana: `TRADE: <IN_MINT> <OUT_MINT> <ATOMIC_AMOUNT> solana jupiter`|
# | - `AgentGroup.propose_trade` has pre-validation to reject trades for  |
# |   tokens flagged as high-risk by GoPlus analysis (honeypots, high     |
# |   taxes, critical warnings) unless the output token is "safe-listed". |
# |                                                                       |
# | **Configuration (`config.json` - CRITICAL):**                         |
# | - **EVM:** `rpc_urls`, `chain_ids`, `private_key` (or `EVM_PRIVATE_KEY` env). |
# | - **Solana:** `solana_settings` with `solana_rpc_url_mainnet`,        |
# |   `solana_rpc_url_devnet`, `solana_private_key_b58` (or               |
# |   `SOLANA_PRIVATE_KEY_B58` env).                                      |
# | - **GoPlus API Key:** Under `token_analysis_apis.goplus_security.api_key` |
# |   (or `GOPLUS_API_KEY` env). Obtain from `https://gopluslabs.io/`.    |
# | - `chain_name_to_id_map`: Defines chain names agents can use and maps |
# |   them to API-specific IDs and types ('evm', 'solana').               |
# | - `token_addresses`: For both EVM (contract addresses) and Solana     |
# |   (mint addresses), including `NATIVE` and wrapped native tokens.     |
# |                                                                       |
# | **Testing:**                                                          |
# | - `test_evm_utils.py`: For EVM wallet, connection, balance, trading.  |
# | - `test_solana_utils.py`: For Solana wallet, connection, balance, Jupiter swaps.|
# | - `test_token_analyzer.py`: For GoPlus and DexScreener API calls for |
# |   both EVM and Solana tokens. Also contains a manual test outline for |
# |   verifying AI agent integration with these analysis features.        |
# \-----------------------------------------------------------------------*/
import google.generativeai as genai
import json
from datetime import datetime, timedelta
import random
import time
import http.server
import socketserver
import threading
import websockets
import asyncio
import requests
import os
import aiohttp
from typing import List, Dict, Optional, Any

from evm_utils import (
    connect_to_network as evm_connect_to_network,
    load_wallet as evm_load_wallet,
    execute_trade as evm_execute_trade,
    get_token_balance as evm_get_token_balance,
    approve_token as evm_approve_token,
    load_config
)
from solana_utils import (
    _load_solana_config as solana_utils_load_config,
    get_solana_rpc_url,
    get_async_solana_client,
    load_solana_keypair,
    fetch_jupiter_quote,
    execute_jupiter_swap
)
from token_analyzer import (
    fetch_token_security_report,
    fetch_pairs_for_token,
    TokenSecurityReport,
    PairReport
)

websocket_server_running = False
http_server_running = False

class AIAgent:
    """
    Represents an AI agent with a role, processing inputs and voting on transactions.
    Aware of token analysis features and different blockchain types for trades.
    """
    def __init__(self, name: str, role: str, api_key: str, social_handle: str,
                 valid_chain_names_for_analysis: Optional[List[str]] = None):
        """
        Initializes an AI Agent.
        Args:
            name: Name of the agent.
            role: Role of the agent.
            api_key: API key for the generative AI model.
            social_handle: Social media handle for the agent.
            valid_chain_names_for_analysis: List of chain names agents can request analysis for.
                                            This is typically derived from AgentGroup's CHAIN_NAME_TO_ID_MAP.
        """
        self.name = name; self.role = role; self.social_handle = social_handle
        genai.configure(api_key=api_key); self.model = genai.GenerativeModel('gemini-pro')
        self.valid_chain_names_for_analysis = valid_chain_names_for_analysis or \
            ["ethereum", "bsc", "polygon", "arbitrum", "base", "solana", "sepolia", "polygon_mumbai"] # Fallback

    def process_input(self, input_text: str, context: Dict) -> str:
        """
        Generates a response based on input text and current context.
        Guides agent to use token analysis before proposing trades for EVM or Solana.
        """
        prompt_context = context.copy()
        prompt_context['valid_analysis_chain_names'] = self.valid_chain_names_for_analysis # Ensure this is in prompt
        prompt = f"""As AI Agent '{self.name}' (@{self.social_handle}), your role is '{self.role}'.
Context: {json.dumps(prompt_context, indent=2, default=str)}
Input: "{input_text}"

**Critical Instructions:**
1.  **Consult Analysis:** Before proposing trades or actions, CHECK `available_token_analyses_summary`.
    - AVOID tokens if `is_honeypot: true` or `is_solana_major_risk: true`.
    - AVOID tokens with `buy_tax_percent` or `sell_tax_percent` or Solana `transfer_tax` (if available) > 20% unless extremely strong, explicit justification.
    - HEED warnings. Mention analysis use (e.g., "Token X analysis good, propose...").
2.  **Request Analysis (if needed):** `ANALYZE_TOKEN: <TOKEN_ADDRESS_OR_MINT> <CHAIN_NAME>`
    (Valid chains: {', '.join(self.valid_chain_names_for_analysis)})
3.  **Propose EVM Trade:** `TRADE: <IN_TOKEN_SYMBOL_OR_ADDR> <OUT_TOKEN_SYMBOL_OR_ADDR> <IN_AMOUNT> <EVM_NETWORK_NAME> <DEX_NAME>`
4.  **Propose Solana Trade (via Jupiter):** `TRADE: <INPUT_MINT_ADDRESS> <OUTPUT_MINT_ADDRESS> <INPUT_AMOUNT_ATOMIC_UNITS> solana jupiter`
    (Example: `TRADE: So11111111111111111111111111111111111111112 EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v 100000000 solana jupiter` for 0.1 SOL to USDC. AMOUNT IS ATOMIC.)

Your Response:"""
        try: return self.model.generate_content(prompt).text
        except Exception as e: print(f"Error in {self.name} (process_input): {e}"); return f"Error: {e}"

    def vote_on_transaction(self, transaction: Dict, context: Dict) -> str:
        """
        Generates a vote (APPROVE/REJECT) and reasoning for a proposed transaction.
        Guides agent to use token analysis (EVM or Solana) for voting.
        """
        prompt = f"""As AI Agent '{self.name}' ({self.role}), evaluate proposed transaction:
{json.dumps(transaction, indent=2)}

**Critical Voting Instructions:**
- REVIEW `available_token_analyses_summary` in Context for involved assets (check by output token address/mint).
- REJECT if analysis indicates high risk (e.g., `is_honeypot: true` for EVM, `is_solana_major_risk: true` for Solana, taxes > 20%, critical warnings) unless proposer gives compelling, explicit justification for the risk.
- Your reasoning MUST state if you consulted analysis and how findings influenced your vote.

Context: {json.dumps(context, indent=2, default=str)}
Your Vote (Format: "APPROVE" or "REJECT", then reasoning on new lines):"""
        try: return self.model.generate_content(prompt).text
        except Exception as e: print(f"Error in {self.name} (vote): {e}"); return f"REJECT - Error: {e}"

class CryptoPortfolio:
    def __init__(self): self.holdings:Dict[str,float]={}; self.transaction_history:List[Dict]=[]
    def update_holding(self,sym:str,amt:float):
        bal=self.holdings.get(sym,0.0)+amt
        if abs(bal)<1e-12: self.holdings.pop(sym,None)
        else: self.holdings[sym]=bal;
        self.transaction_history.append({"date":datetime.now().isoformat(),"crypto":sym,"amt_chg":amt,"new_bal":self.holdings.get(sym,0.0)})
    def get_portfolio_summary(self)->str: return json.dumps(self.holdings)
    def get_transaction_history(self)->str: return json.dumps(self.transaction_history)

class MultisigWallet:
    def __init__(self,agents:List[AIAgent],req_sigs:int): self.agents=agents;self.required_signatures=req_sigs;self.pending_transactions:List[Dict]=[]
    def propose_transaction(self,tx_data:Dict):tx_id=f"tx_{int(time.time())}_{random.randint(1000,9999)}";self.pending_transactions.append({"id":tx_id,"transaction":tx_data,"votes":[],"status":"pending"});print(f"Tx proposed (ID:{tx_id}): {json.dumps(tx_data)}")
    def vote_on_transactions(self,ctx:Dict):
        for tx_w in self.pending_transactions:
            if tx_w["status"]=="pending":
                voted=[v['agent']for v in tx_w['votes']];[tx_w["votes"].append({"agent":a.name,"vote":(v_resp:=a.vote_on_transaction(tx_w["transaction"],ctx))})or print(f"Agent {a.name} voted on Tx {tx_w['id']}:'{v_resp.splitlines()[0]}'")for a in self.agents if a.name not in voted]
                appr=sum(1 for v in tx_w["votes"]if v["vote"].strip().upper().startswith("APPROVE"));rej=sum(1 for v in tx_w["votes"]if v["vote"].strip().upper().startswith("REJECT"));n_ags=len(self.agents)
                if appr>=self.required_signatures:tx_w["status"]="approved";print(f"Tx {tx_w['id']} APPROVED ({appr}/{n_ags}).")
                elif rej>(n_ags-self.required_signatures)or len(tx_w['votes'])==n_ags:tx_w["status"]="rejected";print(f"Tx {tx_w['id']} REJECTED (A:{appr},R:{rej},V:{len(tx_w['votes'])}).")
    def get_approved_transactions(self)->List[Dict]:return[tx_w for tx_w in self.pending_transactions if tx_w["status"]=="approved"]
    def mark_transaction_processed(self,tx_id:str,status:str,hash_val:Optional[str]=None,err_msg:Optional[str]=None):
        for tx_w in self.pending_transactions:
            if tx_w["id"]==tx_id:tx_w["status"]=status;hash_val and setattr(tx_w,'tx_hash',hash_val);err_msg and setattr(tx_w,'error_message',err_msg);print(f"Tx {tx_id} status:{status}");break
    def clear_finalized_transactions(self):
        pre_count=len(self.pending_transactions);self.pending_transactions=[tx for tx in self.pending_transactions if tx["status"]in["pending","approved"]]
        if pre_count - len(self.pending_transactions)>0: print(f"Cleared {pre_count - len(self.pending_transactions)} finalized txs.")

class AgentGroup:
    """
    Manages a group of AI agents, their discussions, context (including token analysis reports),
    and orchestrates trade proposals and execution (EVM & Solana) based on multi-signature consensus.
    Includes safety checks based on token analysis before proposing trades.
    WARNING: Live trading risks apply if configured for mainnet.
    """
    SAFE_OUTPUT_TOKENS_BY_CHAIN: Dict[str, List[str]] = { # Case-insensitive checks will be done by lowercasing these
        "ethereum":["0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2","0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48","0xdac17f958d2ee523a2206206994597c13d831ec7","0x6b175474e89094c44da98b954eedeac495271d0f"],
        "polygon":["0x0d500b1d8e8ef31e21c99d1db9a6444d3adf1270","0x3c499c542cef5e3811e1192ce70d8cc03d5c3359","0xc2132d05d31c914a87c6611c10748aeb04b58e8f"],
        "solana": ["So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "Gh9ZwEmdLJ8DscKNTkTqPbNwLNNBjuSzaG9Vp2KGtKJr"]
    }

    def __init__(self, agents_definitions: List[Dict], initial_simulated_btc_amount: float):
        self.evm_config = load_config(); self.solana_config_loaded = solana_utils_load_config()
        if not self.evm_config: print("CRIT WARN: EVM config fail. EVM impaired."); self.evm_config = {}
        if not self.solana_config_loaded: print("CRIT WARN: Solana config fail. Solana impaired.")

        # Maps user-friendly chain names to API-specific chain IDs and types.
        self.CHAIN_NAME_TO_ID_MAP = self.evm_config.get("chain_name_to_id_map", {
            "ethereum":{"goplus":"1","dexscreener":"ethereum","type":"evm"}, "bsc":{"goplus":"56","dexscreener":"bsc","type":"evm"},
            "polygon":{"goplus":"137","dexscreener":"polygon","type":"evm"}, "arbitrum":{"goplus":"42161","dexscreener":"arbitrum","type":"evm"},
            "base":{"goplus":"8453","dexscreener":"base","type":"evm"},
            "solana":{"goplus":"solana","dexscreener":"solana","rpc_network_key":"devnet","type":"solana"}, # 'rpc_network_key' used by solana_utils to pick RPC URL
            "sepolia":{"goplus":"11155111","dexscreener":"ethereum","type":"evm"}, "polygon_mumbai":{"goplus":"80001","dexscreener":"polygon","type":"evm"}
        })
        gemini_api_key = os.getenv("GEMINI_API_KEY")
        valid_chains = list(self.CHAIN_NAME_TO_ID_MAP.keys())
        self.agents = [AIAgent(d["name"],d["role"],gemini_api_key,d["social_handle"],valid_chain_names_for_analysis=valid_chains) for d in agents_definitions]
        self.portfolio=CryptoPortfolio(); self.simulated_fund_usd=0.0
        if initial_simulated_btc_amount > 0: self.portfolio.update_holding("BTC", initial_simulated_btc_amount)

        self.context:Dict[str,Any]={
            "portfolio_summary":self.portfolio.get_portfolio_summary(),
            "simulated_fund_usd":self.simulated_fund_usd,
            "token_analysis_reports":{}, # Stores full analysis reports: {token_addr: {'security': TokenSecurityReport, 'pairs': List[PairReport]}}
            "available_token_analyses_summary":{}, # Stores brief summaries for LLM: {token_addr: {'security_summary': {...}, 'pair_info_summary': {...}}}
            "valid_analysis_chain_names":valid_chains # List of chain names agents can request analysis for
        }
        num_agents=len(self.agents);def_req_sigs=1 if num_agents<=1 else min(num_agents,2)
        req_sigs=max(1,min(num_agents,self.evm_config.get("multisig_required_signatures",def_req_sigs)))
        self.multisig_wallet=MultisigWallet(self.agents,required_signatures=req_sigs)
        self.discussion_log:List[Dict]=[];self.current_day=1;self.websocket_clients=set();self.synopsis="";self.discussion_state_file="discussion_state.json"

    async def update_context_with_responses(self, responses: List[str]):
        """
        Processes agent responses for commands (TRADE, ANALYZE_TOKEN) and updates shared context.
        Token analysis fetching is now asynchronous.
        """
        for response_text in responses:
            if "TRADE:" in response_text: self.propose_trade(response_text.split("TRADE:", 1)[1].strip())
            if "ANALYZE_TOKEN:" in response_text:
                try:
                    command_part = response_text.split("ANALYZE_TOKEN:",1)[1].strip(); parts = command_part.split()
                    if len(parts)==2:
                        token_addr, chain_name = parts[0].strip(), parts[1].strip().lower()
                        await self.log_message(f"Agent requested analysis: {token_addr} on {chain_name}", "INFO")
                        if chain_name not in self.CHAIN_NAME_TO_ID_MAP:
                            await self.log_message(f"Unsupported chain for analysis: {chain_name}. Valid: {list(self.CHAIN_NAME_TO_ID_MAP.keys())}", "WARN")
                            self.context["available_token_analyses_summary"].setdefault(token_addr,{})["error"]=f"Unsupported chain: {chain_name}"; continue

                        # Initialize context storage for this token
                        self.context["token_analysis_reports"].setdefault(token_addr,{});
                        self.context["available_token_analyses_summary"].setdefault(token_addr,{})

                        goplus_id = self.CHAIN_NAME_TO_ID_MAP[chain_name].get("goplus")
                        dex_chain_name = self.CHAIN_NAME_TO_ID_MAP[chain_name].get("dexscreener")
                        sec_summary = {"retrieved_at": int(time.time()), "error": "Not fetched yet"}

                        if goplus_id:
                            # fetch_token_security_report is async, so await it directly
                            security_report: Optional[TokenSecurityReport] = await fetch_token_security_report(token_addr, goplus_id)
                            if security_report:
                                self.context["token_analysis_reports"][token_addr]["security"] = security_report
                                # Create a concise summary for the LLM context based on chain type
                                if chain_name == "solana": # Solana specific summary
                                    sec_summary = {
                                        "is_solana_major_risk": security_report.get("is_honeypot"), # is_honeypot is derived for Solana
                                        "transfer_tax_percent": (security_report.get("transfer_tax") or 0) * 100 if security_report.get("transfer_tax") is not None else None,
                                        "is_mintable": security_report.get("is_mintable"),
                                        "is_freezable": security_report.get("is_trading_pausable"), # Mapped from freezable
                                        "warnings_count": len(security_report.get("warnings", [])),
                                        "top_warnings": security_report.get("warnings", [])[:2],
                                        "retrieved_at": security_report.get("retrieved_at")
                                    }
                                else: # EVM summary
                                    sec_summary = {
                                        "is_honeypot":security_report.get("is_honeypot"),
                                        "buy_tax_percent":(security_report.get("buy_tax")or 0)*100,
                                        "sell_tax_percent":(security_report.get("sell_tax")or 0)*100,
                                        "warnings_count":len(security_report.get("warnings",[])),
                                        "top_warnings":security_report.get("warnings",[])[:2],
                                        "retrieved_at":security_report.get("retrieved_at")
                                    }
                                self.context["available_token_analyses_summary"][token_addr]["security_summary"] = sec_summary
                                await self.log_message(f"Security report for {token_addr} updated. Risk flags processed.", "INFO")
                            else:
                                await self.log_message(f"Failed GoPlus security report for {token_addr}.", "WARN")
                                self.context["available_token_analyses_summary"][token_addr]["security_summary"] = "Error fetching/processing security data."

                        if dex_chain_name: # DexScreener call is sync, use to_thread
                            pair_reps: List[PairReport] = await asyncio.to_thread(fetch_pairs_for_token, token_addr, dex_chain_name)
                            if pair_reps:
                                self.context["token_analysis_reports"][token_addr]["pairs"] = pair_reps
                                self.context["available_token_analyses_summary"][token_addr]["pair_info_summary"] = {
                                    "pair_count":len(pair_reps),
                                    "total_liquidity_usd":sum(p.get('liquidity_usd',0)or 0 for p in pair_reps),
                                    "top_pair_liq_usd":pair_reps[0].get("liquidity_usd")if pair_reps else None,
                                    "newest_pair_creation_ts":pair_reps[0].get("pair_created_at")if pair_reps else None
                                }
                                await self.log_message(f"Pair reports for {token_addr} updated (Count: {len(pair_reps)}).","INFO")
                            else:
                                await self.log_message(f"Failed DexScreener pairs for {token_addr}.","WARN")
                                self.context["available_token_analyses_summary"][token_addr]["pair_info_summary"] = "Error fetching pair data."
                    else: await self.log_message(f"Invalid ANALYZE_TOKEN format: '{command_part}'. Expected <ADDRESS_OR_MINT> <CHAIN_NAME>.","WARNING")
                except Exception as e: await self.log_message(f"Error processing ANALYZE_TOKEN command ('{response_text}'): {type(e).__name__} - {e}",level="ERROR")

        self.context["portfolio_summary"]=self.portfolio.get_portfolio_summary(); self.context["simulated_fund_usd"]=self.simulated_fund_usd
        self.context['valid_analysis_chain_names']=list(self.CHAIN_NAME_TO_ID_MAP.keys())


    def propose_trade(self, trade_details_string: str):
        """
        Parses trade string, performs pre-proposal validation using token analysis (for output token), then proposes.
        Format EVM: <IN_TOKEN> <OUT_TOKEN> <IN_AMOUNT> <NETWORK_NAME> <DEX_NAME>
        Format SOL: <IN_MINT> <OUT_MINT> <IN_AMOUNT_ATOMIC> solana jupiter
        """
        log_func = lambda msg, level: asyncio.create_task(self.log_message(msg, level=level)) # Helper for async logging
        parts = trade_details_string.strip().split()

        if len(parts) == 5:
            input_token_str, output_token_str, input_amount_str, network_name_str, platform_name_str = parts
            network_name = network_name_str.lower()
            platform_name = platform_name_str.lower()

            network_config = self.CHAIN_NAME_TO_ID_MAP.get(network_name, {})
            network_type = network_config.get("type")
            if not network_type: log_func(f"Trade REJECTED (System): Network '{network_name}' not defined in CHAIN_NAME_TO_ID_MAP.", "ERROR"); return

            try:
                input_amount_val = float(input_amount_str)
                if (network_type == "evm" and input_amount_val <= 1e-18) or \
                   (network_type == "solana" and input_amount_val <= 0): # Solana amount is atomic
                    log_func(f"Trade REJECTED (System): Amount too small or invalid: {input_amount_str} for {network_type}", "WARNING"); return

                # --- Pre-Proposal Validation for the Output Token (token being acquired) ---
                token_to_check_on_risk = output_token_str # This is the symbol or address/mint provided by agent
                resolved_output_token_address = None

                if network_type == "evm":
                    # If it's an EVM chain, try to resolve symbol to address if not already an address
                    if "0x" in token_to_check_on_risk.lower() and len(token_to_check_on_risk) == 42 : # Basic EVM address check
                        resolved_output_token_address = token_to_check_on_risk
                    else: # Assume it's a symbol, try to get address from config
                        resolved_output_token_address = self.evm_config.get("token_addresses", {}).get(network_name, {}).get(token_to_check_on_risk.upper())
                elif network_type == "solana":
                    # For Solana, agent is expected to provide the mint address directly for output_token_str
                    resolved_output_token_address = token_to_check_on_risk # Assume it's a mint address

                # Check against safe list for the specific chain
                safe_tokens_for_this_chain = [addr.lower() for addr in self.SAFE_OUTPUT_TOKENS_BY_CHAIN.get(network_name, [])]

                if resolved_output_token_address and (resolved_output_token_address.lower() not in safe_tokens_for_this_chain):
                    log_func(f"Pre-proposal check for non-safe output token: {resolved_output_token_address} (from '{output_token_str}') on {network_name}", "INFO")
                    # Retrieve analysis summary for the resolved address
                    analysis_data = self.context.get("available_token_analyses_summary", {}).get(resolved_output_token_address, {})
                    security_summary = analysis_data.get("security_summary") # This is the dict we need

                    if isinstance(security_summary, str): # Error string from analysis
                        log_func(f"WARNING: Analysis for {resolved_output_token_address} resulted in error string '{security_summary}'. Proposing without full safety pre-check.", "WARNING")
                    elif security_summary: # It's a dict, proceed with checks
                        is_high_risk = False
                        rejection_reason = ""

                        if network_type == "evm":
                            if security_summary.get("is_honeypot") is True: is_high_risk=True; rejection_reason="EVM Honeypot"
                            if (security_summary.get("buy_tax_percent",0)>20 or security_summary.get("sell_tax_percent",0)>20): is_high_risk=True; rejection_reason="Excessive EVM Taxes"
                        elif network_type == "solana":
                            if security_summary.get("is_solana_major_risk") is True: is_high_risk=True; rejection_reason="Solana Major Risk/Honeypot"
                            sol_transfer_tax = security_summary.get("transfer_tax") # This is 0-1 float from report
                            if sol_transfer_tax is not None and sol_transfer_tax > 0.20: is_high_risk=True; rejection_reason=f"Excessive Solana Transfer Tax ({sol_transfer_tax*100:.1f}%)"

                        if any("CRITICAL:" in w.upper() for w in security_summary.get("top_warnings",[])):
                            is_high_risk=True; rejection_reason=f"Critical Security Warning(s): {security_summary.get('top_warnings')}"

                        if is_high_risk:
                            log_func(f"SYSTEM REJECTED TRADE: {rejection_reason} for {resolved_output_token_address}. Trade: {trade_details_string}", "ERROR"); return

                    elif not security_summary: # No analysis summary found for this specific address
                         # Heuristic to check if it looks like an address rather than a common symbol we might have missed resolving
                        if ("0x" in resolved_output_token_address.lower() and len(resolved_output_token_address)==42) or \
                           (len(resolved_output_token_address) > 30 and len(resolved_output_token_address) < 50 and network_type == "solana"):
                            log_func(f"WARNING: No analysis summary found for OUTPUT token {resolved_output_token_address}. Proposing without system safety pre-check: {trade_details_string}", "WARNING")

                elif not resolved_output_token_address and not ("0x" in token_to_check_on_risk.lower() or len(token_to_check_on_risk) > 30) : # It was a symbol but not found in config
                    log_func(f"WARNING: Output token SYMBOL '{token_to_check_on_risk}' not found in config for network '{network_name}' and is not an address. Proposing as-is.", "WARNING")

                # If all checks passed or token is safe-listed or no address to check
                proposal_data = {"action":"TRADE","input_token":input_token_str.upper(),"output_token":output_token_str.upper(),
                                 "input_amount":input_amount_val,"network_name":network_name,"platform_name":platform_name, "chain_type":network_type}
                self.multisig_wallet.propose_transaction(proposal_data)
            except ValueError: log_func(f"Invalid number format for trade amount: '{input_amount_str}' in '{trade_details_string}'", "WARNING")
        elif len(parts)==3 and parts[0].upper()in["BUY","SELL"]: # Simulated legacy trade
            action,amount_s,crypto=parts;amount=float(amount_s);self.multisig_wallet.propose_transaction({"action":action.upper(),"amount":amount,"crypto":crypto.upper(),"simulated":True})
        else: log_func(f"Unrecognized trade proposal format: '{trade_details_string}'. Expected 5 parts for on-chain or 3 for simulated.", "WARNING")

    async def execute_approved_transactions(self):
        approved_tx_wrappers = self.multisig_wallet.get_approved_transactions()
        if not approved_tx_wrappers: return
        await self.log_message(f"Processing {len(approved_tx_wrappers)} approved transaction(s)...", "INFO")
        _evm_w3,_evm_wallet,_evm_net_name = None,None,None
        _sol_client,_sol_keypair,_sol_net_name = None,None,None

        for tx_w in approved_tx_wrappers:
            tx,tx_id = tx_w['transaction'],tx_w['id']
            status,tx_hash,err_msg = tx_w['status'],None,None # Ensure err_msg is defined
            await self.log_message(f"Attempting to execute Tx ID {tx_id}: {json.dumps(tx)}", "DEBUG")
            if tx.get("simulated"): self.multisig_wallet.mark_transaction_processed(tx_id,f"executed_simulated_{tx['action'].lower()}",err_msg=err_msg); continue # Use err_msg here

            chain_type, net_name = tx.get("chain_type"), tx.get("network_name")
            if chain_type=="evm":
                await self.log_message(f"Preparing EVM trade for Tx {tx_id} on {net_name}...", "WARNING")
                if net_name!=_evm_net_name or not _evm_w3 or not _evm_wallet:
                    _evm_w3=evm_connect_to_network(net_name,'config.json')
                    if _evm_w3: _evm_wallet=evm_load_wallet(_evm_w3,net_name,'config.json'); _evm_net_name=net_name if _evm_wallet else None
                    if not _evm_wallet: err_msg="EVM wallet/network failed.";status="failed_evm_setup";await self.log_message(err_msg,"ERROR");self.multisig_wallet.mark_transaction_processed(tx_id,status,err_msg=err_msg);continue
                tx_hash,success,msg = await asyncio.to_thread(evm_execute_trade,_evm_w3,_evm_wallet,net_name,tx.get("platform_name"),tx["input_token"],tx["output_token"],tx["input_amount"],'config.json')
                if success: status="executed_onchain_evm_success";await self.log_message(f"EVM Trade SUCCESS (Tx {tx_id}): Hash {tx_hash}. {msg}","INFO");self.portfolio.update_holding(tx["input_token"],-float(tx["input_amount"]))
                else: status="failed_onchain_evm_execution";err_msg=msg;await self.log_message(f"EVM Trade FAILED (Tx {tx_id}): {msg}. Hash(if any):{tx_hash}","ERROR")
            elif chain_type=="solana":
                await self.log_message(f"Preparing Solana trade for Tx ID {tx_id} on {net_name} via Jupiter...","WARN")
                sol_rpc_key=self.CHAIN_NAME_TO_ID_MAP.get(net_name,{}).get("rpc_network_key","devnet")
                if net_name!=_sol_net_name or not _sol_client or not _sol_keypair:
                    sol_rpc_url=get_solana_rpc_url(sol_rpc_key);_sol_keypair=load_solana_keypair()
                    if not sol_rpc_url or not _sol_keypair:err_msg="Solana RPC/Signer not configured.";status="failed_solana_setup";await self.log_message(err_msg,"ERROR");self.multisig_wallet.mark_transaction_processed(tx_id,status,err_msg=err_msg);continue
                    if _sol_client:await _sol_client.close() # Close previous if switching
                    _sol_client=await get_async_solana_client(rpc_url_override=sol_rpc_url)
                    if not _sol_client:err_msg=f"Failed to connect to Solana {sol_rpc_key} RPC.";status="failed_solana_rpc";await self.log_message(err_msg,"ERROR");self.multisig_wallet.mark_transaction_processed(tx_id,status,err_msg=err_msg);continue
                    _sol_net_name=net_name
                amt_atomic=int(tx["input_amount"]) # Agent must provide atomic units for Solana
                # Define do_sol_swap_task inside execute_approved_transactions as it uses its scope
                async def do_sol_swap_task():
                    async with aiohttp.ClientSession() as http_session: # Session for this task
                        quote=await fetch_jupiter_quote(tx["input_token"],tx["output_token"],amt_atomic,str(_sol_keypair.pubkey()),self.evm_config.get("solana_slippage_bps", 500),http_session)
                        if not quote:return{"success":False,"error_message":"Failed to get Jupiter quote"}
                        return await execute_jupiter_swap(quote,_sol_keypair,_sol_client,http_session)
                swap_outcome = await do_sol_swap_task() # Await the task directly
                tx_hash=swap_outcome.get("signature")
                if swap_outcome.get("success"):status="executed_onchain_solana_success";await self.log_message(f"Solana Trade SUCCESS (Tx {tx_id}): Sig {tx_hash}. In:{swap_outcome.get('input_amount_processed')} Out:{swap_outcome.get('output_amount_processed')}","INFO");await self.log_message(f"Simulated portfolio NOT YET UPDATED for Solana trade input {tx['input_token']}.","WARN")
                else:status="failed_onchain_solana_execution";err_msg=swap_outcome.get('error_message','Unknown Solana swap error');await self.log_message(f"Solana Trade FAILED (Tx {tx_id}): {err_msg}. Sig(if any):{tx_hash}","ERROR")
            else: status="failed_unsupported_chain_type";err_msg=f"Unsupported chain_type '{chain_type}'";await self.log_message(f"Tx {tx_id} {err_msg}","ERROR")
            self.multisig_wallet.mark_transaction_processed(tx_id,status,tx_hash=tx_hash,error_message=err_msg)
        self.context["portfolio_summary"]=self.portfolio.get_portfolio_summary();self.context["simulated_fund_usd"]=self.simulated_fund_usd
        self.multisig_wallet.clear_finalized_transactions()
        if _sol_client:await _sol_client.close();_sol_client=None;_sol_net_name=None;print("Closed active Solana client session.")

    # --- Other AgentGroup methods (generate_synopsis, export_discussion_log, etc.) ---
    # These methods are largely unchanged by this specific subtask, but would use the updated context.
    # For brevity, they are represented by the "..." from the previous step if no direct changes were specified for them here.
    async def generate_synopsis(self):
        prompt = f"Summarize key discussion points, decisions, and outcomes of any executed/failed on-chain transactions from Day {self.current_day}:\n\nDiscussion Highlights:\n"
        max_interactions = self.evm_config.get("synopsis_max_interactions", 20); recent_interactions = self.discussion_log[-max_interactions:]
        if recent_interactions: [prompt := prompt + f"- @{i['social_handle']} on '{i['topic'][:30]}...': {i['response'][:100].replace(chr(10),' ')}...\n" for i in recent_interactions]
        else: prompt += "- No discussion points recorded.\n"
        processed_txs = []
        for tx_w in self.multisig_wallet.pending_transactions:
            if tx_w['status'] not in ['pending','approved']:
                tx_info,s=tx_w['transaction'],f"TxID {tx_w['id']}:{tx_info.get('action','N/A')} {tx_info.get('input_token','N/A')if tx_info.get('action')=='TRADE'else tx_info.get('crypto','N/A')}-Status:{tx_w['status']}."
                if tx_w.get('tx_hash'):s+=f" (Hash:{tx_w['tx_hash'][:12]}...)"
                if tx_w.get('error_message'):s+=f" (Error:{tx_w['error_message'][:50]}...)"
                processed_txs.append(s)
        if processed_txs:prompt+="\nTransaction Attempts Summary:\n"+"\n".join(processed_txs)
        else:prompt+="\n- No on-chain transaction attempts processed today.\n"
        try:self.synopsis=self.agents[0].model.generate_content(prompt).text
        except Exception as e:self.synopsis=f"Error generating synopsis:{e}";print(f"Synopsis error:{e}")
        await self.log_message(f"\n--- Day {self.current_day} Synopsis ---\n{self.synopsis}\n--- End Synopsis ---","INFO");await self.broadcast({"type":"synopsis","content":self.synopsis})

    def export_discussion_log(self,fn="crypto_discussion_log_full.json"):
        try:
            with open(fn,'w')as f:json.dump(self.discussion_log,f,indent=2,default=str)
            print(f"Full discussion log exported to {fn}")
        except Exception as e:print(f"Error exporting discussion log:{e}")

    def generate_seo_friendly_html(self,fn="crypto_discussion_log.html"):
        ws_port=self.evm_config.get("websocket_port",8765)
        html=f"<!DOCTYPE html><html lang=en><head><meta charset=UTF-8><meta name=viewport content=\"width=device-width,initial-scale=1\"><title>AI Crypto Agents Log</title><style>body{{font-family:monospace;line-height:1.6;padding:20px;max-width:900px;margin:0 auto;background-color:#0a0a0a;color:#0f0}}h1,h2{{color:#0f0;border-bottom:1px solid #0c0;padding-bottom:5px}}#log,#terminal{{border:1px solid #0c0;padding:15px;margin-bottom:20px;border-radius:8px;height:400px;overflow-y:auto;background-color:#001a00;font-size:.9em}}#synopsis{{border:1px solid #0c0;padding:15px;margin-top:20px;background-color:#001a00;border-radius:8px}}.interaction{{margin-bottom:15px;padding-bottom:10px;border-bottom:1px dotted #030}}.timestamp{{color:#090;font-size:.8em}}.agent{{font-weight:700;color:#3c3}}.topic{{font-style:italic;color:#0a0;margin:5px 0}}#status{{color:#f33;font-weight:700;text-align:center;padding:10px;background-color:#1a0000;border-radius:5px;margin-bottom:10px}}pre{{white-space:pre-wrap;word-wrap:break-word;color:#cfc}}</style></head><body><h1>AI Crypto Agents Log</h1><div id=status>Connecting...</div><h2>System Terminal</h2><div id=terminal><p>Terminal init...</p></div><h2>Agent Discussion</h2><div id=log><p>Log init...</p></div><h2>Daily Synopsis</h2><div id=synopsis><p>Synopsis init...</p></div><script>const term=document.getElementById('terminal'),logDiv=document.getElementById('log'),synDiv=document.getElementById('synopsis'),statDiv=document.getElementById('status');let sock;function fmt(t){{if('string'!=typeof t)t=String(t);return t.replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\\n/g,'<br>').replace(/    /g,'&nbsp;&nbsp;&nbsp;&nbsp;')}}function appTerm(t){{const e=document.createElement('p');e.innerHTML=fmt(t),term.appendChild(e),term.scrollTop=term.scrollHeight}}function appLog(t){{const e=document.createElement('div');e.classList.add('interaction'),e.innerHTML=`<p class=timestamp>${{new Date(t.timestamp).toLocaleString()}}</p><p class=agent>@${{t.social_handle}} (${{t.agent}})</p><p class=topic>Topic: ${{fmt(t.topic)}}</p><pre>${{fmt(t.response)}}</pre>`,logDiv.appendChild(e),logDiv.scrollTop=logDiv.scrollHeight}}function updSyn(t){{synDiv.innerHTML=`<h2>Daily Synopsis</h2><pre>${{fmt(t)}}</pre>`}}function connSock(){{const t=window.location.protocol==='https:'?'wss:':'ws:',e=document.domain||window.location.hostname||'localhost',o={ws_port};sock=new WebSocket(`${{t}}//${{e}}:${{o}}`),sock.onopen=function(t){{statDiv.textContent='Live feed connected.';statDiv.style.color='#3c3';statDiv.style.backgroundColor='#001a00';console.log('WS connected');appTerm('WS connected.')}},sock.onmessage=function(t){{try{{const e=JSON.parse(t.data);'interaction'===e.type?appLog(e.content):'synopsis'===e.type?updSyn(e.content):'message'===e.type&&appTerm(e.content)}}catch(e){{console.error('Error parsing JSON/UI update:',e,'Data:',t.data);appTerm(`Error processing message: ${{t.data}}`)}}}},sock.onclose=function(t){{statDiv.textContent='Live feed disconnected. Retrying in 5s...';statDiv.style.color='#f33';statDiv.style.backgroundColor='#1a0000';console.log('WS closed. Reconnecting...');appTerm('WS closed. Reconnecting...');setTimeout(connSock,5e3)}},sock.onerror=function(t){{console.error('WS error:',t);statDiv.textContent='WS conn error.';statDiv.style.color='#f33';appTerm(`WS error: ${{t.message||'Unknown'}}`)}}}}connSock();</script></body></html>"""
        try:
            with open(fn,'w',encoding='utf-8')as f:f.write(html)
            print(f"HTML log page generated: {fn}")
        except Exception as e:print(f"Error writing HTML file '{fn}': {e}")

    def push_to_social_networks(self):
        if not self.synopsis:print("No synopsis to push.");return
        for cfg in self.evm_config.get("social_media_platforms",[]):print(f"SIMULATING: Pushing synopsis to {cfg.get('name','N/A')}...")
    async def register(self,ws):self.websocket_clients.add(ws);await self.log_message(f"Client {ws.remote_address} connected. Total:{len(self.websocket_clients)}",level="DEBUG")
    async def unregister(self,ws):self.websocket_clients.discard(ws);await self.log_message(f"Client {ws.remote_address} disconnected. Total:{len(self.websocket_clients)}",level="DEBUG")
    async def broadcast(self,msg:Dict):
        if self.websocket_clients:
            for c in list(self.websocket_clients):
                try:await asyncio.wait_for(c.send(json.dumps(msg)),timeout=1.0)
                except Exception:self.websocket_clients.discard(c)
    def push_to_api(self,data:Dict):
        ep=self.evm_config.get("external_api_endpoint")
        if not ep:return
        try:
            r=requests.post(ep,json=data,timeout=self.evm_config.get("api_timeout_seconds",10))
            if r.status_code<300:print(f"Pushed to {ep} for {data['agent']}. Status:{r.status_code}")
            else:print(f"Failed push to {ep} for {data['agent']}. Status:{r.status_code}, Resp:{r.text[:100]}")
        except Exception as e:print(f"Error pushing to {ep} for {data['agent']}: {e}")

async def start_websocket_server(ag_instance:AgentGroup):
    global websocket_server_running
    async def ws_handler(ws,path):await ag_instance.register(ws);try:await ws.wait_closed()finally:await ag_instance.unregister(ws)
    if websocket_server_running:await ag_instance.log_message("WS server already running.","WARN");return
    websocket_server_running=True;host,port=ag_instance.evm_config.get("websocket_host","localhost"),ag_instance.evm_config.get("websocket_port",8765)
    try:server=await websockets.serve(ws_handler,host,port);await ag_instance.log_message(f"WS server on ws://{host}:{port}","INFO");await server.wait_closed()
    except Exception as e:await ag_instance.log_message(f"WS server error:{e}","CRITICAL")
    finally:websocket_server_running=False;await ag_instance.log_message("WS server shut down.","INFO")

def run_http_server(html_path:str,ag_instance:AgentGroup):
    global http_server_running
    if http_server_running:print("HTTP server already running.");return
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self,*a,**kw):super().__init__(*a,directory=os.path.dirname(os.path.abspath(html_path))or'.',**kw)
        def do_GET(self):
            if self.path=='/':self.path=os.path.basename(html_path)
            super().do_GET()
    host,port=ag_instance.evm_config.get("http_host","localhost"),ag_instance.evm_config.get("http_port",8000)
    for attempt in range(3):
        curr_port=port+attempt
        try:
            with socketserver.TCPServer((host,curr_port),Handler)as httpd:http_server_running=True;print(f"HTTP server: http://{host}:{curr_port}/{os.path.basename(html_path)}");httpd.serve_forever();break
        except OSError as e:
            if e.errno in[98,10048]:print(f"HTTP Port {curr_port} in use. Trying next...")
            else:print(f"HTTP server OSError:{e}");break
        except Exception as e:print(f"HTTP server error:{e}");break
    if not http_server_running:print("HTTP server failed to start.")
    http_server_running=False

async def main():
    gemini_key=os.getenv("GEMINI_API_KEY");
    if not gemini_key:print("CRITICAL: GEMINI_API_KEY env var not set.");return
    agent_defs=[{"name":"AlphaSeeker","role":"Identifies trends & proposes trades. Must use ANALYSIS_TOKEN first.","social_handle":"AlphaSeekerBot"},
                  {"name":"RiskGuard","role":"Analyzes trade risks & token safety. Votes diligently.","social_handle":"RiskGuardBot"},
                  {"name":"PortfolioOptimus","role":"Develops strategies, suggests rebalancing trades. Checks analysis.","social_handle":"PortfolioOptBot"}]
    try:btc_p=float(os.getenv("MOCK_BTC_PRICE_USD","60000"));usd_v=float(os.getenv("MOCK_INITIAL_USD_FUND","1000"));init_btc=usd_v/btc_p if btc_p>0 else .0001
    except Exception as e:print(f"Warn:Sim funding error({e}).Defaulting.");init_btc=.0001
    ag=AgentGroup(agent_defs,initial_simulated_btc_amount=init_btc)
    html_fn="crypto_discussion_log.html";ag.generate_seo_friendly_html(html_fn)
    await ag.log_message("Init AI Agent Group & services...","INFO")
    ws_task=asyncio.create_task(start_websocket_server(ag))
    http_thread=threading.Thread(target=run_http_server,args=(html_fn,ag),daemon=True);http_thread.start()
    await asyncio.sleep(1)
    if not websocket_server_running:await ag.log_message("WS server failed. Live HTML impaired.","CRITICAL")
    n_days=ag.evm_config.get("discussion_simulation_days",1);await ag.autonomous_discussion(num_simulation_days=n_days)
    await ag.log_message("Discussion complete. Shutting down...","INFO")
    if ws_task and not ws_task.done():
        ws_task.cancel();
        try:await ws_task
        except asyncio.CancelledError:await ag.log_message("WS server task cancelled.","INFO")
        except Exception as e:await ag.log_message(f"Error during WS shutdown:{e}","ERROR")
    ag.export_discussion_log();await ag.log_message("Script finished.","INFO")

if __name__=="__main__":
    try:asyncio.run(main())
    except KeyboardInterrupt:print("\nApp interrupted. Shutting down...")
    except Exception as e:print(f"CRITICAL ERROR in __main__:{type(e).__name__}-{e}");import traceback;traceback.print_exc()
    finally:print("App exit.")
```

[end of ai_agent.py]
