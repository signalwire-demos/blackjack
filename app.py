#!/usr/bin/env python3
"""
Dealer - The SignalWire Blackjack Dealer (Refactored)
An AI-powered blackjack dealer that plays casino-style blackjack via voice/video
Uses stateless architecture with centralized state management
"""

import json
import random
import os
import time
import threading
import warnings
from pathlib import Path
from signalwire import AgentBase, AgentServer
from signalwire.core.function_result import SwaigFunctionResult
from signalwire.rest import RestClient
from dotenv import load_dotenv
from fastapi.responses import JSONResponse

# Load environment variables
load_dotenv()

# Store the SWML handler info for reuse
swml_handler_info = {"id": None, "address_id": None, "address": None}

# Records *why* SWML handler registration didn't happen, surfaced to /get_token
# so a silent skip doesn't become a baffling browser error. Cleared on success.
swml_setup_error = None
# Serializes the lazy re-registration retry in /get_token.
_swml_setup_lock = threading.Lock()

# Plain-language definitions for blackjack vocabulary the player may not know.
GLOSSARY = {
    "wager": "your bet - the chips you put up before the hand is dealt",
    "bet": "the chips you put up before the hand is dealt",
    "ante": "a bet placed before the hand begins",
    "stakes": "the chips you're betting",
    "chips": "the tokens used to place bets, like play money",
    "hit": "take another card to try to get closer to 21",
    "stand": "stop taking cards and keep your current total",
    "double down": "double your bet and take exactly one more card",
    "bust": "going over 21 - you lose the hand automatically",
    "push": "a tie - your bet is returned and no one wins",
    "blackjack": "a two-card hand totaling 21 (an ace plus a ten-value card), pays one and a half times your bet",
    "hole card": "the dealer's face-down card",
    "twenty one": "the goal of the game - get your cards as close to 21 as possible without going over",
    "21": "the goal of the game - get your cards as close to 21 as possible without going over",
}

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
                "After calling place_bet, announce the result to the player and STOP - do NOT call place_bet again or any other function",
            ]) \
            .set_step_criteria("A valid bet has been placed and cards have been dealt") \
            .set_functions(["place_bet", "explain_term"]) \
            .set_valid_steps(["playing"])
        
        # Playing phase
        default_context.add_step("playing") \
            .add_section("Current Task", "Manage the active blackjack hand") \
            .add_bullets("CRITICAL RULES - YOU MUST FOLLOW THESE", [
                "WAIT for the player to speak before calling ANY function - do NOT proactively call functions",
                "The player currently has ${global_data.game_state.player_score} points",
                "When player says 'hit' or wants another card: call the hit function",
                "When player says 'stand' or wants to stay: call the stand function",
                "When player says 'double down': call the double_down function",
                "Only call ONE function per player request - never call multiple functions at once",
                "Split is NOT available at this table - do not offer it as an option",
                "NEVER make up cards or scores - ONLY use what the functions return",
                "NEVER deal cards yourself - the hit function deals cards",
                "NEVER calculate scores yourself - the functions calculate scores",
                "The hit function will tell you EXACTLY what card was drawn and the new score",
                "If the function says 'the hand continues', keep playing - player has NOT busted",
                "Only say the player busted if the function explicitly says 'bust'"
            ]) \
            .set_step_criteria("Hand is complete and the winner is determined.") \
            .set_functions(["hit", "stand", "double_down", "explain_term"]) \
            .set_valid_steps(["hand_complete", "game_over"])


        # Post-Game phase
        default_context.add_step("hand_complete") \
            .add_section("Current Task", "The hand is complete. Review the results and wait for player's decision.") \
            .add_bullets("Important Instructions", [
                "The cards are still on the table - explain what happened in this hand",
                "Tell the user their chip count and how much they won or lost",
                "Ask if they want to play another hand and WAIT for their response",
                "Do NOT call new_hand until the player explicitly says they want to play again",
                "If the user wants to play again, you MUST call new_hand first",
                "The new_hand function will reset the table and change to betting step",
                "Only after calling new_hand can you take a new bet"
            ]) \
            .set_step_criteria("User has indicated whether they want to play another hand") \
            .set_functions(["new_hand", "explain_term"]) \
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
            .set_functions(["explain_term"]) \
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
                response += "\n\nThe hand is now in play. Announce the cards to the player and ask if they want to hit, stand, or double down. Do NOT call any function yet - wait for the player to respond."

            result = SwaigFunctionResult(response)

            # Transition to playing step so hit/stand/double_down tools are available
            if game_state["player_score"] != 21:
                result.swml_change_step("playing")
            
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
                response += f"\n\nYou have {game_state['player_score']} points. The hand continues. Tell the player their new card and total, then wait for them to say hit or stand. Do NOT call any function until the player responds."
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
        
        @self.tool(
            name="explain_term",
            description=(
                "Look up the plain-language definition of a word the player didn't understand. "
                "Call this WHENEVER the player asks what a word means, says they don't understand a term, "
                "or sounds confused by vocabulary (e.g. 'what does wager mean?', 'what's a push?'). "
                "After calling, re-ask your previous question using the plain definition."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "The word or phrase the player did not understand"
                    },
                    "previous_question": {
                        "type": "string",
                        "description": "The question you were asking the player when they got confused, so you can re-ask it in plain words"
                    }
                },
                "required": ["term"]
            }
        )
        def explain_term(args, raw_data):
            term = args.get("term", "").lower().strip().strip("?.,!'\"")
            previous_question = args.get("previous_question", "").strip()

            definition = GLOSSARY.get(term)
            if not definition:
                for key, val in GLOSSARY.items():
                    if key in term or term in key:
                        definition = val
                        break

            if definition:
                response = (
                    f"The word \"{term}\" means: {definition}.\n\n"
                    f"Tell the player the definition in your own words, then re-ask your previous question "
                    f"using plain language instead of \"{term}\"."
                )
            else:
                response = (
                    f"\"{term}\" is not a standard blackjack term in our glossary. "
                    f"Apologize, briefly explain what you meant in plain words, and continue."
                )

            if previous_question:
                response += f"\n\nYour previous question was: \"{previous_question}\". Re-ask it without the confusing word."

            return SwaigFunctionResult(response)

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

        # Get the base URL using SDK's auto-detection from X-Forwarded headers
        # Falls back to SWML_PROXY_URL_BASE or APP_URL if needed
        base_url = self.get_full_url(include_auth=False)

        # Set video URLs dynamically based on detected host
        if base_url:
            self.set_param("video_idle_file", f"{base_url}/sigmond_bj_idle.mp4")
            self.set_param("video_talking_file", f"{base_url}/sigmond_bj_talking.mp4")
            self.set_param("background_file", f"{base_url}/casino.mp3")
            print(f"Set video URLs to use host: {base_url}")

        # Optional post-prompt URL from environment
        post_prompt_url = os.environ.get("POST_PROMPT_URL")
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


