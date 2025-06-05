"""
ai_agent.py: Main script for AI agent group simulation and EVM interaction.

This script orchestrates a group of AI agents that discuss cryptocurrency trends,
propose trades, vote on them, and can execute approved trades on EVM-compatible
blockchains via `evm_utils.py`. It also supports fetching token security and
pair data via `token_analyzer.py`.

--------------------------------------------------------------------------------
Quick Start / How to Use:
--------------------------------------------------------------------------------
1.  **Configure Environment:**
    *   Copy `config.json.example` to `config.json`.
    *   **CRITICAL**: Fill `config.json` with your details, ESPECIALLY for a
        TESTNET (e.g., Sepolia, Polygon Mumbai). This includes:
        *   `rpc_urls`: Valid RPC endpoint URLs for your chosen networks.
        *   `chain_ids`: Correct chain IDs for those networks.
        *   `private_key`: A **TESTNET** private key.
            **SECURITY WARNING**: For any real value or mainnet interaction,
            DO NOT put your private key directly in `config.json`. Instead, set it as an
            environment variable `EVM_PRIVATE_KEY`. The script prioritizes this env var.
            If using `config.json` for a testnet key, ensure it's in your `.gitignore`.
        *   `dex_routers` and `token_addresses`: Correct contract addresses for your
            chosen testnet(s).
        *   `goplus_api_key` (under `token_analysis_apis.goplus_security`): Your API key
            from GoPlus Security (https://gopluslabs.io/) for token analysis.
    *   Set the `GEMINI_API_KEY` environment variable with your Google Gemini API key.

2.  **Install Dependencies:**
    *   `pip install google-generativeai web3 websockets requests python-dotenv`
    *   (Consider a `requirements.txt` for managing dependencies).

3.  **Verify EVM Utilities (Recommended):**
    *   Run `python test_evm_utils.py`.
    *   This script helps test your `config.json` setup and basic EVM functions
        against your chosen testnet. Follow its interactive prompts.

4.  **Verify Token Analyzer (Recommended):**
    *   Run `python test_token_analyzer.py`.
    *   This tests GoPlus and DexScreener API calls. Requires GoPlus API key in `config.json`
        or as `GOPLUS_API_KEY` environment variable for full security analysis testing.

5.  **Run the AI Agent Simulation:**
    *   `python ai_agent.py`
    *   The agents will begin their discussion process. They can request token analysis
        using `ANALYZE_TOKEN: <TOKEN_ADDRESS> <CHAIN_NAME>`.
    *   If on-chain transactions are proposed and approved, and your `config.json` is
        set up for a funded testnet wallet, the script will attempt to execute these trades.

--------------------------------------------------------------------------------
IMPORTANT SECURITY AND OPERATIONAL NOTES:
--------------------------------------------------------------------------------
1.  LIVE TRADING RISK: If configured with a mainnet RPC and a private key
    holding real funds (STRONGLY DISCOURAGED FOR MOST USERS), this system
    COULD EXECUTE REAL FINANCIAL TRANSACTIONS. Automated systems are complex and
    can lead to losses due to bugs, market volatility, or flawed agent logic.

2.  PRIVATE KEY SECURITY: The security of the private key is PARAMOUNT.
    Refer to the "Quick Start" section for best practices. Accidental exposure
    of a private key for a funded wallet will likely result in permanent loss
    of those funds. The system prioritizes `EVM_PRIVATE_KEY` env var over `config.json`.

3.  TESTNET FIRST: Always thoroughly test on an EVM-compatible TESTNET
    before even considering mainnet operations with real funds.

4.  ISOLATED WALLET: For any mainnet experimentation, use a dedicated,
    isolated wallet with a VERY LIMITED amount of funds that you are
    entirely prepared to lose.

5.  NO LIABILITY: This software is provided "as-is". The authors and
    contributors disclaim all liability for any financial losses or other
    damages incurred through its use. USE AT YOUR OWN RISK.
--------------------------------------------------------------------------------
"""
# /*-----------------------------------------------------------------------    # |                    **Token Analysis Features**                        |
# |-----------------------------------------------------------------------|
# | This system integrates token analysis capabilities to help AI agents  |
# | make more informed decisions and avoid risky assets.                  |
# |                                                                       |
# | **Key Components:**                                                   |
# | - `token_analyzer.py`: Module responsible for fetching data from:     |
# |   - GoPlus Security: For detailed smart contract security analysis    |
# |     (honeypots, taxes, LP status, vulnerabilities, etc.).             |
# |     Requires API key.                                                 |
# |   - DexScreener: For real-time trading pair data (liquidity, volume,  |
# |     pair age, etc.). Public API used, no key needed for basic calls.  |
# |                                                                       |
# | **Agent Interaction:**                                                |
# | - Agents can request analysis for a token using the command:          |
# |   `ANALYZE_TOKEN: <TOKEN_ADDRESS> <CHAIN_NAME>`                       |
# |   (e.g., `ANALYZE_TOKEN: 0x..... ethereum`)                           |
# |   Valid chain names are defined in `config.json` or `AgentGroup`.     |
# | - Analysis results (summaries) are added to                           |
# |   `available_token_analyses_summary` in the agent context.            |
# | - Agents are prompted to check this summary before proposing trades   |
# |   or voting on transactions.                                          |
# |                                                                       |
# | **Configuration (IMPORTANT for GoPlus):**                             |
# | - A GoPlus Security API key is REQUIRED for security analysis.        |
# |   1. Sign up at `https://gopluslabs.io/`.                             |
# |   2. Obtain your API Key from your GoPlus dashboard.                  |
# |   3. Add it to `config.json` under `token_analysis_apis.goplus_security.api_key` |
# |      OR set it as an environment variable `GOPLUS_API_KEY` (recommended). |
# |      The environment variable takes precedence.                         |
# |                                                                       |
# | **Safety Features:**                                                  |
# | - `AgentGroup.propose_trade` includes pre-validation to automatically |
# |   reject trades for tokens identified as honeypots, having excessive  |
# |   taxes (>25%), or critical security warnings from GoPlus.            |
# | - This system check applies to the *output token* of a trade if it's  |
# |   not on a predefined 'safe list' (e.g., WETH, major stablecoins).     |
# |                                                                       |
# | **Testing:**                                                          |
# | - Use `test_token_analyzer.py` to test the analyzer functions         |
# |   directly (requires configured API key for GoPlus).                  |
# | - Follow manual test cases outlined in `test_token_analyzer.py` to    |
# |   verify agent integration and decision-making based on analysis.     |
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
from typing import List, Dict, Optional, Any

from evm_utils import (
    connect_to_network, load_wallet, execute_trade,
    get_token_balance, approve_token, load_config
)
from token_analyzer import (
    fetch_token_security_report, fetch_pairs_for_token,
    TokenSecurityReport, PairReport
)

websocket_server_running = False
http_server_running = False

