// Configuration
// Token and address will be fetched dynamically from /get_token
let currentToken = null;
let currentDestination = null;
const BASE_URL = '/card_images';  // Absolute path from web root

// SignalWire v4 (@signalwire/js) connection state.
let client;
let call;
let isMuted = false;
let subscriptions = [];      // every RxJS Subscription; unsubscribed in teardown
let remoteVideoEl = null;    // the <video> element we create for the remote media
let lastStreamSig = '';      // remote track-set signature, for re-attach detection
let teardownDone = false;    // dedup teardown across status/complete/error/hangup

let gameState = {
    playerHand: [],
    dealerHand: [],
    playerScore: 0,
    dealerScore: 0,
    chips: 1000,
    currentBet: 0,
    gamePhase: 'waiting'
};

// UI Elements
const connectBtn = document.getElementById('connectBtn');
const hangupBtn = document.getElementById('hangupBtn');
const muteBtn = document.getElementById('muteBtn');
const startMutedCheckbox = document.getElementById('startMuted');
const showLogCheckbox = document.getElementById('showLog');
const statusDiv = document.getElementById('status');
const eventLog = document.getElementById('event-log');
const eventLogHeader = document.getElementById('event-log-header');
const eventEntries = document.getElementById('event-entries');

// Game UI Elements
const chipCount = document.getElementById('chipCount');
const betAmount = document.getElementById('betAmount');
const playerCards = document.getElementById('playerCards');
const dealerCards = document.getElementById('dealerCards');
const playerScore = document.getElementById('playerScore');
const dealerScore = document.getElementById('dealerScore');
const gameActions = document.getElementById('gameActions');
const resultMessage = document.getElementById('resultMessage');

// Event logging
function logEvent(message, data = null, isUserEvent = false) {
    const entry = document.createElement('div');
    entry.className = isUserEvent ? 'event-entry user-event' : 'event-entry';
    const time = new Date().toLocaleTimeString();

    let dataStr = '';
    if (data) {
        try {
            const seen = new WeakSet();
            dataStr = JSON.stringify(data, (key, value) => {
                if (typeof value === 'object' && value !== null) {
                    if (seen.has(value)) {
                        return '[Circular Reference]';
                    }
                    seen.add(value);
                }
                return value;
            }, 2);
        } catch (e) {
            dataStr = 'Error serializing data: ' + e.message;
        }
    }

    entry.innerHTML = `
        <div class="event-time">${time}</div>
        <div>${isUserEvent ? '🎲 GAME EVENT: ' : ''}${message}</div>
        ${dataStr ? `<div style="color: #888; margin-left: 10px;">${dataStr}</div>` : ''}
    `;
    eventEntries.appendChild(entry);
    eventEntries.scrollTop = eventEntries.scrollHeight;
}

// Card display functions
function getCardImagePath(card) {
    if (!card) return `${BASE_URL}/card_back.png`;

    // The bot now sends the correct filename directly
    if (card.image) {
        return `${BASE_URL}/${card.image}`;
    }

    // Fallback to constructing filename if image not provided
    return `${BASE_URL}/${card.rank}_of_${card.suit}.png`;
}

function displayCard(container, card, faceDown = false) {
    const cardDiv = document.createElement('div');
    cardDiv.className = 'card';

    console.log('displayCard called with:', { card, faceDown, container: container.id });

    if (faceDown) {
        cardDiv.classList.add('face-down');
        const img = document.createElement('img');
        img.src = `${BASE_URL}/card_back.png`;
        console.log('Showing face-down card with image:', img.src);
        cardDiv.appendChild(img);
    } else {
        const img = document.createElement('img');
        const imagePath = getCardImagePath(card);
        img.src = imagePath;
        console.log('Showing face-up card with image:', imagePath, 'Card data:', card);
        img.onerror = function() {
            // Fallback if image not found
            console.error('Card image not found:', card, 'Path was:', imagePath);
            this.src = `${BASE_URL}/card_back.png`;
        };
        cardDiv.appendChild(img);
    }

    container.appendChild(cardDiv);
}

function clearCards(container) {
    container.innerHTML = '';
}

