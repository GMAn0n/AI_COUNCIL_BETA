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

# Global variables
websocket_server_running = False
http_server_running = False

class AIAgent:
    def __init__(self, name, role, api_key, social_handle):
        self.name = name
        self.role = role
        self.social_handle = social_handle
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-pro')

    def process_input(self, input_text, context):
        prompt = f"""As an AI assistant with the role of {self.role} and social media handle @{self.social_handle}, respond to the following in the context of financial markets and cryptocurrency:
        
        Context: {json.dumps(context)}
        
        Input: {input_text}
        
        Provide your analysis, recommendations, or comments based on your role. Include relevant hashtags and mention other agents using their handles when appropriate."""
        
        response = self.model.generate_content(prompt)
        return response.text

    def vote_on_transaction(self, transaction, context):
        prompt = f"""As an AI assistant with the role of {self.role}, evaluate the following transaction:
        
        Transaction: {json.dumps(transaction)}
        Context: {json.dumps(context)}
        
        Should this transaction be approved? Respond with APPROVE or REJECT, followed by your reasoning."""
        
        response = self.model.generate_content(prompt)
        return response.text

class CryptoPortfolio:
    def __init__(self):
        self.holdings = {}
        self.transaction_history = []

    def update_holding(self, crypto, amount):
        if crypto in self.holdings:
            self.holdings[crypto] += amount
        else:
            self.holdings[crypto] = amount
        
        self.transaction_history.append({
            "date": datetime.now().isoformat(),
            "crypto": crypto,
            "amount": amount
        })

    def get_portfolio_summary(self):
        return json.dumps(self.holdings)

    def get_transaction_history(self):
        return json.dumps(self.transaction_history)

class MultisigWallet:
    def __init__(self, agents, required_signatures):
        self.agents = agents
        self.required_signatures = required_signatures
        self.pending_transactions = []

    def propose_transaction(self, transaction):
        self.pending_transactions.append({
            "transaction": transaction,
            "votes": [],
            "status": "pending"
        })

    def vote_on_transactions(self, context):
        for tx in self.pending_transactions:
            if tx["status"] == "pending":
                for agent in self.agents:
                    vote = agent.vote_on_transaction(tx["transaction"], context)
                    tx["votes"].append({"agent": agent.name, "vote": vote})
                
                approvals = sum(1 for vote in tx["votes"] if vote["vote"].startswith("APPROVE"))
                if approvals >= self.required_signatures:
                    tx["status"] = "approved"
                elif len(tx["votes"]) == len(self.agents):
                    tx["status"] = "rejected"

    def get_approved_transactions(self):
        return [tx["transaction"] for tx in self.pending_transactions if tx["status"] == "approved"]

    def clear_processed_transactions(self):
        self.pending_transactions = [tx for tx in self.pending_transactions if tx["status"] == "pending"]