class AIAgent:
    """
    Represents an AI agent with a role, processing inputs and voting on transactions.
    Now includes awareness of token analysis features.
    """
    def __init__(self, name: str, role: str, api_key: str, social_handle: str,
                 valid_chain_names_for_analysis: Optional[List[str]] = None):
        """
        Initializes an AI Agent.
        Args:
            name (str): Name of the agent.
            role (str): Role of the agent.
            api_key (str): API key for the generative AI model.
            social_handle (str): Social media handle for the agent.
            valid_chain_names_for_analysis (Optional[List[str]]): List of chain names
                agents can request analysis for (e.g., ['ethereum', 'polygon']).
        """
        self.name = name
        self.role = role
        self.social_handle = social_handle
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-pro')
        self.valid_chain_names_for_analysis = valid_chain_names_for_analysis or \
            ["ethereum", "bsc", "polygon", "arbitrum", "base", "sepolia", "polygon_mumbai"] # Fallback

    def process_input(self, input_text: str, context: Dict) -> str:
        """
        Generates a response based on input text and current context.
        Guides agent to use token analysis before proposing trades.
        """
        prompt_context = context.copy()
        prompt_context['valid_analysis_chain_names'] = self.valid_chain_names_for_analysis

        prompt = f"""As AI Agent '{self.name}' (@{self.social_handle}), your role is '{self.role}'.
Analyze the provided input within the current financial/crypto market context.
The context includes portfolio summaries, trends, and summaries of available token analyses.

**IMPORTANT**: Before proposing any TRADE or making decisions about specific tokens, you MUST:
1.  Check the `available_token_analyses_summary` in the Current Context below.
2.  If a token has a security summary:
    *   **AVOID proposing actions for tokens flagged as `is_honeypot: true`.**
    *   **AVOID tokens with `buy_tax_percent` or `sell_tax_percent` greater than 20% unless you have an extremely strong, explicitly stated justification.**
    *   **HEAVILY CONSIDER any warnings listed (e.g., `warnings_count`, `top_warnings`).**
3.  If analysis for a token is missing or outdated, you can request it.
When you use information from an analysis (or note its absence), briefly mention it in your reasoning (e.g., "Token X analysis shows low risk, so I propose..." or "No analysis for Token Y, requesting it first...").

Current Context:
{json.dumps(prompt_context, indent=2, default=str)}

Input for your consideration:
"{input_text}"

Your tasks:
1. Provide expert analysis, recommendations, or comments based on your role.
2. If you need security and liquidity data for a token to make a sound decision, request it using:
   `ANALYZE_TOKEN: <TOKEN_ADDRESS> <CHAIN_NAME>`
   (Example: `ANALYZE_TOKEN: 0x6982508145454Ce325dDbE47a25d4ec3d2311933 ethereum`)
   Valid chain names: {', '.join(self.valid_chain_names_for_analysis)}.
3. If proposing a trade, use the EXACT format:
   `TRADE: <INPUT_TOKEN_SYMBOL_OR_ADDRESS> <OUTPUT_TOKEN_SYMBOL_OR_ADDRESS> <INPUT_AMOUNT> <NETWORK_NAME> <DEX_NAME>`
   (Example: `TRADE: WETH 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48 1.0 ethereum uniswap_v2`)
   (Note: For common tokens like WETH, USDC, use symbol. For less common tokens, prefer using their full ADDRESS.)

Include relevant hashtags and mentions in your main response.
Your Response:"""

        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            error_message = f"Error in {self.name} (process_input): {type(e).__name__} - {e}"
            print(error_message)
            return f"Error: Could not generate content. Details: {error_message}"

    def vote_on_transaction(self, transaction: Dict, context: Dict) -> str:
        """
        Generates a vote (APPROVE/REJECT) and reasoning for a proposed transaction.
        Guides agent to use token analysis for voting.
        """
        prompt = f"""As AI Agent '{self.name}' ({self.role}), evaluate the following proposed transaction.
**CRITICAL VOTING INSTRUCTION**: Before casting your vote, you MUST review any available token analysis for the assets involved. Check the 'available_token_analyses_summary' in the Context below.
- If analysis indicates HIGH RISK (e.g., `is_honeypot: true`, excessive taxes >20%, critical security warnings), you should generally REJECT unless there's an overwhelmingly strong, stated rationale from the proposer that explicitly addresses and justifies these risks.
- Your reasoning for APPROVE/REJECT MUST state that you consulted the analysis (or noted its absence) and how any findings (or lack thereof) influenced your decision.

Transaction Details:
{json.dumps(transaction, indent=2)}

Current Market & Portfolio Context (including available token analysis summaries):
{json.dumps(context, indent=2, default=str)}

Your Vote (Format: Single line "APPROVE" or "REJECT", followed by detailed reasoning on new lines):"""

        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            error_message = f"Error in {self.name} (vote_on_transaction): {type(e).__name__} - {e}"
            print(error_message)
            return f"REJECT - Error during voting: {error_message}"


class CryptoPortfolio:
    """Manages simulated cryptocurrency holdings and transaction history."""
    def __init__(self):
        self.holdings: Dict[str, float] = {}
        self.transaction_history: List[Dict] = []

    def update_holding(self, crypto_symbol: str, amount_change: float):
        current_balance = self.holdings.get(crypto_symbol, 0.0)
        new_balance = current_balance + amount_change
        if abs(new_balance) < 1e-12:
            if crypto_symbol in self.holdings: del self.holdings[crypto_symbol]
        else:
            self.holdings[crypto_symbol] = new_balance
            if new_balance < 0: print(f"Warning: Simulated holding for {crypto_symbol} is negative: {new_balance:.18f}")
        self.transaction_history.append({
            "date": datetime.now().isoformat(), "crypto": crypto_symbol,
            "amount_change": amount_change, "new_simulated_balance": self.holdings.get(crypto_symbol, 0.0)
        })

    def get_portfolio_summary(self) -> str: return json.dumps(self.holdings)
    def get_transaction_history(self) -> str: return json.dumps(self.transaction_history)