function updateGameDisplay() {
    chipCount.textContent = gameState.chips;
    betAmount.textContent = gameState.currentBet;

    if (gameState.playerScore > 0) {
        playerScore.textContent = gameState.playerScore;
        playerScore.style.display = 'inline-block';
    } else {
        playerScore.style.display = 'none';
    }

    if (gameState.dealerScore > 0 && gameState.gamePhase !== 'playing') {
        dealerScore.textContent = gameState.dealerScore;
        dealerScore.style.display = 'inline-block';
    } else if (gameState.dealerHand.length > 0) {
        // Show only visible card score during play
        const visibleScore = gameState.dealerHand[0] ?
            (gameState.dealerHand[0].rank === 'ace' ? 11 : gameState.dealerHand[0].value || 10) : 0;
        dealerScore.textContent = visibleScore + ' + ?';
        dealerScore.style.display = 'inline-block';
    } else {
        dealerScore.style.display = 'none';
    }
}

function showResult(message, duration = 3000, type = '') {
    const resultText = resultMessage.querySelector('.result-text');
    if (resultText) {
        resultText.textContent = message;
    } else {
        resultMessage.textContent = message;
    }

    // Remove any previous type classes
    resultMessage.classList.remove('win', 'lose', 'push', 'blackjack');

    // Add appropriate class based on message content or explicit type
    if (type) {
        resultMessage.classList.add(type);
    } else if (message.toLowerCase().includes('blackjack')) {
        resultMessage.classList.add('blackjack');
        createParticles();
    } else if (message.toLowerCase().includes('win') || message.toLowerCase().includes('dealer bust')) {
        resultMessage.classList.add('win');
        createParticles();
    } else if (message.toLowerCase().includes('lose') || message.toLowerCase().includes('bust')) {
        resultMessage.classList.add('lose');
    } else if (message.toLowerCase().includes('push') || message.toLowerCase().includes('tie')) {
        resultMessage.classList.add('push');
    }

    resultMessage.classList.add('show');

    setTimeout(() => {
        resultMessage.classList.remove('show');
    }, duration);
}

function createParticles() {
    const particlesContainer = document.getElementById('particles');
    if (!particlesContainer) return;

    // Clear existing particles
    particlesContainer.innerHTML = '';

    // Create particles
    const colors = ['#ffd700', '#ffea00', '#4CAF50', '#fff'];
    for (let i = 0; i < 20; i++) {
        const particle = document.createElement('div');
        particle.className = 'particle';
        particle.style.background = colors[Math.floor(Math.random() * colors.length)];
        particle.style.left = (Math.random() * 200 - 100) + 'px';
        particle.style.top = (Math.random() * 100 - 50) + 'px';
        particle.style.animationDelay = (Math.random() * 0.5) + 's';
        particle.style.transform = `rotate(${Math.random() * 360}deg)`;
        particlesContainer.appendChild(particle);
    }

    // Clean up particles after animation
    setTimeout(() => {
        particlesContainer.innerHTML = '';
    }, 1500);
}

