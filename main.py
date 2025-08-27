"""
AI-powered Discord Defense Bot
Runs a single Discord bot with AI-generated responses.
"""
import os

# Import the Flask app from bot.py for Gunicorn
from bot import app

# Simple main entry point - just run the bot
if __name__ == "__main__":
    try:
        # Import and run the bot
        import bot
    except KeyboardInterrupt:
        print("\nBot shutting down...")
    except Exception as e:
        print(f"Error starting bot: {e}")