class MultisigWallet:
    """Simulates a conceptual multi-signature wallet for transaction proposals and voting."""
    def __init__(self, agents: List[AIAgent], required_signatures: int):
        self.agents = agents; self.required_signatures = required_signatures
        self.pending_transactions: List[Dict] = []

    def propose_transaction(self, transaction_data: Dict):
        tx_id = f"tx_{int(time.time())}_{random.randint(1000,9999)}"
        proposal = {"id": tx_id, "transaction": transaction_data, "votes": [], "status": "pending"}
        self.pending_transactions.append(proposal)
        print(f"Transaction proposed (ID: {tx_id}): {json.dumps(transaction_data)}")

    def vote_on_transactions(self, context: Dict):
        for tx_w in self.pending_transactions: # tx_w for tx_wrapper
            if tx_w["status"] == "pending":
                voted_agents = {v['agent'] for v in tx_w['votes']}
                for agent in self.agents:
                    if agent.name not in voted_agents:
                        vote_resp = agent.vote_on_transaction(tx_w["transaction"], context)
                        tx_w["votes"].append({"agent": agent.name, "vote": vote_resp})
                        print(f"Agent {agent.name} voted on Tx {tx_w['id']}: '{vote_resp.splitlines()[0]}'")

                approvals = sum(1 for v in tx_w["votes"] if v["vote"].strip().upper().startswith("APPROVE"))
                rejects = sum(1 for v in tx_w["votes"] if v["vote"].strip().upper().startswith("REJECT"))
                n_agents = len(self.agents)

                if approvals >= self.required_signatures: tx_w["status"] = "approved"; print(f"Tx {tx_w['id']} APPROVED ({approvals}/{n_agents}).")
                elif rejects > (n_agents - self.required_signatures) or len(tx_w['votes']) == n_agents:
                    tx_w["status"] = "rejected"; print(f"Tx {tx_w['id']} REJECTED (A:{approvals},R:{rejects},TotalV:{len(tx_w['votes'])}).")

    def get_approved_transactions(self) -> List[Dict]:
        return [tx_w for tx_w in self.pending_transactions if tx_w["status"] == "approved"]

    def mark_transaction_processed(self, tx_id: str, status: str, hash_val: Optional[str]=None, err_msg: Optional[str]=None):
        for tx_w in self.pending_transactions:
            if tx_w["id"] == tx_id:
                tx_w["status"] = status
                if hash_val: tx_w["tx_hash"] = hash_val
                if err_msg: tx_w["error_message"] = err_msg
                print(f"Tx {tx_id} status: {status}"); break

    def clear_finalized_transactions(self): # Periodically clean up fully processed tx
        count = len(self.pending_transactions)
        self.pending_transactions = [tx_w for tx_w in self.pending_transactions if tx_w["status"] in ["pending", "approved"]]
        if count - len(self.pending_transactions) > 0: print(f"Cleared {count - len(self.pending_transactions)} finalized txs.")