function handleUserEvent(params) {
    console.log('Handling user event:', params);

    // The event data structure can vary - sometimes it's params.event, sometimes it's direct
    let eventData = params;

    // If params has an event property, use that
    if (params && params.event) {
        eventData = params.event;
    }

    if (!eventData || !eventData.type) {
        console.log('No valid event data found in:', params);
        return;
    }

    switch(eventData.type) {
        case 'clear_table':
            // Clear the table for a new hand
            clearCards(playerCards);
            clearCards(dealerCards);
            gameState.playerHand = [];
            gameState.dealerHand = [];
            gameState.playerScore = 0;
            gameState.dealerScore = 0;
            gameState.chips = eventData.chips;
            gameState.gamePhase = 'betting';
            updateGameDisplay();
            gameActions.style.display = 'none';
            logEvent('Table cleared for new hand', { chips: eventData.chips }, true);
            break;

        case 'bet_placed':
            gameState.currentBet = eventData.amount;
            gameState.chips = eventData.remaining_chips;
            updateGameDisplay();
            logEvent('Bet placed', { amount: eventData.amount }, true);
            break;

        case 'cards_dealt':
            clearCards(playerCards);
            clearCards(dealerCards);

            console.log('Cards dealt event received:', eventData);
            console.log('Player hand:', eventData.player_hand);
            console.log('Dealer hand:', eventData.dealer_hand);

            gameState.playerHand = eventData.player_hand;
            gameState.dealerHand = eventData.dealer_hand;
            gameState.playerScore = eventData.player_score;
            gameState.gamePhase = 'playing';

            // Display player cards
            eventData.player_hand.forEach((card, index) => {
                console.log(`Displaying player card ${index}:`, card);
                displayCard(playerCards, card);
            });

            // Display dealer cards (one face up, one face down)
            console.log('Displaying dealer first card:', eventData.dealer_hand[0]);
            displayCard(dealerCards, eventData.dealer_hand[0]);
            console.log('Displaying dealer hole card (face down)');
            displayCard(dealerCards, null, true); // Face-down card

            updateGameDisplay();

            // Show action buttons if not blackjack
            if (gameState.playerScore !== 21) {
                gameActions.style.display = 'flex';
            }

            logEvent('Cards dealt', {
                playerScore: eventData.player_score,
                dealerVisible: eventData.dealer_visible_score
            }, true);

            if (gameState.playerScore === 21) {
                showResult('BLACKJACK!');
            }
            break;

        case 'player_hit':
            // Clear and redraw all cards to ensure sync
            clearCards(playerCards);

            // Update the game state with the full hand from server
            if (eventData.player_hand) {
                gameState.playerHand = eventData.player_hand;
                // Redraw all cards from the authoritative server state
                eventData.player_hand.forEach((card, index) => {
                    console.log(`Redrawing player card ${index} after hit:`, card);
                    displayCard(playerCards, card);
                });
            } else {
                // Fallback to just adding the new card if full hand not provided
                displayCard(playerCards, eventData.new_card);
            }

            gameState.playerScore = eventData.player_score;
            updateGameDisplay();

            if (eventData.busted) {
                gameActions.style.display = 'none';
                showResult('BUST!');
            }

            logEvent('Player hit', {
                newCard: eventData.new_card.rank + ' of ' + eventData.new_card.suit,
                score: eventData.player_score,
                busted: eventData.busted
            }, true);
            break;

        case 'player_stand':
            gameActions.style.display = 'none';
            logEvent('Player stands', { score: eventData.player_score }, true);
            break;

        case 'double_down':
            displayCard(playerCards, eventData.new_card);
            gameState.playerScore = eventData.player_score;
            gameState.currentBet = eventData.new_bet;
            gameState.chips = eventData.remaining_chips;
            gameActions.style.display = 'none';
            updateGameDisplay();

            logEvent('Double down', {
                newBet: eventData.new_bet,
                score: eventData.player_score
            }, true);
            break;

        case 'dealer_play':
            // Clear and redraw dealer cards (reveal hole card)
            clearCards(dealerCards);
            eventData.dealer_hand.forEach(card => {
                displayCard(dealerCards, card);
            });

            gameState.dealerScore = eventData.dealer_score;
            gameState.gamePhase = 'dealer_playing';  // Change phase so score shows
            updateGameDisplay();

            if (eventData.dealer_busted) {
                showResult('DEALER BUSTS!');
            }

            logEvent('Dealer plays', {
                score: eventData.dealer_score,
                busted: eventData.dealer_busted
            }, true);
            break;

        case 'hand_resolved':
            gameState.chips = eventData.total_chips;
            updateGameDisplay();

            showResult(eventData.result, 5000);

            // Hide action buttons
            gameActions.style.display = 'none';

            logEvent('Hand resolved', {
                result: eventData.result,
                winnings: eventData.winnings,
                totalChips: eventData.total_chips
            }, true);
            break;

        case 'game_reset':
            clearCards(playerCards);
            clearCards(dealerCards);
            gameState = {
                playerHand: [],
                dealerHand: [],
                playerScore: 0,
                dealerScore: 0,
                chips: eventData.chips,
                currentBet: 0,
                gamePhase: 'betting'
            };
            updateGameDisplay();
            gameActions.style.display = 'none';

            logEvent('New hand ready', { chips: eventData.chips }, true);
            break;
    }
}

// Voice commands are handled by the AI agent directly
// No UI buttons needed for game actions

// ============================================================================
// SignalWire v4 (@signalwire/js) connection layer
// ----------------------------------------------------------------------------
// v4 is a rewrite of the connection layer, not a rename: the client constructor
// auto-connects, there is no rootElement / negotiateVideo / .on() events /
// roomSession.start(). Everything is RxJS observables and we render media
// ourselves.
// ============================================================================

// Hardened token fetch. Tolerates the legacy FastAPI tuple-bug array shape and
// validates the payload so a falsy token never silently reaches the SDK (which
// would surface as a misleading InvalidCredentialsError).
async function fetchGuestToken() {
    const resp = await fetch('/get_token');
    let data = await resp.json();
    if (Array.isArray(data)) data = data[0] || {};          // legacy [{...}, 500] shape
    if (!resp.ok || data.error) throw new Error(data.error || `HTTP ${resp.status}`);
    if (!data.token || !data.address) throw new Error('Token response missing token/address');
    return data;
}

