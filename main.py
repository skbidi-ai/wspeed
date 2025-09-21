import asyncio
import threading
import logging
import os
from fixed_bot import DiscordBot
from web_server import create_app
from database import mod_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

def run_discord_bot():
    """Run the Discord bot in a separate thread"""
    try:
        import time
        time.sleep(3)  # Wait 3 seconds before connecting to avoid rate limits
        
        bot = DiscordBot()
        discord_token = os.getenv('DISCORD_TOKEN')
        if not discord_token:
            logger.error("DISCORD_TOKEN environment variable not found")
            return
        
        logger.info("Starting Discord bot...")
        asyncio.run(bot.bot.start(discord_token))
    except Exception as e:
        logger.error(f"Error running Discord bot: {e}")
        # Wait before retrying
        import time
        time.sleep(10)
        logger.info("Retrying Discord bot connection...")
        try:
            bot = DiscordBot()
            asyncio.run(bot.bot.start(discord_token))
        except Exception as retry_error:
            logger.error(f"Retry failed: {retry_error}")

def run_flask_server():
    """Run the Flask server for uptime monitoring"""
    try:
        app = create_app()
        logger.info("Starting Flask server on port 5000...")
        app.run(host='0.0.0.0', port=5000, debug=False)
    except Exception as e:
        logger.error(f"Error running Flask server: {e}")

if __name__ == "__main__":
    logger.info("Starting Discord bot with Flask uptime endpoint...")
    
    # Initialize database tables
    try:
        logger.info("Initializing database tables...")
        mod_db.init_database()
        logger.info("Database tables initialized successfully!")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        # Continue anyway - bot can still work without moderation features
    
    # Start Discord bot in a separate thread
    discord_thread = threading.Thread(target=run_discord_bot, daemon=True)
    discord_thread.start()
    
    # Start Flask server in the main thread
    run_flask_server()