class AgentGroup:
    """
    Manages AI agents, discussions, context (including token analysis),
    and orchestrates trade proposals and execution. Includes safety checks.
    WARNING: Live trading risks apply if configured for mainnet.
    """
    SAFE_OUTPUT_TOKENS_BY_CHAIN: Dict[str, List[str]] = { # Addresses should be checksummed
        "ethereum": [ # Mainnet Ethereum
            "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", # WETH
            "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", # USDC
            "0xdAC17F958D2ee523a2206206994597C13D831ec7", # USDT
            "0x6B175474E89094C44Da98b954EedeAC495271d0F"  # DAI
        ],
        "polygon": [ # Polygon PoS
            "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270", # WMATIC
            "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359", # USDC (Native)
            "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"  # USDT (Bridged)
        ],
        "sepolia": [ # Sepolia Testnet - these are examples, verify addresses
            "0x7b79995e5f793A07Bc00c21412e50Ea00A78R7Sp", # WETH on Sepolia (example, verify)
            # Add common testnet stablecoin addresses for Sepolia if available
        ],
        "polygon_mumbai": [ # Polygon Mumbai Testnet
            "0x9c3C9283D3e44854697Cd22D3Faa240Cfb032889", # WMATIC on Mumbai
            # Add common testnet stablecoin addresses for Mumbai
        ]
    }

    def __init__(self, agents_definitions: List[Dict], initial_simulated_btc_amount: float):
        self.evm_config = load_config()
        if not self.evm_config:
            print("CRITICAL WARNING: EVM config (`config.json`) not found/loaded. Functionality impaired.")
            self.evm_config = {}

        # Defines mapping from user-friendly chain names to API-specific chain IDs.
        self.CHAIN_NAME_TO_ID_MAP = self.evm_config.get("chain_name_to_id_map", {
            "ethereum": {"goplus": "1", "dexscreener": "ethereum"}, "bsc": {"goplus": "56", "dexscreener": "bsc"},
            "polygon": {"goplus": "137", "dexscreener": "polygon"}, "arbitrum": {"goplus": "42161", "dexscreener": "arbitrum"},
            "optimism": {"goplus": "10", "dexscreener": "optimism"}, "avalanche": {"goplus": "43114", "dexscreener": "avalanche"},
            "base": {"goplus": "8453", "dexscreener": "base"}, "fantom": {"goplus": "250", "dexscreener": "fantom"},
            "sepolia": {"goplus": "11155111", "dexscreener": "ethereum"}, "polygon_mumbai": {"goplus": "80001", "dexscreener": "polygon"}
        })

        gemini_api_key = os.getenv("GEMINI_API_KEY")
        valid_chain_names = list(self.CHAIN_NAME_TO_ID_MAP.keys())
        self.agents = [ # Agents re-initialized with chain map knowledge
            AIAgent(d["name"], d["role"], gemini_api_key, d["social_handle"],
                    valid_chain_names_for_analysis=valid_chain_names)
            for d in agents_definitions
        ]

        self.portfolio = CryptoPortfolio()
        self.simulated_fund_usd = 0.0
        if initial_simulated_btc_amount > 0: self.portfolio.update_holding("BTC", initial_simulated_btc_amount)

        # Context for agents, including token analysis placeholders
        self.context: Dict[str, Any] = {
            "portfolio_summary": self.portfolio.get_portfolio_summary(),
            "simulated_fund_usd": self.simulated_fund_usd,
            "token_analysis_reports": {}, # Stores full reports: {token_addr: {'security': TokenSecurityReport, 'pairs': List[PairReport]}}
            "available_token_analyses_summary": {}, # Stores brief summaries for LLM: {token_addr: {'security_summary': {...}, 'pair_info_summary': {...}}}
            "recent_discussion_topics": [], "market_news_feed": [], "key_support_resistance": {},
            "valid_analysis_chain_names": valid_chain_names
        }

        num_agents = len(self.agents)
        default_req_sigs = 1 if num_agents <= 1 else min(num_agents, 2)
        req_sigs = max(1, min(num_agents, self.evm_config.get("multisig_required_signatures", default_req_sigs)))
        self.multisig_wallet = MultisigWallet(self.agents, required_signatures=req_sigs)

        self.discussion_log: List[Dict] = []
        self.current_day = 1
        self.websocket_clients = set()
        self.synopsis = ""
        self.discussion_state_file = "discussion_state.json"

    def save_state(self):
        state = {
            "current_day": self.current_day, "discussion_log": self.discussion_log,
            "context": {
                "portfolio_summary": self.context.get("portfolio_summary"), "simulated_fund_usd": self.context.get("simulated_fund_usd"),
                "recent_discussion_topics": self.context.get("recent_discussion_topics"), "market_news_feed": self.context.get("market_news_feed"),
                "key_support_resistance": self.context.get("key_support_resistance"),
                "available_token_analyses_summary": self.context.get("available_token_analyses_summary") # Save summaries
            },
            "portfolio_holdings": self.portfolio.holdings, "simulated_fund_usd": self.simulated_fund_usd,
            "pending_transactions": self.multisig_wallet.pending_transactions
        }
        try:
            with open(self.discussion_state_file, 'w') as f: json.dump(state, f, indent=2, default=str)
        except Exception as e: print(f"Error saving state: {e}")

    def load_state(self):
        if os.path.exists(self.discussion_state_file):
            try:
                with open(self.discussion_state_file, 'r') as f: state = json.load(f)
                self.current_day = state.get('current_day', 1)
                self.discussion_log = state.get('discussion_log', [])
                loaded_ctx = state.get('context', {})
                self.context.update(loaded_ctx) # Merge loaded context, specific keys below ensure defaults
                self.context.setdefault("token_analysis_reports", {}) # Ensure this exists
                self.context.setdefault("available_token_analyses_summary", {})
                self.portfolio.holdings = state.get('portfolio_holdings', {})
                self.simulated_fund_usd = state.get('simulated_fund_usd', 0.0)
                self.multisig_wallet.pending_transactions = state.get('pending_transactions', [])
                self.context["portfolio_summary"] = self.portfolio.get_portfolio_summary() # Refresh from actual holdings
                self.context["simulated_fund_usd"] = self.simulated_fund_usd
                self.context["valid_analysis_chain_names"] = list(self.CHAIN_NAME_TO_ID_MAP.keys())
                print(f"AgentGroup state loaded. Resuming from Day {self.current_day}.")
                return True
            except Exception as e: print(f"Error loading state: {e}. Starting fresh."); self.context["token_analysis_reports"]={}; self.context["available_token_analyses_summary"]={}
        else: print("No saved state. Starting fresh."); self.context["token_analysis_reports"]={}; self.context["available_token_analyses_summary"]={}
        return False

    async def log_message(self, message: str, level: str ="INFO"):
        log_entry = f"[{level}] {datetime.now().isoformat()}: {message}"; print(log_entry)
        await self.broadcast({"type": "message", "content": log_entry})

    async def log_interaction(self, agent: AIAgent, topic: str, response: str):
        interaction = {"timestamp":datetime.now().isoformat(),"agent":agent.name,"social_handle":agent.social_handle,"topic":topic,"response":response}
        self.discussion_log.append(interaction)
        print(f"@{agent.social_handle} (Topic: {topic.strip()[:30]}...): {response.strip().splitlines()[0][:80]}...")
        await self.broadcast({"type": "interaction", "content": interaction}); self.push_to_api(interaction)

    async def autonomous_discussion(self, num_simulation_days: int):
        """Main simulation loop. WARNING: Can trigger real trades if configured."""
        await self.log_message(f"Starting autonomous discussion for {num_simulation_days} day(s)...", level="WARNING")
        if self.load_state(): await self.log_message(f"Resumed from Day {self.current_day}.", level="INFO")
        self.context['valid_analysis_chain_names'] = list(self.CHAIN_NAME_TO_ID_MAP.keys())

        end_day = self.current_day + num_simulation_days
        while self.current_day < end_day:
            await self.log_message(f"\n--- Starting Simulation Day {self.current_day} ---", level="INFO")
            await self.daily_discussion_cycle()
            await self.generate_synopsis()
            self.save_state()
            await self.log_message(f"--- End of Simulation Day {self.current_day}. State saved. ---", level="INFO")
            if self.current_day < end_day -1 : await asyncio.sleep(self.evm_config.get("pause_between_days_seconds", 2))
            self.current_day += 1

    async def daily_discussion_cycle(self):
        """A single day's cycle of discussion, analysis, voting, and execution."""
        if self.current_day == 1 or self.evm_config.get("run_daily_scenario", False): await self.simulate_scenario_discussion()
        num_rounds = self.evm_config.get("discussion_rounds_per_day", 2)
        for i in range(num_rounds):
            await self.log_message(f"Day {self.current_day}, Discussion Round {i+1}/{num_rounds} starting...", level="DEBUG")
            for agent in self.agents:
                topic = self.generate_topic_for_agent(agent)
                self.context['available_token_analyses_summary'] = self.context.get('available_token_analyses_summary', {}) # Ensure present
                response = agent.process_input(topic, self.context)
                await self.log_interaction(agent, topic, response)
                await self.update_context_with_responses([response])
        await self.log_message(f"Day {self.current_day}: Voting on proposed transactions...", level="INFO")
        self.multisig_wallet.vote_on_transactions(self.context)
        await self.execute_approved_transactions()

    async def simulate_scenario_discussion(self):
        asset = random.choice(["ETH", "SOL", "AVAX", "LINK", "ARB", "OP"])
        scenario = (f"Hypothetical Scenario (Day {self.current_day}): Major CEX '{random.choice(['Coinbase', 'Binance', 'Kraken'])}' "
                    f"announces unexpected regulatory scrutiny. Discuss market impact and potential safe-haven assets like {asset}.")
        await self.log_message(f"Presenting scenario: {scenario}", level="INFO")
        responses = []
        for agent in self.agents:
            resp = agent.process_input(scenario, self.context); await self.log_interaction(agent, f"Scenario: CEX Scrutiny & {asset}", resp)
            responses.append({"agent": agent.name, "response": resp})
        self.context.setdefault("daily_scenarios", []).append({"day": self.current_day, "scenario": scenario, "responses": responses})

    def generate_topic_for_agent(self, agent: AIAgent) -> str:
        """Generates a relevant discussion topic for an agent."""
        topics = [
            "Market sentiment check: Bullish, Bearish, or Indecisive? Key indicators?",
            "Identify a crypto narrative gaining traction. How can we capitalize or mitigate risk?",
            f"Request analysis for a token of interest: `ANALYZE_TOKEN: <ADDRESS> <CHAIN_NAME>`. Valid chains: {', '.join(agent.valid_chain_names_for_analysis)}",
            "Propose a DEX trade considering our portfolio and recent analyses: `TRADE: <IN_TOKEN> <OUT_TOKEN> <AMOUNT> <NETWORK> <DEX>`",
            "Review our `available_token_analyses_summary`. Any insights for immediate action?"
        ]
        return random.choice(topics)

    async def update_context_with_responses(self, responses: List[str]):
        """Processes agent responses for commands and updates shared context."""
        for resp_text in responses:
            # Simplified parsing for keywords
            if "TRADE:" in resp_text: self.propose_trade(resp_text.split("TRADE:", 1)[1].strip())

            if "ANALYZE_TOKEN:" in resp_text:
                try:
                    cmd_part = resp_text.split("ANALYZE_TOKEN:", 1)[1].strip()
                    parts = cmd_part.split()
                    if len(parts) == 2:
                        token_addr, chain_name = parts[0].strip(), parts[1].strip().lower()
                        await self.log_message(f"Agent requested analysis: {token_addr} on {chain_name}", level="INFO")

                        if chain_name not in self.CHAIN_NAME_TO_ID_MAP:
                            await self.log_message(f"Unsupported chain for analysis: {chain_name}. Valid: {list(self.CHAIN_NAME_TO_ID_MAP.keys())}", level="WARNING")
                            self.context["available_token_analyses_summary"].setdefault(token_addr, {})["error"] = f"Unsupported chain: {chain_name}"
                            continue

                        self.context["token_analysis_reports"].setdefault(token_addr, {})
                        self.context["available_token_analyses_summary"].setdefault(token_addr, {})

                        goplus_id = self.CHAIN_NAME_TO_ID_MAP[chain_name]["goplus"]
                        sec_report: Optional[TokenSecurityReport] = await asyncio.to_thread(fetch_token_security_report, token_addr, goplus_id)
                        if sec_report:
                            self.context["token_analysis_reports"][token_addr]["security"] = sec_report
                            self.context["available_token_analyses_summary"][token_addr]["security_summary"] = {
                                "is_honeypot":sec_report.get("is_honeypot"),"buy_tax_percent":(sec_report.get("buy_tax")or 0)*100,
                                "sell_tax_percent":(sec_report.get("sell_tax")or 0)*100,"warnings_count":len(sec_report.get("warnings",[])),
                                "top_warnings":sec_report.get("warnings",[])[:2],"retrieved_at":sec_report.get("retrieved_at")
                            }
                            await self.log_message(f"Security report for {token_addr} updated.",level="INFO")
                        else:
                            await self.log_message(f"Failed to fetch GoPlus security report for {token_addr}.",level="WARNING")
                            self.context["available_token_analyses_summary"][token_addr]["security_summary"] = "Error fetching."

                        dex_chain_name = self.CHAIN_NAME_TO_ID_MAP[chain_name]["dexscreener"]
                        pair_reps: List[PairReport] = await asyncio.to_thread(fetch_pairs_for_token, token_addr, dex_chain_name)
                        if pair_reps:
                            self.context["token_analysis_reports"][token_addr]["pairs"] = pair_reps
                            self.context["available_token_analyses_summary"][token_addr]["pair_info_summary"] = {
                                "pair_count":len(pair_reps),"total_liquidity_usd":sum(p.get('liquidity_usd',0)or 0 for p in pair_reps),
                                "top_pair_liq_usd":pair_reps[0].get("liquidity_usd")if pair_reps else None,
                                "newest_pair_created_ts":pair_reps[0].get("pair_created_at")if pair_reps else None
                            }
                            await self.log_message(f"Pair reports for {token_addr} updated (Count: {len(pair_reps)}).",level="INFO")
                        else:
                            await self.log_message(f"Failed to fetch DexScreener pairs for {token_addr}.",level="WARNING")
                            self.context["available_token_analyses_summary"][token_addr]["pair_info_summary"] = "Error fetching."
                    else: await self.log_message(f"Invalid ANALYZE_TOKEN format: '{cmd_part}'. Expected <ADDRESS> <CHAIN_NAME>.",level="WARNING")
                except Exception as e: await self.log_message(f"Error processing ANALYZE_TOKEN ('{resp_text}'): {e}",level="ERROR")

        self.context["portfolio_summary"] = self.portfolio.get_portfolio_summary()
        self.context["simulated_fund_usd"] = self.simulated_fund_usd
        self.context['valid_analysis_chain_names'] = list(self.CHAIN_NAME_TO_ID_MAP.keys())


    def propose_trade(self, trade_details_string: str):
        """
        Parses trade string, performs pre-proposal validation using token analysis, then proposes.
        Format: <INPUT_TOKEN_SYMBOL_OR_ADDRESS> <OUTPUT_TOKEN_SYMBOL_OR_ADDRESS> <INPUT_AMOUNT> <NETWORK_NAME> <DEX_NAME>
        """
        log_func = lambda msg, level: asyncio.create_task(self.log_message(msg, level=level)) # For async logging
        parts = trade_details_string.strip().split()

        if len(parts) == 5:
            input_token_str, output_token_str, input_amount_str, network_name_str, dex_name_str = parts
            network_name = network_name_str.lower() # Standardize network name

            try:
                input_amount = float(input_amount_str)
                if input_amount <= 1e-18: # Effectively zero or negative
                    log_func(f"Trade proposal REJECTED (System): Invalid amount (<=0): {input_amount_str}", "WARNING"); return

                # --- Pre-Proposal Validation for Output Token ---
                # Identify the token being acquired (output_token_str).
                # This could be a symbol (e.g., "USDC") or an address ("0x...").
                # For validation, we need an address. If it's a common symbol for a "safe" token, we might skip detailed checks.

                # Attempt to resolve output_token_str to an address if it's a known symbol on the network.
                # Otherwise, assume it's already an address if it starts with "0x".
                token_to_check_for_risk = output_token_str # This is what the agent provided
                output_token_address = None

                if "0x" in output_token_str.lower():
                    output_token_address = output_token_str # Assume it's an address
                else: # It's a symbol, try to find its address from config for the given network
                    output_token_address = self.evm_config.get("token_addresses", {}).get(network_name, {}).get(output_token_str.upper())

                # If we have an address for the output token, and it's not on the "safe list" for its chain, perform checks.
                current_chain_safe_list = [addr.lower() for addr in self.SAFE_OUTPUT_TOKENS_BY_CHAIN.get(network_name, [])]

                if output_token_address and (output_token_address.lower() not in current_chain_safe_list):
                    log_func(f"Pre-proposal check for token: {output_token_address} (resolved from '{output_token_str}') on network {network_name}", "INFO")
                    analysis_summary = self.context.get("available_token_analyses_summary", {}).get(output_token_address)

                    if analysis_summary and isinstance(analysis_summary.get("security_summary"), dict):
                        sec_summary = analysis_summary["security_summary"]
                        if sec_summary.get("is_honeypot") is True:
                            log_func(f"SYSTEM REJECTED TRADE: Output token {output_token_address} is a confirmed honeypot. Trade: {trade_details_string}", "ERROR"); return

                        buy_tax_pct = sec_summary.get("buy_tax_percent", 0.0)
                        sell_tax_pct = sec_summary.get("sell_tax_percent", 0.0)
                        if buy_tax_pct > 20.0 or sell_tax_pct > 20.0: # Tax > 20%
                            log_func(f"SYSTEM REJECTED TRADE: Excessive taxes for {output_token_address}. Buy: {buy_tax_pct:.1f}%, Sell: {sell_tax_pct:.1f}%. Trade: {trade_details_string}", "ERROR"); return

                        if sec_summary.get("warnings_count", 0) > 0:
                             for warning_msg in sec_summary.get("top_warnings", []):
                                if "CRITICAL:" in warning_msg.upper(): # Check for critical warnings
                                    log_func(f"SYSTEM REJECTED TRADE: Critical security warning for {output_token_address}: '{warning_msg}'. Trade: {trade_details_string}", "ERROR"); return
                    elif not analysis_summary: # No analysis available for this non-safe address
                         log_func(f"WARNING: No analysis summary for OUTPUT token {output_token_address} (from '{output_token_str}'). Proposing without safety pre-check: {trade_details_string}", "WARNING")
                elif not output_token_address and "0x" not in output_token_str.lower(): # Symbol not found in config, and not an address
                    log_func(f"WARNING: Output token symbol '{output_token_str}' not found in config for network '{network_name}' and is not an address. Proposing as-is.", "WARNING")


                # If all checks pass or not applicable, proceed to propose
                proposal_data = {
                    "action": "TRADE", "input_token": input_token_str.upper(), "output_token": output_token_str.upper(),
                    "input_amount": input_amount, "network_name": network_name, "dex_name": dex_name_str.lower()
                }
                self.multisig_wallet.propose_transaction(proposal_data)

            except ValueError:
                log_func(f"Invalid number format for trade amount: '{input_amount_str}' in proposal '{trade_details_string}'", "WARNING")

        elif len(parts) == 3 and parts[0].upper() in ["BUY", "SELL"]: # Legacy simulated trade
            action, amount_str, crypto_symbol = parts
            try:
                amount = float(amount_str)
                sim_proposal = {"action": action.upper(), "amount": amount, "crypto": crypto_symbol.upper(), "simulated": True}
                self.multisig_wallet.propose_transaction(sim_proposal)
            except ValueError:
                 log_func(f"Invalid amount in old-format simulated proposal: '{amount_str}'", "WARNING")
        else:
            log_func(f"Unrecognized trade proposal format: '{trade_details_string}'. Expected 5 parts for on-chain or 3 for simulated.", "WARNING")

    async def execute_approved_transactions(self):
        """Executes approved transactions, handling simulated and on-chain trades."""
        approved_tx_wrappers = self.multisig_wallet.get_approved_transactions()
        if not approved_tx_wrappers: return

        await self.log_message(f"Processing {len(approved_tx_wrappers)} approved transaction(s)...", level="INFO")
        default_network = self.evm_config.get('default_network', 'sepolia')
        default_dex = self.evm_config.get('default_dex', 'uniswap_v2')
        _active_web3_instance, _active_wallet_account, _active_network_name = None, None, None

        for tx_wrapper in approved_tx_wrappers:
            tx_data, tx_id = tx_wrapper['transaction'], tx_wrapper['id']
            final_status, tx_hash_onchain, error_msg = tx_wrapper['status'], None, None # error_msg must be defined
            await self.log_message(f"Attempting to execute Tx ID {tx_id}: {json.dumps(tx_data)}", level="DEBUG")

            if tx_data.get("simulated"):
                action, amount, crypto = tx_data["action"], tx_data["amount"], tx_data["crypto"]
                if action == "BUY":
                    if self.simulated_fund_usd >= amount:
                        self.simulated_fund_usd -= amount
                        await self.log_message(f"Simulated BUY (Tx ID {tx_id}): {amount} USD for {crypto}. Fund USD: ${self.simulated_fund_usd:.2f}.", level="INFO")
                        final_status = "executed_simulated_buy"
                    else: final_status = "failed_simulated_insufficient_funds"; await self.log_message(f"Simulated BUY (Tx ID {tx_id}) FAILED: Insufficient USD.", level="WARNING")
                elif action == "SELL":
                    current_holding = self.portfolio.holdings.get(crypto, 0)
                    if current_holding >= amount:
                        self.portfolio.update_holding(crypto, -amount)
                        await self.log_message(f"Simulated SELL (Tx ID {tx_id}): {amount} of {crypto}. Portfolio: {self.portfolio.get_portfolio_summary()}.", level="INFO")
                        final_status = "executed_simulated_sell"
                    else: final_status = "failed_simulated_insufficient_tokens"; await self.log_message(f"Simulated SELL (Tx ID {tx_id}) FAILED: Insufficient {crypto} ({current_holding}).", level="WARNING")
                self.multisig_wallet.mark_transaction_processed(tx_id, final_status, error_message=error_msg)
                continue

            if tx_data["action"] == "TRADE":
                trade_network = tx_data.get("network_name", default_network)
                await self.log_message(f"Preparing ON-CHAIN trade for Tx ID {tx_id}: {tx_data['input_amount']:.6f} {tx_data['input_token']} for {tx_data['output_token']} on {trade_network}.", level="WARNING")

                if trade_network != _active_network_name or not _active_web3_instance or not _active_wallet_account:
                    await self.log_message(f"Connecting to {trade_network} & loading wallet for Tx ID {tx_id}...", level="DEBUG")
                    if not self.evm_config or not self.evm_config.get('rpc_urls'):
                        error_msg = "Missing RPC URLs in EVM config."; final_status = "failed_config_error"
                        await self.log_message(f"CRITICAL Error for Tx ID {tx_id}: {error_msg}", level="ERROR")
                    else:
                        _active_web3_instance = connect_to_network(trade_network, config_path='config.json')
                        if _active_web3_instance:
                            _active_wallet_account = load_wallet(_active_web3_instance, trade_network, config_path='config.json')
                            if _active_wallet_account: _active_network_name = trade_network; await self.log_message(f"Connected to {trade_network}, wallet {_active_wallet_account.address} loaded.", level="INFO")
                            else: error_msg = f"Failed to load wallet for {trade_network}."; final_status = "failed_wallet_load"; _active_web3_instance = _active_network_name = None
                        else: error_msg = f"Failed to connect to {trade_network}."; final_status = "failed_network_connect"; _active_network_name = None
                    if error_msg: self.multisig_wallet.mark_transaction_processed(tx_id, final_status, error_message=error_msg); continue

                tx_hash_onchain, trade_success, message = await asyncio.to_thread(
                    execute_trade, _active_web3_instance, _active_wallet_account, trade_network,
                    tx_data.get("dex_name", default_dex), tx_data["input_token"], tx_data["output_token"],
                    tx_data["input_amount"], 'config.json'
                )

                if trade_success:
                    final_status = "executed_onchain_success"
                    await self.log_message(f"ON-CHAIN Trade SUCCESS (Tx ID {tx_id}): Hash {tx_hash_onchain}. {message}", level="INFO")
                    self.portfolio.update_holding(tx_data["input_token"], -tx_data["input_amount"])
                    await self.log_message(f"Simulated portfolio: -{tx_data['input_amount']:.8f} {tx_data['input_token']}. Check on-chain balance for {tx_data['output_token']}.", level="INFO")
                else:
                    final_status = "failed_onchain_execution"; error_msg = message
                    await self.log_message(f"ON-CHAIN Trade FAILED (Tx ID {tx_id}): {message}. Hash(if any): {tx_hash_onchain}", level="ERROR")
                self.multisig_wallet.mark_transaction_processed(tx_id, final_status, tx_hash=tx_hash_onchain, error_message=error_msg)

        self.context["portfolio_summary"] = self.portfolio.get_portfolio_summary()
        self.context["simulated_fund_usd"] = self.simulated_fund_usd
        self.multisig_wallet.clear_finalized_transactions() # Call this to clean up processed txs from active list

    async def generate_synopsis(self):
        prompt = f"Summarize key discussion points, decisions, and outcomes of any executed/failed on-chain transactions from Day {self.current_day}:\n\nDiscussion Highlights:\n"
        max_interactions = self.evm_config.get("synopsis_max_interactions", 20)
        recent_interactions = self.discussion_log[-max_interactions:]
        if recent_interactions:
            for interaction in recent_interactions: prompt += f"- @{interaction['social_handle']} on '{interaction['topic'][:30]}...': {interaction['response'][:100].replace(chr(10),' ')}...\n"
        else: prompt += "- No discussion points recorded.\n"

        processed_tx_summary = []
        for tx_w in self.multisig_wallet.pending_transactions: # Review all txs for status
            if tx_w['status'] not in ['pending', 'approved']:
                tx_info, summary = tx_w['transaction'], f"TxID {tx_w['id']}: {tx_info.get('action','N/A')} "
                summary += f"{tx_info.get('input_token','N/A') if tx_info.get('action')=='TRADE' else tx_info.get('crypto','N/A')} - Status: {tx_w['status']}."
                if tx_w.get('tx_hash'): summary += f" (Hash: {tx_w['tx_hash'][:12]}...)"
                if tx_w.get('error_message'): summary += f" (Error: {tx_w['error_message'][:50]}...)"
                processed_tx_summary.append(summary)
        if processed_tx_summary: prompt += "\nTransaction Attempts Summary:\n" + "\n".join(processed_tx_summary)
        else: prompt += "\n- No on-chain transaction attempts processed today.\n"

        try: response = self.agents[0].model.generate_content(prompt); self.synopsis = response.text
        except Exception as e: self.synopsis = f"Error generating synopsis: {e}"; print(f"Synopsis generation error: {e}")
        await self.log_message(f"\n--- Day {self.current_day} Synopsis ---\n{self.synopsis}\n--- End Synopsis ---", level="INFO")
        await self.broadcast({"type": "synopsis", "content": self.synopsis})

    def export_discussion_log(self, filename="crypto_discussion_log_full.json"):
        try:
            with open(filename, 'w') as f: json.dump(self.discussion_log, f, indent=2, default=str)
            print(f"Full discussion log exported to {filename}")
        except Exception as e: print(f"Error exporting discussion log: {e}")

    def generate_seo_friendly_html(self, filename="crypto_discussion_log.html"):
        ws_port = self.evm_config.get("websocket_port", 8765)
        # Minified HTML and JS for brevity in this large file
        html_content=f"<!DOCTYPE html><html lang=en><head><meta charset=UTF-8><meta name=viewport content=\"width=device-width,initial-scale=1\"><title>AI Crypto Agents Log</title><style>body{{font-family:monospace;line-height:1.6;padding:20px;max-width:900px;margin:0 auto;background-color:#0a0a0a;color:#0f0}}h1,h2{{color:#0f0;border-bottom:1px solid #0c0;padding-bottom:5px}}#log,#terminal{{border:1px solid #0c0;padding:15px;margin-bottom:20px;border-radius:8px;height:400px;overflow-y:auto;background-color:#001a00;font-size:.9em}}#synopsis{{border:1px solid #0c0;padding:15px;margin-top:20px;background-color:#001a00;border-radius:8px}}.interaction{{margin-bottom:15px;padding-bottom:10px;border-bottom:1px dotted #030}}.timestamp{{color:#090;font-size:.8em}}.agent{{font-weight:700;color:#3c3}}.topic{{font-style:italic;color:#0a0;margin:5px 0}}#status{{color:#f33;font-weight:700;text-align:center;padding:10px;background-color:#1a0000;border-radius:5px;margin-bottom:10px}}pre{{white-space:pre-wrap;word-wrap:break-word;color:#cfc}}</style></head><body><h1>AI Crypto Agents Log</h1><div id=status>Connecting...</div><h2>System Terminal</h2><div id=terminal><p>Terminal init...</p></div><h2>Agent Discussion</h2><div id=log><p>Log init...</p></div><h2>Daily Synopsis</h2><div id=synopsis><p>Synopsis init...</p></div><script>const terminal=document.getElementById('terminal'),log=document.getElementById('log'),synopsisDiv=document.getElementById('synopsis'),statusDiv=document.getElementById('status');let socket;function format(t){{if('string'!=typeof t)t=String(t);const e=t.replace(/</g,'&lt;').replace(/>/g,'&gt;');return e.replace(/\\n/g,'<br>').replace(/    /g,'&nbsp;&nbsp;&nbsp;&nbsp;')}}function appendTerm(t){{const e=document.createElement('p');e.innerHTML=format(t),terminal.appendChild(e),terminal.scrollTop=terminal.scrollHeight}}function appendLog(t){{const e=document.createElement('div');e.classList.add('interaction'),e.innerHTML=`<p class=timestamp>${{new Date(t.timestamp).toLocaleString()}}</p><p class=agent>@${{t.social_handle}} (${{t.agent}})</p><p class=topic>Topic: ${{format(t.topic)}}</p><pre>${{format(t.response)}}</pre>`,log.appendChild(e),log.scrollTop=log.scrollHeight}}function updateSynopsis(t){{synopsisDiv.innerHTML=`<h2>Daily Synopsis</h2><pre>${{format(t)}}</pre>`}}function connectSocket(){{const t=window.location.protocol==='https:'?'wss:':'ws:',e=document.domain||window.location.hostname||'localhost',o={ws_port};socket=new WebSocket(`${{t}}//${{e}}:${{o}}`),socket.onopen=function(t){{statusDiv.textContent='Live feed connected.';statusDiv.style.color='#3c3';statusDiv.style.backgroundColor='#001a00';console.log('WS connected');appendTerm('WS connected.')}},socket.onmessage=function(t){{try{{const e=JSON.parse(t.data);'interaction'===e.type?appendLog(e.content):'synopsis'===e.type?updateSynopsis(e.content):'message'===e.type&&appendTerm(e.content)}}catch(e){{console.error('Error parsing JSON/UI update:',e,'Data:',t.data);appendTerm(`Error processing message: ${{t.data}}`)}}}},socket.onclose=function(t){{statusDiv.textContent='Live feed disconnected. Retrying in 5s...';statusDiv.style.color='#f33';statusDiv.style.backgroundColor='#1a0000';console.log('WS closed. Reconnecting...');appendTerm('WS closed. Reconnecting...');setTimeout(connectSocket,5e3)}},socket.onerror=function(t){{console.error('WS error:',t);statusDiv.textContent='WS conn error.';statusDiv.style.color='#f33';appendTerm(`WS error: ${{t.message||'Unknown'}}`)}}}}connectSocket();</script></body></html>"""
        try:
            with open(filename, 'w', encoding='utf-8') as f: f.write(html_content)
            print(f"HTML log page generated: {filename}")
        except Exception as e: print(f"Error writing HTML file '{filename}': {e}")

    def push_to_social_networks(self):
        if not self.synopsis: print("No synopsis to push."); return
        for platform_config in self.evm_config.get("social_media_platforms",[]):
            print(f"SIMULATING: Pushing synopsis to {platform_config.get('name','N/A')}...")

    async def register(self, websocket): self.websocket_clients.add(websocket); await self.log_message(f"Client {websocket.remote_address} connected. Total: {len(self.websocket_clients)}", level="DEBUG")
    async def unregister(self, websocket): self.websocket_clients.discard(websocket); await self.log_message(f"Client {websocket.remote_address} disconnected. Total: {len(self.websocket_clients)}", level="DEBUG")
    async def broadcast(self, msg_payload: Dict):
        if self.websocket_clients:
            for client in list(self.websocket_clients):
                try: await asyncio.wait_for(client.send(json.dumps(msg_payload)), timeout=1.0)
                except Exception: self.websocket_clients.discard(client)

    def push_to_api(self, interaction_data: Dict):
        api_endpoint = self.evm_config.get("external_api_endpoint")
        if not api_endpoint: return
        try:
            resp = requests.post(api_endpoint, json=interaction_data, timeout=self.evm_config.get("api_timeout_seconds",10))
            if resp.status_code<300: print(f"Pushed to {api_endpoint} for {interaction_data['agent']}. Status:{resp.status_code}")
            else: print(f"Failed push to {api_endpoint} for {interaction_data['agent']}. Status:{resp.status_code}, Resp:{resp.text[:100]}")
        except Exception as e: print(f"Error pushing to {api_endpoint} for {interaction_data['agent']}: {e}")