// v4 renders no media for us. Create our own <video> and (re)attach the remote
// stream whenever its track set changes: the SDK re-emits the SAME MediaStream
// object as tracks arrive, and Chromium may never render a late video track
// unless srcObject is re-assigned. Signature = sorted "kind:id" per track.
function attachRemoteStream(stream) {
    if (!stream) return;
    const sig = stream.getTracks().map(t => t.kind + ':' + t.id).sort().join(',');
    if (sig === lastStreamSig && remoteVideoEl && remoteVideoEl.srcObject === stream) return;
    lastStreamSig = sig;

    const container = document.getElementById('video-container');
    if (!remoteVideoEl) {
        remoteVideoEl = document.createElement('video');
        remoteVideoEl.autoplay = true;
        remoteVideoEl.playsInline = true;
        // Leave UNMUTED: this element carries the remote audio, and connect is
        // user-gesture-initiated so autoplay-with-sound is allowed.
        remoteVideoEl.style.width = '100%';
        remoteVideoEl.style.height = '100%';
        remoteVideoEl.style.objectFit = 'cover';
        if (container) container.appendChild(remoteVideoEl);
    }
    remoteVideoEl.srcObject = stream;
    remoteVideoEl.play().catch(err => logEvent('Remote video play() failed', { error: err.message }));
    logEvent('Attached remote stream', { tracks: sig });
}

// Connect to the dealer with a dynamically-fetched guest token.
async function connectToCall() {
    teardownDone = false;
    try {
        // Disable button and show connecting state
        connectBtn.disabled = true;
        connectBtn.textContent = '⏳ Connecting...';
        connectBtn.style.background = 'linear-gradient(135deg, rgba(128, 128, 128, 0.7), rgba(96, 96, 96, 0.7))';
        connectBtn.style.borderColor = 'rgba(128, 128, 128, 0.5)';

        eventEntries.innerHTML = '';
        logEvent('Starting new connection...');
        statusDiv.textContent = 'Getting token...';

        // Fail-fast: fetch the first token BEFORE constructing the client. If
        // authenticate() is the first fetch and throws inside the constructor,
        // the SDK surfaces it only via errors$ and the isConnected$ gate hangs.
        const tokenData = await fetchGuestToken();
        currentToken = tokenData.token;
        currentDestination = tokenData.address;
        logEvent('Got token', { destination: currentDestination, tokenLength: currentToken.length });

        const SignalWireSDK = window.SignalWire || SignalWire;
        if (!SignalWireSDK || typeof SignalWireSDK.SignalWire !== 'function') {
            throw new Error('SignalWire v4 SDK not loaded (window.SignalWire.SignalWire missing)');
        }

        statusDiv.textContent = 'Initializing client...';

        // Credential provider: return the cached first token once, then re-fetch
        // a fresh guest token on subsequent calls (refresh / reconnect).
        let usedInitialToken = false;
        const credentialProvider = {
            authenticate: async () => {
                if (!usedInitialToken) {
                    usedInitialToken = true;
                    return { token: currentToken };
                }
                const fresh = await fetchGuestToken();
                currentToken = fresh.token;
                currentDestination = fresh.address;
                return { token: currentToken };
            }
        };

        // v4: SignalWire is a CLASS and the constructor AUTO-CONNECTS.
        client = new SignalWireSDK.SignalWire(credentialProvider);

        // v4 replaces logLevel:'debug' with error/warning observables.
        subscriptions.push(client.errors$.subscribe(e => logEvent('SDK error', { code: e?.code, message: e?.message })));
        subscriptions.push(client.warnings$.subscribe(w => logEvent('SDK warning', { code: w?.code, message: w?.message })));

        // Gate the dial on isConnected$ emitting true. It replays synchronously on
        // subscribe (settle via flag, defer unsubscribe) and NEVER errors on bad
        // creds, so add a timeout or the UI hangs forever.
        statusDiv.textContent = 'Connecting...';
        await new Promise((resolve, reject) => {
            let settled = false;
            const timer = setTimeout(() => {
                if (!settled) { settled = true; reject(new Error('Timed out waiting for SignalWire connection')); }
            }, 15000);
            const sub = client.isConnected$.subscribe(connected => {
                if (connected && !settled) {
                    settled = true;
                    clearTimeout(timer);
                    setTimeout(() => sub.unsubscribe(), 0);   // deferred: replays synchronously
                    resolve();
                }
            });
        });
        logEvent('Client connected');

        statusDiv.textContent = 'Dialing...';

        // v4 dial: destination is the first POSITIONAL arg. Receive-only avatar
        // video (video:false + receiveVideo:true) means NO camera-permission
        // prompt. Audio is captured for the player's mic.
        call = await client.dial(currentDestination, {
            audio: true,
            video: false,
            receiveAudio: true,
            receiveVideo: true,
            userVariables: {
                userName: 'Blackjack Player',
                interface: 'web-ui',
                timestamp: new Date().toISOString()
            }
        });
        logEvent('Dial initiated');

        // Remote media: subscribe and render it ourselves (v4 injects no <video>).
        subscriptions.push(call.remoteStream$.subscribe(stream => attachRemoteStream(stream)));

        // Game events: ONE subscription. Payload lives in evt.params;
        // handleUserEvent already unwraps the {event:{...}} vs flat shapes.
        subscriptions.push(call.subscribe('user_event').subscribe(evt => {
            const payload = (evt && evt.params !== undefined) ? evt.params : evt;
            logEvent('user_event', payload, true);
            handleUserEvent(payload);
        }));

        // Call lifecycle via status$ (replaces call.joined / room.left / destroy /
        // call.ended / disconnected / etc.). Also handle complete() — the SDK
        // completes subjects on destroy, sometimes without a terminal status.
        subscriptions.push(call.status$.subscribe({
            next: (status) => {
                logEvent('call.status', { status });
                if (status === 'connected') {
                    statusDiv.textContent = 'Connected to Dealer';
                    connectBtn.style.display = 'none';
                    hangupBtn.style.display = 'inline-block';
                    muteBtn.style.display = 'inline-block';
                    // Honor "start muted".
                    if (startMutedCheckbox && startMutedCheckbox.checked && !isMuted) {
                        toggleMute();
                    }
                } else if (status === 'disconnected' || status === 'failed' || status === 'destroyed') {
                    handleDisconnect();
                }
            },
            complete: () => handleDisconnect()
        }));

    } catch (error) {
        logEvent('Connection error', { error: error.message });
        // Show the actual blocker, not a generic string (saves a debugging round-trip).
        statusDiv.textContent = 'Connection failed: ' + error.message;
        console.error('Connection error:', error);
        handleDisconnect();
    }
}