def find_resource_address(addresses, agent_name):
    """
    Find the resource address matching /public/{agent_name} from a list of addresses.

    When phone numbers are attached to a handler, multiple addresses exist.
    We want the resource address (e.g., /public/blackjack) not the phone number address.
    """
    expected_address = f"/public/{agent_name}"

    # First, try to find exact match for /public/{agent_name}
    for addr in addresses:
        audio_channel = addr.get("channels", {}).get("audio", "")
        if audio_channel == expected_address:
            return addr

    # Fallback: find any address that looks like a resource address (not a phone number)
    for addr in addresses:
        audio_channel = addr.get("channels", {}).get("audio", "")
        if audio_channel.startswith("/public/") and not any(c.isdigit() for c in audio_channel.split("/")[-1][:3]):
            return addr

    # Last resort: return first address
    return addresses[0] if addresses else None


def find_existing_handler(client, agent_name):
    """Find an existing SWML handler by name via RestClient.

    Response shapes are identical to the legacy raw Fabric endpoints, so the
    parsing below is a 1:1 port: list items carry
    {id, display_name, swml_webhook: {name, primary_request_url}}, and
    list_addresses() returns {data: [{id, channels: {audio: "/public/..."}}]}.
    """
    try:
        # swml_webhooks is the current path for an External SWML Handler.
        handlers = client.fabric.swml_webhooks.list().get("data", [])

        for handler in handlers:
            # The name is nested in swml_webhook object
            swml_webhook = handler.get("swml_webhook", {})
            handler_name = swml_webhook.get("name") or handler.get("display_name")

            # Check if this handler matches our agent name
            if handler_name == agent_name:
                handler_id = handler.get("id")
                handler_url = swml_webhook.get("primary_request_url", "")
                # Get the address for this handler
                addresses = client.fabric.swml_webhooks.list_addresses(handler_id).get("data", [])
                resource_addr = find_resource_address(addresses, agent_name)
                if resource_addr:
                    return {
                        "id": handler_id,
                        "name": handler_name,
                        "url": handler_url,
                        "address_id": resource_addr["id"],
                        "address": resource_addr["channels"]["audio"]
                    }
    except Exception as e:
        print(f"Error checking existing handlers: {e}")
    return None