async def start_websocket_server(ag_instance: AgentGroup): # ag_instance for AgentGroup instance
    global websocket_server_running
    async def ws_handler(ws, path): await ag_instance.register(ws); try: await ws.wait_closed() finally: await ag_instance.unregister(ws)
    if websocket_server_running: await ag_instance.log_message("WS server already running.",level="WARN"); return
    websocket_server_running = True
    host,port=ag_instance.evm_config.get("websocket_host","localhost"),ag_instance.evm_config.get("websocket_port",8765)
    try:
        server=await websockets.serve(ws_handler,host,port); await ag_instance.log_message(f"WS server on ws://{host}:{port}",level="INFO"); await server.wait_closed()
    except Exception as e: await ag_instance.log_message(f"WS server error: {e}",level="CRITICAL")
    finally: websocket_server_running=False; await ag_instance.log_message("WS server shut down.",level="INFO")

def run_http_server(html_path: str, ag_instance: AgentGroup):
    global http_server_running
    if http_server_running: print("HTTP server already running."); return
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=os.path.dirname(os.path.abspath(html_path))or'.',**kwargs)
        def do_GET(self):
            if self.path=='/':self.path=os.path.basename(html_path)
            super().do_GET()
    host,port=ag_instance.evm_config.get("http_host","localhost"),ag_instance.evm_config.get("http_port",8000)
    for attempt in range(3):
        curr_port=port+attempt
        try:
            with socketserver.TCPServer((host,curr_port),Handler)as httpd:
                http_server_running=True;print(f"HTTP server: http://{host}:{curr_port}/{os.path.basename(html_path)}");httpd.serve_forever();break
        except OSError as e:
            if e.errno in[98,10048]:print(f"HTTP Port {curr_port} in use. Trying next...")
            else:print(f"HTTP server OSError:{e}");break
        except Exception as e:print(f"HTTP server error:{e}");break
    if not http_server_running:print("HTTP server failed to start.")
    http_server_running=False