function handleDisconnect() {
    if (teardownDone) return;   // dedup across status/complete/error/hangup
    teardownDone = true;

    // Unsubscribe every RxJS subscription.
    subscriptions.forEach(s => { try { s.unsubscribe(); } catch (e) { /* ignore */ } });
    subscriptions = [];

    statusDiv.textContent = 'Disconnected';
    // Reset connect button
    connectBtn.disabled = false;
    connectBtn.textContent = '📞 Connect';
    connectBtn.style.background = '';
    connectBtn.style.borderColor = '';
    connectBtn.style.display = 'inline-block';
    hangupBtn.style.display = 'none';
    muteBtn.style.display = 'none';
    muteBtn.textContent = 'Mute';
    isMuted = false;
    gameActions.style.display = 'none';

    // Clear the game board
    clearCards(playerCards);
    clearCards(dealerCards);

    // Reset game state
    gameState = {
        playerHand: [],
        dealerHand: [],
        playerScore: 0,
        dealerScore: 0,
        chips: 1000,
        currentBet: 0,
        gamePhase: 'waiting'
    };
    updateGameDisplay();

    // Hide scores
    playerScore.style.display = 'none';
    dealerScore.style.display = 'none';

    // Clear any result message
    const rm = document.getElementById('resultMessage');
    if (rm) {
        rm.classList.remove('show');
    }

    // Tear down the remote media element we created.
    if (remoteVideoEl) {
        if (remoteVideoEl.srcObject) {
            remoteVideoEl.srcObject.getTracks().forEach(track => {
                try { track.stop(); } catch (e) { /* ignore */ }
            });
            remoteVideoEl.srcObject = null;
        }
        try { remoteVideoEl.pause(); } catch (e) { /* ignore */ }
        if (remoteVideoEl.parentNode) remoteVideoEl.parentNode.removeChild(remoteVideoEl);
        remoteVideoEl = null;
    }
    lastStreamSig = '';

    // Clean up anything else left in the container (defensive), but keep the
    // placeholder: it is markup from index.html, not something the SDK added, and
    // it has to survive teardown or the frame goes blank after a call ends with no
    // way to click-to-start again.
    const videoContainer = document.getElementById('video-container');
    if (videoContainer) {
        Array.from(videoContainer.children).forEach((child) => {
            if (child.id !== 'video-placeholder') videoContainer.removeChild(child);
        });
    }

    call = null;

    if (client) {
        try { client.disconnect(); } catch (e) { /* ignore */ }
        client = null;
    }
}