class AgentGroup:
    def __init__(self, agents, initial_btc_amount):
        self.agents = agents
        self.portfolio = CryptoPortfolio()
        self.fund_usd = 0  # Initialize USD fund to 0
        self.portfolio.update_holding("BTC", initial_btc_amount)
        self.context = {
            "portfolio": self.portfolio.get_portfolio_summary(),
            "latest_trends": [],
            "viral_metas": [],
            "multiplication_strategies": [],
            "simulated_scenarios": []
        }
        self.multisig_wallet = MultisigWallet(agents, required_signatures=2)
        self.discussion_log = []
        self.current_day = 1
        self.websocket_clients = set()
        self.synopsis = ""
        self.discussion_state_file = "discussion_state.json"

    def save_state(self):
        state = {
            "current_day": self.current_day,
            "discussion_log": self.discussion_log,
            "context": self.context,
            "portfolio": self.portfolio.holdings,
            "fund_usd": self.fund_usd
        }
        with open(self.discussion_state_file, 'w') as f:
            json.dump(state, f)

    def load_state(self):
        if os.path.exists(self.discussion_state_file):
            with open(self.discussion_state_file, 'r') as f:
                state = json.load(f)
            self.current_day = state['current_day']
            self.discussion_log = state['discussion_log']
            self.context = state['context']
            self.portfolio.holdings = state['portfolio']
            self.fund_usd = state['fund_usd']
            return True
        return False

    async def log_message(self, message):
        print(message)
        await self.broadcast({"type": "message", "content": message})

    async def log_interaction(self, agent, topic, response):
        interaction = {
            "timestamp": datetime.now().isoformat(),
            "agent": agent.name,
            "social_handle": agent.social_handle,
            "topic": topic,
            "response": response
        }
        self.discussion_log.append(interaction)
        print(f"@{agent.social_handle}: {response}")
        
        await self.broadcast({"type": "interaction", "content": interaction})
        
        # Push to API
        self.push_to_api(interaction)

    async def autonomous_discussion(self, num_days):
        await self.log_message("Starting autonomous discussion...")
        if self.load_state():
            await self.log_message(f"Resuming discussion from day {self.current_day}")
        for day in range(self.current_day, num_days + 1):
            self.current_day = day
            await self.log_message(f"\nDay {self.current_day}:")
            await self.daily_discussion()
            await self.generate_synopsis()
            self.save_state()
            await asyncio.sleep(2)  # Add a delay between days for readability

    async def daily_discussion(self):
        if self.current_day <= 3:
            await self.simulate_scenario()
        for _ in range(3):  # 3 discussion rounds per day
            for agent in self.agents:
                topic = self.generate_topic()
                response = agent.process_input(topic, self.context)
                await self.log_interaction(agent, topic, response)
                self.update_context([response])
        self.multisig_wallet.vote_on_transactions(self.context)
        self.execute_approved_transactions()

    async def simulate_scenario(self):
        asset = random.choice(["ETH", "ADA", "DOT", "LINK", "UNI"])
        scenario = f"What if we invested our $500 worth of Bitcoin in {asset}?"
        await self.log_message(f"Simulating scenario: {scenario}")
        for agent in self.agents:
            response = agent.process_input(scenario, self.context)
            await self.log_interaction(agent, scenario, response)
            self.update_context([response])
        self.context["simulated_scenarios"].append({"day": self.current_day, "scenario": scenario})

    def generate_topic(self):
        topics = [
            "What's the next big trend in crypto that could multiply our investment?",
            "How can we leverage our small crypto holding to maximize returns?",
            "What low-risk strategies can we employ to grow our limited crypto fund?",
            "Are there any emerging altcoins or DeFi projects that could provide high returns on a small investment?",
            "What viral marketing strategies could we use to attract more funding or partnerships?",
            "How can we use our expertise to offer services and grow our fund?",
            "What are some creative ways to participate in the crypto ecosystem with limited capital?",
            "Based on our simulated scenarios, what actions should we consider taking?"
        ]
        return random.choice(topics)

    def update_context(self, responses):
        for response in responses:
            if "TREND:" in response:
                self.context["latest_trends"].append(response.split("TREND:")[1].strip())
            if "VIRAL_META:" in response:
                self.context["viral_metas"].append(response.split("VIRAL_META:")[1].strip())
            if "TRADE:" in response:
                self.propose_trade(response.split("TRADE:")[1].strip())
            if "MULTIPLY_STRATEGY:" in response:
                self.context["multiplication_strategies"].append(response.split("MULTIPLY_STRATEGY:")[1].strip())

    def propose_trade(self, trade_info):
        parts = trade_info.split()
        if len(parts) == 3:
            action, amount, crypto = parts
            amount = float(amount)
            self.multisig_wallet.propose_transaction({
                "action": action,
                "amount": amount,
                "crypto": crypto
            })

    def execute_approved_transactions(self):
        for tx in self.multisig_wallet.get_approved_transactions():
            if tx["action"] == "BUY" and self.fund_usd >= tx["amount"]:
                self.fund_usd -= tx["amount"]
                self.portfolio.update_holding(tx["crypto"], tx["amount"])
            elif tx["action"] == "SELL":
                self.fund_usd += tx["amount"]
                self.portfolio.update_holding(tx["crypto"], -tx["amount"])
        
        self.context["current_fund_usd"] = self.fund_usd
        self.context["portfolio"] = self.portfolio.get_portfolio_summary()
        self.multisig_wallet.clear_processed_transactions()

    async def generate_synopsis(self):
        prompt = f"Summarize the key points and decisions from today's discussion:\n\n"
        for interaction in self.discussion_log[-len(self.agents)*3:]:
            prompt += f"{interaction['agent']}: {interaction['response']}\n"
        
        response = self.agents[0].model.generate_content(prompt)
        self.synopsis = response.text
        await self.log_message(f"\nDay {self.current_day} Synopsis:\n{self.synopsis}")
        
        await self.broadcast({"type": "synopsis", "content": self.synopsis})

    def export_discussion_log(self, filename):
        with open(filename, 'w') as f:
            json.dump(self.discussion_log, f, indent=2)
        print(f"Discussion log exported to {filename}")

    def generate_seo_friendly_html(self, filename):
        html_content = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>AI Crypto Agents Live Discussion Log</title>
            <meta name="description" content="Live autonomous discussion log of AI agents analyzing cryptocurrency trends and making investment decisions.">
            <style>
                body {
                    font-family: 'Courier New', monospace;
                    line-height: 1.6;
                    padding: 20px;
                    max-width: 800px;
                    margin: 0 auto;
                    background-color: #000;
                    color: #0f0;
                }
                h1 { color: #0f0; }
                #log {
                    border: 1px solid #0f0;
                    padding: 10px;
                    margin-bottom: 20px;
                    border-radius: 5px;
                    height: 400px;
                    overflow-y: auto;
                    background-color: rgba(0, 255, 0, 0.1);
                }
                #synopsis {
                    border: 1px solid #0f0;
                    padding: 10px;
                    margin-top: 20px;
                    background-color: rgba(0, 255, 0, 0.1);
                }
                .interaction { margin-bottom: 10px; }
                .timestamp { color: #0a0; font-size: 0.8em; }
                .agent { font-weight: bold; color: #0f0; }
                .topic { font-style: italic; color: #0c0; }
                #status { color: #f00; }
                #terminal {
                    border: 1px solid #0f0;
                    padding: 10px;
                    margin-bottom: 20px;
                    border-radius: 5px;
                    height: 200px;
                    overflow-y: auto;
                    background-color: rgba(0, 255, 0, 0.1);
                }
            </style>
        </head>
        <body>
            <h1>AI Crypto Agents Live Discussion Log</h1>
            <div id="status"></div>
            <h2>Terminal Output</h2>
            <div id="terminal"></div>
            <h2>Discussion Log</h2>
            <div id="log"></div>
            <div id="synopsis"></div>
            <script>
                const terminal = document.getElementById('terminal');
                const log = document.getElementById('log');
                const synopsis = document.getElementById('synopsis');
                const status = document.getElementById('status');
                let socket;

                function connectWebSocket() {
                    socket = new WebSocket('ws://localhost:8765');

                    socket.onopen = function(event) {
                        status.textContent = 'Connected to live discussion.';
                        status.style.color = '#0f0';
                        console.log('WebSocket connection established');
                    };

                    socket.onmessage = function(event) {
                        console.log('Received message:', event.data);
                        const data = JSON.parse(event.data);
                        if (data.type === 'interaction') {
                            const interaction = data.content;
                            const interactionHtml = `
                                <div class="interaction">
                                    <p class="timestamp">${interaction.timestamp}</p>
                                    <p class="agent">@${interaction.social_handle} (${interaction.agent})</p>
                                    <p class="topic">Topic: ${interaction.topic}</p>
                                    <p>${interaction.response}</p>
                                </div>
                            `;
                            log.innerHTML += interactionHtml;
                            log.scrollTop = log.scrollHeight;
                        } else if (data.type === 'synopsis') {
                            synopsis.innerHTML = `<h2>Daily Synopsis</h2><p>${data.content}</p>`;
                        } else if (data.type === 'message') {
                            terminal.innerHTML += `<p>${data.content}</p>`;
                            terminal.scrollTop = terminal.scrollHeight;
                        }
                    };

                    socket.onclose = function(event) {
                        status.textContent = 'Disconnected from live discussion. Attempting to reconnect...';
                        status.style.color = '#f00';
                        console.log('WebSocket connection closed. Attempting to reconnect...');
                        setTimeout(connectWebSocket, 5000);
                    };

                    socket.onerror = function(error) {
                        console.error('WebSocket error:', error);
                    };
                }

                connectWebSocket();
            </script>
        </body>
        </html>
        """

        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(html_content)
            print(f"SEO-friendly HTML with live updates exported to {filename}")
        except UnicodeEncodeError:
            print("Warning: Unable to write some characters. Falling back to ASCII encoding.")
            with open(filename, 'w', encoding='ascii', errors='ignore') as f:
                f.write(html_content)
            print(f"SEO-friendly HTML exported to {filename} (some characters may be missing)")

    def push_to_social_networks(self):
        # Placeholder for social network API integration
        social_networks = ["Twitter", "Facebook", "LinkedIn"]
        for network in social_networks:
            print(f"Pushing latest update to {network} API...")
            # Implement actual API calls here when accounts are created

    async def register(self, websocket):
        self.websocket_clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            self.websocket_clients.remove(websocket)

    async def broadcast(self, message):
        if self.websocket_clients:
            print(f"Broadcasting message: {message}")
            websockets_to_remove = set()
            for websocket in self.websocket_clients:
                try:
                    await asyncio.wait_for(websocket.send(json.dumps(message)), timeout=1.0)
                    print(f"Message sent to {websocket.remote_address}")
                except (websockets.exceptions.ConnectionClosed, asyncio.TimeoutError) as e:
                    print(f"Error sending message to {websocket.remote_address}: {e}")
                    websockets_to_remove.add(websocket)
            
            # Remove closed connections
            self.websocket_clients -= websockets_to_remove
        else:
            print("No WebSocket clients connected. Message not sent.")

    def push_to_api(self, interaction):
        # Simulating API push. Replace with actual API endpoint and logic
        api_endpoint = "https://api.example.com/push-update"
        try:
            # response = requests.post(api_endpoint, json=interaction)
            # if response.status_code == 200:
            #     print(f"Successfully pushed update to API")
            # else:
            #     print(f"Failed to push update to API. Status code: {response.status_code}")
            print(f"Simulated API push: {interaction}")
        except Exception as e:
            print(f"Error pushing to API: {e}")

    async def unregister(self, websocket):
        self.websocket_clients.remove(websocket)

async def start_websocket_server(agent_group):
    global websocket_server_running
    async def handler(websocket, path):
        print(f"New WebSocket connection from {websocket.remote_address}")
        await agent_group.register(websocket)
        try:
            async for message in websocket:
                print(f"Received message from client {websocket.remote_address}: {message}")
                # Handle any incoming messages if needed
        except websockets.exceptions.ConnectionClosed:
            print(f"WebSocket connection closed for {websocket.remote_address}")
        finally:
            await agent_group.unregister(websocket)

    try:
        server = await websockets.serve(handler, "localhost", 8765)
        websocket_server_running = True
        print("WebSocket server started on ws://localhost:8765")
        await server.wait_closed()
    except Exception as e:
        print(f"Error starting WebSocket server: {e}")
    finally:
        websocket_server_running = False

def run_http_server(html_file):
    global http_server_running
    class Handler(http.server.SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            with open(html_file, 'rb') as file:
                self.wfile.write(file.read())

    port = 8000
    while not http_server_running:
        try:
            with socketserver.TCPServer(("", port), Handler) as httpd:
                http_server_running = True
                print(f"HTTP server started. Live discussion log is now available at http://localhost:{port}")
                httpd.serve_forever()
        except OSError as e:
            if e.errno == 98 or e.errno == 10048:  # Address already in use
                print(f"Port {port} is already in use. Trying the next port.")
                port += 1
            else:
                raise

async def main():
    gemini_api_key = "AIzaSyDtEgGyrrp1cQSkVSYIU5aQ6ZGnlMs8RzU"

    agents = [
        AIAgent("TrendSpotter", "Identify emerging trends and multiplication strategies in crypto", gemini_api_key, "crypto_trend_guru"),
        AIAgent("ViralCreator", "Create viral metas and marketing strategies to grow our fund", gemini_api_key, "viral_crypto_memes"),
        AIAgent("PortfolioManager", "Manage our limited crypto portfolio and suggest optimal trades", gemini_api_key, "crypto_portfolio_pro"),
    ]

    initial_btc = 500 / 30000  # Assuming 1 BTC = $30,000, adjust as needed

    agent_group = AgentGroup(agents, initial_btc_amount=initial_btc)
    
    # Generate initial HTML file
    agent_group.generate_seo_friendly_html("crypto_discussion_log.html")

    print("Starting servers...")
    
    # Start WebSocket server
    websocket_task = asyncio.create_task(start_websocket_server(agent_group))
    
    # Start HTTP server in a separate thread
    http_thread = threading.Thread(target=run_http_server, args=("crypto_discussion_log.html",))
    http_thread.start()

    # Wait for WebSocket server to start
    await asyncio.sleep(2)

    # Run the autonomous discussion
    await agent_group.autonomous_discussion(num_days=3)

    # Wait for the WebSocket server to complete
    await websocket_task

    print("Discussion and WebSocket server have completed.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Shutting down...")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        print("Script terminated.")
