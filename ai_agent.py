"""
ai_agent.py: Main script for AI agent group simulation and EVM interaction.

This script orchestrates a group of AI agents that discuss cryptocurrency trends,
propose trades, vote on them, and can execute approved trades on EVM-compatible
blockchains via `evm_utils.py`.

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
    *   Set the `GEMINI_API_KEY` environment variable with your Google Gemini API key.

2.  **Install Dependencies:**
    *   `pip install google-generativeai web3 websockets requests` (and any others)

3.  **Verify EVM Utilities (Recommended):**
    *   Run `python test_evm_utils.py`.
    *   This script helps test your `config.json` setup and basic EVM functions
        against your chosen testnet. Follow its interactive prompts.

4.  **Run the AI Agent Simulation:**
    *   `python ai_agent.py`
    *   The agents will begin their discussion process. If on-chain transactions
        are proposed and approved, and your `config.json` is set up for a
        funded testnet wallet, the script will attempt to execute these trades.

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
    of those funds.

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

# EVM Utils imports
from evm_utils import (
    connect_to_network,
    load_wallet,
    execute_trade,
    get_token_balance,
    approve_token,
    load_config
)

# Global variables to track server status
websocket_server_running = False
http_server_running = False

class AIAgent:
    """
    Represents an individual AI agent with a specific role, capable of processing
    information and voting on transactions.
    """
    def __init__(self, name, role, api_key, social_handle):
        self.name = name
        self.role = role
        self.social_handle = social_handle
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-pro') # Or other compatible model

    def process_input(self, input_text, context):
        """
        Generates a response from the AI agent based on input text and context.
        """
        prompt = f"""As an AI assistant named {self.name} with the role of '{self.role}' (social media handle @{self.social_handle}), provide your expert analysis, recommendations, or comments on the following input. Focus on the context of financial markets, cryptocurrency, and decentralized finance.

Current Context:
{json.dumps(context, indent=2)}

Input for your consideration:
"{input_text}"

Your Response (include relevant hashtags and mention other agents like @{self.social_handle} if needed):"""

        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"Error during AI agent {self.name} content generation: {e}")
            return f"Error: Could not generate content due to: {e}"


    def vote_on_transaction(self, transaction, context):
        """
        Generates a vote (APPROVE/REJECT) and reasoning for a proposed transaction.
        """
        prompt = f"""As AI Agent '{self.name}' ({self.role}), you must evaluate the following proposed financial transaction.
Given your role and the current market context, decide whether to APPROVE or REJECT it.
Provide clear reasoning for your decision.

Transaction Details:
{json.dumps(transaction, indent=2)}

Current Market & Portfolio Context:
{json.dumps(context, indent=2)}

