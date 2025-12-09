# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a SignalWire Blackjack game featuring an AI-powered dealer that integrates with web applications using WebRTC video calling. The project demonstrates building sophisticated SignalWire AI Agents with real-time communication and stateless architecture.

## Key Architecture Components

### Main Components
- **bot/sigmond_blackjack.py**: Core AI dealer agent using SignalWire Agents SDK - implements stateless blackjack game logic with conversation flow control via steps (betting → playing → hand_complete). Uses `AgentServer` with `serve_static_files()` to serve static files without authentication, while the agent's authenticated routes are at `/blackjack`.
- **web_server.py**: Standalone static file server (optional, for separate deployment)
- **web/client/**: Interactive web interface - handles WebRTC video calls and real-time game UI updates via SWML events

### State Management Pattern
The game uses a stateless architecture where all game state is persisted via `update_global_data()` and retrieved from `global_data` on each function call. No reliance on instance variables or session state.

### Conversation Flow
Step-based conversation management with structured transitions:
1. **betting**: Accept bets, deal initial cards
2. **playing**: Handle hit/stand/double down actions
3. **hand_complete**: Show results, offer new hand
4. **game_over**: Handle out-of-chips scenario

## Development Commands

### Running the Application

#### Start the Blackjack Dealer Bot:
```bash
cd bot
./bot.sh start    # Start on port 5000
./bot.sh stop     # Stop the dealer
./bot.sh restart  # Restart the dealer
./bot.sh status   # Check if running
./bot.sh logs     # View logs
```

#### Direct Python execution:
```bash
# Run the dealer with integrated web serving
cd bot
python sigmond_blackjack.py  # Runs on port 5000 by default

# Or specify a custom port:
python sigmond_blackjack.py --port 8080

# The bot now serves:
# - Web client at http://localhost:5000/ (serves client/index.html) - NO AUTH REQUIRED
# - Card images at http://localhost:5000/card_images/ - NO AUTH REQUIRED
# - Media files at root (e.g., http://localhost:5000/sigmond_bj_idle.mp4) - NO AUTH REQUIRED
# - SWML endpoint at http://localhost:5000/blackjack - REQUIRES BASIC AUTH
```

#### Standalone Web Server (optional):
```bash
python web_server.py --port 8080  # Only needed for separate deployment
```

#### Heroku/Dokku Deployment:
```bash
# The Procfile runs: python bot/sigmond_blackjack.py --port $PORT
# For Heroku: git push heroku main
# For Dokku: git push dokku main

# The app will automatically use the PORT environment variable
# Single process serves both the agent API and web client
```

### Testing SWAIG Functions
```bash
cd bot
swaig-test sigmond_blackjack.py --list-tools
swaig-test sigmond_blackjack.py --exec place_bet --amount 50
```

### Dependencies Installation
```bash
pip install -r requirements.txt
# Main dependency: signalwire-agents (includes fastapi, uvicorn)
```

## Environment Variables

**Optional:**
- `SWML_PROXY_URL_BASE`: Base URL when behind reverse proxy (used for media file URLs, defaults to `http://localhost:{port}`)
- `SWML_BASIC_AUTH_USER`: Basic auth username (auto-generated if not set)
- `SWML_BASIC_AUTH_PASSWORD`: Basic auth password (auto-generated if not set)
- `PORT`: Agent port (default: 5000, used by Heroku/Dokku)

**For HTTPS:**
- `SWML_SSL_ENABLED=true`
- `SWML_SSL_CERT_PATH=/path/to/cert.pem`
- `SWML_SSL_KEY_PATH=/path/to/key.pem`
- `SWML_DOMAIN=yourdomain.com`

## Key Implementation Patterns

### SWML User Events
Communication with frontend via real-time events:
```python
result.swml_user_event({
    "type": "cards_dealt",
    "player_hand": game_state["player_hand"],
    "dealer_hand": [game_state["dealer_hand"][0], None],
    "player_score": game_state["player_score"]
})
```

### State Persistence
```python
game_state, global_data = get_game_state(raw_data)
# Modify game_state
global_data['game_state'] = game_state
result.update_global_data(global_data)
```

### Step Transitions
```python
result.swml_change_step("hand_complete")
```

## Game Functions

- **place_bet**: Accepts bet amount, deals initial cards, checks for blackjack
- **hit**: Draws card for player, checks for bust/21
- **stand**: Plays dealer hand following casino rules, resolves game
- **double_down**: Doubles bet, draws one card, completes hand
- **new_hand**: Resets table, transitions back to betting step

## Important Files to Modify

When updating the game:
1. **bot/sigmond_blackjack.py**: Game logic, conversation flow, SWAIG functions, static file serving
2. **web/client/app.js**: Frontend game logic, event handlers, UI updates
3. **web/client/index.html**: UI structure and layout

## Authentication

- The web client and all static files (card images, videos, audio) are served without authentication
- Only the `/blackjack` SWML endpoint requires Basic Auth credentials
- This allows public access to the web interface while protecting the agent API

## Testing Checklist

Before deploying changes:
1. Verify all SWAIG functions work via swaig-test
2. Check conversation step transitions flow correctly
3. Ensure SWML events update the UI properly
4. Test edge cases: blackjack, bust, push, out of chips
5. Verify state persistence across function calls