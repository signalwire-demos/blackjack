#!/usr/bin/env python3
"""
Dealer - The SignalWire Blackjack Dealer (Refactored)
An AI-powered blackjack dealer that plays casino-style blackjack via voice/video
Uses stateless architecture with centralized state management
"""

import json
import random
import argparse
import os
import time
import requests
from pathlib import Path
from signalwire_agents import AgentBase, AgentServer
from signalwire_agents.core.function_result import SwaigFunctionResult
from dotenv import load_dotenv
from fastapi.responses import JSONResponse

# Load environment variables
load_dotenv()

# Store the SWML handler info for reuse
swml_handler_info = {"id": None, "address_id": None, "address": None}

class BlackjackDealer(AgentBase):
    """Dealer - Your professional blackjack dealer"""
    
    def __init__(self):
        super().__init__(
            name="Dealer",
            route="/blackjack",
            record_call=True
        )
        
        # Set up dealer personality
        self.prompt_add_section(
            "Personality", 
            "You are a professional blackjack dealer at a high-end casino. You're friendly but professional, "
            "explaining the rules clearly and maintaining the excitement of the game. You follow standard "
            "casino blackjack rules: dealer hits on 16 and below, stands on 17 and above."
        )
        
        # Define conversation contexts
        contexts = self.define_contexts()
        
        default_context = contexts.add_context("default") \
            .add_section("Goal", "Run an engaging blackjack game, manage bets, deal cards, and ensure fair play according to casino rules.")
        
        # Betting phase - this is the starting point
        default_context.add_step("betting") \
            .add_section("Current Task", "Take the player's bet") \
            .add_bullets("Betting Process", [
                "The player has ${global_data.current_chips} chips",
                "Ask how much they'd like to bet (minimum 10, maximum ${global_data.current_chips})",
                "When they tell you an amount, call place_bet function with that amount",
            ]) \
            .set_step_criteria("A valid bet has been placed and cards have been dealt") \
            .set_functions(["place_bet"]) \
            .set_valid_steps(["playing"])
        
        # Playing phase
        default_context.add_step("playing") \
            .add_section("Current Task", "Manage the active blackjack hand") \
            .add_bullets("CRITICAL RULES - YOU MUST FOLLOW THESE", [
                "The player currently has ${global_data.game_state.player_score} points",
                "When player says 'hit' or wants another card: YOU MUST CALL THE hit FUNCTION",
                "When player says 'stand' or wants to stay: YOU MUST CALL THE stand FUNCTION", 
                "When player says 'double down': YOU MUST CALL THE double_down FUNCTION",
                "Split is NOT available at this table - do not offer it as an option",
                "NEVER make up cards or scores - ONLY use what the functions return",
                "NEVER deal cards yourself - the hit function deals cards",
                "NEVER calculate scores yourself - the functions calculate scores",
                "The hit function will tell you EXACTLY what card was drawn and the new score",
                "If the function says 'the hand continues', keep playing - player has NOT busted",
                "Only say the player busted if the function explicitly says 'bust'"
            ]) \
            .set_step_criteria("Hand is complete and the winner is determined.") \
            .set_functions(["hit", "stand", "double_down"]) \
            .set_valid_steps(["hand_complete", "game_over"])


        # Post-Game phase
        default_context.add_step("hand_complete") \
            .add_section("Current Task", "The hand is complete. Review the results and wait for player's decision.") \
            .add_bullets("Important Instructions", [
                "The cards are still on the table - explain what happened in this hand",
                "Tell the user their chip count and how much they won or lost",
                "Ask if they want to play another hand",
                "DO NOT take any bets or start a new game until you call new_hand",
                "If the user wants to play again, you MUST call new_hand first",
                "The new_hand function will reset the table and change to betting step",
                "Only after calling new_hand can you take a new bet"
            ]) \
            .set_step_criteria("User has indicated whether they want to play another hand") \
            .set_functions(["new_hand"]) \
            .set_valid_steps(["betting"])
        
        # Game Over phase - when player runs out of chips
        default_context.add_step("game_over") \
            .add_section("Current Task", "The game is over. The player has run out of chips.") \
            .add_bullets("Important Instructions", [
                "The cards are still on the table - explain what happened in this final hand",
                "Tell the user they have no chips left and the game is over",
                "Thank them for playing",
                "Ask if they want to hang up or stay connected",
                "You cannot start a new game - they are out of chips",
                "Be sympathetic but professional about their loss"
            ]) \
            .set_step_criteria("User has acknowledged the game is over") \
            .set_functions([]) \
            .set_valid_steps([])
        
        # No resolution phase needed - handled automatically in hit/stand/double_down
        
        # Helper function to get/initialize game state
        def get_game_state(raw_data):
            """Get the current game state from global_data, or initialize if needed"""
            global_data = raw_data.get('global_data', {})
            
            # Default state structure
            default = {
                "deck": [],
                "player_hand": [],
                "dealer_hand": [],
                "player_score": 0,
                "dealer_score": 0,
                "current_bet": 0,
                "player_chips": 1000,
                "game_phase": "waiting",  # waiting, bet_placed, playing, resolution
                "hand_in_progress": False
            }
            
            return global_data.get('game_state', default), global_data
        
        # Helper function to add save action to result
        def add_save_action(result, game_state, global_data):
            """Add the save game state action to the result"""
            global_data['game_state'] = game_state
            # Also update top-level chip count for AI visibility
            global_data['current_chips'] = game_state['player_chips']
            result.update_global_data(global_data)
            return result
        
        # Helper function to resolve the hand and determine payouts
        def resolve_hand_internally(game_state):
            """Resolve the hand and update chips - returns result text"""
            player_score = game_state["player_score"]
            dealer_score = game_state["dealer_score"]
            bet = game_state["current_bet"]
            
            # Determine winner
            if player_score > 21:
                result_text = "You bust. House wins."
                winnings = 0
            elif dealer_score > 21:
                result_text = "I bust! You win!"
                winnings = bet * 2
            elif player_score > dealer_score:
                result_text = "You win!"
                winnings = bet * 2
            elif dealer_score > player_score:
                result_text = "House wins."
                winnings = 0
            else:
                result_text = "Push. We tied."
                winnings = bet  # Return the bet
            
            # Check for blackjack bonus
            if player_score == 21 and len(game_state["player_hand"]) == 2 and dealer_score != 21:
                result_text = "Blackjack pays three to two!"
                winnings = int(bet * 2.5)
            
            game_state["player_chips"] += winnings
            game_state["hand_in_progress"] = False
            game_state["game_phase"] = "waiting"
            
            # Don't clear hands here - keep them for display in hand_complete step
            response = f"\n\nHand complete! {result_text}\n"
            response += f"Player had {player_score}, Dealer had {dealer_score}.\n"
            if winnings > bet:
                response += f"Player wins {winnings - bet} chips! "
            elif winnings == bet:
                response += f"Player's bet of {bet} chips is returned. "
            else:
                response += f"Player loses their {bet} chip bet. "
            response += f"Player now has {game_state['player_chips']} chips total."
            
            if game_state["player_chips"] < 10:
                response += "\n\nYou're out of chips! Game over. Thanks for playing!"
            
            return response, result_text, winnings
        
        # Define game functions
        @self.tool(
            name="place_bet",
            wait_file="/bet.mp3",
            description="Place a bet to start a new hand",
            parameters={
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "integer",
                        "description": "The amount of chips to bet",
                        "minimum": 10
                    }
                },
                "required": ["amount"]
            }
        )
        def place_bet(args, raw_data):
            """Place a bet and prepare for a new hand"""
            game_state, global_data = get_game_state(raw_data)
            amount = args["amount"]
            
            # Check if a hand is already in progress
            if game_state.get("hand_in_progress", False):
                return SwaigFunctionResult("There's already a hand in progress. Please finish it first.")
            
            # Check if player is out of chips
            if game_state["player_chips"] < 10:
                return SwaigFunctionResult(f"You only have {game_state['player_chips']} chips left, which is below the minimum bet of 10. Game over! Thanks for playing!")
            
            if amount > game_state["player_chips"]:
                return SwaigFunctionResult(f"You don't have that many chips. You have {game_state['player_chips']} chips.")
            
            if amount < 10:
                return SwaigFunctionResult("Minimum bet is ten chips at this table.")
            
            # Update state for new bet
            game_state["current_bet"] = amount
            game_state["player_chips"] -= amount
            game_state["game_phase"] = "bet_placed"  # Ready to deal cards
            game_state["hand_in_progress"] = True
            
            # Clear hands for new game
            game_state["player_hand"] = []
            game_state["dealer_hand"] = []
            game_state["player_score"] = 0
            game_state["dealer_score"] = 0
            
            # Save state first
            global_data['game_state'] = game_state
            
            # Now automatically deal the cards
            # Check if we have enough cards (need at least 15 for safety)
            if len(game_state["deck"]) < 15:
                game_state["deck"] = self._create_deck()
                random.shuffle(game_state["deck"])
                shuffled_new_deck = True
            else:
                shuffled_new_deck = False
            
            # Deal cards
            game_state["player_hand"] = [
                game_state["deck"].pop(),
                game_state["deck"].pop()
            ]
            game_state["dealer_hand"] = [
                game_state["deck"].pop(),
                game_state["deck"].pop()
            ]
            
            # Calculate scores
            game_state["player_score"] = self._calculate_score(game_state["player_hand"])
            game_state["dealer_score"] = self._calculate_score(game_state["dealer_hand"])
            game_state["game_phase"] = "playing"
            
            # Build response
            response = f"Perfect! You've bet {amount} chips. You have {game_state['player_chips']} chips remaining.\n\n"
            if shuffled_new_deck:
                response += "Shuffling a fresh deck.\n\n"
            
            player_cards_str = ", ".join([self._card_name(card) for card in game_state["player_hand"]])
            dealer_visible = self._card_name(game_state["dealer_hand"][0])
            
            response += f"Cards dealt! You have: {player_cards_str} for a total of {game_state['player_score']} points.\n"
            response += f"I'm showing {dealer_visible} with my other card face down."
            
            # Check for blackjack
            if game_state["player_score"] == 21:
                response += "\n\nBlackjack! Twenty-one!"
                # Play dealer's hand and resolve immediately
                response += self._play_dealer_hand(game_state)
                resolution_text, result_text, winnings = resolve_hand_internally(game_state)
                response += resolution_text
            else:
                response += "\n\nThe hand is now in play. What would you like to do?"
            
            result = SwaigFunctionResult(response)
            
            # Save complete state
            add_save_action(result, game_state, global_data)
            
            # Send UI updates
            # Send a clear event to ensure UI is clean before dealing
            result.swml_user_event({
                "type": "clear_table",
                "chips": game_state["player_chips"] + amount
            })
            
            result.swml_user_event({
                "type": "bet_placed",
                "amount": amount,
                "remaining_chips": game_state["player_chips"]
            })
            
            result.swml_user_event({
                "type": "cards_dealt",
                "player_hand": game_state["player_hand"],
                "dealer_hand": [game_state["dealer_hand"][0], None],  # Hide hole card
                "player_score": game_state["player_score"],
                "dealer_visible_score": self._calculate_score([game_state["dealer_hand"][0]])
            })
            
            # If blackjack, send resolution events and change to appropriate step
            if game_state["player_score"] == 21:
                result.swml_user_event({
                    "type": "dealer_play",
                    "dealer_hand": game_state["dealer_hand"],
                    "dealer_score": game_state["dealer_score"],
                    "dealer_busted": game_state["dealer_score"] > 21
                })
                
                result.swml_user_event({
                    "type": "hand_resolved",
                    "result": result_text,
                    "player_score": game_state["player_score"],
                    "dealer_score": game_state["dealer_score"],
                    "winnings": winnings,
                    "total_chips": game_state["player_chips"]
                })
                
                # Change to game_over if out of chips, otherwise hand_complete
                if game_state["player_chips"] < 10:
                    result.swml_change_step("game_over")
                else:
                    result.swml_change_step("hand_complete")
            
            return result
        
        @self.tool(
            name="hit",
            wait_file="/hit.mp3",
            description="Player takes another card",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
        def hit(args, raw_data):
            """Deal another card to the player"""
            game_state, global_data = get_game_state(raw_data)
            
            # Verify we can hit
            if game_state["game_phase"] != "playing":
                return SwaigFunctionResult("You can't hit right now. The hand is not in play.")
            
            if not game_state.get("hand_in_progress", False):
                return SwaigFunctionResult("No hand in progress. Please place a bet first.")
            
            # Draw a card
            new_card = game_state["deck"].pop()
            game_state["player_hand"].append(new_card)
            game_state["player_score"] = self._calculate_score(game_state["player_hand"])
            
            # Build response
            player_cards_str = ", ".join([self._card_name(card) for card in game_state["player_hand"]])
            response = f"The player hits and receives: {self._card_name(new_card)}.\n"
            response += f"Player's complete hand: {player_cards_str}.\n"
            response += f"Player's total: {game_state['player_score']} points."
            
            if game_state["player_score"] > 21:
                response += " That's a bust! You're over twenty-one."
                # Resolve the hand immediately
                resolution_text, result_text, winnings = resolve_hand_internally(game_state)
                response += resolution_text
            elif game_state["player_score"] == 21:
                response += " Twenty-one! Perfect!"
                # Auto-play dealer's hand
                response += self._play_dealer_hand(game_state)
                # Resolve the hand
                resolution_text, result_text, winnings = resolve_hand_internally(game_state)
                response += resolution_text
            else:
                # Clearly state the situation and current score
                response += f"\n\nYou have {game_state['player_score']} points. The hand continues. What would you like to do?"
                result_text = None
                winnings = None
            
            result = SwaigFunctionResult(response)
            
            # Save state
            add_save_action(result, game_state, global_data)
            
            # Send UI update
            result.swml_user_event({
                "type": "player_hit",
                "new_card": new_card,
                "player_hand": game_state["player_hand"],
                "player_score": game_state["player_score"],
                "busted": game_state["player_score"] > 21
            })
            
            # If hand is resolved, send updates
            if game_state["player_score"] >= 21:
                if game_state["player_score"] == 21:
                    result.swml_user_event({
                        "type": "dealer_play",
                        "dealer_hand": game_state["dealer_hand"],
                        "dealer_score": game_state["dealer_score"],
                        "dealer_busted": game_state["dealer_score"] > 21
                    })
                if result_text and winnings is not None:
                    result.swml_user_event({
                        "type": "hand_resolved",
                        "result": result_text,
                        "player_score": game_state["player_score"],
                        "dealer_score": game_state["dealer_score"],
                        "winnings": winnings,
                        "total_chips": game_state["player_chips"]
                    })
                    # Change to game_over if out of chips, otherwise hand_complete
                    if game_state["player_chips"] < 10:
                        result.swml_change_step("game_over")
                    else:
                        result.swml_change_step("hand_complete")
            
            return result
        
        @self.tool(
            name="stand",
            wait_file="/deal.mp3",
            description="Player stands with current hand",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
        def stand(args, raw_data):
            """Player stands, dealer's turn begins"""
            game_state, global_data = get_game_state(raw_data)
            
            # Verify we can stand
            if game_state["game_phase"] != "playing":
                return SwaigFunctionResult("You can't stand right now. The hand is not in play.")
            
            if not game_state.get("hand_in_progress", False):
                return SwaigFunctionResult("No hand in progress. Please place a bet first.")
            
            response = f"The player stands with {game_state['player_score']} points. Now it's the dealer's turn.\n"
            
            # Play dealer's hand
            response += self._play_dealer_hand(game_state)
            
            # Resolve the hand immediately
            resolution_text, result_text, winnings = resolve_hand_internally(game_state)
            response += resolution_text
            
            result = SwaigFunctionResult(response)
            
            # Save state
            add_save_action(result, game_state, global_data)
            
            # Send UI updates
            result.swml_user_event({
                "type": "player_stand",
                "player_score": game_state["player_score"]
            })
            
            result.swml_user_event({
                "type": "dealer_play",
                "dealer_hand": game_state["dealer_hand"],
                "dealer_score": game_state["dealer_score"],
                "dealer_busted": game_state["dealer_score"] > 21
            })
            
            result.swml_user_event({
                "type": "hand_resolved",
                "result": result_text,
                "player_score": game_state["player_score"],
                "dealer_score": game_state["dealer_score"],
                "winnings": winnings,
                "total_chips": game_state["player_chips"]
            })
            
            # Change to game_over if out of chips, otherwise hand_complete
            if game_state["player_chips"] < 10:
                result.swml_change_step("game_over")
            else:
                result.swml_change_step("hand_complete")
            
            return result
        
        @self.tool(
            name="double_down",
            wait_file="/hit.mp3",
            description="Double the bet and take exactly one more card",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
        def double_down(args, raw_data):
            """Double down - double bet, take one card, then stand"""
            game_state, global_data = get_game_state(raw_data)
            
            # Verify we can double down
            if game_state["game_phase"] != "playing":
                return SwaigFunctionResult("You can't double down right now.")
            
            if len(game_state["player_hand"]) != 2:
                return SwaigFunctionResult("You can only double down on your first two cards.")
            
            if game_state["current_bet"] > game_state["player_chips"]:
                return SwaigFunctionResult(f"You need {game_state['current_bet']} more chips to double down.")
            
            # Double the bet
            game_state["player_chips"] -= game_state["current_bet"]
            game_state["current_bet"] *= 2
            
            # Take one card
            new_card = game_state["deck"].pop()
            game_state["player_hand"].append(new_card)
            game_state["player_score"] = self._calculate_score(game_state["player_hand"])
            
            response = f"The player doubles down! The bet is now doubled to {game_state['current_bet']} chips.\n"
            response += f"Player receives one final card: {self._card_name(new_card)}.\n"
            response += f"Player's final total: {game_state['player_score']} points. Player has {game_state['player_chips']} chips remaining."
            
            if game_state["player_score"] > 21:
                response += " That's a bust!"
                # Resolve immediately
                resolution_text, result_text, winnings = resolve_hand_internally(game_state)
                response += resolution_text
            else:
                # Dealer plays
                response += "\n\n" + self._play_dealer_hand(game_state)
                # Resolve the hand
                resolution_text, result_text, winnings = resolve_hand_internally(game_state)
                response += resolution_text
            
            result = SwaigFunctionResult(response)
            
            # Save state
            add_save_action(result, game_state, global_data)
            
            # Send UI updates
            result.swml_user_event({
                "type": "double_down",
                "new_bet": game_state["current_bet"],
                "new_card": new_card,
                "player_hand": game_state["player_hand"],
                "player_score": game_state["player_score"],
                "remaining_chips": game_state["player_chips"]
            })
            
            if game_state["player_score"] <= 21:
                result.swml_user_event({
                    "type": "dealer_play",
                    "dealer_hand": game_state["dealer_hand"],
                    "dealer_score": game_state["dealer_score"],
                    "dealer_busted": game_state["dealer_score"] > 21
                })
            
            result.swml_user_event({
                "type": "hand_resolved",
                "result": result_text,
                "player_score": game_state["player_score"],
                "dealer_score": game_state["dealer_score"],
                "winnings": winnings,
                "total_chips": game_state["player_chips"]
            })
            
            # Change to game_over if out of chips, otherwise hand_complete
            if game_state["player_chips"] < 10:
                result.swml_change_step("game_over")
            else:
                result.swml_change_step("hand_complete")
            
            return result
        
        @self.tool(
            name="new_hand",
            wait_file="/shuffling.mp3",
            description="Start a new hand after the current one is complete",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            }
        )
        def new_hand(args, raw_data):
            """Start a new hand and transition back to betting step"""
            game_state, global_data = get_game_state(raw_data)
            
            # Reset the game state for a new hand
            game_state["player_hand"] = []
            game_state["dealer_hand"] = []
            game_state["player_score"] = 0
            game_state["dealer_score"] = 0
            game_state["current_bet"] = 0
            game_state["hand_in_progress"] = False
            game_state["game_phase"] = "waiting"
            
            # Create response that changes step and resets UI
            result = SwaigFunctionResult(f"Starting a new hand. You have {game_state['player_chips']} chips.")
            
            # Save the reset state
            add_save_action(result, game_state, global_data)
            
            # Change to betting step
            result.swml_change_step("betting")
            
            # Send UI reset event to clear the table
            result.swml_user_event({
                "type": "game_reset",
                "chips": game_state["player_chips"]
            })
            
            return result
        
        # No need for resolve_hand or reset_game - all handled automatically
        # Configure voice
        self.add_language(
            name="English",
            code="en-US",
            voice="elevenlabs.adam"
        )
        
        # Add game-related hints for speech recognition
        self.add_hints([
            "blackjack",
            "twenty one",
            "hit",
            "stand",
            "double down",
            "bet",
            "all in",
            "dealer",
            "cards"
        ])

        # Set non-URL conversation parameters
        self.set_params({
            "vad_config": "75",
            "end_of_speech_timeout": 300
        })

        # Initialize global data
        self.set_global_data({
            "assistant_name": "Dealer",
            "game": "Blackjack",
            "rules": "Dealer hits on 16, stands on 17",
            "starting_chips": 1000,
            "current_chips": 1000  # Start with initial chip count visible
        })
    
    def _play_dealer_hand(self, game_state):
        """Play out the dealer's hand according to casino rules"""
        dealer_cards_str = ", ".join([self._card_name(card) for card in game_state["dealer_hand"]])
        response = f"\nDealer reveals hole card. Dealer's complete hand: {dealer_cards_str} for {game_state['dealer_score']} points.\n"
        
        # Dealer draws cards according to rules
        while game_state["dealer_score"] < 17:
            new_card = game_state["deck"].pop()
            game_state["dealer_hand"].append(new_card)
            game_state["dealer_score"] = self._calculate_score(game_state["dealer_hand"])
            response += f"Dealer draws {self._card_name(new_card)}. Dealer now has {game_state['dealer_score']} points.\n"
        
        if game_state["dealer_score"] > 21:
            response += "Dealer busts! Over 21!"
        else:
            response += f"Dealer stands with {game_state['dealer_score']} points."
        
        return response
    
    def _create_deck(self):
        """Create a standard 52-card deck"""
        suits = ['hearts', 'diamonds', 'clubs', 'spades']
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'jack', 'queen', 'king', 'ace']
        deck = []
        for suit in suits:
            for rank in ranks:
                value = 10 if rank in ['jack', 'queen', 'king'] else 11 if rank == 'ace' else int(rank)
                deck.append({
                    'rank': rank,
                    'suit': suit,
                    'value': value,
                    'image': f"{rank}_of_{suit}.png"
                })
        return deck
    
    def _calculate_score(self, hand):
        """Calculate the score of a hand, handling aces appropriately"""
        score = sum(card['value'] for card in hand)
        aces = sum(1 for card in hand if card['rank'] == 'ace')
        
        # Adjust for aces
        while score > 21 and aces > 0:
            score -= 10
            aces -= 1
        
        return score
    
    def _card_name(self, card):
        """Get the display name of a card"""
        return f"{card['rank'].capitalize()} of {card['suit'].capitalize()}"

    def on_swml_request(self, request_data: dict, callback_path: str, request=None) -> dict:
        """Handle incoming SWML requests and configure the AI agent dynamically"""
        from typing import Dict

        # Detect host from request for video URLs
        host = "localhost:5000"
        protocol = "http"

        if request:
            # Try to get the host from headers
            headers = {k.lower(): v for k, v in request.headers.items()}
            host = headers.get('host', host)

            # Check if we're behind a proxy with x-forwarded-proto
            protocol = headers.get('x-forwarded-proto', 'https')

            # Override protocol for local development
            if 'localhost' in host or '127.0.0.1' in host:
                protocol = 'http'

        # Set video URLs dynamically based on request host
        base_url = f"{protocol}://{host}"
        self.set_param("video_idle_file", f"{base_url}/sigmond_bj_idle.mp4")
        self.set_param("video_talking_file", f"{base_url}/sigmond_bj_talking.mp4")
        self.set_param("background_file", f"{base_url}/casino.mp3")
        print(f"Set video URLs to use host: {base_url}")

        # Optional post-prompt URL from environment
        post_prompt_url = os.environ.get("BLACKJACK_POST_PROMPT_URL")
        if post_prompt_url:
            self.set_post_prompt("Summarize the blackjack session including hands played, bets made, and final chip count.")
            self.set_post_prompt_url(post_prompt_url)

        # Call parent implementation to handle the SWML request
        return super().on_swml_request(request_data, callback_path, request)


HOST = "0.0.0.0"
PORT = int(os.environ.get('PORT', 5000))


def get_signalwire_host():
    """Get the full SignalWire host from space name."""
    space = os.getenv("SIGNALWIRE_SPACE_NAME", "")
    if not space:
        return None
    # If it's already a full domain, use it as-is
    if "." in space:
        return space
    # Otherwise append .signalwire.com
    return f"{space}.signalwire.com"


def find_existing_handler(sw_host, auth, agent_name):
    """Find an existing SWML handler by name."""
    try:
        # List all external SWML handlers
        resp = requests.get(
            f"https://{sw_host}/api/fabric/resources/external_swml_handlers",
            auth=auth,
            headers={"Accept": "application/json"}
        )
        if resp.status_code != 200:
            print(f"Failed to list handlers: {resp.status_code}")
            return None

        handlers = resp.json().get("data", [])

        for handler in handlers:
            # The name is nested in swml_webhook object
            swml_webhook = handler.get("swml_webhook", {})
            handler_name = swml_webhook.get("name") or handler.get("display_name")

            # Check if this handler matches our agent name
            if handler_name == agent_name:
                handler_id = handler.get("id")
                handler_url = swml_webhook.get("primary_request_url", "")
                # Get the address for this handler
                addr_resp = requests.get(
                    f"https://{sw_host}/api/fabric/resources/external_swml_handlers/{handler_id}/addresses",
                    auth=auth,
                    headers={"Accept": "application/json"}
                )
                if addr_resp.status_code == 200:
                    addresses = addr_resp.json().get("data", [])
                    if addresses:
                        return {
                            "id": handler_id,
                            "name": handler_name,
                            "url": handler_url,
                            "address_id": addresses[0]["id"],
                            "address": addresses[0]["channels"]["audio"]
                        }
    except Exception as e:
        print(f"Error checking existing handlers: {e}")
    return None


def setup_swml_handler():
    """Set up SWML handler on startup."""
    sw_host = get_signalwire_host()
    project = os.getenv("SIGNALWIRE_PROJECT_ID", "")
    token = os.getenv("SIGNALWIRE_TOKEN", "")
    agent_name = os.getenv("AGENT_NAME", "blackjack")
    proxy_url = os.getenv("SWML_PROXY_URL_BASE", os.getenv("APP_URL", ""))
    auth_user = os.getenv("SWML_BASIC_AUTH_USER", "signalwire")
    auth_pass = os.getenv("SWML_BASIC_AUTH_PASSWORD", "")

    if not all([sw_host, project, token]):
        print("SignalWire credentials not configured - skipping SWML handler setup")
        return

    if not proxy_url:
        print("SWML_PROXY_URL_BASE/APP_URL not set - skipping SWML handler setup")
        return

    # Build SWML URL with basic auth credentials
    if auth_user and auth_pass and "://" in proxy_url:
        scheme, rest = proxy_url.split("://", 1)
        swml_url = f"{scheme}://{auth_user}:{auth_pass}@{rest}/blackjack"
    else:
        swml_url = proxy_url + "/blackjack"

    auth = (project, token)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    # Look for an existing handler by name
    existing = find_existing_handler(sw_host, auth, agent_name)
    if existing:
        swml_handler_info["id"] = existing["id"]
        swml_handler_info["address_id"] = existing["address_id"]
        swml_handler_info["address"] = existing["address"]

        # Always update the URL to ensure credentials are current
        try:
            update_resp = requests.put(
                f"https://{sw_host}/api/fabric/resources/external_swml_handlers/{existing['id']}",
                json={
                    "primary_request_url": swml_url,
                    "primary_request_method": "POST"
                },
                auth=auth,
                headers=headers
            )
            update_resp.raise_for_status()
            print(f"Updated SWML handler: {existing['name']}")
        except Exception as e:
            print(f"Failed to update handler URL: {e}")

        print(f"Call address: {existing['address']}")
    else:
        # Create a new external SWML handler with the agent name
        try:
            handler_resp = requests.post(
                f"https://{sw_host}/api/fabric/resources/external_swml_handlers",
                json={
                    "name": agent_name,
                    "used_for": "calling",
                    "primary_request_url": swml_url,
                    "primary_request_method": "POST"
                },
                auth=auth,
                headers=headers
            )
            handler_resp.raise_for_status()
            handler_id = handler_resp.json().get("id")
            swml_handler_info["id"] = handler_id

            # Get the address for this handler
            addr_resp = requests.get(
                f"https://{sw_host}/api/fabric/resources/external_swml_handlers/{handler_id}/addresses",
                auth=auth,
                headers={"Accept": "application/json"}
            )
            addr_resp.raise_for_status()
            addresses = addr_resp.json().get("data", [])
            if addresses:
                swml_handler_info["address_id"] = addresses[0]["id"]
                swml_handler_info["address"] = addresses[0]["channels"]["audio"]
                print(f"Created SWML handler: {agent_name}")
                print(f"Call address: {swml_handler_info['address']}")
            else:
                print("No address found for handler")
        except Exception as e:
            print(f"Failed to create SWML handler: {e}")
            # Retry finding existing handler (another worker may have just created it)
            time.sleep(0.5)
            existing = find_existing_handler(sw_host, auth, agent_name)
            if existing:
                swml_handler_info["id"] = existing["id"]
                swml_handler_info["address_id"] = existing["address_id"]
                swml_handler_info["address"] = existing["address"]
                print(f"Found existing SWML handler after retry: {existing['name']}")
                print(f"Call address: {existing['address']}")


def create_server(port=None):
    """Create AgentServer with static file mounting and API endpoints."""
    server = AgentServer(host=HOST, port=port or PORT)
    server.register(BlackjackDealer(), "/blackjack")

    # Serve static files using SDK's built-in method
    web_dir = Path(__file__).parent / "web"
    if web_dir.exists():
        server.serve_static_files(str(web_dir))

    # Add /get_token endpoint for WebRTC calls
    @server.app.get('/get_token')
    def get_token():
        """Get a guest token for the web client to call the agent."""
        sw_host = get_signalwire_host()
        project = os.getenv("SIGNALWIRE_PROJECT_ID", "")
        token = os.getenv("SIGNALWIRE_TOKEN", "")

        if not all([sw_host, project, token]):
            return JSONResponse({"error": "SignalWire credentials not configured"}, status_code=500)

        if not swml_handler_info["address_id"]:
            return JSONResponse({"error": "SWML handler not configured - check startup logs"}, status_code=500)

        auth = (project, token)
        headers = {"Content-Type": "application/json", "Accept": "application/json"}

        try:
            # Create a guest token with access to this address
            expire_at = int(time.time()) + 3600 * 24  # 24 hours

            guest_resp = requests.post(
                f"https://{sw_host}/api/fabric/guests/tokens",
                json={
                    "allowed_addresses": [swml_handler_info["address_id"]],
                    "expire_at": expire_at
                },
                auth=auth,
                headers=headers
            )
            guest_resp.raise_for_status()
            guest_token = guest_resp.json().get("token", "")

            return {
                "token": guest_token,
                "address": swml_handler_info["address"]
            }

        except requests.exceptions.RequestException as e:
            print(f"Token request failed: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response: {e.response.text}")
            return JSONResponse({"error": str(e)}, status_code=500)

    # Add /get_resource_info endpoint for dashboard links
    @server.app.get('/get_resource_info')
    def get_resource_info():
        """Get SWML handler resource info for linking to SignalWire dashboard."""
        sw_host = get_signalwire_host()
        return {
            "space_name": os.getenv("SIGNALWIRE_SPACE_NAME", ""),
            "resource_id": swml_handler_info["id"],
            "dashboard_url": f"https://{sw_host}/neon/resources/{swml_handler_info['id']}/edit?t=addresses" if sw_host and swml_handler_info["id"] else None
        }

    # Set up SWML handler on startup
    @server.app.on_event("startup")
    async def on_startup():
        setup_swml_handler()

    return server


# Create server and expose app for gunicorn
server = create_server()
app = server.app

if __name__ == "__main__":
    # Parse command line arguments for port
    parser = argparse.ArgumentParser(
        description='Blackjack Dealer - SignalWire Casino Game'
    )
    parser.add_argument(
        '--port', '-p',
        type=int,
        default=PORT,
        help='Port to run the agent on (default: 5000 or $PORT)'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("Blackjack Dealer - SignalWire Casino")
    print("=" * 60)
    print()
    print("A professional blackjack dealer ready to deal you in!")
    print()
    print("Starting chips: 1000")
    print("Minimum bet: 10 chips")
    print("Dealer rules: Hits on 16, Stands on 17")
    print()

    # Create and run the server with custom port if specified
    if args.port != PORT:
        server = create_server(port=args.port)
    server.run()