def setup_swml_handler():
    """Set up SWML handler on startup (via the unified RestClient)."""
    global swml_setup_error
    sw_host = get_signalwire_host()
    project = os.getenv("SIGNALWIRE_PROJECT_ID", "")
    token = os.getenv("SIGNALWIRE_TOKEN", "")
    agent_name = os.getenv("AGENT_NAME", "blackjack")
    proxy_url = os.getenv("SWML_PROXY_URL_BASE", os.getenv("APP_URL", ""))
    auth_user = os.getenv("SWML_BASIC_AUTH_USER", "signalwire")
    auth_pass = os.getenv("SWML_BASIC_AUTH_PASSWORD", "")

    if not all([sw_host, project, token]):
        swml_setup_error = "SignalWire credentials not configured (SIGNALWIRE_SPACE_NAME/PROJECT_ID/TOKEN)"
        print(f"{swml_setup_error} - skipping SWML handler setup")
        return

    if not proxy_url:
        swml_setup_error = "SWML_PROXY_URL_BASE/APP_URL not set"
        print(f"{swml_setup_error} - skipping SWML handler setup")
        return

    # Build SWML URL with basic auth credentials
    if auth_user and auth_pass and "://" in proxy_url:
        scheme, rest = proxy_url.split("://", 1)
        swml_url = f"{scheme}://{auth_user}:{auth_pass}@{rest}/blackjack"
    else:
        swml_url = proxy_url + "/blackjack"

    # RestClient() no-args reads SIGNALWIRE_API_TOKEN/SIGNALWIRE_SPACE, which do NOT
    # match this demo's SIGNALWIRE_TOKEN/SIGNALWIRE_SPACE_NAME convention — pass explicitly.
    client = RestClient(project=project, token=token, host=sw_host)

    # Look for an existing handler by name
    existing = find_existing_handler(client, agent_name)
    if existing:
        swml_handler_info["id"] = existing["id"]
        swml_handler_info["address_id"] = existing["address_id"]
        swml_handler_info["address"] = existing["address"]

        # Always update the URL to ensure credentials are current
        try:
            client.fabric.swml_webhooks.update(
                existing["id"],
                primary_request_url=swml_url,
                primary_request_method="POST",
            )
            print(f"Updated SWML handler: {existing['name']}")
        except Exception as e:
            print(f"Failed to update handler URL: {e}")

        print(f"Call address: {existing['address']}")
        swml_setup_error = None
    else:
        # Create a new external SWML handler with the agent name.
        try:
            # create() emits a DeprecationWarning steering phone-number setups toward
            # phone_numbers.set_swml_webhook; a standalone *dialable* handler (guest
            # tokens dial its /public/{name} address) is intentional here.
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                handler = client.fabric.swml_webhooks.create(
                    name=agent_name,
                    used_for="calling",
                    primary_request_url=swml_url,
                    primary_request_method="POST",
                )
            handler_id = handler.get("id")
            swml_handler_info["id"] = handler_id

            # Get the address for this handler
            addresses = client.fabric.swml_webhooks.list_addresses(handler_id).get("data", [])
            resource_addr = find_resource_address(addresses, agent_name)
            if resource_addr:
                swml_handler_info["address_id"] = resource_addr["id"]
                swml_handler_info["address"] = resource_addr["channels"]["audio"]
                print(f"Created SWML handler: {agent_name}")
                print(f"Call address: {swml_handler_info['address']}")
                swml_setup_error = None
            else:
                swml_setup_error = "No address found for created handler"
                print(swml_setup_error)
        except Exception as e:
            swml_setup_error = f"Failed to create SWML handler: {e}"
            print(swml_setup_error)
            # Retry finding existing handler (another worker may have just created it)
            time.sleep(0.5)
            existing = find_existing_handler(client, agent_name)
            if existing:
                swml_handler_info["id"] = existing["id"]
                swml_handler_info["address_id"] = existing["address_id"]
                swml_handler_info["address"] = existing["address"]
                print(f"Found existing SWML handler after retry: {existing['name']}")
                print(f"Call address: {existing['address']}")
                swml_setup_error = None


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

        # If startup registration didn't complete (stray extra worker, or creds/
        # tunnel arrived late), lazily retry once under a lock before giving up.
        if not swml_handler_info["address_id"]:
            with _swml_setup_lock:
                if not swml_handler_info["address_id"]:
                    setup_swml_handler()

        if not swml_handler_info["address_id"]:
            print(f"get_token failed: swml_handler_info = {swml_handler_info}")
            print(f"  SIGNALWIRE_SPACE_NAME={os.getenv('SIGNALWIRE_SPACE_NAME', '(not set)')}")
            print(f"  SIGNALWIRE_PROJECT_ID={'set' if os.getenv('SIGNALWIRE_PROJECT_ID') else '(not set)'}")
            print(f"  SIGNALWIRE_TOKEN={'set' if os.getenv('SIGNALWIRE_TOKEN') else '(not set)'}")
            print(f"  SWML_PROXY_URL_BASE={os.getenv('SWML_PROXY_URL_BASE', '(not set)')}")
            print(f"  APP_URL={os.getenv('APP_URL', '(not set)')}")
            return JSONResponse(
                {"error": f"SWML handler not registered: {swml_setup_error or 'unknown reason - check startup logs'}"},
                status_code=500,
            )

        try:
            # Create a guest token with access to this address (valid 24 hours).
            client = RestClient(project=project, token=token, host=sw_host)
            expire_at = int(time.time()) + 3600 * 24
            guest = client.fabric.tokens.create_guest_token(
                allowed_addresses=[swml_handler_info["address_id"]],
                expire_at=expire_at,
            )
            guest_token = guest.get("token", "")

            return {
                "token": guest_token,
                "address": swml_handler_info["address"]
            }

        except Exception as e:
            print(f"Token request failed: {e}")
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
    server.run()
