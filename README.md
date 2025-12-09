# SignalWire Blackjack - AI Agent Demo

A fully-functional blackjack game demonstrating how to build sophisticated SignalWire AI Agents with integrated web serving. This project showcases a single-service architecture where the AI agent serves both the SWML API and the web client, with real-time communication via WebRTC video calling and event-driven architecture.

## 🎮 Play Now

Visit [https://blackjack.signalwire.me](https://blackjack.signalwire.me) to play!

## Overview

This demonstration application illustrates best practices for building SignalWire AI Agents that:
- Serve both API and web client from a single process
- Maintain complex stateless game logic
- Communicate with web frontends via SWML events
- Manage conversation flow through structured steps
- Integrate WebRTC video/audio for immersive experiences
- Handle real-time user interactions and state synchronization
- Provide public web access while protecting API endpoints

The blackjack game serves as a practical example of these concepts, featuring a professional AI dealer that manages gameplay, maintains state, and provides real-time UI updates through SignalWire's platform.

## Features

- **AI-Powered Dealer**: Professional dealer using ElevenLabs' Adam voice
- **Integrated Web Serving**: Single process serves both API and web client
- **Standard Casino Rules**: Dealer hits on 16, stands on 17
- **Complete Game Mechanics**:
  - Betting system with starting chips (1000)
  - Hit, Stand, and Double Down actions
  - Automatic dealer play following casino rules
  - Blackjack bonus payout (3:2)
- **Interactive Web Interface**: Real-time card display with animations
- **Video Call Integration**: Face-to-face gaming via SignalWire WebRTC
- **Stateless Architecture**: Centralized game state management with proper flow control
- **Step-Based Conversation Flow**: Structured gameplay with betting → playing → hand_complete steps
- **Social Media Ready**: Open Graph meta tags for rich social sharing
- **Authentication**: Public web access with protected API endpoints
- **Event Logging**: Optional debug log for monitoring game events

## Project Structure

```
blackjack/
├── bot/                        # Bot implementation
│   ├── sigmond_blackjack.py   # AI dealer with integrated web server
│   └── bot.sh                 # Control script for starting/stopping
├── web/                       # Web interface and media files
│   ├── client/                # Frontend application
│   │   ├── index.html         # Main UI with Open Graph meta tags
│   │   ├── app.js             # JavaScript game logic
│   │   ├── signalwire.js      # SignalWire SDK
│   │   └── favicon.svg        # Blackjack-themed favicon
│   ├── card_images/           # Playing card images
│   ├── og-image.svg           # Social media preview image
│   ├── sigmond_bj_idle.mp4    # Dealer idle video
│   ├── sigmond_bj_talking.mp4 # Dealer talking video
│   └── casino.mp3             # Background music
├── Procfile                   # Heroku/Dokku deployment config
├── requirements.txt           # Python dependencies
├── runtime.txt                # Python version specification
└── CLAUDE.md                  # Developer documentation
```


## Setup

### Environment Variables

**Optional**:
- `SWML_PROXY_URL_BASE`: Base URL when behind reverse proxy (used for media file URLs, defaults to `http://localhost:{port}`)
- `PORT`: Port to run the service on (default: 5000)
- `SWML_BASIC_AUTH_USER`: Basic auth username for API (auto-generated if not set)
- `SWML_BASIC_AUTH_PASSWORD`: Basic auth password for API (auto-generated if not set)

### Running with HTTPS

To run the bot with HTTPS enabled, set the following environment variables:

```bash
export SWML_SSL_ENABLED=true
export SWML_SSL_CERT_PATH=/path/to/cert.pem
export SWML_SSL_KEY_PATH=/path/to/key.pem
export SWML_DOMAIN=yourdomain.com
```

The SignalWire Agents SDK provides comprehensive security features including:
- SSL/TLS encryption
- Basic authentication (enabled by default)
- HSTS headers
- CORS configuration
- Rate limiting
- Request size limits

For complete security configuration options, see the [SignalWire Agents Security Documentation](https://github.com/signalwire/signalwire-agents/blob/main/docs/security.md).

### Quick Start

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Run the integrated server:
   ```bash
   cd bot
   python sigmond_blackjack.py  # Runs on port 5000 by default
   ```

3. Access the application:
   - Web client: `http://localhost:5000/`
   - API endpoint: `http://localhost:5000/blackjack` (requires auth)

### Using the Control Script

```bash
cd bot
./bot.sh start    # Start the dealer on port 5000
./bot.sh restart  # Restart the dealer
./bot.sh status   # Check if dealer is running
./bot.sh logs     # View logs
./bot.sh stop     # Stop the dealer
```

### Custom Port

```bash
python sigmond_blackjack.py --port 8080
```

### HTTPS Mode

```bash
export SWML_SSL_ENABLED=true
export SWML_SSL_CERT_PATH=/path/to/cert.pem
export SWML_SSL_KEY_PATH=/path/to/key.pem
export SWML_DOMAIN=yourdomain.com
python sigmond_blackjack.py
```

### Deployment

#### Heroku/Dokku

The application is configured for easy deployment to Heroku or Dokku:

```bash
# For Heroku
git push heroku main

# For Dokku
git push dokku main
```

The Procfile automatically configures the service to run on the platform's assigned PORT.

#### Configuration for Production

1. Update the SignalWire token in `web/client/app.js`:
   ```javascript
   const STATIC_TOKEN = 'your-signalwire-token-here';
   ```

2. Update the destination for your SignalWire routing:
   ```javascript
   const DESTINATION = '/public/your-agent-name';
   ```

## How to Play

1. **Connect**: Click "Connect to Dealer" to initiate a video call
2. **Place Bet**: Tell the dealer how much you want to bet (minimum 10 chips)
3. **Initial Deal**: Receive two cards, dealer shows one card
4. **Player Actions**:
   - **Hit**: Say "hit" to take another card
   - **Stand**: Say "stand" to keep your current hand
   - **Double Down**: Say "double down" to double your bet and receive exactly one more card
5. **Dealer Turn**: Dealer reveals hole card and draws according to rules
6. **Resolution**: Hand completes, winner determined, cards remain visible
7. **New Hand**: Say "yes" when asked if you want to play another hand

## Game Flow Architecture

### Conversation Steps

The game uses a structured step-based conversation flow:

1. **betting**: Starting step where players place their bets
   - Functions available: `place_bet`
   - Transitions to: `playing` (after cards dealt)

2. **playing**: Active gameplay where players make decisions
   - Functions available: `hit`, `stand`, `double_down`
   - Transitions to: `hand_complete` (when hand ends)

3. **hand_complete**: Review results with cards still visible
   - Functions available: `new_hand`
   - Transitions to: `betting` (when new hand requested)

4. **game_over**: Handle out-of-chips scenario
   - Player has lost all chips
   - Offer to restart with new bankroll

### State Management

- **Stateless Architecture**: Each function call receives complete game state
- **State Persistence**: SignalWire mirrors back `global_data` between calls
- **Centralized Logic**: All game decisions made by Python, AI only narrates
- **Automatic Resolution**: Hands resolve immediately when complete (bust, 21, or stand)

## Game Rules

- **Goal**: Get as close to 21 as possible without going over
- **Card Values**:
  - Number cards (2-10): Face value
  - Face cards (J, Q, K): 10 points
  - Aces: 1 or 11 points (automatically optimized)
- **Dealer Rules**:
  - Must hit on 16 or below
  - Must stand on 17 or above
- **Payouts**:
  - Regular win: 1:1 (double your bet)
  - Blackjack (21 with first 2 cards): 3:2
  - Push (tie): Bet returned

## Configuration

### Bot Configuration
- **Port**: Configure with `--port` flag (default: 5000)
- **Voice**: Uses ElevenLabs Adam voice
- **Starting Chips**: 1000
- **Minimum Bet**: 10 chips
- **Media Files**: Configured via `SWML_PROXY_URL_BASE` environment variable

### Web Configuration
- **SignalWire Token**: Update `STATIC_TOKEN` in app.js
- **Destination**: Update `DESTINATION` for SignalWire routing
- **Card Images**: Uses relative paths (../card_images from client directory)

## Architecture Updates (v2.0)

### Integrated Web Serving
The application now uses a single-process architecture where the SignalWire agent serves both the API and web client:

- **Single Port**: Everything runs on one port (default 5000)
- **Public Access**: Web client and static files are publicly accessible
- **Protected API**: Only `/blackjack` endpoints require authentication
- **Simplified Deployment**: No need for separate web server process

### Authentication Model
- **Public Routes** (no auth required):
  - `/` - Web client interface
  - `/app.js`, `/signalwire.js` - JavaScript files
  - `/card_images/*` - Card images
  - `/favicon.svg` - Favicon
  - `/og-image.png` - Social media preview
  - Media files (videos, audio)

- **Protected Routes** (Basic Auth required):
  - `/blackjack` - SWML endpoint
  - `/blackjack/swaig` - SWAIG functions
  - `/blackjack/post_prompt` - Post-prompt webhook

### Social Media Integration
- Open Graph meta tags for rich previews
- Custom preview image with game branding
- Optimized for Facebook, Twitter, LinkedIn, Discord

## Technical Implementation

### Core Design Patterns

This application demonstrates several important patterns for SignalWire agent development:

1. **Stateless Architecture Pattern**
   ```python
   # State retrieved from global_data on each call
   game_state, global_data = get_game_state(raw_data)
   
   # State persisted back after modifications
   global_data['game_state'] = game_state
   global_data['current_chips'] = game_state['player_chips']
   result.update_global_data(global_data)
   ```

2. **UI Event Communication Pattern**
   ```python
   # Send real-time updates to web client
   result.swml_user_event({
       "type": "cards_dealt",
       "player_hand": game_state["player_hand"],
       "dealer_hand": [game_state["dealer_hand"][0], None],
       "player_score": game_state["player_score"]
   })
   ```

3. **Conversation Flow Pattern**
   ```python
   # Define structured conversation steps
   default_context.add_step("betting")
       .add_bullets("Betting Process", [
           "The player has ${global_data.current_chips} chips",
           "Ask how much they'd like to bet"
       ])
       .set_functions(["place_bet"])
       .set_valid_steps(["playing"])
   ```

### Key Components

1. **SignalWire Agents SDK Features**:
   - `swml_user_event()`: Send UI update events to client
   - `swml_change_step()`: Navigate between conversation steps
   - `update_global_data()`: Persist state between function calls

2. **Game Functions**:
   - `place_bet`: Accepts bet, deals cards, checks for blackjack
   - `hit`: Draws card, checks for bust or 21
   - `stand`: Plays dealer hand, resolves game
   - `double_down`: Doubles bet, draws one card, resolves
   - `new_hand`: Resets table, transitions to betting

3. **UI Events**:
   - `clear_table`: Resets UI before new hand
   - `bet_placed`: Updates chip display
   - `cards_dealt`: Shows initial cards
   - `player_hit`: Adds card to player hand
   - `dealer_play`: Reveals dealer cards
   - `hand_resolved`: Shows winner and updates chips
   - `game_reset`: Clears table for new hand

### State Flow

```
Start → betting (place_bet) → playing (hit/stand/double_down) → hand_complete (new_hand) → betting
                                                                      ↓
                                                                 game_over (if out of chips)
```

Each step has:
- Clear instructions for the AI
- Available functions
- Valid next steps
- Completion criteria

## Testing

### SWAIG Function Testing
```bash
cd bot
swaig-test sigmond_blackjack.py --list-tools
swaig-test sigmond_blackjack.py --exec place_bet --amount 50
```

### Local Testing
1. Start the server: `python sigmond_blackjack.py`
2. Open browser to `http://localhost:5000`
3. Check API endpoint: `curl -u username:password http://localhost:5000/blackjack`

## Troubleshooting

1. **Port Already in Use**:
   - Default port is 5000, use `--port` flag to specify another
   - Check if another process is using the port: `lsof -i :5000`

2. **Connection Issues**:
   - Verify SignalWire token is correct in `app.js`
   - Check bot is running (`./bot.sh status`)
   - Ensure the destination matches your agent configuration

3. **404 Errors on Static Files**:
   - Ensure you're running from the `bot` directory
   - Check that web files exist in `../web/` relative to bot directory

4. **SWAIG Functions Not Working**:
   - Check browser console for 404 errors on `/blackjack/swaig`
   - Verify Basic Auth credentials are being sent
   - Check agent logs for authentication errors

5. **Game State Issues**:
   - Cards not displaying: Check browser console for WebSocket errors
   - State not persisting: Verify `update_global_data` is called
   - Wrong URLs generated: Check `_build_webhook_url` override is working

## Development Notes

- All game logic handled server-side for security
- Card deck reshuffled when less than 15 cards remain
- UI updates triggered by SWML user events
- Game state maintained by bot, client is display-only
- Step transitions control conversation flow
- Cards remain visible in `hand_complete` for result review

## Architecture Highlights

This project demonstrates key concepts for building SignalWire AI agents with web integration:

### 1. **Stateless Agent Design**
- All game state persisted via `update_global_data()`
- State passed between function calls in `global_data`
- No reliance on instance variables or session state

### 2. **Web-Agent Communication**
- Real-time UI updates via `swml_user_event()`
- WebRTC video/audio integration with SignalWire Fabric
- Event-driven architecture for responsive gameplay

### 3. **Conversation Flow Control**
- Step-based conversation management
- Context-aware function availability
- Automatic transitions based on game state

### 4. **Environment Configuration**
- Media files served from configurable web root
- Flexible deployment options
- Security via basic authentication

## Learning Resources

This codebase serves as a practical example of:
- Building stateless AI agents with SignalWire
- Integrating WebRTC video calling with game logic
- Managing complex conversation flows
- Synchronizing backend state with frontend UI
- Handling real-time user events and responses

For more information on SignalWire technologies:
- [SignalWire Agents SDK (GitHub)](https://github.com/signalwire/signalwire-agents) - Python SDK for building AI agents
- [SignalWire AI Documentation](https://developer.signalwire.com/ai/) - AI Agent guides and tutorials
- [SWML Documentation](https://developer.signalwire.com/swml/) - SignalWire Markup Language reference
- [Browser SDK Documentation](https://developer.signalwire.com/sdks/browser-sdk/) - JavaScript SDK for WebRTC