async def main():
    gemini_key=os.getenv("GEMINI_API_KEY")
    if not gemini_key:print("CRITICAL: GEMINI_API_KEY env var not set.");return
    agent_defs=[{"name":"AlphaSeeker","role":"Identifies trends & proposes trades. Must use ANALYSIS_TOKEN first.","social_handle":"AlphaSeekerBot"},
                  {"name":"RiskGuard","role":"Analyzes risks of proposed trades using token analysis. Votes diligently.","social_handle":"RiskGuardBot"},
                  {"name":"PortfolioOptimus","role":"Develops strategies, suggests rebalancing trades. Checks analysis.","social_handle":"PortfolioOptBot"}]
    temp_agents=[AIAgent(d["name"],d["role"],gemini_key,d["social_handle"])for d in agent_defs] # Pass definitions
    try:
        btc_price=float(os.getenv("MOCK_BTC_PRICE_USD","60000"));usd_val=float(os.getenv("MOCK_INITIAL_USD_FUND","1000"))
        init_btc=usd_val/btc_price if btc_price>0 else .0001
    except Exception as e:print(f"Warn:Sim funding error({e}).Defaulting.");init_btc=.0001

    agent_group=AgentGroup(temp_agents,initial_simulated_btc_amount=init_btc) # Pass agent definitions
    html_log_fn="crypto_discussion_log.html";agent_group.generate_seo_friendly_html(html_log_fn)
    await agent_group.log_message("Init AI Agent Group & services...",level="INFO")
    ws_task=asyncio.create_task(start_websocket_server(agent_group))
    http_thread=threading.Thread(target=run_http_server,args=(html_log_fn,agent_group),daemon=True);http_thread.start()
    await asyncio.sleep(1)
    if not websocket_server_running:await agent_group.log_message("WS server failed. Live HTML impaired.",level="CRITICAL")

    num_days=agent_group.evm_config.get("discussion_simulation_days",1)
    await agent_group.autonomous_discussion(num_simulation_days=num_days)
    await agent_group.log_message("Discussion complete. Shutting down...",level="INFO")
    if ws_task and not ws_task.done():
        ws_task.cancel();
        try:await ws_task
        except asyncio.CancelledError:await agent_group.log_message("WS server task cancelled.",level="INFO")
        except Exception as e:await agent_group.log_message(f"Error during WS shutdown:{e}",level="ERROR")
    agent_group.export_discussion_log();await agent_group.log_message("Script finished.",level="INFO")

if __name__=="__main__":
    try:asyncio.run(main())
    except KeyboardInterrupt:print("\nApp interrupted. Shutting down...")
    except Exception as e:print(f"CRITICAL ERROR in __main__:{type(e).__name__}-{e}");import traceback;traceback.print_exc()
    finally:print("App exit.")