Your Vote (Format: Single line "APPROVE" or "REJECT", followed by detailed reasoning on new lines):"""

        try:
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"Error during AI agent {self.name} voting: {e}")
            return f"REJECT - Error during voting process: {e}"


class CryptoPortfolio:
    """
    Manages cryptocurrency holdings and transaction history for the agent group.
    This is primarily for simulation and off-chain tracking. On-chain balances
    are the source of truth for actual holdings managed by the configured wallet.
    """
    def __init__(self):
        self.holdings = {} # Stores token symbol -> amount
        self.transaction_history = []

    def update_holding(self, crypto_symbol, amount_change):
        """
        Updates the holding for a specific cryptocurrency.
        `amount_change` can be positive (for additions) or negative (for subtractions).
        """
        current_balance = self.holdings.get(crypto_symbol, 0)
        new_balance = current_balance + amount_change
        self.holdings[crypto_symbol] = new_balance

        self.transaction_history.append({
            "date": datetime.now().isoformat(),
            "crypto": crypto_symbol,
            "amount_change": amount_change,
            "new_simulated_balance": new_balance
        })

        # If a token's balance becomes effectively zero, remove it from holdings for clarity
        if abs(new_balance) < 1e-12: # Using a small threshold for floating point comparisons
            del self.holdings[crypto_symbol]
        elif new_balance < 0:
             print(f"Warning: Simulated holding for {crypto_symbol} is now negative: {new_balance:.18f}")


    def get_portfolio_summary(self):
        """Returns a JSON string summary of current holdings."""
        return json.dumps(self.holdings)

    def get_transaction_history(self):
        """Returns a JSON string of the transaction history."""
        return json.dumps(self.transaction_history)

class MultisigWallet:
    """
    Simulates a multi-signature wallet for transaction proposal and voting.
    Does not implement actual on-chain multisig logic but rather a conceptual
    approval workflow before a single configured wallet executes trades.
    """
    def __init__(self, agents, required_signatures):
        self.agents = agents
        self.required_signatures = required_signatures
        self.pending_transactions = [] # Stores transaction proposals with their votes and status

    def propose_transaction(self, transaction_data):
        """
        Adds a new transaction proposal to the pending list.
        `transaction_data` should be a dictionary describing the trade.
        """
        tx_id = f"tx_{int(time.time())}_{random.randint(1000,9999)}"
        proposal = {
            "id": tx_id,
            "transaction": transaction_data,
            "votes": [],
            "status": "pending" # states: pending, approved, rejected, executed_simulated, executed_onchain_success, failed_*
        }
        self.pending_transactions.append(proposal)
        print(f"Transaction proposed (ID: {tx_id}): {json.dumps(transaction_data)}")


    def vote_on_transactions(self, context):
        """
        Facilitates voting by each agent on pending transactions.
        Updates transaction status based on votes.
        """
        for tx_wrapper in self.pending_transactions:
            if tx_wrapper["status"] == "pending":
                voted_agent_names = {vote['agent'] for vote in tx_wrapper['votes']}
                for agent in self.agents:
                    if agent.name not in voted_agent_names:
                        vote_response = agent.vote_on_transaction(tx_wrapper["transaction"], context)
                        tx_wrapper["votes"].append({"agent": agent.name, "vote": vote_response})
                        # Log first line of vote for brevity
                        print(f"Agent {agent.name} voted on Tx ID {tx_wrapper['id']}: '{vote_response.splitlines()[0]}'")

                # Determine overall status based on votes
                approvals = sum(1 for vote in tx_wrapper["votes"] if vote["vote"].strip().upper().startswith("APPROVE"))
                rejects = sum(1 for vote in tx_wrapper["votes"] if vote["vote"].strip().upper().startswith("REJECT"))

                num_agents = len(self.agents)
                if approvals >= self.required_signatures:
                    tx_wrapper["status"] = "approved"
                    print(f"Transaction ID {tx_wrapper['id']} APPROVED with {approvals}/{num_agents} votes.")
                elif rejects > (num_agents - self.required_signatures) or len(tx_wrapper["votes"]) == num_agents:
                    # Reject if approval is no longer possible OR all agents have voted and it's not approved
                    tx_wrapper["status"] = "rejected"
                    print(f"Transaction ID {tx_wrapper['id']} REJECTED. (Approvals: {approvals}, Rejects: {rejects}, Total Votes: {len(tx_wrapper['votes'])})")


    def get_approved_transactions(self):
        """Returns a list of transaction wrappers that have been approved but not yet processed."""
        return [tx_wrapper for tx_wrapper in self.pending_transactions if tx_wrapper["status"] == "approved"]

    def mark_transaction_processed(self, tx_id, final_status, tx_hash=None, error_message=None):
        """Updates the status of a transaction after an attempt to execute it."""
        for tx_wrapper in self.pending_transactions:
            if tx_wrapper["id"] == tx_id:
                tx_wrapper["status"] = final_status
                if tx_hash: tx_wrapper["tx_hash"] = tx_hash
                if error_message: tx_wrapper["error_message"] = error_message
                break

    def clear_finalized_transactions(self):
        """Removes transactions that are no longer pending or just approved (i.e., executed or failed)."""
        # This method might be more useful if we want to archive, for now, execute_approved_transactions updates status.
        # If we want to truly clear, it would be:
        # self.pending_transactions = [tx_wrapper for tx_wrapper in self.pending_transactions if tx_wrapper["status"] in ["pending", "approved"]]
        pass # Current logic in execute_approved_transactions handles marking status.


class AgentGroup:
    """
    Manages a group of AI agents, their discussions, portfolio (simulated),
    and the process of proposing, voting, and executing EVM transactions.

    WARNING: If live trading is enabled via `config.json` and a funded wallet's
    private key, this class can orchestrate REAL financial transactions.
    Understand the risks and test thoroughly on a testnet first.
    """
    def __init__(self, agents, initial_simulated_btc_amount):
        self.agents = agents
        self.portfolio = CryptoPortfolio() # For simulated/off-chain tracking
        self.simulated_fund_usd = 0.0  # Simulated USD fund, not on-chain unless bridged/stablecoin
        if initial_simulated_btc_amount > 0:
            self.portfolio.update_holding("BTC", initial_simulated_btc_amount)

        self.context = { # Shared context for agents
            "portfolio_summary": self.portfolio.get_portfolio_summary(),
            "simulated_fund_usd": self.simulated_fund_usd,
            "recent_discussion_topics": [], # Could store last N topics
            "market_news_feed": [], # Placeholder for external news
            "key_support_resistance": {} # Placeholder for technical analysis data
        }
        # Ensure required_signatures is at least 1 and not more than the number of agents.
        # A common setup is majority or >50%. For 3 agents, 2 is good. For 1 agent, 1.
        num_agents = len(self.agents)
        req_sigs = max(1, min(num_agents, self.evm_config.get("multisig_required_signatures", (num_agents // 2) + 1)))
        self.multisig_wallet = MultisigWallet(agents, required_signatures=req_sigs)

        self.discussion_log = [] # History of agent interactions
        self.current_day = 1     # Simulation day counter
        self.websocket_clients = set() # For live HTML updates
        self.synopsis = ""       # Daily summary of discussions
        self.discussion_state_file = "discussion_state.json" # For saving/loading state

        self.evm_config = load_config() # Load EVM settings (RPC, addresses, etc.)
        if not self.evm_config:
            print("CRITICAL WARNING: EVM configuration (`config.json`) not found or failed to load.")
            print("                 On-chain features will be disabled or may fail.")
            print("                 Please create `config.json` from `config.json.example` and configure it.")
            self.evm_config = {} # Initialize to empty dict to prevent `None.get()` errors

    def save_state(self):
        """Saves the current state of the agent group to a JSON file."""
        state = {
            "current_day": self.current_day,
            "discussion_log": self.discussion_log,
            "context": self.context,
            "portfolio_holdings": self.portfolio.holdings,
            "simulated_fund_usd": self.simulated_fund_usd,
            "pending_transactions": self.multisig_wallet.pending_transactions
        }
        try:
            with open(self.discussion_state_file, 'w') as f:
                json.dump(state, f, indent=2)
            # print(f"AgentGroup state saved for Day {self.current_day}.") # Can be noisy
        except Exception as e:
            print(f"Error saving state to {self.discussion_state_file}: {e}")


    def load_state(self):
        """Loads the agent group state from a JSON file if it exists."""
        if os.path.exists(self.discussion_state_file):
            try:
                with open(self.discussion_state_file, 'r') as f:
                    state = json.load(f)
                self.current_day = state.get('current_day', 1)
                self.discussion_log = state.get('discussion_log', [])
                self.context = state.get('context', self.context)
                self.portfolio.holdings = state.get('portfolio_holdings', {})
                self.simulated_fund_usd = state.get('simulated_fund_usd', 0.0)
                self.multisig_wallet.pending_transactions = state.get('pending_transactions', [])

                # Ensure context reflects loaded state correctly
                self.context["portfolio_summary"] = self.portfolio.get_portfolio_summary()
                self.context["simulated_fund_usd"] = self.simulated_fund_usd
                print(f"AgentGroup state successfully loaded. Resuming from Day {self.current_day}.")
                return True
            except Exception as e:
                print(f"Error loading state from {self.discussion_state_file}: {e}. Starting fresh.")
                return False
        print("No saved state file found. Starting a fresh simulation.")
        return False

    async def log_message(self, message, level="INFO"):
        """Logs a system message and broadcasts it to WebSocket clients."""
        log_entry = f"[{level}] {datetime.now().isoformat()}: {message}"
        print(log_entry) # Server-side log
        await self.broadcast({"type": "message", "content": log_entry}) # Client-side log via WebSocket

    async def log_interaction(self, agent, topic, response):
        """Logs an agent's interaction and broadcasts it."""
        interaction = {
            "timestamp": datetime.now().isoformat(),
            "agent": agent.name, "social_handle": agent.social_handle,
            "topic": topic, "response": response
        }
        self.discussion_log.append(interaction)
        # Log a summary to the console to keep it tidy
        print(f"@{agent.social_handle} (Topic: {topic.strip()[:50]}...): {response.strip().splitlines()[0][:100]}...")

        await self.broadcast({"type": "interaction", "content": interaction})
        self.push_to_api(interaction) # Optionally push to an external API

    async def autonomous_discussion(self, num_simulation_days):
        """
        Main loop for running the autonomous discussion and trading simulation for a number of days.
        WARNING: If live trading is enabled (via `config.json` and a funded wallet),
        this loop can trigger REAL on-chain transactions.
        """
        await self.log_message(f"Starting autonomous discussion for {num_simulation_days} day(s)...", level="WARNING")
        if self.load_state(): # Attempt to resume from saved state
            await self.log_message(f"Resumed discussion from start of Day {self.current_day}.", level="INFO")

        # Loop for the specified number of additional simulation days
        end_day = self.current_day + num_simulation_days
        for day_iterator in range(self.current_day, end_day):
            # `self.current_day` is used by methods, `day_iterator` is just for the loop
            await self.log_message(f"\n--- Starting Simulation Day {self.current_day} ---", level="INFO")
            await self.daily_discussion_cycle()
            await self.generate_synopsis() # Synopsis for the completed day
            self.save_state() # Save state at the end of each day
            await self.log_message(f"--- End of Simulation Day {self.current_day}. State saved. ---", level="INFO")
            self.current_day += 1 # Increment for the next day
            if self.current_day < end_day: # If not the absolute last day of the simulation run
                 await asyncio.sleep(self.evm_config.get("pause_between_days_seconds", 2))

    async def daily_discussion_cycle(self):
        """Simulates a single day of discussions, voting, and transaction execution."""
        # Optionally run a special scenario at the start of the day
        if self.current_day == 1 or self.evm_config.get("run_daily_scenario", False):
            await self.simulate_scenario_discussion()

        num_rounds = self.evm_config.get("discussion_rounds_per_day", 2)
        for i in range(num_rounds):
            await self.log_message(f"Day {self.current_day}, Discussion Round {i+1}/{num_rounds} starting...", level="DEBUG")
            for agent in self.agents:
                topic_for_agent = self.generate_topic_for_agent(agent)
                response = agent.process_input(topic_for_agent, self.context)
                await self.log_interaction(agent, topic_for_agent, response)
                self.update_context_with_responses([response]) # Process agent's response

        await self.log_message("Day {self.current_day}: Voting on proposed transactions...", level="INFO")
        self.multisig_wallet.vote_on_transactions(self.context) # Collect votes
        await self.execute_approved_transactions() # Attempt to execute approved ones

    async def simulate_scenario_discussion(self):
        """Presents a hypothetical scenario for agents to discuss without execution implications."""
        # Example: A scenario involving a major market event or a new technology
        example_assets = ["ETH", "SOL", "AVAX", "LINK", "DOT", "ADA"]
        chosen_asset = random.choice(example_assets)
        scenario = (f"Hypothetical Scenario for Day {self.current_day}: "
                    f"News breaks that '{chosen_asset}' has announced a major partnership with a global tech firm. "
                    f"Discuss potential impacts and strategic considerations for our (simulated) fund.")
        await self.log_message(f"Presenting scenario for discussion: {scenario}", level="INFO")

        scenario_responses = []
        for agent in self.agents:
            response = agent.process_input(scenario, self.context)
            await self.log_interaction(agent, f"Scenario: {chosen_asset} Partnership", response)
            scenario_responses.append({"agent": agent.name, "response": response})
        # Store scenario and its responses in context if needed for later reference by agents
        self.context.setdefault("daily_scenarios", []).append({
            "day": self.current_day, "scenario_prompt": scenario, "responses": scenario_responses
        })


    def generate_topic_for_agent(self, agent):
        """Generates a discussion topic, potentially tailored to the agent's role."""
        # Base topics list
        common_topics = [
            "What is a current cryptocurrency trend that offers significant potential for growth?",
            "Based on our current (simulated) portfolio and market conditions, propose one specific DEX trade. Format: TRADE <IN_TOKEN> <OUT_TOKEN> <IN_AMOUNT> <NETWORK> <DEX>. Justify your proposal.",
            f"Consider the token {random.choice(['WBTC', 'ETH', 'MATIC', 'SOL', 'LINK', 'UNI'])}. Should we consider a (simulated) long or short position? On which DEX and network? Propose a TRADE if applicable.",
            "Identify an undervalued altcoin on a major EVM network (e.g., Ethereum, Polygon) that you believe has strong fundamentals for a long-term hold. Suggest a small initial test buy via a TRADE proposal.",
            "What is a recent 'viral meta' or narrative in the crypto space? How could a fund theoretically (or actually, via a TRADE proposal) gain exposure or mitigate risk related to it?",
            "Review the latest transaction proposals. Should any be re-evaluated or amended based on new information?"
        ]
        # Role-specific topic generation can be added here. For example:
        # if agent.role == "RiskAnalyst":
        #     return "Analyze the risk profile of our current simulated holdings. Suggest any adjustments."
        return random.choice(common_topics)

    def update_context_with_responses(self, responses):
        """Updates the shared context based on keywords or content in agent responses."""
        for response_text in responses:
            if "TREND:" in response_text:
                self.context.setdefault("latest_trends", []).append(response_text.split("TREND:", 1)[1].strip())
            if "VIRAL_META:" in response_text:
                self.context.setdefault("viral_metas", []).append(response_text.split("VIRAL_META:", 1)[1].strip())
            if "TRADE:" in response_text: # Agent proposes a trade
                self.propose_trade(response_text.split("TRADE:", 1)[1].strip()) # Pass the trade details string
            if "MULTIPLY_STRATEGY:" in response_text:
                self.context.setdefault("multiplication_strategies", []).append(response_text.split("MULTIPLY_STRATEGY:", 1)[1].strip())

        # Always update portfolio summary in context as it might change due to (simulated) trades
        self.context["portfolio_summary"] = self.portfolio.get_portfolio_summary()
        self.context["simulated_fund_usd"] = self.simulated_fund_usd


    def propose_trade(self, trade_details_string):
        """
        Parses a trade string from an agent and proposes it to the multisig wallet.
        Expected format from agent: <INPUT_TOKEN_SYMBOL> <OUTPUT_TOKEN_SYMBOL> <INPUT_AMOUNT> <NETWORK_NAME> <DEX_NAME>
        Example: "WETH USDC 1.5 ethereum uniswap_v2"
        """
        parts = trade_details_string.strip().split()
        if len(parts) == 5:
            input_token, output_token, input_amount_str, network_name, dex_name = parts
            try:
                input_amount = float(input_amount_str)
                if input_amount <= 1e-18: # Check for effectively zero or negative amounts
                    asyncio.create_task(self.log_message(f"Warning: Trade proposal has invalid amount (<=0): {input_amount_str}", level="WARNING"))
                    return

                proposal_data = {
                    "action": "TRADE", # Standardized action for on-chain trades
                    "input_token": input_token.upper(),
                    "output_token": output_token.upper(),
                    "input_amount": input_amount,
                    "network_name": network_name.lower(), # Standardize to lowercase
                    "dex_name": dex_name.lower()      # Standardize to lowercase
                }
                self.multisig_wallet.propose_transaction(proposal_data)
            except ValueError:
                asyncio.create_task(self.log_message(f"Warning: Invalid number format for trade amount: '{input_amount_str}' in proposal '{trade_details_string}'", level="WARNING"))

        # Legacy support for simple "BUY"/"SELL" simulated trades (no on-chain execution)
        elif len(parts) == 3 and parts[0].upper() in ["BUY", "SELL"]:
            action, amount_str, crypto_symbol = parts
            try:
                amount = float(amount_str)
                simulated_proposal = {
                    "action": action.upper(), "amount": amount,
                    "crypto": crypto_symbol.upper(), "simulated": True
                }
                self.multisig_wallet.propose_transaction(simulated_proposal)
            except ValueError:
                 asyncio.create_task(self.log_message(f"Warning: Invalid amount in old-format simulated proposal: '{amount_str}'", level="WARNING"))
        else:
            asyncio.create_task(self.log_message(f"Warning: Unrecognized trade proposal format: '{trade_details_string}'. Expected 5 parts for on-chain or 3 for simulated.", level="WARNING"))


    async def execute_approved_transactions(self):
        """
        Executes transactions that have been approved by the agent majority.
        Handles both simulated (off-chain portfolio changes) and real on-chain trades.
        """
        approved_tx_wrappers = self.multisig_wallet.get_approved_transactions()
        if not approved_tx_wrappers:
            return

        await self.log_message(f"Processing {len(approved_tx_wrappers)} approved transaction proposal(s)...", level="INFO")

        # Default network and DEX from config, can be overridden by transaction proposal
        default_network = self.evm_config.get('default_network', 'sepolia') # Safer default
        default_dex = self.evm_config.get('default_dex', 'uniswap_v2') # Example

        # Cache for Web3 instance and wallet account to minimize reconnections for same network
        _active_web3_instance = None
        _active_wallet_account = None
        _active_network_name = None

        for tx_wrapper in approved_tx_wrappers:
            tx_data = tx_wrapper['transaction']
            tx_id = tx_wrapper['id']
            final_status = tx_wrapper['status'] # Should be 'approved' at this stage
            tx_hash_onchain = None
            error_msg = None

            await self.log_message(f"Attempting to execute Tx ID {tx_id}: {json.dumps(tx_data)}", level="DEBUG")

            if tx_data.get("simulated"): # Handle simulated off-chain BUY/SELL
                action = tx_data["action"]
                amount = tx_data["amount"]
                crypto = tx_data["crypto"]
                if action == "BUY": # Simulate BUY USD for Crypto
                    if self.simulated_fund_usd >= amount:
                        self.simulated_fund_usd -= amount
                        # Note: For simulation, price is needed to accurately update crypto quantity.
                        # This is a simplified simulation update.
                        # self.portfolio.update_holding(crypto, amount / MOCK_PRICE)
                        await self.log_message(f"Simulated BUY (Tx ID {tx_id}): {amount} USD for {crypto}. New simulated USD fund: ${self.simulated_fund_usd:.2f}. (Portfolio impact for {crypto} not fully reflected without price).", level="INFO")
                        final_status = "executed_simulated_buy"
                    else:
                        await self.log_message(f"Simulated BUY (Tx ID {tx_id}) FAILED: Insufficient simulated USD funds for {amount} {crypto}.", level="WARNING")
                        final_status = "failed_simulated_insufficient_funds"
                elif action == "SELL": # Simulate SELL Crypto for USD
                    current_holding = self.portfolio.holdings.get(crypto, 0)
                    if current_holding >= amount:
                        self.portfolio.update_holding(crypto, -amount) # Deduct crypto
                        # self.simulated_fund_usd += amount * MOCK_PRICE # Add to USD fund (needs price)
                        await self.log_message(f"Simulated SELL (Tx ID {tx_id}): {amount} of {crypto}. Portfolio updated. (Simulated USD fund impact not fully reflected without price).", level="INFO")
                        final_status = "executed_simulated_sell"
                    else:
                        await self.log_message(f"Simulated SELL (Tx ID {tx_id}) FAILED: Insufficient simulated {crypto} balance ({current_holding}) to sell {amount}.", level="WARNING")
                        final_status = "failed_simulated_insufficient_tokens"

                self.multisig_wallet.mark_transaction_processed(tx_id, final_status)
                continue # Move to the next transaction

            # Process on-chain "TRADE" actions
            if tx_data["action"] == "TRADE":
                trade_network = tx_data.get("network_name", default_network)

                await self.log_message(f"Preparing ON-CHAIN trade for Tx ID {tx_id}: {tx_data['input_amount']:.6f} {tx_data['input_token']} for {tx_data['output_token']} on {trade_network} network.", level="WARNING")

                # Establish or reuse network connection and wallet
                if trade_network != _active_network_name or not _active_web3_instance or not _active_wallet_account:
                    await self.log_message(f"Connecting to {trade_network} and loading wallet for Tx ID {tx_id}...", level="DEBUG")
                    if not self.evm_config or not self.evm_config.get('rpc_urls'): # Double check config
                        await self.log_message("CRITICAL Error: EVM config missing RPC URLs. Cannot perform on-chain actions.", level="ERROR")
                        self.multisig_wallet.mark_transaction_processed(tx_id, "failed_config_error", error_message="Missing RPC URLs in EVM config.")
                        continue # Skip to next transaction

                    _active_web3_instance = connect_to_network(trade_network, config_path='config.json')
                    if _active_web3_instance:
                        _active_wallet_account = load_wallet(_active_web3_instance, trade_network, config_path='config.json')
                        if _active_wallet_account:
                            _active_network_name = trade_network # Cache active connection details
                            await self.log_message(f"Successfully connected to {trade_network} and loaded wallet: {_active_wallet_account.address}", level="INFO")
                        else:
                            await self.log_message(f"Error loading wallet for {trade_network}. Skipping trade (Tx ID {tx_id}).", level="ERROR")
                            _active_web3_instance = _active_network_name = None; self.multisig_wallet.mark_transaction_processed(tx_id, "failed_wallet_load", error_message=f"Failed to load wallet for {trade_network}."); continue
                    else:
                        await self.log_message(f"Error connecting to {trade_network}. Skipping trade (Tx ID {tx_id}).", level="ERROR")
                        _active_network_name = None; self.multisig_wallet.mark_transaction_processed(tx_id, "failed_network_connect", error_message=f"Failed to connect to {trade_network}."); continue

                # Execute the trade (this is a blocking call, run in thread)
                tx_hash_onchain, trade_success, message = await asyncio.to_thread(
                    execute_trade,
                    _active_web3_instance, _active_wallet_account, trade_network,
                    tx_data.get("dex_name", default_dex),
                    tx_data["input_token"], tx_data["output_token"],
                    tx_data["input_amount"], 'config.json' # Make sure config_path is passed
                )

                if trade_success:
                    final_status = "executed_onchain_success"
                    await self.log_message(f"ON-CHAIN Trade SUCCESSFUL (Tx ID {tx_id}). Hash: {tx_hash_onchain}. Details: {message}", level="INFO")
                    # Update simulated portfolio based on successful on-chain trade
                    self.portfolio.update_holding(tx_data["input_token"], -tx_data["input_amount"])
                    # Note: Accurately updating output token amount requires parsing trade logs or fetching post-trade balance.
                    # For now, we log and might need a manual/separate balance refresh mechanism.
                    await self.log_message(f"Simulated portfolio updated: -{tx_data['input_amount']:.8f} {tx_data['input_token']}. Check on-chain balance for {tx_data['output_token']}.", level="INFO")
                else:
                    final_status = "failed_onchain_execution"
                    error_msg = message
                    await self.log_message(f"ON-CHAIN Trade FAILED (Tx ID {tx_id}). Reason: {message}. Hash (if any): {tx_hash_onchain}", level="ERROR")

                self.multisig_wallet.mark_transaction_processed(tx_id, final_status, tx_hash=tx_hash_onchain, error_message=error_msg)

        # Update context after all transactions for the batch are processed
        self.context["portfolio_summary"] = self.portfolio.get_portfolio_summary()
        self.context["simulated_fund_usd"] = self.simulated_fund_usd
        # self.multisig_wallet.clear_finalized_transactions() # Optionally archive/remove fully processed ones


    async def generate_synopsis(self):
        """Generates a daily synopsis of discussions and decisions."""
        prompt = f"Summarize key discussion points, decisions, and outcomes of any executed/failed on-chain transactions from Day {self.current_day}:\n\nDiscussion Highlights:\n"

        # Limit number of interactions in prompt to avoid excessive length
        max_interactions_for_synopsis = self.evm_config.get("synopsis_max_interactions", 20)
        recent_interactions = self.discussion_log[-max_interactions_for_synopsis:]

        if recent_interactions:
            for interaction in recent_interactions:
                prompt += f"- @{interaction['social_handle']} ({interaction['agent']}) on '{interaction['topic'][:30]}...': {interaction['response'][:150].replace(chr(10), ' ')}...\n"
        else:
            prompt += "- No specific discussion points recorded for today.\n"

        # Include summary of transactions processed on this day (not just pending ones)
        # This requires more sophisticated state tracking of transactions by day, or filtering self.multisig_wallet.pending_transactions
        # For simplicity, this example will just note if there were any non-pending ones.
        processed_tx_summary = []
        for tx_wrapper in self.multisig_wallet.pending_transactions: # Review all, even if not cleared yet
            if tx_wrapper['status'] not in ['pending', 'approved']: # Means it was attempted
                tx_info = tx_wrapper['transaction']
                summary = (f"TxID {tx_wrapper['id']}: {tx_info.get('action','N/A')} "
                           f"{tx_info.get('input_token','N/A') if tx_info.get('action')=='TRADE' else tx_info.get('crypto','N/A')} "
                           f"- Status: {tx_wrapper['status']}.")
                if tx_wrapper.get('tx_hash'): summary += f" (Hash: {tx_wrapper.get('tx_hash')[:10]}...)"
                if tx_wrapper.get('error_message'): summary += f" (Error: {tx_wrapper.get('error_message')[:60]}...)"
                processed_tx_summary.append(summary)

        if processed_tx_summary:
            prompt += "\nTransaction Execution Attempts Summary:\n" + "\n".join(processed_tx_summary)
        else:
            prompt += "\n- No on-chain transaction attempts recorded or processed today.\n"

        try:
            response = self.agents[0].model.generate_content(prompt) # Use first agent for summarization
            self.synopsis = response.text
        except Exception as e:
            self.synopsis = f"Error generating synopsis: {e}"
            print(f"Error during synopsis generation: {e}")

        await self.log_message(f"\n--- Day {self.current_day} Synopsis ---\n{self.synopsis}\n--- End Synopsis ---", level="INFO")
        await self.broadcast({"type": "synopsis", "content": self.synopsis}) # Send to WebSocket clients

    def export_discussion_log(self, filename="crypto_discussion_log_full.json"):
        """Exports the complete discussion log to a JSON file."""
        try:
            with open(filename, 'w') as f:
                json.dump(self.discussion_log, f, indent=2)
            print(f"Full discussion log exported to {filename}")
        except Exception as e:
            print(f"Error exporting discussion log: {e}")


    def generate_seo_friendly_html(self, filename="crypto_discussion_log.html"):
        """Generates an HTML file for viewing the live discussion log."""
        # HTML content is extensive, using the one from previous correct generation.
        # It includes CSS for styling and JavaScript for WebSocket connection.
        html_content = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>AI Crypto Agents Live Discussion Log</title>
            <meta name="description" content="Live autonomous discussion log of AI agents analyzing cryptocurrency trends and making investment decisions.">
            <style>
                body { font-family: 'Courier New', monospace; line-height: 1.6; padding: 20px; max-width: 900px; margin: 0 auto; background-color: #0a0a0a; color: #00ff00; }
                h1, h2 { color: #00ff00; border-bottom: 1px solid #00cc00; padding-bottom: 5px;}
                #log, #terminal { border: 1px solid #00cc00; padding: 15px; margin-bottom: 20px; border-radius: 8px; height: 400px; overflow-y: auto; background-color: #001a00; font-size: 0.9em;}
                #synopsis { border: 1px solid #00cc00; padding: 15px; margin-top: 20px; background-color: #001a00; border-radius: 8px;}
                .interaction { margin-bottom: 15px; padding-bottom:10px; border-bottom: 1px dotted #003300;}
                .timestamp { color: #009900; font-size: 0.8em; }
                .agent { font-weight: bold; color: #33cc33; }
                .topic { font-style: italic; color: #00aa00; margin-top: 5px; margin-bottom: 5px;}
                #status { color: #ff3333; font-weight: bold; text-align: center; padding: 10px; background-color: #1a0000; border-radius: 5px; margin-bottom:10px;}
                pre { white-space: pre-wrap; word-wrap: break-word; color: #ccffcc; }
            </style>
        </head>
        <body>
            <h1>AI Crypto Agents Live Discussion Log</h1>
            <div id="status">Connecting to live feed...</div>
            <h2>System Terminal</h2>
            <div id="terminal"><p>Terminal initialized. Waiting for system messages...</p></div>
            <h2>Agent Discussion Log</h2>
            <div id="log"><p>Agent discussion log. Waiting for interactions...</p></div>
            <h2>Daily Synopsis</h2>
            <div id="synopsis"><p>Waiting for daily synopsis...</p></div>
            <script>
                const terminal = document.getElementById('terminal');
                const log = document.getElementById('log');
                const synopsisDiv = document.getElementById('synopsis');
                const status = document.getElementById('status');
                let socket;

                function formatResponse(text) {
                    // Basic formatting: replace newlines with <br> and indent for readability
                    // Escape HTML to prevent XSS if content is not fully trusted
                    const escapedText = text.replace(/</g, "&lt;").replace(/>/g, "&gt;");
                    return escapedText.replace(/\\n/g, '<br>').replace(/    /g, '&nbsp;&nbsp;&nbsp;&nbsp;');
                }

                function appendToTerminal(message) {
                    const p = document.createElement('p');
                    // Message from log_message is already formatted with timestamp and level
                    p.innerHTML = formatResponse(message);
                    terminal.appendChild(p);
                    terminal.scrollTop = terminal.scrollHeight;
                }

                function appendToLog(interaction) {
                    const div = document.createElement('div');
                    div.classList.add('interaction');
                    div.innerHTML = `
                        <p class="timestamp">${new Date(interaction.timestamp).toLocaleString()}</p>
                        <p class="agent">@${interaction.social_handle} (${interaction.agent})</p>
                        <p class="topic">Topic: ${interaction.topic}</p>
                        <pre>${formatResponse(interaction.response)}</pre>
                    `;
                    log.appendChild(div);
                    log.scrollTop = log.scrollHeight;
                }

                function updateSynopsis(content) {
                    synopsisDiv.innerHTML = `<h2>Daily Synopsis</h2><pre>${formatResponse(content)}</pre>`;
                }

                function connectWebSocket() {
                    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                    // Use current hostname, but allow override from config if needed (e.g. if served behind proxy)
                    const wsHost = document.domain || window.location.hostname || 'localhost';
                    const wsPort = {{WEBSOCKET_PORT}}; // Placeholder for config value, default 8765
                    socket = new WebSocket(`${wsProtocol}//${wsHost}:${wsPort}`);

                    socket.onopen = function(event) {
                        status.textContent = 'Live feed connected.';
                        status.style.color = '#33cc33'; status.style.backgroundColor = '#001a00';
                        console.log('WebSocket connection established');
                        appendToTerminal('WebSocket connection established with server.');
                    };

                    socket.onmessage = function(event) {
                        try {
                            const data = JSON.parse(event.data);
                            if (data.type === 'interaction') {
                                appendToLog(data.content);
                            } else if (data.type === 'synopsis') {
                                updateSynopsis(data.content);
                            } else if (data.type === 'message') {
                                appendToTerminal(data.content);
                            }
                        } catch (e) {
                            console.error('Error parsing JSON message or updating UI:', e, "Raw data:", event.data);
                            appendToTerminal(`Error processing message: ${event.data}`);
                        }
                    };

                    socket.onclose = function(event) {
                        status.textContent = 'Live feed disconnected. Attempting to reconnect in 5s...';
                        status.style.color = '#ff3333'; status.style.backgroundColor = '#1a0000';
                        console.log('WebSocket connection closed. Reconnecting...');
                        appendToTerminal('WebSocket connection closed. Attempting to reconnect...');
                        setTimeout(connectWebSocket, 5000);
                    };

                    socket.onerror = function(error) {
                        console.error('WebSocket error:', error);
                        status.textContent = 'WebSocket connection error. Check console.';
                        status.style.color = '#ff3333';
                        appendToTerminal(`WebSocket error: ${(error && error.message) || 'Unknown error'}`);
                    };
                }
                // Replace placeholder for WebSocket port before connecting
                const finalHtmlContent = document.documentElement.innerHTML.replace('{{WEBSOCKET_PORT}}',
                    (typeof agent_group !== 'undefined' && agent_group.evm_config.websocket_port) ? agent_group.evm_config.websocket_port : 8765);
                // This replacement is tricky as script runs in browser, config is server-side.
                // For a static HTML file, the port needs to be known or hardcoded if not dynamically generated.
                // The above replacement won't work directly. Best to use a known default or inject from server if serving HTML dynamically.
                // For this script, assuming default 8765 is okay.
                connectWebSocket(); // Initial connection attempt
            </script>
        </body>
        </html>
        """
        # Replace placeholder for WebSocket port in the HTML string before writing
        # This is a simplified way; a template engine would be better for dynamic HTML.
        ws_port_from_config = self.evm_config.get("websocket_port", 8765)
        final_html_content = html_content.replace('{{WEBSOCKET_PORT}}', str(ws_port_from_config))

        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(final_html_content)
            print(f"HTML log page generated: {filename}")
        except Exception as e:
            print(f"Error writing HTML file '{filename}': {e}")


    def push_to_social_networks(self):
        """Placeholder for pushing updates (e.g., synopsis) to social media."""
        if not self.synopsis:
            print("No synopsis generated yet to push to social media.")
            return
        social_networks = self.evm_config.get("social_media_platforms", [])
        for network in social_networks:
            print(f"SIMULATING: Pushing synopsis to {network['name']} (API: {network.get('api_endpoint','N/A')})...")
            # Example: if network['name'] == 'twitter': twitter_client.post(self.synopsis)

    # --- WebSocket Methods ---
    async def register(self, websocket):
        """Registers a new WebSocket client."""
        self.websocket_clients.add(websocket)
        await self.log_message(f"Client {websocket.remote_address} connected via WebSocket. Total clients: {len(self.websocket_clients)}", level="DEBUG")

    async def unregister(self, websocket):
        """Unregisters a WebSocket client."""
        self.websocket_clients.discard(websocket)
        await self.log_message(f"Client {websocket.remote_address} disconnected from WebSocket. Total clients: {len(self.websocket_clients)}", level="DEBUG")

    async def broadcast(self, message_payload):
        """Broadcasts a JSON message to all connected WebSocket clients."""
        if self.websocket_clients:
            # Create a list of clients to iterate over, as the set may change during iteration if a client disconnects.
            active_clients = list(self.websocket_clients)
            for client_ws in active_clients:
                try:
                    await asyncio.wait_for(client_ws.send(json.dumps(message_payload)), timeout=1.0)
                except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError, ConnectionResetError) as e:
                    print(f"WebSocket broadcast error to {client_ws.remote_address}: {type(e).__name__}. Removing client.")
                    self.websocket_clients.discard(client_ws) # Remove problematic client
                except Exception as e: # Catch other unexpected errors during send
                    print(f"Unexpected WebSocket broadcast error to {client_ws.remote_address}: {e}. Removing client.")
                    self.websocket_clients.discard(client_ws)

    # --- External API Push ---
    def push_to_api(self, interaction_data):
        """Pushes interaction data to a configured external API endpoint."""
        api_endpoint = self.evm_config.get("external_api_endpoint")
        if not api_endpoint:
            # print(f"Simulated API push (no endpoint configured): {interaction_data['topic'][:50]}...") # Can be noisy
            return

        try:
            response = requests.post(api_endpoint, json=interaction_data, timeout=self.evm_config.get("api_timeout_seconds", 10))
            if response.status_code >= 200 and response.status_code < 300:
                print(f"Successfully pushed interaction for agent {interaction_data['agent']} to {api_endpoint}. Status: {response.status_code}")
            else:
                print(f"Failed to push interaction to {api_endpoint}. Status: {response.status_code}, Response: {response.text[:100]}")
        except requests.exceptions.RequestException as e:
            print(f"Error pushing interaction data to {api_endpoint}: {e}")
        except Exception as e:
            print(f"Unexpected error during API push for {interaction_data['agent']}: {e}")


async def start_websocket_server(agent_group_instance):
    """Starts the WebSocket server for live updates."""
    global websocket_server_running
    async def websocket_handler(websocket, path): # 'path' is unused but required by websockets.serve
        await agent_group_instance.register(websocket)
        try:
            # Keep connection alive, handle incoming messages if any (currently none expected from client)
            async for message in websocket:
                await agent_group_instance.log_message(f"Message received from WebSocket client {websocket.remote_address}: {message}", level="DEBUG")
        except websockets.exceptions.ConnectionClosed as e:
            await agent_group_instance.log_message(f"WebSocket client {websocket.remote_address} connection closed. Code: {e.code}, Reason: '{e.reason}'.", level="DEBUG")
        except Exception as e: # Catch any other errors during the WebSocket connection lifetime
            await agent_group_instance.log_message(f"Error with WebSocket client {websocket.remote_address}: {type(e).__name__} - {e}", level="ERROR")
        finally:
            await agent_group_instance.unregister(websocket) # Ensure unregistration on any exit

    if websocket_server_running: # Prevent multiple server instances
        await agent_group_instance.log_message("WebSocket server already attempting to run.", level="WARNING")
        return

    websocket_server_running = True
    host = agent_group_instance.evm_config.get("websocket_host", "localhost")
    port = agent_group_instance.evm_config.get("websocket_port", 8765)

    try:
        server = await websockets.serve(websocket_handler, host, port)
        await agent_group_instance.log_message(f"WebSocket server started on ws://{host}:{port}", level="INFO")
        await server.wait_closed() # Keeps the server running until it's explicitly closed or an error occurs
    except OSError as e: # Specific error for "address already in use"
        await agent_group_instance.log_message(f"WebSocket OSError (likely port {port} is already in use): {e}", level="CRITICAL")
    except Exception as e:
        await agent_group_instance.log_message(f"WebSocket server encountered an error: {type(e).__name__} - {e}", level="CRITICAL")
    finally:
        websocket_server_running = False
        await agent_group_instance.log_message("WebSocket server has shut down.", level="INFO")


def run_http_server(html_file_path, agent_group_instance):
    """Runs a simple HTTP server to serve the discussion log HTML file."""
    global http_server_running
    if http_server_running: # Prevent multiple server instances
        print("HTTP server already attempting to run.") # Use print as log_message is async
        return

    # Handler to serve the specific HTML file from its directory
    class CustomFileHandler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            # Serve files from the directory containing the target HTML file
            super().__init__(*args, directory=os.path.dirname(os.path.abspath(html_file_path)) or '.', **kwargs)

        def do_GET(self):
            # If root is requested, serve the specified HTML file
            if self.path == '/':
                self.path = os.path.basename(html_file_path)
            super().do_GET()

    host = agent_group_instance.evm_config.get("http_host", "localhost")
    port = agent_group_instance.evm_config.get("http_port", 8000)
    max_attempts = 3 # Try a few ports if the default is taken

    for attempt in range(max_attempts):
        current_port = port + attempt
        try:
            with socketserver.TCPServer((host, current_port), CustomFileHandler) as httpd:
                http_server_running = True
                print(f"HTTP server started. View log at http://{host}:{current_port}/{os.path.basename(html_file_path)}")
                httpd.serve_forever() # This is blocking, so run in a thread
                break # Exit loop if server starts
        except OSError as e:
            if e.errno == 98 or e.errno == 10048: # Address already in use (Linux/Windows)
                print(f"HTTP Port {current_port} is in use. Trying next port if available...")
                if attempt == max_attempts - 1:
                    print("HTTP server failed to start: Maximum port attempts reached.")
            else: # Other OS error
                print(f"HTTP server OSError: {e}. Cannot start server."); break
        except Exception as e: # Other unexpected errors
            print(f"HTTP server failed to start due to an unexpected error: {e}"); break

    http_server_running = False # If loop completes without starting server


async def main():
    """Main function to initialize and run the AI agent group."""
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        print("CRITICAL ERROR: The 'GEMINI_API_KEY' environment variable is not set.")
        print("Please set this variable with your Google Gemini API key to proceed.")
        return

    # Define AI Agents
    agents_config = [
        AIAgent("TrendMaster", "Expert in identifying emerging cryptocurrency trends and market sentiment. Focuses on proposing trades (TRADE <IN_TOKEN> <OUT_TOKEN> <IN_AMOUNT> <NETWORK> <DEX>) with strong technical and fundamental justification.", gemini_api_key, "TrendMasterBot"),
        AIAgent("RiskGuardian", "Specializes in analyzing proposed trades for potential risks, considering market volatility, portfolio allocation, and smart contract security. Provides clear APPROVE/REJECT votes with detailed reasoning.", gemini_api_key, "RiskGuardianBot"),
        AIAgent("StrategyArchitect", "Develops long-term investment strategies and identifies tokens with robust fundamentals. May propose initial 'test buys' for promising assets using the TRADE command.", gemini_api_key, "StrategyArchitectBot"),
    ]

    # Initial simulated funding (does not affect on-chain wallet)
    try:
        sim_btc_price = float(os.getenv("MOCK_BTC_PRICE_USD", "60000"))
        sim_initial_usd = float(os.getenv("MOCK_INITIAL_USD_FUND", "1000"))
        initial_sim_btc = sim_initial_usd / sim_btc_price if sim_btc_price > 0 else 0.0001 # Avoid division by zero
    except (ValueError, ZeroDivisionError) as e:
        print(f"Warning: Invalid simulated funding setup via environment variables ({e}). Using small default BTC amount.")
        initial_sim_btc = 0.0001

    # Create the agent group
    agent_group = AgentGroup(agents_config, initial_simulated_btc_amount=initial_sim_btc)

    # Generate the HTML log file (can be done before servers start)
    html_log_filename = "crypto_discussion_log.html"
    agent_group.generate_seo_friendly_html(html_log_filename)

    await agent_group.log_message("Initializing AI Agent Group simulation and web services...", level="INFO")

    # Start WebSocket server for live updates
    websocket_server_task = asyncio.create_task(start_websocket_server(agent_group))

    # Start HTTP server in a separate thread (as it's blocking)
    # The thread is daemonized so it exits when the main program exits.
    http_server_thread = threading.Thread(
        target=run_http_server, args=(html_log_filename, agent_group), daemon=True
    )
    http_server_thread.start()

    await asyncio.sleep(1) # Brief pause to allow server startup messages

    # Check if servers started (WebSocket is async, HTTP is harder to check directly from here)
    if not websocket_server_running:
        await agent_group.log_message("WebSocket server failed to start. Live HTML updates may not work.", level="CRITICAL")

    # Run the main discussion simulation for a configured number of days
    num_days_to_simulate = agent_group.evm_config.get("discussion_simulation_days", 1)
    await agent_group.autonomous_discussion(num_simulation_days=num_days_to_simulate)

    await agent_group.log_message("Autonomous discussion simulation complete. Shutting down services...", level="INFO")

    # Cleanly shut down WebSocket server
    if websocket_server_task and not websocket_server_task.done():
        websocket_server_task.cancel()
        try:
            await websocket_server_task # Wait for cancellation to complete
        except asyncio.CancelledError:
            await agent_group.log_message("WebSocket server task was successfully cancelled.", level="INFO")
        except Exception as e: # Catch any other error during shutdown
            await agent_group.log_message(f"Error encountered during WebSocket server shutdown: {e}", level="ERROR")

    # HTTP server thread is daemon, will exit automatically.
    # For non-daemon, join would be: http_thread.join(timeout=5) after httpd.shutdown() from within the thread.

    agent_group.export_discussion_log() # Save full log at the end
    await agent_group.log_message("Script execution finished.", level="INFO")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nApplication interrupted by user (Ctrl+C). Beginning graceful shutdown...")
        # asyncio tasks are cancelled in main's finally block or if already done.
    except Exception as e: # Catch-all for any unexpected errors in main's execution
        print(f"CRITICAL UNHANDLED ERROR in __main__: {type(e).__name__} - {e}")
        import traceback
        traceback.print_exc() # Print full stack trace for debugging
    finally:
        print("Application exit sequence initiated.")
        # Any final cleanup, though most is handled in main's try/except/finally structure.
        # Ensure all async tasks are properly awaited or cancelled if main exits early.
        # For example, if websocket_server_task was not awaited due to an early error in main.
        # This is complex; robust shutdown often involves signal handlers and more explicit task management.
        print("Application has finished exiting.")