async function hangup() {
    if (call) {
        try {
            await call.hangup();
        } catch (e) {
            logEvent('Hangup error', { error: e.message });
        }
    }
    handleDisconnect();
}

async function toggleMute() {
    try {
        if (call && call.self && typeof call.self.mute === 'function') {
            if (isMuted) {
                await call.self.unmute();
            } else {
                await call.self.mute();
            }
            isMuted = !isMuted;
            muteBtn.textContent = isMuted ? '🔊' : '🔇';
            logEvent(isMuted ? 'Microphone muted' : 'Microphone unmuted');
        } else {
            logEvent('No active call to mute');
        }
    } catch (error) {
        // Fall back to local device mute if the server mute RPC fails.
        logEvent('Server mute failed, falling back to local track mute', { error: error.message });
        try {
            const localStream = call && (call.localStream || (call.self && call.self.localStream));
            if (localStream) {
                const nowMuted = !isMuted;
                localStream.getAudioTracks().forEach(track => { track.enabled = !nowMuted; });
                isMuted = nowMuted;
                muteBtn.textContent = isMuted ? '🔊' : '🔇';
                logEvent(isMuted ? 'Microphone muted (local)' : 'Microphone unmuted (local)');
            }
        } catch (e2) {
            logEvent('Local mute fallback failed', { error: e2.message });
        }
    }
}

// Event listeners with null checks
if (connectBtn) connectBtn.addEventListener('click', connectToCall);
if (hangupBtn) hangupBtn.addEventListener('click', hangup);
if (muteBtn) muteBtn.addEventListener('click', toggleMute);

// The placeholder image doubles as a start control, alongside #connectBtn.
// Delegated from #video-container because the SDK replaces that container's
// children on connect, which would drop a listener bound to the placeholder.
// connectBtn.disabled is the single source of truth for "already connecting or
// connected", so both entry points cannot double-fire connectToCall().
const videoContainerEl = document.getElementById('video-container');
if (videoContainerEl) {
    videoContainerEl.addEventListener('click', (e) => {
        if (e.target.closest('#video-placeholder') && connectBtn && !connectBtn.disabled) {
            connectToCall();
        }
    });
    // The placeholder is role="button" tabindex="0", so it must also activate on
    // Enter and Space to behave like the button it announces itself as.
    videoContainerEl.addEventListener('keydown', (e) => {
        if ((e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar')
            && e.target.closest('#video-placeholder')
            && connectBtn && !connectBtn.disabled) {
            e.preventDefault();   // stop Space from scrolling the page
            connectToCall();
        }
    });
}

if (showLogCheckbox && eventLog) {
    showLogCheckbox.addEventListener('change', (e) => {
        if (e.target.checked) {
            eventLog.classList.add('active');
        } else {
            eventLog.classList.remove('active');
        }
    });
}

if (eventLogHeader) {
    eventLogHeader.addEventListener('click', () => {
        const entries = document.getElementById('event-entries');
        if (entries) {
            if (entries.style.display === 'none') {
                entries.style.display = 'block';
                const arrow = eventLogHeader.querySelector('span:last-child');
                if (arrow) arrow.textContent = '▼';
            } else {
                entries.style.display = 'none';
                const arrow = eventLogHeader.querySelector('span:last-child');
                if (arrow) arrow.textContent = '▶';
            }
        }
    });
}

// Initialize on page load
window.addEventListener('load', () => {
    logEvent('Page loaded, ready to connect');
    updateGameDisplay();

    // Handle page unload - clean up connections
    window.addEventListener('beforeunload', () => {
        if (call) {
            // Try to hangup gracefully but don't wait
            try { call.hangup(); } catch (e) { /* ignore errors during unload */ }
        }
        if (client) {
            try { client.disconnect(); } catch (e) { /* ignore errors during unload */ }
        }
    });

    // Handle page visibility changes (mobile browsers)
    document.addEventListener('visibilitychange', () => {
        if (document.hidden && call) {
            logEvent('Page hidden - connection may be interrupted');
        } else if (!document.hidden && call) {
            logEvent('Page visible again - connection status unknown');
        }
    });
});
