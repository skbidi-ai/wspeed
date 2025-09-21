import discord
from discord.ext import commands
import logging
import asyncio
import re
from typing import Optional
import json
import os
from datetime import datetime, timedelta
from database import mod_db
import difflib
import random
import operator

logger = logging.getLogger(__name__)

# In-memory pet database  
PET_DATABASE = {}
PET_DATA_FILE = os.path.join(os.path.dirname(__file__), "pet_values.json")

# Pet data will be loaded after function definitions

# Chat guide message system
channel_message_counts = {}  # Track messages per channel for chat guide
chat_guide_cooldown = {}     # Prevent spam/duplicates per channel
CHAT_GUIDE_MESSAGE = "**Make sure to check out the [Chat Guide](https://discord.com/channels/1370086525210984458/1410921626241073173) & you are following the guidelines whilst chatting!**"
CHAT_GUIDE_INTERVAL = 100    # Send every 100 messages
CHAT_GUIDE_CHANNEL_ID = 1370086532433838102  # Only send in this specific channel

# Load existing pet data on startup
def load_pet_data():
    global PET_DATABASE
    try:
        logger.info(f"🔄 Attempting to load pet data from {PET_DATA_FILE}")
        if os.path.exists(PET_DATA_FILE):
            logger.info(f"✅ File {PET_DATA_FILE} exists, loading...")
            with open(PET_DATA_FILE, 'r') as f:
                PET_DATABASE = json.load(f)
            logger.info(f"🐾 Successfully loaded {len(PET_DATABASE)} pets from database")
        else:
            PET_DATABASE = {}
            logger.error(f"❌ File {PET_DATA_FILE} not found, starting with empty database")
    except Exception as e:
        logger.error(f"💥 Error loading pet data: {e}")
        logger.error(f"📁 Current working directory: {os.getcwd()}")
        logger.error(f"📂 Contents of directory: {os.listdir('.')}")
        PET_DATABASE = {}

# Save pet data to file
def save_pet_data():
    try:
        with open(PET_DATA_FILE, 'w') as f:
            json.dump(PET_DATABASE, f, indent=2)
        logger.info(f"Saved {len(PET_DATABASE)} pets to database")
    except Exception as e:
        logger.error(f"Error saving pet data: {e}")

# Enhanced pet name detection patterns - Updated for your exact format
PET_PATTERNS = [
    # Primary pattern for the new format: "(Petname)- (Value)┆ Demand: (demand) ┆Image:https://..."
    r'\(([^)]+)\)\s*-\s*([^┆\n]+?)┆\s*Demand:\s*([^┆\n]+?)\s*┆\s*Image:\s*(https?://[^\s\n]+)',
    # Fallback without image
    r'\(([^)]+)\)\s*-\s*([^┆\n]+?)┆\s*Demand:\s*([^┆\n]+)',
    # Legacy patterns for compatibility
    r'([A-Za-z\s]+?)\s*-\s*([^┆\n]+?)┆\s*Demand:\s*([^┆\n]+?)┆\s*Image:\s*(https?://[^\s\n]+)',
    r'([A-Za-z\s]+?)\s*-\s*([^┆\n]+?)┆\s*Demand:\s*([^┆\n]+)',
]

def get_similarity_score(name1, name2):
    """Enhanced similarity scoring with fuzzy matching"""
    name1 = name1.lower().strip()
    name2 = name2.lower().strip()

    # Exact match
    if name1 == name2:
        return 100

    # Check if search term is contained in pet name
    if name1 in name2 or name2 in name1:
        return 95

    # Check word overlap
    words1 = set(name1.split())
    words2 = set(name2.split())
    common_words = words1.intersection(words2)

    if common_words:
        overlap_ratio = len(common_words) / max(len(words1), len(words2))
        if overlap_ratio >= 0.4:
            return int(overlap_ratio * 85)

    # Fuzzy string matching
    from difflib import SequenceMatcher
    ratio = SequenceMatcher(None, name1, name2).ratio()
    if ratio >= 0.6:
        return int(ratio * 80)

    # Partial matches
    if any(word in name2 for word in words1 if len(word) > 2):
        return 60

    return 0

def find_best_pet_matches(search_name, max_results=5):
    """Find best matching pets with improved scoring"""
    matches = []

    for key, pet_data in PET_DATABASE.items():
        score = get_similarity_score(search_name, pet_data['name'])
        if score > 40:  # Lower threshold for better results
            matches.append((pet_data, score))

    # Sort by similarity score (highest first)
    matches.sort(key=lambda x: x[1], reverse=True)
    return matches[:max_results]

async def process_pet_value_message(message, provided_image_url=None):
    """Enhanced pet value processing with instant updates and proper image extraction"""
    content = message.content

    # Skip messages from games like Wordbomb, Trivia, etc.
    if any(game_word in content.lower() for game_word in [
        'wordbomb', 'trivia', 'akinator', 'pokemon', 'countryball', 'higher lower',
        'word chain', 'rhyme time', 'scramble', 'hangman', 'twenty questions',
        'truth or dare', 'never have i ever', 'would you rather', 'counting',
        'rock paper scissors', 'tic tac toe', 'connect 4', 'chess', 'checkers'
    ]):
        logger.info(f"Skipping game message: {content[:50]}...")
        return

    # Skip messages that are just random words without pet context
    if not any(keyword in content.lower() for keyword in [
        'value', 'demand', 'pet', '🐾', '🪙', 'high', 'medium', 'low', 'extremely', 'image:', '┆'
    ]):
        return

    # Collect all images from the message
    image_urls = []

    if message.attachments:
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith('image/'):
                image_url = attachment.url
                image_urls.append(image_url)
                logger.info(f"Found attachment image: {attachment.filename}")

    if message.embeds:
        for embed in message.embeds:
            if embed.image and embed.image.url:
                image_url = embed.image.url
                image_urls.append(image_url)
            elif embed.thumbnail and embed.thumbnail.url:
                image_url = embed.thumbnail.url
                image_urls.append(image_url)

    if provided_image_url:
        image_urls.append(provided_image_url)

    # Enhanced pattern matching with image extraction
    found_pets = []
    for pattern in PET_PATTERNS:
        matches = re.findall(pattern, content, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            if len(match) >= 3:
                pet_name = match[0].strip()
                value = match[1].strip()
                demand = match[2].strip()

                # Check if this pattern includes image URL (4th group)
                extracted_image_url = None
                if len(match) >= 4 and match[3]:
                    extracted_image_url = match[3].strip()
                    # Remove 'lossless' parameter if present
                    if 'quality=lossless' in extracted_image_url:
                        extracted_image_url = extracted_image_url.replace('&quality=lossless', '').replace('quality=lossless&', '').replace('quality=lossless', '')
                    logger.info(f"Extracted image URL from text: {extracted_image_url[:50]}...")

                # Clean pet name - remove "lossless" prefix if present
                original_name = pet_name
                pet_name = re.sub(r'^(lossless\s*)', '', pet_name, flags=re.IGNORECASE).strip()
                pet_name = re.sub(r'[^\w\s]', '', pet_name).strip()

                # Skip if cleaning removed everything or left only short/invalid names
                if (not pet_name or
                    pet_name.lower() in ['lossless', 'losless', 'loss', 'less'] or
                    len(pet_name) < 2):
                    logger.info(f"Skipping invalid pet name after cleaning: '{original_name}' -> '{pet_name}'")
                    continue

                if len(pet_name) >= 2:
                    found_pets.append((pet_name, value, demand, extracted_image_url))

    # Store pets with images - FIXED assignment logic
    for i, pet_data in enumerate(found_pets):
        pet_name, value, demand = pet_data[:3]
        extracted_image_url = pet_data[3] if len(pet_data) > 3 else None

        assigned_image = None

        # Priority 1: Image URL extracted from the message text (most accurate)
        if extracted_image_url:
            assigned_image = extracted_image_url
            logger.info(f"Using extracted image URL for {pet_name}: {assigned_image[:50]}...")
        # Priority 2: Only assign attachment images if there's exactly ONE pet and ONE image
        elif len(found_pets) == 1 and len(image_urls) == 1:
            assigned_image = image_urls[0]
            logger.info(f"Assigning single attachment image to {pet_name}: {assigned_image[:50]}...")
        else:
            logger.info(f"No suitable image found for {pet_name}")

        pet_key = pet_name.lower().replace(' ', '_')

        # Store pet data with instant update - preserve existing image if no new one
        existing_image = PET_DATABASE.get(pet_key, {}).get('image_url')
        final_image = assigned_image if assigned_image else existing_image

        PET_DATABASE[pet_key] = {
            'name': pet_name,
            'value': value,
            'demand': demand,
            'last_updated': message.created_at.isoformat(),
            'message_id': message.id,
            'image_url': final_image
        }

        logger.info(f"Updated pet: {pet_name} - Value: {value} - Demand: {demand} - Image: {'Yes' if assigned_image else 'No'}")

    # Save data immediately for instant updates
    if found_pets:
        save_pet_data()
        logger.info(f"INSTANT UPDATE: Processed {len(found_pets)} pets and saved to database")

# Pet weight formula
BASE_WEIGHTS = {
    1: 1.00, 2: 1.09, 3: 1.18, 4: 1.27, 5: 1.36, 6: 1.45, 7: 1.55, 8: 1.64, 9: 1.73, 10: 1.82,
    11: 1.91, 12: 2.00, 13: 2.09, 14: 2.18, 15: 2.27, 16: 2.36, 17: 2.45, 18: 2.55, 19: 2.64, 20: 2.73,
    21: 2.82, 22: 2.91, 23: 3.00, 24: 3.09, 25: 3.18, 26: 3.27, 27: 3.36, 28: 3.45, 29: 3.55, 30: 3.64,
    31: 3.73, 32: 3.82, 33: 3.91, 34: 4.00, 35: 4.09, 36: 4.18, 37: 4.27, 38: 4.36, 39: 4.45, 40: 4.55,
    41: 4.64, 42: 4.73, 43: 4.82, 44: 4.91, 45: 5.00, 46: 5.09, 47: 5.18, 48: 5.27, 49: 5.36, 50: 5.45,
    51: 5.55, 52: 5.64, 53: 5.73, 54: 5.82, 55: 5.91, 56: 6.00, 57: 6.09, 58: 6.18, 59: 6.27, 60: 6.36,
    61: 6.45, 62: 6.55, 63: 6.64, 64: 6.73, 65: 6.82, 66: 6.91, 67: 7.00, 68: 7.09, 69: 7.18, 70: 7.27,
    71: 7.36, 72: 7.45, 73: 7.55, 74: 7.64, 75: 7.73, 76: 7.82, 77: 7.91, 78: 8.00, 79: 8.09, 80: 8.18,
    81: 8.27, 82: 8.36, 83: 8.45, 84: 8.55, 85: 8.64, 86: 8.73, 87: 8.82, 88: 8.91, 89: 9.00, 90: 9.09,
    91: 9.18, 92: 9.27, 93: 9.36, 94: 9.45, 95: 9.55, 96: 9.64, 97: 9.73, 98: 9.82, 99: 9.91, 100: 10.00
}

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=['gs.', 'gs '], intents=intents)

# Channel IDs
TARGET_CHANNEL_ID = 1401169397850308708
PET_VALUES_CHANNEL_IDS = [
    1406716276373590117,  # PRISMATIC CATEGORY
    1406716328697659583,  # DIVINE CATEGORY
    1406716530326241451,  # MYTHIC CATEGORY
    1406716596302385323,  # LEGENDARY CATEGORY
    1406716645921263787,  # RARE CATEGORY
    1406716717870223360,  # UNCOMMON CATEGORY
    1406716764368404520   # COMMON CATEGORY
]
REPORT_CHANNEL_ID = 1403179951431094404
AUTOMOD_REPORT_CHANNEL_ID = 1405317544507609180

# Automod banned words
BANNED_WORDS = [
    'negr', 'gay', 'epstiened', 'fatass', 'dildo', 'vagina', '@everyone', 'nudes', 'epstein', 'diddy',
    'fetish', 'bitch ass', 'bitchass', 'doxx', 'chong', 'nigga', 'anal', 'asshole', 'boob', 'didy',
    'femboy', '𝗇𝗂𝗀𝗀𝖺', 'horny', 'whore', 'diddle', 'slut', 'sybau', 'lgbtq', 'drug', 'penis',
    'goon', 'dick', 'pussy', 'twerk', 'porn', 'niger', 'fag', 'lgbt', 'slag', 'blackie',
    'prostitute', 'nigger', 'retard', 'diddled', 'niggas', 'dih', 'feet', 'schlong'
]

# Country guessing game data
COUNTRIES_FLAGS = {
    "🇺🇸": "United States", "🇬🇧": "United Kingdom", "🇨🇦": "Canada", "🇦🇺": "Australia", "🇩🇪": "Germany",
    "🇫🇷": "France", "🇮🇹": "Italy", "🇪🇸": "Spain", "🇯🇵": "Japan", "🇰🇷": "South Korea", "🇨🇳": "China",
    "🇧🇷": "Brazil", "🇲🇽": "Mexico", "🇦🇷": "Argentina", "🇮🇳": "India", "🇷🇺": "Russia", "🇿🇦": "South Africa",
    "🇪🇬": "Egypt", "🇳🇬": "Nigeria", "🇰🇪": "Kenya", "🇸🇪": "Sweden", "🇳🇴": "Norway", "🇩🇰": "Denmark",
    "🇫🇮": "Finland", "🇳🇱": "Netherlands", "🇧🇪": "Belgium", "🇨🇭": "Switzerland", "🇦🇹": "Austria",
    "🇵🇱": "Poland", "🇨🇿": "Czech Republic", "🇭🇺": "Hungary", "🇬🇷": "Greece", "🇹🇷": "Turkey",
    "🇮🇪": "Ireland", "🇵🇹": "Portugal", "🇮🇸": "Iceland", "🇱🇺": "Luxembourg", "🇲🇹": "Malta",
    "🇨🇾": "Cyprus", "🇧🇬": "Bulgaria", "🇷🇴": "Romania", "🇭🇷": "Croatia", "🇸🇮": "Slovenia",
    "🇸🇰": "Slovakia", "🇪🇪": "Estonia", "🇱🇻": "Latvia", "🇱🇹": "Lithuania", "🇺🇦": "Ukraine",
    "🇧🇾": "Belarus", "🇲🇩": "Moldova", "🇷🇸": "Serbia", "🇧🇦": "Bosnia and Herzegovina", "🇲🇪": "Montenegro",
    "🇲🇰": "North Macedonia", "🇦🇱": "Albania", "🇽🇰": "Kosovo", "🇮🇱": "Israel", "🇯🇴": "Jordan",
    "🇱🇧": "Lebanon", "🇸🇾": "Syria", "🇮🇶": "Iraq", "🇮🇷": "Iran", "🇸🇦": "Saudi Arabia", "🇦🇪": "UAE",
    "🇰🇼": "Kuwait", "🇶🇦": "Qatar", "🇧🇭": "Bahrain", "🇴🇲": "Oman", "🇾🇪": "Yemen", "🇦🇫": "Afghanistan",
    "🇵🇰": "Pakistan", "🇧🇩": "Bangladesh", "🇱🇰": "Sri Lanka", "🇳🇵": "Nepal", "🇧🇹": "Bhutan",
    "🇲🇻": "Maldives", "🇹🇭": "Thailand", "🇻🇳": "Vietnam", "🇰🇭": "Cambodia", "🇱🇦": "Laos",
    "🇲🇾": "Malaysia", "🇸🇬": "Singapore", "🇮🇩": "Indonesia", "🇵🇭": "Philippines", "🇧🇳": "Brunei",
    "🇹🇱": "East Timor", "🇲🇳": "Mongolia", "🇰🇿": "Kazakhstan", "🇺🇿": "Uzbekistan", "🇰🇬": "Kyrgyzstan",
    "🇹🇯": "Tajikistan", "🇹🇲": "Turkmenistan", "🇬🇪": "Georgia", "🇦🇲": "Armenia", "🇦🇿": "Azerbaijan",
    "🇲🇦": "Morocco", "🇹🇳": "Tunisia", "🇩🇿": "Algeria", "🇱🇾": "Libya", "🇸🇩": "Sudan", "🇪🇭": "Western Sahara",
    "🇲🇷": "Mauritania", "🇲🇱": "Mali", "🇧🇫": "Burkina Faso", "🇳🇪": "Niger", "🇹🇩": "Chad",
    "🇸🇳": "Senegal", "🇬🇲": "Gambia", "🇬🇼": "Guinea-Bissau", "🇬🇳": "Guinea", "🇸🇱": "Sierra Leone",
    "🇱🇷": "Liberia", "🇨🇮": "Ivory Coast", "🇬🇭": "Ghana", "🇹🇬": "Togo", "🇧🇯": "Benin",
    "🇨🇲": "Cameroon", "🇨🇫": "Central African Republic", "🇹🇩": "Chad", "🇸🇸": "South Sudan",
    "🇪🇹": "Ethiopia", "🇪🇷": "Eritrea", "🇩🇯": "Djibouti", "🇸🇴": "Somalia", "🇺🇬": "Uganda",
    "🇷🇼": "Rwanda", "🇧🇮": "Burundi", "🇹🇿": "Tanzania", "🇲🇼": "Malawi", "🇿🇲": "Zambia",
    "🇿🇼": "Zimbabwe", "🇧🇼": "Botswana", "🇳🇦": "Namibia", "🇱🇸": "Lesotho", "🇸🇿": "Eswatini",
    "🇲🇬": "Madagascar", "🇲🇺": "Mauritius", "🇸🇨": "Seychelles", "🇰🇲": "Comoros", "🇨🇻": "Cape Verde",
    "🇸🇹": "Sao Tome and Principe", "🇬🇶": "Equatorial Guinea", "🇬🇦": "Gabon", "🇨🇬": "Republic of the Congo",
    "🇨🇩": "Democratic Republic of the Congo", "🇦🇴": "Angola", "🇧🇲": "Bermuda", "🇵🇷": "Puerto Rico"
}

# Tracking systems
invite_cache = {}
user_invites = {}
user_message_counts = {}
daily_reset = None
weekly_reset = None
monthly_reset = None
WFL_PATTERN = re.compile(r'\bwfl\b', re.IGNORECASE)
last_reaction_time = {}
reaction_cooldown = 1

# Country game tracking
active_games = {}

# Math game tracking
active_math_games = {}

# Group game tracking
active_group_math_games = {}
active_group_country_games = {}
active_group_scramble_games = {}
active_group_wordbomb_games = {}

# Word bomb game data
SCRAMBLE_WORDS = [
    "algorithm", "computer", "keyboard", "monitor", "software", "hardware", "network", "internet",
    "database", "programming", "javascript", "python", "discord", "gaming", "streaming", "challenge",
    "adventure", "treasure", "mystery", "fantasy", "rainbow", "butterfly", "elephant", "dolphin",
    "mountain", "ocean", "forest", "desert", "volcano", "galaxy", "planet", "asteroid", "comet",
    "telescope", "microscope", "laboratory", "experiment", "discovery", "invention", "creativity",
    "imagination", "inspiration", "motivation", "determination", "achievement", "success", "victory",
    "friendship", "kindness", "happiness", "celebration", "festival", "carnival", "fireworks",
    "chocolate", "strawberry", "pineapple", "watermelon", "hamburger", "sandwich", "restaurant",
    "university", "library", "museum", "theater", "concert", "orchestra", "symphony", "melody",
    "harmony", "rhythm", "photography", "painting", "sculpture", "architecture", "literature"
]

WORDBOMB_SEQUENCES = [
    "ing", "tion", "ent", "er", "ly", "ed", "al", "an", "re", "th", "in", "on", "at", "st", "nd",
    "ch", "sh", "ck", "ll", "ss", "ff", "pp", "tt", "dd", "mm", "nn", "rr", "bb", "gg", "zz",
    "ough", "ight", "ould", "ance", "ence", "able", "ible", "ment", "ness", "less", "ful", "ous"
]

def reset_message_counts():
    """Reset message counts based on time periods"""
    global daily_reset, weekly_reset, monthly_reset
    now = discord.utils.utcnow()

    if daily_reset is None or now > daily_reset:
        for user_id in user_message_counts:
            user_message_counts[user_id]['daily'] = 0
        daily_reset = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        logger.info("Reset daily message counts")

    if weekly_reset is None or now > weekly_reset:
        for user_id in user_message_counts:
            user_message_counts[user_id]['weekly'] = 0
        days_ahead = 6 - now.weekday()
        weekly_reset = (now + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)
        logger.info("Reset weekly message counts")

    if monthly_reset is None or now > monthly_reset:
        for user_id in user_message_counts:
            user_message_counts[user_id]['monthly'] = 0
        if now.month == 12:
            monthly_reset = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            monthly_reset = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        logger.info("Reset monthly message counts")

async def cache_invites():
    """Cache all current invites"""
    global invite_cache
    try:
        if bot.guilds:
            invites = await bot.guilds[0].invites()
            invite_cache = {invite.code: {'uses': invite.uses, 'inviter': invite.inviter} for invite in invites}
            logger.info(f"Cached {len(invite_cache)} invites")
    except Exception as e:
        logger.error(f"Error caching invites: {e}")

def calculate_weight_multiplier(current_age, current_weight):
    if current_age not in BASE_WEIGHTS:
        return None
    base_weight_at_current_age = BASE_WEIGHTS[current_age]
    multiplier = current_weight / base_weight_at_current_age
    return multiplier

def predict_weights(current_age, current_weight, target_ages=None):
    multiplier = calculate_weight_multiplier(current_age, current_weight)
    if multiplier is None:
        return None

    if target_ages is None:
        target_ages = list(range(1, 101))

    predictions = {}
    for age in target_ages:
        if age in BASE_WEIGHTS:
            predicted_weight = BASE_WEIGHTS[age] * multiplier
            predictions[age] = round(predicted_weight, 2)

    return predictions

# Automod Ban View
class AutomodBanView(discord.ui.View):
    def __init__(self, user, message_content, channel):
        super().__init__(timeout=300)
        self.user = user
        self.message_content = message_content
        self.channel = channel

    @discord.ui.button(label="🔨 Ban User", style=discord.ButtonStyle.danger)
    async def ban_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.ban_members:
            await interaction.response.send_message("<:GsWrong:1414561861352816753>   You don't have permission to ban users.", ephemeral=True)
            return

        try:
            await self.user.ban(reason=f"Automod violation: {self.message_content[:100]}")

            embed = discord.Embed(
                title="🔨 User Banned Successfully",
                description=f"{self.user.mention} has been banned for automod violation.",
                color=0xFFC916,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="👮 Moderator", value=interaction.user.mention, inline=True)
            embed.add_field(name="📋 Reason", value=f"Automod violation: {self.message_content[:100]}", inline=False)
            embed.set_footer(text="🔥 Game Services Automod System")

            await interaction.edit_original_response(embed=embed, view=None)

        except Exception as e:
            await interaction.response.send_message(f"<:GsWrong:1414561861352816753>   Error banning user: {str(e)}", ephemeral=True)
    @discord.ui.button(label="<:GsWrong:1414561861352816753> Dismiss", style=discord.ButtonStyle.secondary)
    async def dismiss_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message("<:GsWrong:1414561861352816753>   You don't have permission to dismiss reports.", ephemeral=True)
            return

        embed = discord.Embed(
            title="<:GsWrong:1414561861352816753>  Automod Report Dismissed",
            description="The automod report has been dismissed by a moderator.",
            color=0x808080,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="👮 Dismissed By", value=interaction.user.mention, inline=True)
        embed.set_footer(text="🔥 Game Services Automod System")

        await interaction.edit_original_response(embed=embed, view=None)

@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    logger.info(f'Bot is in {len(bot.guilds)} guilds')
    
    # Debug: List all registered commands
    logger.info(f"Total commands registered: {len(list(bot.commands))}")
    logger.info(f"Registered commands: {[cmd.name for cmd in bot.commands]}")
    logger.info(f"Commands with aliases: {[(cmd.name, cmd.aliases) for cmd in bot.commands if cmd.aliases]}")
    
    # Test if petvalue command specifically exists
    petvalue_cmd = bot.get_command('petvalue')
    v_cmd = bot.get_command('v')
    logger.info(f"petvalue command found: {petvalue_cmd is not None}")
    logger.info(f"v alias found: {v_cmd is not None}")
    
    # Test command loading
    if len(list(bot.commands)) == 0:
        logger.error("🚨 CRITICAL: No commands registered! This is the problem!")
    else:
        logger.info(f"<:GsRight:1414593140156792893>  Commands successfully registered: {len(list(bot.commands))} total")

    # Initialize database tables
    try:
        mod_db.init_database()
        logger.info("Database tables initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")

    load_pet_data()
    await cache_invites()
    reset_message_counts()

    target_channel = bot.get_channel(TARGET_CHANNEL_ID)
    if target_channel:
        logger.info(f'Monitoring channel: {target_channel.name} ({target_channel.id})')

    logger.info(f'Pet database loaded with {len(PET_DATABASE)} pets (auto-scanning disabled)')
    
    # Debug command registration at the end
    logger.info("🔍 FINAL COMMAND DEBUG:")
    logger.info(f"Total commands registered: {len(list(bot.commands))}")
    logger.info(f"Registered commands: {[cmd.name for cmd in bot.commands]}")
    logger.info(f"Commands with aliases: {[(cmd.name, cmd.aliases) for cmd in bot.commands if cmd.aliases]}")
    
    # Test specific commands
    petvalue_cmd = bot.get_command('petvalue')
    v_cmd = bot.get_command('v')
    logger.info(f"petvalue command found: {petvalue_cmd is not None}")
    logger.info(f"v alias found: {v_cmd is not None}")
    
    if len(list(bot.commands)) == 0:
        logger.error("🚨 CRITICAL: No commands registered at end of on_ready!")
    else:
        logger.info(f"<:GsRight:1414593140156792893>  ON_READY COMPLETE: {len(list(bot.commands))} commands active")

@bot.event
async def on_disconnect():
    logger.warning("Bot disconnected from Discord!")

@bot.event
async def on_resumed():
    logger.info("Bot reconnected to Discord!")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    # Track message counts
    user_id = message.author.id
    if user_id not in user_message_counts:
        user_message_counts[user_id] = {'daily': 0, 'weekly': 0, 'monthly': 0, 'last_message': discord.utils.utcnow()}

    reset_message_counts()

    user_message_counts[user_id]['daily'] += 1
    user_message_counts[user_id]['weekly'] += 1
    user_message_counts[user_id]['monthly'] += 1
    user_message_counts[user_id]['last_message'] = discord.utils.utcnow()

    # Chat guide message system - only track messages in the specific channel
    channel_id = message.channel.id
    if channel_id == CHAT_GUIDE_CHANNEL_ID:
        if channel_id not in channel_message_counts:
            channel_message_counts[channel_id] = 0

        channel_message_counts[channel_id] += 1

        # Check if we should send chat guide message
        if channel_message_counts[channel_id] % CHAT_GUIDE_INTERVAL == 0:
            # Check cooldown to prevent spam (5 minute cooldown)
            current_time = discord.utils.utcnow()
            if channel_id not in chat_guide_cooldown or \
               (current_time - chat_guide_cooldown[channel_id]).total_seconds() > 300:
                try:
                    await message.channel.send(CHAT_GUIDE_MESSAGE)
                    chat_guide_cooldown[channel_id] = current_time
                    logger.info(f"Sent chat guide message in {message.channel.name} after {channel_message_counts[channel_id]} messages")
                except Exception as e:
                    logger.error(f"Error sending chat guide message: {e}")

    # Automoderation check (skip admins)
    is_admin = message.author.guild_permissions.manage_guild or message.author.guild_permissions.administrator

    if not is_admin:
        message_lower = message.content.lower()
        for banned_word in BANNED_WORDS:
            if banned_word.lower() in message_lower:
                try:
                    # Delete the message with error handling
                    try:
                        await message.delete()
                        message_deleted = True
                    except discord.NotFound:
                        logger.info(f"Message already deleted by {message.author}")
                        message_deleted = False
                    except discord.Forbidden:
                        logger.warning(f"No permission to delete message by {message.author}")
                        message_deleted = False
                    except Exception as del_error:
                        logger.error(f"Error deleting message: {del_error}")
                        message_deleted = False

                    # Warn and mute the user with permission checks
                    duration_minutes = 10
                    timeout_duration = timedelta(minutes=duration_minutes)

                    # Check if bot can timeout users
                    bot_member = message.guild.get_member(bot.user.id)
                    if not bot_member or not bot_member.guild_permissions.moderate_members:
                        logger.error(f"Bot missing moderate_members permission for automod")
                        continue

                    # Check role hierarchy
                    if message.author.top_role >= bot_member.top_role:
                        logger.warning(f"Cannot automod {message.author} - role hierarchy")
                        continue

                    try:
                        await message.author.timeout(timeout_duration, reason=f"Automod: Used banned word '{banned_word}'")
                        timeout_success = True
                    except discord.Forbidden as timeout_error:
                        logger.error(f"Permission error timing out {message.author}: {timeout_error}")
                        timeout_success = False
                    except Exception as timeout_error:
                        logger.error(f"Error timing out {message.author}: {timeout_error}")
                        timeout_success = False

                    # Log in database with error handling
                    try:
                        action_id = mod_db.add_moderation_action(
                            user_id=message.author.id,
                            moderator_id=bot.user.id,
                            server_id=message.guild.id,
                            action_type="warn",
                            reason=f"Automod: Used banned word '{banned_word}'"
                        )

                        if timeout_success:
                            mod_db.add_moderation_action(
                                user_id=message.author.id,
                                moderator_id=bot.user.id,
                                server_id=message.guild.id,
                                action_type="mute",
                                reason=f"Automod: Used banned word '{banned_word}'",
                                duration_minutes=duration_minutes
                            )
                        database_logged = True
                    except Exception as db_error:
                        logger.error(f"Database error in automod: {db_error}")
                        database_logged = False

                    # Send to automod report channel
                    automod_channel = bot.get_channel(AUTOMOD_REPORT_CHANNEL_ID)
                    if automod_channel:
                        embed = discord.Embed(
                            title="⚠️ Automod Violation Detected",
                            description=f"User {message.author.mention} has been automatically warned and muted.",
                            color=0xFFC916,
                            timestamp=discord.utils.utcnow()
                        )
                        embed.add_field(name="👤 User", value=f"{message.author.mention} ({message.author})", inline=False)
                        embed.add_field(name="📍 Channel", value=f"{message.channel.mention}", inline=True)
                        embed.add_field(name="🚫 Triggered Word", value=f"||{banned_word}||", inline=True)
                        embed.add_field(name="💬 Message Content", value=f"||{message.content[:500]}||", inline=False)
                        actions_taken = []
                        if database_logged:
                            actions_taken.append("• Warned user")
                        if timeout_success:
                            actions_taken.append("• Muted for 10 minutes")
                        if message_deleted:
                            actions_taken.append("• Message deleted")

                        if not actions_taken:
                            actions_taken.append("• No actions taken (permission errors)")

                        embed.add_field(name="⚡ Actions Taken", value="\n".join(actions_taken), inline=False)
                        embed.set_footer(text="🔥 Game Services Automod System")

                        view = AutomodBanView(message.author, message.content, message.channel)
                        await automod_channel.send(embed=embed, view=view)

                    # DM the user (only if any action was taken)
                    if timeout_success or database_logged:
                        try:
                            dm_embed = discord.Embed(
                                title="⚠️ Automod Warning",
                                description="Your message contained inappropriate content and has been removed.",
                                color=0xFFC916,
                                timestamp=discord.utils.utcnow()
                            )
                            dm_embed.add_field(name="🏠 Server", value=f"{message.guild.name}", inline=True)
                            if timeout_success:
                                dm_embed.add_field(name="⏱️ Mute Duration", value="10 minutes", inline=True)
                            dm_embed.add_field(name="📋 Reason", value=f"Used inappropriate word: ||{banned_word}||", inline=False)
                            dm_embed.add_field(name="🚨 Appeal", value="If you believe this was a mistake, contact staff in our appeals server:\nhttps://discord.gg/ahharETNNR", inline=False)
                            dm_embed.set_footer(text="🔥 Game Services Automod System")

                            await message.author.send(embed=dm_embed)
                        except discord.Forbidden:
                            logger.info(f"Cannot DM {message.author} - DMs disabled")
                        except Exception as dm_error:
                            logger.error(f"Error sending automod DM: {dm_error}")

                except Exception as e:
                    logger.error(f"Unexpected error in automod for {message.author}: {e}")
                    # Continue processing other banned words

                return  # Stop processing if automod triggered

    # Check for group math game answers
    if message.channel.id in active_group_math_games:
        game = active_group_math_games[message.channel.id]
        user_id = message.author.id

        # Check if user already answered this round
        if user_id not in game['answered_this_round']:
            if message.content.strip().replace('-', '').isdigit():
                user_answer = int(message.content.strip())
                if user_answer == game['answer']:
                    # Award point
                    if user_id not in game['players']:
                        game['players'][user_id] = 0
                    game['players'][user_id] += 1
                    game['answered_this_round'].add(user_id)

                    # React to show it was correct
                    try:
                        await message.add_reaction('<:GsRight:1414593140156792893> ')
                    except:
                        pass

    # Check for group country game answers
    if message.channel.id in active_group_country_games:
        game = active_group_country_games[message.channel.id]
        user_id = message.author.id

        # Check if user already answered this round
        if user_id not in game['answered_this_round']:
            if message.content.lower().strip() == game['country'].lower():
                # Award point
                if user_id not in game['players']:
                    game['players'][user_id] = 0
                game['players'][user_id] += 1
                game['answered_this_round'].add(user_id)

                # React to show it was correct
                try:
                    await message.add_reaction('<:GsRight:1414593140156792893>')
                except:
                    pass

    # Check for group scramble game answers
    if message.channel.id in active_group_scramble_games:
        game = active_group_scramble_games[message.channel.id]
        user_id = message.author.id

        # Check if user already answered this round
        if user_id not in game['answered_this_round']:
            if message.content.lower().strip() == game['word'].lower():
                # Award point
                if user_id not in game['players']:
                    game['players'][user_id] = 0
                game['players'][user_id] += 1
                game['answered_this_round'].add(user_id)

                # React to show it was correct
                try:
                    await message.add_reaction('<:GsRight:1414593140156792893> ')
                except:
                    pass

    # Check for group wordbomb game answers
    if message.channel.id in active_group_wordbomb_games:
        game = active_group_wordbomb_games[message.channel.id]
        user_id = message.author.id

        # Check if user already answered this round
        if user_id not in game['answered_this_round']:
            answer = message.content.lower().strip()
            # Enhanced validation for proper words
            if (len(answer) >= 3 and
                game['sequence'].lower() in answer and
                answer.isalpha() and
                answer not in game['used_words'] and
                is_valid_word(answer, game['sequence'])):

                # Award point
                if user_id not in game['players']:
                    game['players'][user_id] = 0
                game['players'][user_id] += 1
                game['answered_this_round'].add(user_id)
                game['used_words'].add(answer)

                # React to show it was correct
                try:
                    await message.add_reaction('<:GsRight:1414593140156792893> ')
                except:
                    pass

    # Process commands
    await bot.process_commands(message)

    # WFL reactions
    if message.channel.id == TARGET_CHANNEL_ID:
        if WFL_PATTERN.search(message.content):
            current_time = asyncio.get_event_loop().time()
            if (message.channel.id in last_reaction_time and
                current_time - last_reaction_time[message.channel.id] < reaction_cooldown):
                return

            last_reaction_time[message.channel.id] = current_time

            reactions = ['W1', 'F1', 'L1']
            try:
                for emoji_name in reactions:
                    emoji = discord.utils.get(message.guild.emojis, name=emoji_name)
                    if emoji:
                        await message.add_reaction(emoji)
                    await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f'Error adding reactions: {e}')

@bot.command()
async def petweight(ctx, current_age: int, current_weight: float, target_age: Optional[int] = None):
    """🐾 Calculate pet weight at different ages"""
    try:
        if current_age < 1 or current_age > 100:
            await ctx.send("<:GsWrong:1414561861352816753>   Pet Age must be between 1 and 100")
            return

        if current_weight <= 0:
            await ctx.send("<:GsWrong:1414561861352816753>   Pet Weight must be greater than 0")
            return

        if target_age is not None:
            if target_age < 1 or target_age > 100:
                await ctx.send("<:GsWrong:1414561861352816753>   Pet Target age must be between 1 and 100")
                return

            predictions = predict_weights(current_age, current_weight, [target_age])
            if predictions is None:
                await ctx.send("<:GsWrong:1414561861352816753>   Invalid Pet age provided")
                return
            predicted_weight = predictions[target_age]
            embed = discord.Embed(
                title="Petweight Prediction",
                url="https://discord.gg/4Jy4R8kMaf",  # <- clickable title link
                color=0xFFC916
            )
            embed.add_field(name="Current Info:", value=f"**Age:** {current_age} \n**Weight:** {current_weight} <:KG:1414601553167519864>  ", inline=False)
            
            embed.add_field(name=f"Predicted Weight at Age {target_age}", value=f"**{predicted_weight} <:KG:1414601553167519864> ** ", inline=False)
            
            embed.set_footer(text="🔥 Game Services • Pet Weight Calculator")
            
            await ctx.reply(embed=embed, mention_author=True)
            await ctx.message.add_reaction('<:GsRight:1414593140156792893>')

        else:
            predictions = predict_weights(current_age, current_weight)
            if predictions is None:
                await ctx.send("<:GsWrong:1414561861352816753>   Invalid age provided")
                return

            key_ages = []
            for age in range(current_age, min(current_age + 11, 101)):
                if age in predictions:
                    key_ages.append(age)

            if len(key_ages) < 10:
                for age in range(max(1, current_age - 5), current_age):
                    if age in predictions and age not in key_ages:
                        key_ages.insert(0, age)

            key_ages = sorted(key_ages)[:10]

            embed = discord.Embed(
                title="Petweight Prediction",
                url="https://discord.gg/4Jy4R8kMaf",  # <- clickable title link
                color=0xFFC916
            )
            embed.add_field(name=" Current Info:", value=f"**Age:** {current_age} 📅\n**Weight:** {current_weight} <:KG:1414601553167519864> ", inline=False)

            weight_text = ""
            for age in key_ages:
                marker = " ← **Current**" if age == current_age else ""
                weight_text += f"**Age {age}:** {predictions[age]} kg{marker}\n"

            embed.add_field(name="Weight Predictions:", value=weight_text, inline=False)
            embed.add_field(name="Tip:", value="Use `gs.petweight <age> <weight> <target_age>` to predict weight at a specific age", inline=False)
            embed.set_footer(text="🔥 Game Services • Pet Weight Calculator")

            await ctx.reply(embed=embed, mention_author=True)
            await ctx.message.add_reaction('<:GsRight:1414593140156792893>')

    except ValueError:
        await ctx.send("<:GsWrong:1414561861352816753>   Please provide valid numbers for age and weight")
    except Exception as e:
        logger.error(f"Error in petweight command: {e}")
        await ctx.send("<:GsWrong:1414561861352816753>   An error occurred while calculating weights")

@bot.command(aliases=['v', 'value', 'val'])
async def petvalue(ctx, *, pet_name: str):
    """🐾 Look up pet value information"""
    try:
        # Lazy fallback: Load pets if database is empty 
        if not PET_DATABASE:
            logger.warning("PET_DATABASE is empty, attempting to reload...")
            load_pet_data()
            
        logger.info(f"🔍 Pet value lookup for '{pet_name}' - Database has {len(PET_DATABASE)} pets")
        # Enhanced search
        clean_name = re.sub(r'[^\w\s]', '', pet_name).strip().lower().replace(' ', '_')

        # Direct match first
        exact_match = None
        for key, pet_data in PET_DATABASE.items():
            if key == clean_name or pet_data['name'].lower() == pet_name.lower():
                exact_match = pet_data
                break

        if exact_match:
            embed = discord.Embed(
                title=exact_match['name'],
                url="https://discord.gg/4Jy4R8kMaf",  # <- clickable title link
                color=0xFFC916
            )
            embed.set_author(
                name="Game Services Values",
                icon_url="https://images-ext-1.discordapp.net/external/o1Y_94Itjl4AeBMbyiY7Xow1UI36KpW2nqWOJ1bZcT0/%3Fsize%3D1024/https/cdn.discordapp.com/avatars/1381546186183278612/19ed5075b4b08f29a41dd99d080c31e9.png?format=webp&quality=lossless"  # <- must be a direct image link
            )

            embed.add_field(name="<:ExclamationMark:1412880724809482260>  __Pets are valued based on Mimic  <:MimicOctopus:1412404639164403752>__", value="> __1KG Mimic = 100 Value__", inline=False)

 
            embed.add_field(name="Value", value=f"{exact_match['value']} <:Sheckles:1412881740099223582>  ", inline=True)
            
            embed.add_field(name="Demand", value=f"{exact_match['demand']}", inline=True)

            embed.add_field(
                name="Trend",
                value=exact_match.get("trend") or "Adding",
                inline=True
            )
            embed.add_field(
                name="Tier",
                value=exact_match.get("tier") or "Adding",
                inline=True
            )
            embed.add_field(
                name="Obtained By",
                value=exact_match.get("obtainement") or "Adding",
                inline=True
            )

            if 'image_url' in exact_match and exact_match['image_url']:
                try:
                    # Clean the image URL and ensure it's properly formatted
                    image_url = exact_match['image_url'].strip()
                    # Remove 'lossless' parameter if present
                    if 'quality=lossless' in image_url:
                        image_url = image_url.replace('&quality=lossless', '').replace('quality=lossless&', '').replace('quality=lossless', '')
                    embed.set_thumbnail(url=image_url)
                    logger.info(f"<:GsRight:1414593140156792893>  Successfully displaying image for {exact_match['name']}")
                except Exception as e:
                    logger.error(f"<:GsWrong:1414561861352816753>   Error setting image for {exact_match['name']}: {e}")
            else:
                logger.warning(f"No image available for {exact_match['name']}")

            embed.set_footer(text="🔥 Game Services • Info: (100% match)")

            from discord.ui import View, Button

            # build ONE link-button view
            view = View()

            # first button
            view.add_item(Button(
                label="Suggest Values",
                url="https://discord.com/channels/1370086525210984458/1391747223884136590",
                style=discord.ButtonStyle.link
            ))

            # second button
            view.add_item(Button(
                label="Values Explained",
                url="https://discord.com/channels/1370086525210984458/1370101881308713193/1406781226018406450",
                style=discord.ButtonStyle.link
            ))
            # send a single reply with the embed + button
            try:
                reply_msg = await ctx.reply(embed=embed, view=view, mention_author=True)
            except Exception as e:
                # fallback if sending with a view fails for any reason
                print(f"")
                reply_msg = await ctx.reply(embed=embed, mention_author=True)

            # add reaction to the original message (the one that triggered the command)
            try:
                await ctx.message.add_reaction('<:GsRight:1414593140156792893>')
            except Exception as e:
                # Ignore/log permission/emoji errors
                print(f"")

            return



        # Fuzzy search
        best_matches = find_best_pet_matches(pet_name, max_results=5)
        if best_matches:
            # Auto-select best match
            top_match = best_matches[0]
            pet_data = top_match[0]  # dict for the pet

            embed = discord.Embed(
                title=pet_data["name"],  
                url="https://discord.gg/4Jy4R8kMaf",
                color=0xFFC916
            )

            embed.set_author(
                name="Game Services Values",
                icon_url="https://cdn.discordapp.com/avatars/1381546186183278612/19ed5075b4b08f29a41dd99d080c31e9.png?size=1024"
            )

            embed.add_field(
                name="<:ExclamationMark:1412880724809482260>  __Pets are valued based on Mimic__  <:MimicOctopus:1412404639164403752>",
                value="> __1KG Mimic = 100 Value__",
                inline=False
            )
            

            embed.add_field(
                name="Value",
                value=f"{pet_data['value']} <:Sheckles:1412881740099223582>",
                inline=True
            )

            embed.add_field(
                name="Demand",
                value=pet_data["demand"],
                inline=True
            )

            embed.add_field(
                name="Trend",
                value=pet_data["trend"],
                inline=True
            )

            embed.add_field(
                name="Tier",
                value=pet_data["tier"],
                inline=True
            )

            embed.add_field(
                name="Obtained By",
                value=pet_data["obtainement"],
                inline=True
            )

            # <:GsRight:1414593140156792893>  Add thumbnail if available
            if 'image_url' in pet_data and pet_data['image_url']:
                try:
                    image_url = pet_data['image_url'].strip()
                    if 'quality=lossless' in image_url:
                        image_url = image_url.replace('&quality=lossless', '').replace('quality=lossless&', '').replace('quality=lossless', '')
                    embed.set_thumbnail(url=image_url)
                    logger.info(f"<:GsRight:1414593140156792893>  Successfully displaying image for {pet_data['name']}")
                except Exception as e:
                    logger.error(f"<:GsWrong:1414561861352816753>   Error setting image for {pet_data['name']}: {e}")
            else:
                logger.warning(f"No image available for {pet_data['name']}")

            # <:GsRight:1414593140156792893>  Add footer after match quality
            footer_text = "🔥 Game Services • INSTANT UPDATES"
            if top_match[1] < 100:
                footer_text = f"🔥 Game Services • Info: ({top_match[1]}% match)"
            embed.set_footer(text=footer_text)

            from discord.ui import View, Button

            # build ONE link-button view
            view = View()

            # first button
            view.add_item(Button(
                label="Suggest Values",
                url="https://discord.com/channels/1370086525210984458/1391747223884136590",
                style=discord.ButtonStyle.link
            ))

            # second button
            view.add_item(Button(
                label="Values Explained",
                url="https://discord.com/channels/1370086525210984458/1370101881308713193/1406781226018406450",
                style=discord.ButtonStyle.link
            ))
            # send a single reply with the embed + button
            try:
                reply_msg = await ctx.reply(embed=embed, view=view, mention_author=True)
            except Exception as e:
                # fallback if sending with a view fails for any reason
                print(f"")
                reply_msg = await ctx.reply(embed=embed, mention_author=True)

            # add reaction to the original message (the one that triggered the command)
            try:
                await ctx.message.add_reaction('<:GsRight:1414593140156792893>')
            except Exception as e:
                # Ignore/log permission/emoji errors
                print(f"")

            return

        else:
            embed = discord.Embed(
                title="",
                description=f"<:GsWrong:1414561861352816753>  Pet  **{pet_name}**  not found. Names are exactly how they are in-game, \ndouble check!",
                color=0xFFC916  # Gold color
            )
            embed.set_footer(text="🔥 Game Services")
            embed.set_author(
                name="Game Services Values",
                icon_url="https://images-ext-1.discordapp.net/external/o1Y_94Itjl4AeBMbyiY7Xow1UI36KpW2nqWOJ1bZcT0/%3Fsize%3D1024/https/cdn.discordapp.com/avatars/1381546186183278612/19ed5075b4b08f29a41dd99d080c31e9.png?format=webp&quality=lossless"  # <- must be a direct image link
            )
            await ctx.reply(embed=embed)

            try:
                await ctx.message.add_reaction('<:GsWrong:1414561861352816753>')
            except:
                pass

    except Exception as e:
        logger.error(f"Error in petvalue command: {e}")
        await ctx.send("<:GsWrong:1414561861352816753>   An error occurred while looking up pet values")

    if not ctx.author.guild_permissions.administrator:
        await ctx.send("<:GsWrong:1414561861352816753>   You need administrator permissions to force update the database.")
        return

@bot.command(aliases=['pets', 'list'])
async def petlist(ctx, page: int = 1):
    """List all pets in the database"""
    try:
        if not PET_DATABASE:
            await ctx.send("<:GsWrong:1414561861352816753>   No pets found in database")
            return

        pets_per_page = 15
        total_pets = len(PET_DATABASE)
        total_pages = (total_pets + pets_per_page - 1) // pets_per_page

        if page < 1 or page > total_pages:
            await ctx.send(f"<:GsWrong:1414561861352816753>   Invalid page number. Pages available: 1-{total_pages}")
            return

        start_idx = (page - 1) * pets_per_page
        end_idx = start_idx + pets_per_page

        pets = list(PET_DATABASE.values())[start_idx:end_idx]

        embed = discord.Embed(title="🐾 Pet Database", color=0xFFC916)
        embed.add_field(name="📊 Total Pets", value=f"**{total_pets}** pets ", inline=True)
        embed.add_field(name="📄 Page", value=f"**{page}/{total_pages}** ", inline=True)
        pet_list = ""
        for pet in pets:
            demand_emoji = {"High": "🔥", "Medium": "📈", "Low": "📉", "Extremely High": "💎", "Terrible": "💀"}.get(pet['demand'], "📊")
            pet_list += f"• **{pet['name']}** - {pet['value']} | {pet['demand']} {demand_emoji}\n"

        embed.add_field(name="🐾 Pets", value=pet_list or "No pets on this page", inline=False)

        if page < total_pages:
            embed.add_field(name="💡 Navigation", value=f"Use `gs.petlist {page + 1}` for next page ➡️\nUse `gs.v <name>` to get detailed info 🔍", inline=False)
        else:
            embed.add_field(name="💡 Usage", value="Use `gs.v <name>` to get detailed pet info 🔍", inline=False)

        embed.set_footer(text="🔥 Game Services • AUTO-SCAN ALL MESSAGES")
        await ctx.send(embed=embed)

    except Exception as e:
        logger.error(f"Error in petlist command: {e}")
        await ctx.send("<:GsWrong:1414561861352816753>   An error occurred while listing pets")

@bot.command(aliases=['country', 'flag', 'guess'])
async def countryguess(ctx):
    """🌍 Start a country guessing game"""
    if ctx.channel.id in active_games:
        await ctx.send("🎮 A game is already active in this channel! Wait for it to finish.")
        return

    # Select random country
    flag, country = random.choice(list(COUNTRIES_FLAGS.items()))
    active_games[ctx.channel.id] = {
        'country': country,
        'players': {},
        'round': 1,
        'max_rounds': 5,
        'start_time': discord.utils.utcnow()
    }

    embed = discord.Embed(
        title="🌍 Country Guessing Game Started!",
        description=f"**Round 1/5:** What country does this flag belong to? 🤔\n\n{flag}",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="⏰ Time Limit", value="15 seconds per round ⏱️", inline=True)
    embed.add_field(name="🎯 How to Play", value="Just type the country name! 💬", inline=True)
    embed.add_field(name="🏆 Scoring", value="First correct answer gets a point! 🥇", inline=True)
    embed.set_footer(text="🔥 Game Services • Anyone can play!")

    await ctx.send(embed=embed)

    # Wait for answers
    def check(m):
        return (m.channel == ctx.channel and
                not m.author.bot and
                m.content.lower().strip() == country.lower())

    try:
        winner_msg = await bot.wait_for('message', check=check, timeout=15.0)

        # Award point
        user_id = winner_msg.author.id
        if user_id not in active_games[ctx.channel.id]['players']:
            active_games[ctx.channel.id]['players'][user_id] = 0
        active_games[ctx.channel.id]['players'][user_id] += 1

        embed = discord.Embed(
            title="<:GsRight:1414593140156792893>  Correct Answer!",
            description=f"🎉 {winner_msg.author.mention} got it right! That's **{country}**.",
            color=0xFFC916
        )
        embed.set_footer(text="🔥 Game Services • Great job!")
        await ctx.send(embed=embed)

        # Continue game or end
        if active_games[ctx.channel.id]['round'] < 5:
            await asyncio.sleep(2)
            active_games[ctx.channel.id]['round'] += 1
            await continue_country_game(ctx)
        else:
            await end_country_game(ctx)

    except asyncio.TimeoutError:
        embed = discord.Embed(
            title="⏰ Time's Up!",
            description=f"No one got it! The answer was **{country}** {flag}",
            color=0xFFC916
        )
        embed.set_footer(text="🔥 Game Services • Better luck next time!")
        await ctx.send(embed=embed)

        if active_games[ctx.channel.id]['round'] < 5:
            await asyncio.sleep(2)
            active_games[ctx.channel.id]['round'] += 1
            await continue_country_game(ctx)
        else:
            await end_country_game(ctx)

async def continue_country_game(ctx):
    """Continue the country guessing game"""
    if ctx.channel.id not in active_games:
        return

    game = active_games[ctx.channel.id]
    flag, country = random.choice(list(COUNTRIES_FLAGS.items()))
    game['country'] = country

    embed = discord.Embed(
        title="🌍 Country Guessing Game",
        description=f"**Round {game['round']}/5:** What country does this flag belong to? 🤔\n\n{flag}",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="⏰ Time Limit", value="15 seconds ⏱️", inline=True)
    embed.add_field(name="🏆 Current Scores", value="\n".join([f"<@{uid}>: {score} 🎯" for uid, score in game['players'].items()]) if game['players'] else "No scores yet 📊", inline=True)
    embed.set_footer(text="🔥 Game Services • Keep guessing!")

    await ctx.send(embed=embed)

    def check(m):
        return (m.channel == ctx.channel and
                not m.author.bot and
                m.content.lower().strip() == country.lower())

    try:
        winner_msg = await bot.wait_for('message', check=check, timeout=15.0)

        user_id = winner_msg.author.id
        if user_id not in game['players']:
            game['players'][user_id] = 0
        game['players'][user_id] += 1

        embed = discord.Embed(
            title="<:GsRight:1414593140156792893>  Correct Answer!",
            description=f"🎉 {winner_msg.author.mention} got it right! That's **{country}**.",
            color=0xFFC916
        )
        await ctx.send(embed=embed)

        if game['round'] < 5:
            await asyncio.sleep(2)
            game['round'] += 1
            await continue_country_game(ctx)
        else:
            await end_country_game(ctx)

    except asyncio.TimeoutError:
        embed = discord.Embed(
            title="⏰ Time's Up!",
            description=f"No one got it! The answer was **{country}** {flag}",
            color=0xFFC916
        )
        await ctx.send(embed=embed)

        if game['round'] < 5:
            await asyncio.sleep(2)
            game['round'] += 1
            await continue_country_game(ctx)
        else:
            await end_country_game(ctx)

async def end_country_game(ctx):
    """End the country guessing game and show results"""
    if ctx.channel.id not in active_games:
        return

    game = active_games[ctx.channel.id]

    if not game['players']:
        embed = discord.Embed(
            title="🎮 Game Over!",
            description="No one scored any points! Better luck next time! 😅",
            color=0xFFC916
        )
        embed.set_footer(text="🔥 Game Services • Thanks for playing!")
    else:
        # Sort players by score
        sorted_players = sorted(game['players'].items(), key=lambda x: x[1], reverse=True)

        leaderboard = ""
        for i, (user_id, score) in enumerate(sorted_players, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            leaderboard += f"{medal} <@{user_id}>: **{score}** points\n"

        embed = discord.Embed(
            title="🎮 Game Over! Final Scores:",
            description=leaderboard,
            color=0xFFC916,
            timestamp=discord.utils.utcnow()
        )

        if sorted_players:
            winner_id = sorted_players[0][0]
            winner_score = sorted_players[0][1]
            embed.add_field(name="🏆 Winner", value=f"🎉 <@{winner_id}> with **{winner_score}** points!", inline=False)

        embed.add_field(name="🔄 Play Again", value="Use `gs.countryguess` to start a new game! 🌍", inline=False)
        embed.set_footer(text="🔥 Game Services • Thanks for playing!")

    await ctx.send(embed=embed)
    del active_games[ctx.channel.id]

@bot.command(name="mathquestions", aliases=['math', 'mathgame', 'mathquiz'])
async def mathquestions(ctx):
    """🧮 Start a math questions game"""
    if ctx.channel.id in active_math_games:
        await ctx.send("🎮 A math game is already active in this channel! Wait for it to finish.")
        return

    # Generate first math question
    num1, num2, operation, answer = generate_math_question()
    active_math_games[ctx.channel.id] = {
        'answer': answer,
        'players': {},
        'round': 1,
        'max_rounds': 5,
        'start_time': discord.utils.utcnow()
    }

    embed = discord.Embed(
        title="🧮 Math Questions Game Started!",
        description=f"**Round 1/5:** What is the answer to this equation? 🤔\n\n**{num1} {operation} {num2} = ?**",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="⏰ Time Limit", value="15 seconds per round ⏱️", inline=True)
    embed.add_field(name="🎯 How to Play", value="Just type the number! 💬", inline=True)
    embed.add_field(name="🏆 Scoring", value="First correct answer gets a point! 🥇", inline=True)
    embed.set_footer(text="🔥 Game Services • Anyone can play!")

    await ctx.send(embed=embed)

    # Wait for answers
    def check(m):
        return (m.channel == ctx.channel and
                not m.author.bot and
                m.content.strip().replace('-', '').isdigit() and
                int(m.content.strip()) == answer)

    try:
        winner_msg = await bot.wait_for('message', check=check, timeout=15.0)

        # Award point
        user_id = winner_msg.author.id
        if user_id not in active_math_games[ctx.channel.id]['players']:
            active_math_games[ctx.channel.id]['players'][user_id] = 0
        active_math_games[ctx.channel.id]['players'][user_id] += 1

        embed = discord.Embed(
            title="<:GsRight:1414593140156792893>  Correct Answer!",
            description=f"🎉 {winner_msg.author.mention} got it right! The answer was **{answer}**.",
            color=0xFFC916
        )
        embed.set_footer(text="🔥 Game Services • Great job!")
        await ctx.send(embed=embed)

        # Continue game or end
        if active_math_games[ctx.channel.id]['round'] < 5:
            await asyncio.sleep(2)
            active_math_games[ctx.channel.id]['round'] += 1
            await continue_math_game(ctx)
        else:
            await end_math_game(ctx)

    except asyncio.TimeoutError:
        embed = discord.Embed(
            title="⏰ Time's Up!",
            description=f"No one got it! The answer was **{answer}**",
            color=0xFFC916
        )
        embed.set_footer(text="🔥 Game Services • Better luck next time!")
        await ctx.send(embed=embed)

        if active_math_games[ctx.channel.id]['round'] < 5:
            await asyncio.sleep(2)
            active_math_games[ctx.channel.id]['round'] += 1
            await continue_math_game(ctx)
        else:
            await end_math_game(ctx)

def generate_math_question():
    """Generate a random math question"""
    operations = ['+', '-', '*', '/']
    operation = random.choice(operations)

    if operation == '+':
        num1 = random.randint(10, 100)
        num2 = random.randint(10, 100)
        answer = num1 + num2
    elif operation == '-':
        num1 = random.randint(20, 100)
        num2 = random.randint(10, num1)  # Ensure positive result
        answer = num1 - num2
    elif operation == '*':
        num1 = random.randint(2, 15)
        num2 = random.randint(2, 15)
        answer = num1 * num2
    else:  # division
        answer = random.randint(2, 20)
        num2 = random.randint(2, 12)
        num1 = answer * num2  # Ensure clean division
        operation = '÷'

    return num1, num2, operation, answer

async def continue_math_game(ctx):
    """Continue the math game"""
    if ctx.channel.id not in active_math_games:
        return

    game = active_math_games[ctx.channel.id]
    num1, num2, operation, answer = generate_math_question()
    game['answer'] = answer

    embed = discord.Embed(
        title="🧮 Math Questions Game",
        description=f"**Round {game['round']}/5:** What is the answer to this equation? 🤔\n\n**{num1} {operation} {num2} = ?**",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="⏰ Time Limit", value="15 seconds ⏱️", inline=True)
    embed.add_field(name="🏆 Current Scores", value="\n".join([f"<@{uid}>: {score} 🎯" for uid, score in game['players'].items()]) if game['players'] else "No scores yet 📊", inline=True)
    embed.set_footer(text="🔥 Game Services • Keep calculating!")

    await ctx.send(embed=embed)

    def check(m):
        return (m.channel == ctx.channel and
                not m.author.bot and
                m.content.strip().replace('-', '').isdigit() and
                int(m.content.strip()) == answer)

    try:
        winner_msg = await bot.wait_for('message', check=check, timeout=15.0)

        user_id = winner_msg.author.id
        if user_id not in game['players']:
            game['players'][user_id] = 0
        game['players'][user_id] += 1

        embed = discord.Embed(
            title="<:GsRight:1414593140156792893>  Correct Answer!",
            description=f"🎉 {winner_msg.author.mention} got it right! The answer was **{answer}**.",
            color=0xFFC916
        )
        await ctx.send(embed=embed)

        if game['round'] < 5:
            await asyncio.sleep(2)
            game['round'] += 1
            await continue_math_game(ctx)
        else:
            await end_math_game(ctx)

    except asyncio.TimeoutError:
        embed = discord.Embed(
            title="⏰ Time's Up!",
            description=f"No one got it! The answer was **{answer}**",
            color=0xFFC916
        )
        await ctx.send(embed=embed)

        if game['round'] < 5:
            await asyncio.sleep(2)
            game['round'] += 1
            await continue_math_game(ctx)
        else:
            await end_math_game(ctx)

async def end_math_game(ctx):
    """End the math game and show results"""
    if ctx.channel.id not in active_math_games:
        return

    game = active_math_games[ctx.channel.id]

    if not game['players']:
        embed = discord.Embed(
            title="🎮 Game Over!",
            description="No one scored any points! Better luck next time! 😅",
            color=0xFFC916
        )
        embed.set_footer(text="🔥 Game Services • Thanks for playing!")
    else:
        # Sort players by score
        sorted_players = sorted(game['players'].items(), key=lambda x: x[1], reverse=True)

        leaderboard = ""
        for i, (user_id, score) in enumerate(sorted_players, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            leaderboard += f"{medal} <@{user_id}>: **{score}** points\n"

        embed = discord.Embed(
            title="🎮 Game Over! Final Scores:",
            description=leaderboard,
            color=0xFFC916,
            timestamp=discord.utils.utcnow()
        )

        if sorted_players:
            winner_id = sorted_players[0][0]
            winner_score = sorted_players[0][1]
            embed.add_field(name="🏆 Winner", value=f"🎉 <@{winner_id}> with **{winner_score}** points!", inline=False)

        embed.add_field(name="🔄 Play Again", value="Use `gs.mathquestions` to start a new game! 🧮", inline=False)
        embed.set_footer(text="🔥 Game Services • Thanks for playing!")

    await ctx.send(embed=embed)
    del active_math_games[ctx.channel.id]

@bot.command(name="groupmath", aliases=['gmath', 'groupmathgame', 'mgame'])
async def group_math_game(ctx):
    """🧮 Start a group math game where everyone can participate"""
    if ctx.channel.id in active_group_math_games:
        await ctx.send("🎮 A group math game is already active in this channel! Wait for it to finish.")
        return

    # Create participation embed
    embed = discord.Embed(
        title="🧮 Group Math Game - Join Now!",
        description="React with <:GsRight:1414593140156792893>  to participate in the group math challenge!\n\n**20 seconds to join...**",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="🎯 How to Play", value="Answer math questions as fast as you can! 💬", inline=True)
    embed.add_field(name="🏆 Scoring", value="1 point for each correct answer! 🥇", inline=True)
    embed.add_field(name="📊 Rounds", value="10 questions total 📝", inline=True)
    embed.set_footer(text="🔥 Game Services • React to join!")

    message = await ctx.send(embed=embed)

    # Bot reacts first
    await message.add_reaction("<:GsRight:1414593140156792893> ")

    # Wait 20 seconds for reactions
    await asyncio.sleep(20)

    # Get participants
    updated_message = await ctx.channel.fetch_message(message.id)
    participants = set()
    for reaction in updated_message.reactions:
        if str(reaction.emoji) == "<:GsRight:1414593140156792893> ":
            async for user in reaction.users():
                if not user.bot:
                    participants.add(user.id)

    if not participants:
        await ctx.send("<:GsWrong:1414561861352816753>   No one joined the game! Better luck next time.")
        return

    # Generate first math question
    num1, num2, operation, answer = generate_math_question()
    active_group_math_games[ctx.channel.id] = {
        'answer': answer,
        'players': {},
        'round': 1,
        'max_rounds': 10,
        'start_time': discord.utils.utcnow(),
        'answered_this_round': set(),
        'participants': participants
    }

    embed = discord.Embed(
        title="🧮 Group Math Game Started!",
        description=f"**Round 1/10:** 🤔\n\n**{num1} {operation} {num2} = ?**",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="⏰ Time Limit", value="20 seconds per round ⏱️", inline=True)
    embed.add_field(name="👥 Players", value=f"{len(participants)} joined! 🎯", inline=True)
    embed.add_field(name="🏆 Scoring", value="1 point for each correct answer! 🥇", inline=True)
    embed.set_footer(text="🔥 Game Services • Group Math Challenge!")

    await ctx.send(embed=embed)

    # Wait for answers
    await asyncio.sleep(20)  # Give 20 seconds for everyone to answer
    await continue_group_math_game(ctx)

@bot.command(name="groupcountriesquiz", aliases=['gcountry', 'groupcountry', 'gcountries', 'countrygame', 'countries', 'flags'])
async def group_country_quiz(ctx):
    """🌍 Start a group countries quiz where everyone can participate"""
    if ctx.channel.id in active_group_country_games:
        await ctx.send("🎮 A group countries quiz is already active in this channel! Wait for it to finish.")
        return

    # Create participation embed
    embed = discord.Embed(
        title="🌍 Group Countries Quiz - Join Now!",
        description="React with <:GsRight:1414593140156792893>  to participate in the geography challenge!\n\n**20 seconds to join...**",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="🎯 How to Play", value="Guess country names from flags! 🏳️", inline=True)
    embed.add_field(name="🏆 Scoring", value="1 point for each correct guess! 🥇", inline=True)
    embed.add_field(name="📊 Rounds", value="10 flags total 🌍", inline=True)
    embed.set_footer(text="🔥 Game Services • React to join!")

    message = await ctx.send(embed=embed)

    # Bot reacts first
    await message.add_reaction("<:GsRight:1414593140156792893> ")

    # Wait 20 seconds for reactions
    await asyncio.sleep(20)

    # Get participants
    updated_message = await ctx.channel.fetch_message(message.id)
    participants = set()
    for reaction in updated_message.reactions:
        if str(reaction.emoji) == "<:GsRight:1414593140156792893> ":
            async for user in reaction.users():
                if not user.bot:
                    participants.add(user.id)

    if not participants:
        await ctx.send("<:GsWrong:1414561861352816753>   No one joined the game! Better luck next time.")
        return

    # Select random country
    flag, country = random.choice(list(COUNTRIES_FLAGS.items()))
    active_group_country_games[ctx.channel.id] = {
        'country': country,
        'players': {},
        'round': 1,
        'max_rounds': 10,
        'start_time': discord.utils.utcnow(),
        'answered_this_round': set(),
        'participants': participants
    }

    embed = discord.Embed(
        title="🌍 Group Countries Quiz Started!",
        description=f"**Round 1/10:** Guess this country! 🤔\n\n{flag}",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="⏰ Time Limit", value="20 seconds per round ⏱️", inline=True)
    embed.add_field(name="👥 Players", value=f"{len(participants)} joined! 🎯", inline=True)
    embed.add_field(name="🏆 Scoring", value="1 point for each correct answer! 🥇", inline=True)
    embed.set_footer(text="🔥 Game Services • Group Geography Challenge!")

    await ctx.send(embed=embed)

    # Wait for answers
    await asyncio.sleep(20)  # Give 20 seconds for everyone to answer
    await continue_group_country_game(ctx)

async def continue_group_math_game(ctx):
    """Continue the group math game"""
    if ctx.channel.id not in active_group_math_games:
        return

    game = active_group_math_games[ctx.channel.id]

    # Show who got the last question right
    if game['answered_this_round']:
        correct_users = [f"<@{uid}>" for uid in game['answered_this_round']]
        embed = discord.Embed(
            title="<:GsRight:1414593140156792893>  Correct Answers!",
            description=f"🎉 **{len(correct_users)}** players got it right!\n{', '.join(correct_users)}",
            color=0xFFC916
        )
        embed.add_field(name="📊 Answer", value=f"**{game['answer']}**", inline=True)
        await ctx.send(embed=embed)
        await asyncio.sleep(2)

    if game['round'] >= game['max_rounds']:
        await end_group_math_game(ctx)
        return

    # Clear answered set for new round
    game['answered_this_round'].clear()
    game['round'] += 1

    # Generate new question
    num1, num2, operation, answer = generate_math_question()
    game['answer'] = answer

    embed = discord.Embed(
        title="🧮 Group Math Game",
        description=f"**Round {game['round']}/10:** What's the answer? 🤔\n\n**{num1} {operation} {num2} = ?**",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="⏰ Time Limit", value="15 seconds ⏱️", inline=True)
    embed.add_field(name="👥 Players", value=f"{len(game['players'])} participating 🎯", inline=True)
    embed.set_footer(text="🔥 Game Services • Keep calculating!")

    await ctx.send(embed=embed)
    await asyncio.sleep(20)
    await continue_group_math_game(ctx)

async def continue_group_country_game(ctx):
    """Continue the group country game"""
    if ctx.channel.id not in active_group_country_games:
        return

    game = active_group_country_games[ctx.channel.id]

    # Show who got the last question right
    if game['answered_this_round']:
        correct_users = [f"<@{uid}>" for uid in game['answered_this_round']]
        embed = discord.Embed(
            title="<:GsRight:1414593140156792893>  Correct Answers!",
            description=f"🎉 **{len(correct_users)}** players got it right!\n{', '.join(correct_users)}",
            color=0xFFC916
        )
        embed.add_field(name="🌍 Answer", value=f"**{game['country']}**", inline=True)
        await ctx.send(embed=embed)
        await asyncio.sleep(2)

    if game['round'] >= game['max_rounds']:
        await end_group_country_game(ctx)
        return

    # Clear answered set for new round
    game['answered_this_round'].clear()
    game['round'] += 1

    # Generate new country
    flag, country = random.choice(list(COUNTRIES_FLAGS.items()))
    game['country'] = country

    embed = discord.Embed(
        title="🌍 Group Countries Quiz",
        description=f"**Round {game['round']}/10:** What country is this? 🤔\n\n{flag}",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="⏰ Time Limit", value="15 seconds ⏱️", inline=True)
    embed.add_field(name="👥 Players", value=f"{len(game['players'])} participating 🎯", inline=True)
    embed.set_footer(text="🔥 Game Services • Keep guessing!")

    await ctx.send(embed=embed)
    await asyncio.sleep(20)
    await continue_group_country_game(ctx)

async def end_group_math_game(ctx):
    """End the group math game and show leaderboard"""
    if ctx.channel.id not in active_group_math_games:
        return

    game = active_group_math_games[ctx.channel.id]

    if not game['players']:
        embed = discord.Embed(
            title="🎮 Group Math Game Over!",
            description="No one participated! Better luck next time! 😅",
            color=0xFFC916
        )
        embed.set_footer(text="🔥 Game Services • Thanks for playing!")
    else:
        # Sort players by score
        sorted_players = sorted(game['players'].items(), key=lambda x: x[1], reverse=True)

        leaderboard = ""
        for i, (user_id, score) in enumerate(sorted_players, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            percentage = int((score / game['max_rounds']) * 100)
            leaderboard += f"{medal} <@{user_id}>: **{score}/{game['max_rounds']}** ({percentage}%)\n"

        embed = discord.Embed(
            title="🎮 Group Math Game Over! Final Leaderboard:",
            description=leaderboard,
            color=0xFFC916,
            timestamp=discord.utils.utcnow()
        )

        if sorted_players:
            winner_id = sorted_players[0][0]
            winner_score = sorted_players[0][1]
            embed.add_field(name="🏆 Winner", value=f"🎉 <@{winner_id}> with **{winner_score}** points!", inline=False)

        embed.add_field(name="📊 Game Stats", value=f"**{len(game['players'])}** total participants\n**{game['max_rounds']}** questions asked", inline=True)
        embed.add_field(name="🔄 Play Again", value="Use `gs.groupmath` to start a new game! 🧮", inline=False)
        embed.set_footer(text="🔥 Game Services • Thanks for playing!")

    await ctx.send(embed=embed)
    del active_group_math_games[ctx.channel.id]

async def end_group_country_game(ctx):
    """End the group country game and show leaderboard"""
    if ctx.channel.id not in active_group_country_games:
        return

    game = active_group_country_games[ctx.channel.id]

    if not game['players']:
        embed = discord.Embed(
            title="🎮 Group Countries Quiz Over!",
            description="No one participated! Better luck next time! 😅",
            color=0xFFC916
        )
        embed.set_footer(text="🔥 Game Services • Thanks for playing!")
    else:
        # Sort players by score
        sorted_players = sorted(game['players'].items(), key=lambda x: x[1], reverse=True)

        leaderboard = ""
        for i, (user_id, score) in enumerate(sorted_players, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            percentage = int((score / game['max_rounds']) * 100)
            leaderboard += f"{medal} <@{user_id}>: **{score}/{game['max_rounds']}** ({percentage}%)\n"

        embed = discord.Embed(
            title="🎮 Group Countries Quiz Over! Final Leaderboard:",
            description=leaderboard,
            color=0xFFC916,
            timestamp=discord.utils.utcnow()
        )

        if sorted_players:
            winner_id = sorted_players[0][0]
            winner_score = sorted_players[0][1]
            embed.add_field(name="🏆 Winner", value=f"🎉 <@{winner_id}> with **{winner_score}** points!", inline=False)

        embed.add_field(name="📊 Game Stats", value=f"**{len(game['players'])}** total participants\n**{game['max_rounds']}** questions asked", inline=True)
        embed.add_field(name="🔄 Play Again", value="Use `gs.groupcountriesquiz` to start a new game! 🌍", inline=False)
        embed.set_footer(text="🔥 Game Services • Thanks for playing!")

    await ctx.send(embed=embed)
    del active_group_country_games[ctx.channel.id]

@bot.command(name="groupscramble", aliases=['gscramble', 'groupunscramble', 'gunscramble', 'scramble', 'unscramble', 'wordgame'])
async def group_scramble_game(ctx):
    """🔤 Start a group word scramble game where everyone can participate"""
    if ctx.channel.id in active_group_scramble_games:
        await ctx.send("🎮 A group scramble game is already active in this channel! Wait for it to finish.")
        return

    # Create participation embed
    embed = discord.Embed(
        title="🔤 Group Word Scramble - Join Now!",
        description="React with <:GsRight:1414593140156792893>  to participate in the word scramble challenge!\n\n**20 seconds to join...**",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="🎯 How to Play", value="Unscramble mixed up words! 🔤", inline=True)
    embed.add_field(name="🏆 Scoring", value="1 point for each word solved! 🥇", inline=True)
    embed.add_field(name="📊 Rounds", value="10 words total 📝", inline=True)
    embed.set_footer(text="🔥 Game Services • React to join!")

    message = await ctx.send(embed=embed)

    # Bot reacts first
    await message.add_reaction("<:GsRight:1414593140156792893> ")

    # Wait 20 seconds for reactions
    await asyncio.sleep(20)

    # Get participants
    updated_message = await ctx.channel.fetch_message(message.id)
    participants = set()
    for reaction in updated_message.reactions:
        if str(reaction.emoji) == "<:GsRight:1414593140156792893> ":
            async for user in reaction.users():
                if not user.bot:
                    participants.add(user.id)

    if not participants:
        await ctx.send("<:GsWrong:1414561861352816753>   No one joined the game! Better luck next time.")
        return

    # Select random word and scramble it
    word = random.choice(SCRAMBLE_WORDS)
    scrambled = scramble_word(word)

    active_group_scramble_games[ctx.channel.id] = {
        'word': word,
        'scrambled': scrambled,
        'players': {},
        'round': 1,
        'max_rounds': 10,
        'start_time': discord.utils.utcnow(),
        'answered_this_round': set(),
        'participants': participants
    }

    embed = discord.Embed(
        title="🔤 Group Word Scramble Started!",
        description=f"**Round 1/10:** Unscramble this word! 🤔\n\n{scrambled.upper()}",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="⏰ Time Limit", value="20 seconds per round ⏱️", inline=True)
    embed.add_field(name="👥 Players", value=f"{len(participants)} joined! 🎯", inline=True)
    embed.add_field(name="💡 Hint", value=f"The word has **{len(word)}** letters", inline=True)
    embed.set_footer(text="🔥 Game Services • Group Word Challenge!")

    await ctx.send(embed=embed)

    # Wait for answers
    await asyncio.sleep(20)  # Give 20 seconds for everyone to answer
    await continue_group_scramble_game(ctx)

def scramble_word(word):
    """Scramble a word by shuffling its letters"""
    word_list = list(word)
    random.shuffle(word_list)
    scrambled = ''.join(word_list)

    # Make sure it's actually scrambled
    attempts = 0
    while scrambled.lower() == word.lower() and attempts < 10:
        random.shuffle(word_list)
        scrambled = ''.join(word_list)
        attempts += 1

    return scrambled

def is_valid_word(word, sequence):
    """Validate that a word is proper for wordbomb (prevents cheating like 'chhhh')"""
    # Basic checks
    if len(word) < 3:
        return False

    # Must contain the sequence
    if sequence.lower() not in word.lower():
        return False

    # Check for excessive repetition (like "chhhh") - STRICT VALIDATION
    char_counts = {}
    for char in word:
        char_counts[char] = char_counts.get(char, 0) + 1

    # For sequences like "ch", prevent words like "chhhh" by limiting consecutive repeats
    sequence_chars = set(sequence.lower())
    for char in sequence_chars:
        if char in char_counts and char_counts[char] > 2:
            # Special case: if the sequence is just repeated chars (like "chhhh"), reject it
            if word.lower().count(char * 3) > 0:  # 3+ consecutive same chars
                return False

    # No single character should appear more than 3 times total
    max_repeats = max(char_counts.values())
    if max_repeats > 3:
        return False

    # Prevent words that are just the sequence repeated
    if word.lower() == sequence.lower() * (len(word) // len(sequence)):
        return False

    # Check for reasonable word structure (vowels and consonants)
    vowels = set('aeiou')
    has_vowel = any(char in vowels for char in word)
    has_consonant = any(char not in vowels and char.isalpha() for char in word)

    # Must have at least one vowel and one consonant for longer words
    if len(word) > 3 and not (has_vowel and has_consonant):
        return False

    # Prevent nonsense words that are just repeated characters
    unique_chars = len(set(word.lower()))
    if unique_chars < 2 and len(word) > 3:  # Words like "aaaa" or "bbbb"
        return False

    return True

async def continue_group_scramble_game(ctx):
    """Continue the group scramble game"""
    if ctx.channel.id not in active_group_scramble_games:
        return

    game = active_group_scramble_games[ctx.channel.id]

    # Show who got the last question right
    if game['answered_this_round']:
        correct_users = [f"<@{uid}>" for uid in game['answered_this_round']]
        embed = discord.Embed(
            title="<:GsRight:1414593140156792893>  Correct Answers!",
            description=f"🎉 **{len(correct_users)}** players got it right!\n{', '.join(correct_users)}",
            color=0xFFC916
        )
        embed.add_field(name="📝 Answer", value=f"**{game['word'].upper()}**", inline=True)
        await ctx.send(embed=embed)
        await asyncio.sleep(2)

    if game['round'] >= game['max_rounds']:
        await end_group_scramble_game(ctx)
        return

    # Clear answered set for new round
    game['answered_this_round'].clear()
    game['round'] += 1

    # Generate new scramble
    word = random.choice(SCRAMBLE_WORDS)
    scrambled = scramble_word(word)
    game['word'] = word
    game['scrambled'] = scrambled

    embed = discord.Embed(
        title="🔤 Group Word Scramble",
        description=f"**Round {game['round']}/10:** Unscramble this word! 🤔\n\n**{scrambled.upper()}**",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="⏰ Time Limit", value="20 seconds ⏱️", inline=True)
    embed.add_field(name="👥 Players", value=f"{len(game['players'])} participating 🎯", inline=True)
    embed.add_field(name="💡 Hint", value=f"The word has **{len(word)}** letters", inline=False)
    embed.set_footer(text="🔥 Game Services • Keep unscrambling!")

    await ctx.send(embed=embed)
    await asyncio.sleep(20)
    await continue_group_scramble_game(ctx)

async def end_group_scramble_game(ctx):
    """End the group scramble game and show leaderboard"""
    if ctx.channel.id not in active_group_scramble_games:
        return

    game = active_group_scramble_games[ctx.channel.id]

    if not game['players']:
        embed = discord.Embed(
            title="🎮 Group Word Scramble Over!",
            description="No one participated! Better luck next time! 😅",
            color=0xFFC916
        )
        embed.set_footer(text="🔥 Game Services • Thanks for playing!")
    else:
        # Sort players by score
        sorted_players = sorted(game['players'].items(), key=lambda x: x[1], reverse=True)

        leaderboard = ""
        for i, (user_id, score) in enumerate(sorted_players, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            percentage = int((score / game['max_rounds']) * 100)
            leaderboard += f"{medal} <@{user_id}>: **{score}/{game['max_rounds']}** ({percentage}%)\n"

        embed = discord.Embed(
            title="🎮 Group Word Scramble Over! Final Leaderboard:",
            description=leaderboard,
            color=0xFFC916,
            timestamp=discord.utils.utcnow()
        )

        if sorted_players:
            winner_id = sorted_players[0][0]
            winner_score = sorted_players[0][1]
            embed.add_field(name="🏆 Winner", value=f"🎉 <@{winner_id}> with **{winner_score}** words!", inline=False)

        embed.add_field(name="📊 Game Stats", value=f"**{len(game['players'])}** total participants\n**{game['max_rounds']}** words scrambled", inline=True)
        embed.add_field(name="🔄 Play Again", value="Use `gs.groupscramble` to start a new game! 🔤", inline=False)
        embed.set_footer(text="🔥 Game Services • Thanks for playing!")

    await ctx.send(embed=embed)
    del active_group_scramble_games[ctx.channel.id]

@bot.command(name="groupwordbomb", aliases=['gwordbomb', 'groupbomb', 'gbomb', 'wordbomb', 'bomb'])
async def group_wordbomb_game(ctx):
    """💣 Start a group word bomb game where everyone can participate"""
    if ctx.channel.id in active_group_wordbomb_games:
        await ctx.send("🎮 A group word bomb game is already active in this channel! Wait for it to finish.")
        return

    # Create participation embed
    embed = discord.Embed(
        title="💣 Group Word Bomb - Join Now!",
        description="React with <:GsRight:1414593140156792893>  to participate in the word bomb challenge!\n\n**20 seconds to join...**",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="🎯 How to Play", value="Make words with given letter sequences! 💣", inline=True)
    embed.add_field(name="🏆 Scoring", value="1 point for each valid word! 🥇", inline=True)
    embed.add_field(name="📊 Rounds", value="10 sequences total 💥", inline=True)
    embed.set_footer(text="🔥 Game Services • React to join!")

    message = await ctx.send(embed=embed)

    # Bot reacts first
    await message.add_reaction("<:GsRight:1414593140156792893> ")

    # Wait 20 seconds for reactions
    await asyncio.sleep(20)

    # Get participants
    updated_message = await ctx.channel.fetch_message(message.id)
    participants = set()
    for reaction in updated_message.reactions:
        if str(reaction.emoji) == "<:GsRight:1414593140156792893> ":
            async for user in reaction.users():
                if not user.bot:
                    participants.add(user.id)

    if not participants:
        await ctx.send("<:GsWrong:1414561861352816753>   No one joined the game! Better luck next time.")
        return

    # Select random letter sequence
    sequence = random.choice(WORDBOMB_SEQUENCES)

    active_group_wordbomb_games[ctx.channel.id] = {
        'sequence': sequence,
        'players': {},
        'round': 1,
        'max_rounds': 10,
        'start_time': discord.utils.utcnow(),
        'answered_this_round': set(),
        'used_words': set(),
        'participants': participants
    }

    embed = discord.Embed(
        title="💣 Group Word Bomb Started!",
        description=f"**Round 1/10:** Make words containing! 💥\n\n**{sequence.upper()}**",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="⏰ Time Limit", value="25 seconds per round ⏱️", inline=True)
    embed.add_field(name="👥 Players", value=f"{len(participants)} joined! 🎯", inline=True)
    embed.add_field(name="📋 Rules", value="At least 3 letters, no repeats!", inline=True)
    embed.set_footer(text="🔥 Game Services • Group Word Bomb!")

    await ctx.send(embed=embed)

    # Wait for answers
    await asyncio.sleep(25)  # Give 25 seconds for everyone to answer
    await continue_group_wordbomb_game(ctx)

async def continue_group_wordbomb_game(ctx):
    """Continue the group word bomb game"""
    if ctx.channel.id not in active_group_wordbomb_games:
        return

    game = active_group_wordbomb_games[ctx.channel.id]

    # Show who got words this round
    if game['answered_this_round']:
        correct_users = [f"<@{uid}>" for uid in game['answered_this_round']]
        embed = discord.Embed(
            title="💥 Words Found!",
            description=f"🎉 **{len(correct_users)}** players found valid words!\n{', '.join(correct_users)}",
            color=0xFFC916
        )
        embed.add_field(name="🔤 Sequence", value=f"**{game['sequence'].upper()}**", inline=True)
        embed.add_field(name="📊 Words Found", value=f"**{len(game['used_words'])}** total", inline=True)
        await ctx.send(embed=embed)
        await asyncio.sleep(2)

    if game['round'] >= game['max_rounds']:
        await end_group_wordbomb_game(ctx)
        return

    # Clear answered set for new round but keep used words
    game['answered_this_round'].clear()
    game['round'] += 1

    # Generate new sequence
    sequence = random.choice(WORDBOMB_SEQUENCES)
    game['sequence'] = sequence
    game['used_words'].clear()  # Reset used words for new sequence

    embed = discord.Embed(
        title="💣 Group Word Bomb",
        description=f"**Round {game['round']}/10:** Make words containing! 💥\n\n**{sequence.upper()}**",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="⏰ Time Limit", value="25 seconds ⏱️", inline=True)
    embed.add_field(name="👥 Players", value=f"{len(game['players'])} participating 🎯", inline=True)
    embed.add_field(name="📋 Remember", value="At least 3 letters, no repeats!", inline=False)
    embed.set_footer(text="🔥 Game Services • Keep bombing!")

    await ctx.send(embed=embed)
    await asyncio.sleep(25)
    await continue_group_wordbomb_game(ctx)

async def end_group_wordbomb_game(ctx):
    """End the group word bomb game and show leaderboard"""
    if ctx.channel.id not in active_group_wordbomb_games:
        return

    game = active_group_wordbomb_games[ctx.channel.id]

    if not game['players']:
        embed = discord.Embed(
            title="🎮 Group Word Bomb Over!",
            description="No one participated! Better luck next time! 😅",
            color=0xFFC916
        )
        embed.set_footer(text="🔥 Game Services • Thanks for playing!")
    else:
        # Sort players by score
        sorted_players = sorted(game['players'].items(), key=lambda x: x[1], reverse=True)

        leaderboard = ""
        for i, (user_id, score) in enumerate(sorted_players, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            leaderboard += f"{medal} <@{user_id}>: **{score}** words found\n"

        embed = discord.Embed(
            title="🎮 Group Word Bomb Over! Final Leaderboard:",
            description=leaderboard,
            color=0xFFC916,
            timestamp=discord.utils.utcnow()
        )

        if sorted_players:
            winner_id = sorted_players[0][0]
            winner_score = sorted_players[0][1]
            embed.add_field(name="🏆 Winner", value=f"🎉 <@{winner_id}> with **{winner_score}** words!", inline=False)

        embed.add_field(name="📊 Game Stats", value=f"**{len(game['players'])}** total participants\n**{game['max_rounds']}** sequences bombed", inline=True)
        embed.add_field(name="🔄 Play Again", value="Use `gs.groupwordbomb` to start a new game! 💣", inline=False)
        embed.set_footer(text="🔥 Game Services • Thanks for playing!")

    await ctx.send(embed=embed)
    del active_group_wordbomb_games[ctx.channel.id]

@bot.command(name="c", aliases=["calc", "calculator"])
async def calculate(ctx, *, expression: str):
    """🧮 Calculator feature - Calculate math expressions"""
    try:
        # Replace common symbols with Python operators
        expression = expression.replace('x', '*').replace('X', '*').replace('÷', '/').replace('×', '*')

        # Remove spaces
        expression = expression.replace(' ', '')

        # Basic validation - only allow numbers, operators, and parentheses
        allowed_chars = set('0123456789+-*/.,()')
        if not all(c in allowed_chars for c in expression):
            await ctx.send("<:GsWrong:1414561861352816753>   Invalid characters in expression. Use only numbers and operators (+, -, *, /, x)")
            return

        # Evaluate the expression safely
        try:
            result = eval(expression)

            # Format result nicely
            if isinstance(result, float):
                if result.is_integer():
                    result = int(result)
                else:
                    result = round(result, 6)  # Round to 6 decimal places

            embed = discord.Embed(
                title="🧮 Calculator Result",
                color=0xFFC916,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="📝 Expression", value=f"`{expression}`", inline=False)
            embed.add_field(name="🎯 Result", value=f"**{result}**", inline=False)
            embed.add_field(name="💡 Usage", value="Try: `gs.c 4+11`, `gs.c 4/11`, `gs.c 4x11`, `gs.c (5+3)*2`", inline=False)
            embed.set_footer(text="🔥 Game Services • Calculator")

            await ctx.send(embed=embed)

        except ZeroDivisionError:
            embed = discord.Embed(
                title="<:GsWrong:1414561861352816753>   Calculation Error",
                description="Cannot divide by zero!",
                color=0xFFC916
            )
            embed.add_field(name="📝 Expression", value=f"`{expression}`", inline=False)
            embed.set_footer(text="🔥 Game Services • Calculator")
            await ctx.send(embed=embed)

        except Exception as e:
            embed = discord.Embed(
                title="<:GsWrong:1414561861352816753>   Calculation Error",
                description="Invalid mathematical expression!",
                color=0xFFC916
            )
            embed.add_field(name="📝 Expression", value=f"`{expression}`", inline=False)
            embed.add_field(name="💡 Tip", value="Make sure your expression is valid. Example: `gs.c 4+11`", inline=False)
            embed.set_footer(text="🔥 Game Services • Calculator")
            await ctx.send(embed=embed)

    except Exception as e:
        logger.error(f"Error in calculator command: {e}")
        await ctx.send("<:GsWrong:1414561861352816753>   An error occurred while calculating the expression.")

@bot.command(name="m", aliases=["messages", "msgs"])
async def show_messages(ctx, user: discord.Member = None):
    """📊 Show message statistics for a user"""
    target_user = user or ctx.author
    user_id = target_user.id

    if user_id not in user_message_counts:
        user_message_counts[user_id] = {'daily': 0, 'weekly': 0, 'monthly': 0, 'last_message': discord.utils.utcnow()}

    data = user_message_counts[user_id]

    embed = discord.Embed(title="📊 Message Statistics", color=0xFFC916, timestamp=discord.utils.utcnow())
    embed.set_thumbnail(url=target_user.display_avatar.url)

    embed.add_field(name="📅 Daily Messages", value=f"**{data['daily']}** messages 📝", inline=True)
    embed.add_field(name="📄 Weekly Messages", value=f"**{data['weekly']}** messages 📚", inline=True)
    embed.add_field(name="📚 Monthly Messages", value=f"**{data['monthly']}** messages 📖", inline=True)

    if data['last_message']:
        last_msg_time = data['last_message']
        time_ago = discord.utils.utcnow() - last_msg_time
        if time_ago.days > 0:
            last_msg_str = f"{time_ago.days} days ago 📅"
        elif time_ago.seconds > 3600:
            last_msg_str = f"{time_ago.seconds // 3600} hours ago ⏰"
        elif time_ago.seconds > 60:
            last_msg_str = f"{time_ago.seconds // 60} minutes ago ⏱️"
        else:
            last_msg_str = "Just now 🕐"

        embed.add_field(name="⏰ Last Message", value=last_msg_str, inline=True)

    embed.add_field(name="👤 User", value=f"{target_user.mention} 🎯", inline=False)
    embed.set_footer(text="🔥 Game Services • Message Tracking System")

    await ctx.send(embed=embed)

@bot.command(name="msgtop", aliases=["messageleaderboard", "msgleaderboard"])
async def message_leaderboard(ctx, period: str = "daily"):
    """🏆 Show top message senders"""
    if period.lower() not in ['daily', 'weekly', 'monthly']:
        embed = discord.Embed(
            title="<:GsWrong:1414561861352816753>   Invalid Period",
            description="Please specify: `daily`, `weekly`, or `monthly` 📅",
            color=0xFFC916
        )
        await ctx.send(embed=embed)
        return

    if not user_message_counts:
        embed = discord.Embed(
            title=f"📊 {period.title()} Message Leaderboard",
            description="No message data available yet. 📊",
            color=0xFFC916
        )
        await ctx.send(embed=embed)
        return

    # Sort by the specified period
    leaderboard = []
    for user_id, data in user_message_counts.items():
        count = data[period.lower()]
        if count > 0:
            leaderboard.append((user_id, count))

    leaderboard.sort(key=lambda x: x[1], reverse=True)
    leaderboard = leaderboard[:10]  # Top 10

    embed = discord.Embed(
        title=f"🏆 {period.title()} Message Leaderboard",
        description=f"Top 10 most active members ({period.lower()}) 💬",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )

    leaderboard_text = ""
    for i, (user_id, count) in enumerate(leaderboard, 1):
        user = bot.get_user(user_id)
        if user:
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
            leaderboard_text += f"{medal} {user.mention}: **{count}** messages 📝\n"

    if leaderboard_text:
        embed.add_field(name="📋 Rankings", value=leaderboard_text, inline=False)
    else:
        embed.add_field(name="📋 Rankings", value="No active users found 😴", inline=False)

    embed.add_field(name="🔄 Refresh", value=f"Use `gs.msgtop {period}` to update 📊", inline=False)
    embed.set_footer(text="🔥 Game Services • Message Tracking System")
    await ctx.send(embed=embed)

# Moderation commands and views (kept from original code)
class ReportConfirmationView(discord.ui.View):
    def __init__(self, user, reporter, reason, report_channel, report_embed):
        super().__init__(timeout=300)
        self.user = user
        self.reporter = reporter
        self.reason = reason
        self.report_channel = report_channel
        self.report_embed = report_embed
        self.confirmed = None

    @discord.ui.button(label="Submit Report", style=discord.ButtonStyle.danger, emoji="🚨")
    async def submit_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.reporter:
            try:
                await interaction.response.send_message("Only the reporter can submit this report.", ephemeral=True)
            except:
                pass
            return

        try:
            await interaction.response.defer()

            self.confirmed = True

            # Send to report channel with staff moderation view
            staff_view = StaffModerationView(self.user, self.reporter, self.reason)
            await self.report_channel.send(embed=self.report_embed, view=staff_view)

            # Confirmation to reporter
            confirm_embed = discord.Embed(
                title="<:GsRight:1414593140156792893>  Report Submitted Successfully",
                description=f"Your report against {self.user.mention} has been sent to the moderation team.",
                color=0xFFC916,
                timestamp=discord.utils.utcnow()
            )
            confirm_embed.add_field(name="📋 Reason", value=self.reason, inline=False)
            confirm_embed.add_field(name="⏱️ Next Steps",
                                   value="Our moderation team will review this report. Thank you for helping keep our community safe!",
                                   inline=False)
            confirm_embed.set_footer(text=f"🔥 Game Services Report System • Report ID: {interaction.message.id}")

            try:
                await interaction.edit_original_response(embed=confirm_embed, view=None)
            except discord.errors.NotFound:
                await interaction.followup.send(embed=confirm_embed, ephemeral=True)
            self.stop()
        except Exception as e:
            logger.error(f"Error submitting report: {e}")
            try:
                await interaction.followup.send("Report submitted successfully!", ephemeral=True)
            except:
                pass

    @discord.ui.button(label="Cancel Report", style=discord.ButtonStyle.secondary, emoji="<:GsWrong:1414561861352816753>  ")
    async def cancel_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.reporter:
            try:
                await interaction.response.send_message("Only the reporter can cancel this report.", ephemeral=True)
            except:
                pass
            return

        try:
            await interaction.response.defer()

            self.confirmed = False
            cancel_embed = discord.Embed(
                title="<:GsWrong:1414561861352816753>   Report Cancelled",
                description="Your report has been cancelled and will not be sent to the moderation team.",
                color=0x808080
            )
            try:
                await interaction.edit_original_response(embed=cancel_embed, view=None)
            except discord.errors.NotFound:
                await interaction.followup.send(embed=cancel_embed, ephemeral=True)
            self.stop()
        except Exception as e:
            logger.error(f"Error cancelling report: {e}")
            try:
                await interaction.followup.send("Report cancelled.", ephemeral=True)
            except:
                pass

class StaffModerationView(discord.ui.View):
    def __init__(self, reported_user, reporter, reason):
        super().__init__(timeout=3600)  # 1 hour timeout
        self.reported_user = reported_user
        self.reporter = reporter
        self.reason = reason

    @discord.ui.button(label="Approve Report", style=discord.ButtonStyle.success, emoji="<:GsRight:1414593140156792893>")
    async def approve_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.kick_members:
            try:
                await interaction.response.send_message("You don't have permission to moderate reports.", ephemeral=True)
            except:
                pass
            return

        try:
            # Create moderation action view
            mod_view = QuickModerationView(self.reported_user, interaction.user, self.reason)

            embed = discord.Embed(
                title="<:GsRight:1414593140156792893>  Report Approved - Choose Action",
                description=f"Report against {self.reported_user.mention} has been approved by {interaction.user.mention}",
                color=0xFFC916,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="📋 Original Reason", value=self.reason, inline=False)
            embed.add_field(name="👤 Reporter", value=self.reporter.mention, inline=True)
            embed.add_field(name="👮 Reviewing Staff", value=interaction.user.mention, inline=True)
            embed.set_footer(text="🔥 Game Services Moderation System")

            await interaction.response.edit_message(embed=embed, view=mod_view)
        except Exception as e:
            logger.error(f"Error approving report: {e}")
            try:
                await interaction.response.defer()
                await interaction.followup.send("Report approved successfully!", ephemeral=True)
            except:
                pass

    @discord.ui.button(label="Deny Report", style=discord.ButtonStyle.danger, emoji="<:GsWrong:1414561861352816753>  ")
    async def deny_report(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.kick_members:
            try:
                await interaction.response.send_message("You don't have permission to moderate reports.", ephemeral=True)
            except:
                pass
            return

        try:
            embed = discord.Embed(
                title="<:GsWrong:1414561861352816753>   Report Denied",
                description=f"Report against {self.reported_user.mention} has been denied by {interaction.user.mention}",
                color=0x808080,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="📋 Original Reason", value=self.reason, inline=False)
            embed.add_field(name="👤 Reporter", value=self.reporter.mention, inline=True)
            embed.add_field(name="👮 Reviewing Staff", value=interaction.user.mention, inline=True)
            embed.add_field(name="📝 Status", value="No action taken - Report deemed invalid", inline=False)
            embed.set_footer(text="🔥 Game Services Moderation System")

            await interaction.response.edit_message(embed=embed, view=None)
        except Exception as e:
            logger.error(f"Error denying report: {e}")
            try:
                await interaction.response.defer()
                await interaction.followup.send("Report denied successfully!", ephemeral=True)
            except:
                pass

class QuickModerationView(discord.ui.View):
    def __init__(self, user, moderator, reason, reporter=None):
        super().__init__(timeout=1800)  # 30 minutes timeout
        self.user = user
        self.moderator = moderator
        self.reason = f"Report violation: {reason}"
        self.reporter = reporter

    @discord.ui.button(label="Warn", style=discord.ButtonStyle.secondary, emoji="⚠️")
    async def quick_warn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.execute_quick_action(interaction, "warn")

    @discord.ui.button(label="Mute 5m", style=discord.ButtonStyle.primary, emoji="🔇")
    async def quick_mute_5m(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.execute_quick_action(interaction, "mute", "5m")

    @discord.ui.button(label="Mute 10m", style=discord.ButtonStyle.primary, emoji="🔇")
    async def quick_mute_10m(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.execute_quick_action(interaction, "mute", "10m")

    @discord.ui.button(label="Mute 20m", style=discord.ButtonStyle.primary, emoji="🔇")
    async def quick_mute_20m(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.execute_quick_action(interaction, "mute", "20m")

    @discord.ui.button(label="Kick", style=discord.ButtonStyle.danger, emoji="👢")
    async def quick_kick(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.execute_quick_action(interaction, "kick")

    async def execute_quick_action(self, interaction, action_type, duration=None):
        try:
            if action_type == "warn":
                action_id = mod_db.add_moderation_action(
                    user_id=self.user.id,
                    moderator_id=self.moderator.id,
                    server_id=interaction.guild.id,
                    action_type="warn",
                    reason=self.reason
                )

            elif action_type == "mute":
                duration_minutes = parse_duration(duration)
                if duration_minutes and duration_minutes > 0:
                    # Discord timeout max is 28 days, ensure we don't exceed it
                    max_minutes = 28 * 24 * 60  # 28 days in minutes
                    duration_minutes = min(duration_minutes, max_minutes)
                    timeout_until = discord.utils.utcnow() + timedelta(minutes=duration_minutes)
                    await self.user.timeout(timeout_until, reason=self.reason)
                else:
                    # Default to 10 minutes if parsing fails
                    timeout_until = discord.utils.utcnow() + timedelta(minutes=10)
                    await self.user.timeout(timeout_until, reason=self.reason)
                    duration_minutes = 10

                action_id = mod_db.add_moderation_action(
                    user_id=self.user.id,
                    moderator_id=self.moderator.id,
                    server_id=interaction.guild.id,
                    action_type="mute",
                    reason=self.reason,
                    duration_minutes=duration_minutes
                )

            elif action_type == "kick":
                await interaction.guild.kick(self.user, reason=self.reason)
                action_id = mod_db.add_moderation_action(
                    user_id=self.user.id,
                    moderator_id=self.moderator.id,
                    server_id=interaction.guild.id,
                    action_type="kick",
                    reason=self.reason
                )

            # Send DM to user
            dm_success = await self.send_dm_notification(action_type, duration)

            # Create success embed
            if action_type == "warn": title = "⚠️ Warning Issued"
            elif action_type == "mute": title = f"🔇 User Muted for {duration}"
            elif action_type == "kick": title = "👢 User Kicked"

            embed = discord.Embed(
                title=f"{title} Successfully",
                color=0xFFC916,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="👤 User", value=f"{self.user.mention} ({self.user})", inline=False)
            embed.add_field(name="👮 Moderator", value=f"{self.moderator.mention}", inline=True)
            embed.add_field(name="📋 Reason", value=self.reason, inline=False)
            embed.add_field(name="🆔 Action ID", value=f"#{action_id}", inline=True)
            embed.add_field(name="💬 DM Status", value="<:GsRight:1414593140156792893>  Sent" if dm_success else "<:GsWrong:1414561861352816753>   Failed", inline=True)
            embed.add_field(name="📊 Database", value="<:GsRight:1414593140156792893>  Logged", inline=True)
            if self.reporter:
                embed.add_field(name="👤 Original Reporter", value=self.reporter.mention, inline=True)
            embed.set_footer(text="🔥 Game Services Moderation System")

            await interaction.edit_original_response(embed=embed, view=None)

        except Exception as e:
            logger.error(f"Error executing quick action {action_type}: {e}")
            await interaction.response.send_message(f"Error executing {action_type}: {str(e)}", ephemeral=True)

    async def send_dm_notification(self, action_type, duration=None):
        """Send DM notification to the user and return success status"""
        try:
            if action_type == "warn":
                title = "⚠️ You Have Been Warned"
                description = "You have been warned in the server"
            elif action_type == "mute":
                title = "🔇 You Have Been Muted"
                description = "You have been muted from the server"
            elif action_type == "kick":
                title = "👢 You Have Been Kicked"
                description = "You have been kicked from the server"
            else:
                title = f"You have been {action_type}"
                description = f"You have been {action_type} from the server"

            embed = discord.Embed(
                title=title,
                description=description,
                color=0xFFC916,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="🏠 Server", value=f"{self.moderator.guild.name} (Roblox)", inline=True)
            embed.add_field(name="👤 Moderator", value=f"{self.moderator} (on study arc)", inline=True)
            if duration:
                embed.add_field(name="⏱️ Duration", value=duration, inline=True)
            embed.add_field(name="📋 Reason", value=self.reason, inline=False)
            embed.add_field(
                name="🚨 Appeal Process",
                value="If you believe this action was taken in error, you may appeal this decision in our appeals server:\n🔗 https://discord.gg/ahharETNNR",
                inline=False
            )
            embed.set_footer(text="🔥 Game Services Moderation System • Today at " + discord.utils.utcnow().strftime("%I:%M %p"))

            await self.user.send(embed=embed)
            return True
        except Exception as e:
            logger.error(f"Error sending DM to {self.user}: {e}")
            return False

# Confirmation View for moderation actions
class ConfirmationView(discord.ui.View):
    def __init__(self, action_type, user, moderator, reason, duration=None):
        super().__init__(timeout=300)
        self.action_type = action_type
        self.user = user
        self.moderator = moderator
        self.reason = reason
        self.duration = duration

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, emoji="<:GsRight:1414593140156792893> ")
    async def confirm_action(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.moderator:
            try:
                await interaction.response.send_message("Only the moderator can confirm this action.", ephemeral=True)
            except:
                pass
            return

        try:
            # Acknowledge the interaction first
            await interaction.response.defer()

            # Check bot permissions first
            bot_member = interaction.guild.get_member(interaction.client.user.id)
            if not bot_member:
                await interaction.followup.send("<:GsWrong:1414561861352816753>   Error: Bot member not found in guild.", ephemeral=True)
                return

            # Check if bot can perform the action
            permission_check = self.check_bot_permissions(bot_member, interaction.guild)
            if not permission_check["success"]:
                await interaction.followup.send(f"<:GsWrong:1414561861352816753>   **Bot Missing Permissions**\n{permission_check['error']}", ephemeral=True)
                return

            # Check role hierarchy
            if self.user.top_role >= bot_member.top_role:
                await interaction.followup.send(f"<:GsWrong:1414561861352816753>   **Role Hierarchy Error**\nI cannot {self.action_type} {self.user.mention} because their role is equal to or higher than mine.\n\n**Solution:** Move my role above theirs in Server Settings → Roles.", ephemeral=True)
                return

            if self.action_type == "warn":
                action_id = mod_db.add_moderation_action(
                    user_id=self.user.id,
                    moderator_id=self.moderator.id,
                    server_id=interaction.guild.id,
                    action_type="warn",
                    reason=self.reason
                )

            elif self.action_type == "mute":
                duration_minutes = parse_duration(self.duration)
                if duration_minutes and duration_minutes > 0:
                    # Discord timeout max is 28 days, ensure we don't exceed it
                    max_minutes = 28 * 24 * 60  # 28 days in minutes
                    duration_minutes = min(duration_minutes, max_minutes)
                    timeout_until = discord.utils.utcnow() + timedelta(minutes=duration_minutes)
                    try:
                        await self.user.timeout(timeout_until, reason=self.reason)
                    except discord.Forbidden as e:
                        await interaction.followup.send(f"<:GsWrong:1414561861352816753>   **Permission Error**: Cannot mute {self.user.mention}\n\n**Possible causes:**\n• Bot missing `Moderate Members` permission\n• Target user has higher role than bot\n• Target user is server owner\n\n**Error details:** {str(e)}", ephemeral=True)
                        return
                    except Exception as e:
                        await interaction.followup.send(f"<:GsWrong:1414561861352816753>   **Mute Failed**: {str(e)}", ephemeral=True)
                        return
                else:
                    # Default to 10 minutes if parsing fails
                    timeout_until = discord.utils.utcnow() + timedelta(minutes=10)
                    try:
                        await self.user.timeout(timeout_until, reason=self.reason)
                    except discord.Forbidden as e:
                        await interaction.followup.send(f"<:GsWrong:1414561861352816753>   **Permission Error**: Cannot mute {self.user.mention}\n\n**Possible causes:**\n• Bot missing `Moderate Members` permission\n• Target user has higher role than bot\n• Target user is server owner\n\n**Error details:** {str(e)}", ephemeral=True)
                        return
                    except Exception as e:
                        await interaction.followup.send(f"<:GsWrong:1414561861352816753>   **Mute Failed**: {str(e)}", ephemeral=True)
                        return
                    duration_minutes = 10

                action_id = mod_db.add_moderation_action(
                    user_id=self.user.id,
                    moderator_id=self.moderator.id,
                    server_id=interaction.guild.id,
                    action_type="mute",
                    reason=self.reason,
                    duration_minutes=duration_minutes
                )

            elif self.action_type == "kick":
                try:
                    await interaction.guild.kick(self.user, reason=self.reason)
                except discord.Forbidden as e:
                    await interaction.followup.send(f"<:GsWrong:1414561861352816753>   **Permission Error**: Cannot kick {self.user.mention}\n\n**Possible causes:**\n• Bot missing `Kick Members` permission\n• Target user has higher role than bot\n• Target user is server owner\n\n**Error details:** {str(e)}", ephemeral=True)
                    return
                except Exception as e:
                    await interaction.followup.send(f"<:GsWrong:1414561861352816753>   **Kick Failed**: {str(e)}", ephemeral=True)
                    return
                action_id = mod_db.add_moderation_action(
                    user_id=self.user.id,
                    moderator_id=self.moderator.id,
                    server_id=interaction.guild.id,
                    action_type="kick",
                    reason=self.reason
                )

            elif self.action_type == "ban":
                duration_minutes = None
                if self.duration and self.duration != "permanent":
                    duration_minutes = parse_duration(self.duration)

                try:
                    await interaction.guild.ban(self.user, reason=self.reason)
                except discord.Forbidden as e:
                    await interaction.followup.send(f"<:GsWrong:1414561861352816753>   **Permission Error**: Cannot ban {self.user.mention}\n\n**Possible causes:**\n• Bot missing `Ban Members` permission\n• Target user has higher role than bot\n• Target user is server owner\n\n**Error details:** {str(e)}", ephemeral=True)
                    return
                except Exception as e:
                    await interaction.followup.send(f"<:GsWrong:1414561861352816753>   **Ban Failed**: {str(e)}", ephemeral=True)
                    return
                action_id = mod_db.add_moderation_action(
                    user_id=self.user.id,
                    moderator_id=self.moderator.id,
                    server_id=interaction.guild.id,
                    action_type="ban",
                    reason=self.reason,
                    duration_minutes=duration_minutes
                )

            elif self.action_type == "mutewarn":
                # First apply the warning
                warn_action_id = mod_db.add_moderation_action(
                    user_id=self.user.id,
                    moderator_id=self.moderator.id,
                    server_id=interaction.guild.id,
                    action_type="warn",
                    reason=self.reason
                )

                # Then apply the mute
                duration_minutes = parse_duration(self.duration)
                if duration_minutes and duration_minutes > 0:
                    # Discord timeout max is 28 days, ensure we don't exceed it
                    max_minutes = 28 * 24 * 60  # 28 days in minutes
                    duration_minutes = min(duration_minutes, max_minutes)
                    timeout_until = discord.utils.utcnow() + timedelta(minutes=duration_minutes)
                    try:
                        await self.user.timeout(timeout_until, reason=self.reason)
                    except discord.Forbidden as e:
                        await interaction.followup.send(f"<:GsWrong:1414561861352816753>   **Permission Error**: Cannot mute {self.user.mention}\n\n**Possible causes:**\n• Bot missing `Moderate Members` permission\n• Target user has higher role than bot\n• Target user is server owner\n\n**Error details:** {str(e)}", ephemeral=True)
                        return
                    except Exception as e:
                        await interaction.followup.send(f"<:GsWrong:1414561861352816753>   **Mute Failed**: {str(e)}", ephemeral=True)
                        return
                else:
                    # Default to 10 minutes if parsing fails
                    timeout_until = discord.utils.utcnow() + timedelta(minutes=10)
                    try:
                        await self.user.timeout(timeout_until, reason=self.reason)
                    except discord.Forbidden as e:
                        await interaction.followup.send(f"<:GsWrong:1414561861352816753>   **Permission Error**: Cannot mute {self.user.mention}\n\n**Possible causes:**\n• Bot missing `Moderate Members` permission\n• Target user has higher role than bot\n• Target user is server owner\n\n**Error details:** {str(e)}", ephemeral=True)
                        return
                    except Exception as e:
                        await interaction.followup.send(f"<:GsWrong:1414561861352816753>   **Mute Failed**: {str(e)}", ephemeral=True)
                        return
                    duration_minutes = 10

                action_id = mod_db.add_moderation_action(
                    user_id=self.user.id,
                    moderator_id=self.moderator.id,
                    server_id=interaction.guild.id,
                    action_type="mute",
                    reason=self.reason,
                    duration_minutes=duration_minutes
                )

            # Send DM to user
            dm_success = await self.send_dm_notification()

            # Create success embed
            action_titles = {
                "warn": "⚠️ Warning Issued",
                "mute": f"🔇 User Muted for {self.duration}",
                "kick": "👢 User Kicked",
                "ban": f"🔨 User Banned ({self.duration})",
                "mutewarn": f"⚠️🔇 User Warned + Muted for {self.duration}"
            }

            embed = discord.Embed(
                title=f"{action_titles[self.action_type]} Successfully",
                color=0xFFC916,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="👤 User", value=f"{self.user.mention} ({self.user})", inline=False)
            embed.add_field(name="👮 Moderator", value=f"{self.moderator.mention}", inline=True)
            embed.add_field(name="🏠 Server", value=f"{interaction.guild.name}", inline=True)
            embed.add_field(name="📋 Reason", value=self.reason, inline=False)
            embed.add_field(name="🆔 Action ID", value=f"#{action_id}", inline=True)
            embed.add_field(name="💬 DM Status", value="<:GsRight:1414593140156792893>  Sent" if dm_success else "<:GsWrong:1414561861352816753>   Failed", inline=True)
            embed.add_field(name="📊 Database", value="<:GsRight:1414593140156792893>  Logged", inline=True)

            if self.duration and self.action_type in ["mute", "ban", "mutewarn"]:
                embed.add_field(name="⏱️ Duration", value=self.duration, inline=True)

            embed.set_footer(text="🔥 Game Services Moderation System")

            try:
                await interaction.edit_original_response(embed=embed, view=None)
            except discord.errors.NotFound:
                # If edit fails, try to send a new message
                await interaction.followup.send(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f"Error executing {self.action_type}: {e}")
            try:
                await interaction.followup.send(f"<:GsWrong:1414561861352816753>   **Unexpected Error**\nFailed to execute {self.action_type}: {str(e)}", ephemeral=True)
            except:
                pass

    def check_bot_permissions(self, bot_member, guild):
        """Check if bot has required permissions for the action"""
        required_perms = {
            "warn": ["send_messages"],
            "mute": ["moderate_members"],
            "kick": ["kick_members"],
            "ban": ["ban_members"],
            "mutewarn": ["moderate_members"]
        }

        permissions_needed = required_perms.get(self.action_type, [])
        missing_perms = []

        for perm in permissions_needed:
            if not getattr(bot_member.guild_permissions, perm, False):
                missing_perms.append(perm.replace('_', ' ').title())

        if missing_perms:
            perm_list = ', '.join(missing_perms)
            return {
                "success": False,
                "error": f"I'm missing these permissions: **{perm_list}**\n\n**How to fix:**\n1. Go to Server Settings → Roles\n2. Find my role and edit permissions\n3. Enable the missing permissions above"
            }

        return {"success": True, "error": None}

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="<:GsWrong:1414561861352816753>  ")
    async def cancel_action(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.moderator:
            try:
                await interaction.response.send_message("Only the moderator can cancel this action.", ephemeral=True)
            except:
                pass
            return

        try:
            await interaction.response.defer()

            embed = discord.Embed(
                title="<:GsWrong:1414561861352816753>   Action Cancelled",
                description=f"The {self.action_type} action has been cancelled.",
                color=0x808080
            )
            embed.set_footer(text="🔥 Game Services Moderation System")

            try:
                await interaction.edit_original_response(embed=embed, view=None)
            except discord.errors.NotFound:
                await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.error(f"Error cancelling action: {e}")
            try:
                await interaction.followup.send("<:GsWrong:1414561861352816753>   Error occurred while cancelling, but action was not executed.", ephemeral=True)
            except:
                pass

    async def send_dm_notification(self):
        """Send DM notification to the user and return success status"""
        try:
            action_titles = {
                "warn": "⚠️ You Have Been Warned",
                "mute": "🔇 You Have Been Muted",
                "kick": "👢 You Have Been Kicked",
                "ban": "🔨 You Have Been Banned",
                "mutewarn": "⚠️🔇 You Have Been Warned + Muted"
            }

            action_descriptions = {
                "warn": "You have been warned in the server",
                "mute": "You have been muted from the server",
                "kick": "You have been kicked from the server",
                "ban": "You have been banned from the server",
                "mutewarn": "You have been warned and muted from the server"
            }

            embed = discord.Embed(
                title=action_titles[self.action_type],
                description=action_descriptions[self.action_type],
                color=0xFFC916,
                timestamp=discord.utils.utcnow()
            )
            embed.add_field(name="🏠 Server", value=f"{self.moderator.guild.name}", inline=True)
            embed.add_field(name="👤 Moderator", value=f"{self.moderator}", inline=True)

            if self.duration and self.action_type in ["mute", "ban", "mutewarn"]:
                embed.add_field(name="⏱️ Duration", value=self.duration, inline=True)

            embed.add_field(name="📋 Reason", value=self.reason, inline=False)
            embed.add_field(
                name="🚨 Appeal Process",
                value="If you believe this action was taken in error, you may appeal this decision in our appeals server:\n🔗 https://discord.gg/ahharETNNR",
                inline=False
            )
            embed.set_footer(text="🔥 Game Services Moderation System")

            await self.user.send(embed=embed)
            return True
        except Exception as e:
            logger.error(f"Error sending DM to {self.user}: {e}")
            return False

# Utility functions
def parse_duration(duration_str):
    """Parse duration string like '1h', '30m', '2d' into minutes"""
    if not duration_str:
        return 10  # Default 10 minutes

    duration_str = duration_str.lower().strip()
    if duration_str == "permanent":
        return None

    # Extract number and unit
    match = re.match(r'(\d+)([mhd])', duration_str)
    if not match:
        return 10  # Default 10 minutes

    number, unit = match.groups()
    number = int(number)

    # Ensure positive number
    if number <= 0:
        return 10

    if unit == 'm':
        return number
    elif unit == 'h':
        return number * 60
    elif unit == 'd':
        return number * 24 * 60

    return 10

def format_duration(minutes):
    """Format minutes into readable duration"""
    if not minutes:
        return "Permanent"

    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    elif minutes < 1440:  # Less than a day
        hours = minutes // 60
        remaining_minutes = minutes % 60
        if remaining_minutes:
            return f"{hours} hour{'s' if hours != 1 else ''} {remaining_minutes} minute{'s' if remaining_minutes != 1 else ''}"
        else:
            return f"{hours} hour{'s' if hours != 1 else ''}"
    else:  # Days
        days = minutes // 1440
        remaining_hours = (minutes % 1440) // 60
        if remaining_hours:
            return f"{days} day{'s' if days != 1 else ''} {remaining_hours} hour{'s' if remaining_hours != 1 else ''}"
        else:
            return f"{days} day{'s' if days != 1 else ''}"

# Moderation commands
@bot.command(name="warn", aliases=["w"])
async def warn_user(ctx, user: discord.Member, *, reason="No reason provided"):
    """Warn a user with 2-step confirmation"""
    if not ctx.author.guild_permissions.kick_members:
        await ctx.send("You don't have permission to warn users.")
        return

    if user.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        await ctx.send("You cannot warn users with equal or higher roles.")
        return

    # Create confirmation embed
    embed = discord.Embed(
        title="⚠️ Confirm Warning",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="User", value=f"{user.mention} ({user})", inline=False)
    embed.add_field(name="Moderator", value=f"{ctx.author.mention}", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text="🔥 Click Confirm to proceed or Cancel to abort")

    view = ConfirmationView("warn", user, ctx.author, reason)
    await ctx.send(embed=embed, view=view)

@bot.command(name="mute", aliases=["timeout"])
async def mute_user(ctx, user: discord.Member, duration="1h", *, reason="No reason provided"):
    """Mute a user with 2-step confirmation"""
    if not ctx.author.guild_permissions.moderate_members:
        await ctx.send("You don't have permission to mute users.")
        return

    if user.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        await ctx.send("You cannot mute users with equal or higher roles.")
        return

    # Create confirmation embed
    embed = discord.Embed(
        title="🔇 Confirm Mute",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="User", value=f"{user.mention} ({user})", inline=False)
    embed.add_field(name="Moderator", value=f"{ctx.author.mention}", inline=True)
    embed.add_field(name="Duration", value=duration, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text="🔥 Click Confirm to proceed or Cancel to abort")

    view = ConfirmationView("mute", user, ctx.author, reason, duration)
    await ctx.send(embed=embed, view=view)

@bot.command(name="ban", aliases=["b"])
async def ban_user(ctx, user: discord.Member, duration="permanent", *, reason="No reason provided"):
    """Ban a user with 2-step confirmation"""
    if not ctx.author.guild_permissions.ban_members:
        await ctx.send("You don't have permission to ban users.")
        return

    if user.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        await ctx.send("You cannot ban users with equal or higher roles.")
        return

    # Create confirmation embed
    embed = discord.Embed(
        title="🔨 Confirm Ban",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="User", value=f"{user.mention} ({user})", inline=False)
    embed.add_field(name="Moderator", value=f"{ctx.author.mention}", inline=True)
    embed.add_field(name="Duration", value=duration, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text="🔥 Click Confirm to proceed or Cancel to abort")

    view = ConfirmationView("ban", user, ctx.author, reason, duration)
    await ctx.send(embed=embed, view=view)

@bot.command(name="kick", aliases=["k"])
async def kick_user(ctx, user: discord.Member, *, reason="No reason provided"):
    """Kick a user with 2-step confirmation"""
    if not ctx.author.guild_permissions.kick_members:
        await ctx.send("You don't have permission to kick users.")
        return

    if user.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        await ctx.send("You cannot kick users with equal or higher roles.")
        return

    # Create confirmation embed
    embed = discord.Embed(
        title="👢 Confirm Kick",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="User", value=f"{user.mention} ({user})", inline=False)
    embed.add_field(name="Moderator", value=f"{ctx.author.mention}", inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.set_footer(text="🔥 Click Confirm to proceed or Cancel to abort")

    view = ConfirmationView("kick", user, ctx.author, reason)
    await ctx.send(embed=embed, view=view)

@bot.command(name="mutewarn", aliases=["mw"])
async def mutewarn_user(ctx, user: discord.Member, duration="1h", *, reason="No reason provided"):
    """Warn and mute a user simultaneously with 2-step confirmation"""
    if not ctx.author.guild_permissions.moderate_members:
        await ctx.send("You don't have permission to mute and warn users.")
        return

    if user.top_role >= ctx.author.top_role and ctx.author != ctx.guild.owner:
        await ctx.send("You cannot warn/mute users with equal or higher roles.")
        return

    # Create confirmation embed
    embed = discord.Embed(
        title="⚠️🔇 Confirm Warn + Mute",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="User", value=f"{user.mention} ({user})", inline=False)
    embed.add_field(name="Moderator", value=f"{ctx.author.mention}", inline=True)
    embed.add_field(name="Duration", value=duration, inline=True)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="Actions", value="Will apply **both** warning and mute", inline=False)
    embed.set_footer(text="🔥 Click Confirm to proceed or Cancel to abort")

    view = ConfirmationView("mutewarn", user, ctx.author, reason, duration)
    await ctx.send(embed=embed, view=view)

@bot.command(name="unmute", aliases=["um"])
async def unmute_user(ctx, user: discord.Member, *, reason="No reason provided"):
    """Unmute a user"""
    if not ctx.author.guild_permissions.moderate_members:
        await ctx.send("You don't have permission to unmute users.")
        return

    try:
        if not user.is_timed_out():
            await ctx.send(f"{user.mention} is not currently muted.")
            return

        # Remove timeout
        await user.timeout(None, reason=f"Unmuted by {ctx.author}: {reason}")

        # Create success embed
        embed = discord.Embed(
            title="🔊 User Unmuted",
            color=0xFFC916,
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="🏠 Server", value=f"{ctx.guild.name}", inline=True)
        embed.add_field(name="👤 Moderator", value=f"{ctx.author} (on study arc)", inline=True)
        embed.add_field(name="📋 Reason", value=reason, inline=False)
        embed.add_field(
            name="🚨 Appeal Process",
            value="If you believe this action was taken in error, you may appeal this decision in our appeals server:",
            inline=False
        )
        embed.set_footer(text="🔥 Game Services Moderation System • Today at " + discord.utils.utcnow().strftime("%I:%M %p"))

        await ctx.send(embed=embed)

        # DM the user
        try:
            dm_embed = discord.Embed(
                title="🔊 You Have Been Unmuted",
                description="You have been unmuted from the server",
                color=0xFFC916,
                timestamp=discord.utils.utcnow()
            )
            dm_embed.add_field(name="🏠 Server", value=f"{ctx.guild.name}", inline=True)
            dm_embed.add_field(name="👤 Moderator", value=f"{ctx.author} (on study arc)", inline=True)
            dm_embed.add_field(name="📋 Reason", value=reason, inline=False)
            dm_embed.add_field(
                name="🚨 Appeal Process",
                value="If you believe this action was taken in error, you may appeal this decision in our appeals server:\n🔗 https://discord.gg/ahharETNNR",
                inline=False
            )
            dm_embed.set_footer(text="🔥 Game Services Moderation System")

            await user.send(embed=dm_embed)
        except discord.Forbidden:
            logger.info(f"Could not DM {user} - DMs disabled")

    except Exception as e:
        logger.error(f"Error unmuting user: {e}")
        await ctx.send(f"Error unmuting {user.mention}: {str(e)}")

@bot.command(name="removewarn", aliases=["unwarn", "rw"])
async def remove_warn(ctx, action_id_str: str, *, removal_reason="No reason provided"):
    """Remove a moderation action"""
    if not ctx.author.guild_permissions.kick_members:
        await ctx.send("You don't have permission to remove moderation actions.")
        return

    # Try to convert action_id_str to integer
    try:
        action_id = int(action_id_str)
    except ValueError:
        embed = discord.Embed(
            title="<:GsWrong:1414561861352816753>   Invalid Action ID",
            description="Please provide a valid action ID number.",
            color=0xFFC916
        )
        embed.add_field(name="💡 Usage", value="`gs.removewarn <action_id> [reason]`", inline=False)
        embed.add_field(name="📋 Example", value="`gs.removewarn 123 mistake by staff`", inline=False)
        embed.add_field(name="🔍 How to find Action ID", value="Use `gs.warns @user` to see action IDs", inline=False)
        embed.set_footer(text="🔥 Game Services Moderation System")
        await ctx.send(embed=embed)
        return

    # Remove from database
    removed_action = mod_db.remove_moderation_action(action_id, ctx.author.id, removal_reason)

    if not removed_action:
        await ctx.send("No active moderation action found with that ID.")
        return

    embed = discord.Embed(
        title="<:GsRight:1414593140156792893>  Moderation Action Removed Successfully",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="🆔 Action ID", value=f"#{action_id}", inline=True)
    embed.add_field(name="🏷️ Original Action", value=removed_action['action_type'].title(), inline=True)
    embed.add_field(name="👤 Target User", value=f"<@{removed_action['user_id']}>", inline=True)
    embed.add_field(name="👮 Original Moderator", value=f"<@{removed_action['moderator_id']}>", inline=True)
    embed.add_field(name="🗑️ Removed By", value=f"{ctx.author.mention}", inline=True)
    embed.add_field(name="📊 Database", value="<:GsRight:1414593140156792893>  Updated", inline=True)
    embed.add_field(name="📝 Removal Reason", value=removal_reason, inline=False)
    embed.add_field(name="📋 Original Reason", value=removed_action['reason'], inline=False)
    embed.set_footer(text="🔥 Game Services Moderation System")

    await ctx.send(embed=embed)

    # If it was a mute, remove the timeout
    if removed_action['action_type'] == 'mute':
        try:
            user = ctx.guild.get_member(removed_action['user_id'])
            if user and user.is_timed_out():
                await user.timeout(None, reason=f"Mute removed by {ctx.author}")
        except Exception as e:
            logger.error(f"Error removing timeout: {e}")

@bot.command(name="warns", aliases=["warnlist"])
async def user_warns(ctx, user: discord.Member = None):
    """Show warning history for a user in this server"""
    if not user:
        user = ctx.author

    records = mod_db.get_user_record(user.id, ctx.guild.id)
    warn_records = [r for r in records if r['action_type'] == 'warn' and r['is_active']]

    if not warn_records:
        embed = discord.Embed(
            title="📋 No Warning History",
            description=f"{user.mention} has no warning history in **{ctx.guild.name}**.",
            color=0xFFC916
        )
        embed.set_footer(text="🔥 Game Services Moderation System")
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title=f"⚠️ Warning History for {user.display_name}",
        description=f"Server: **{ctx.guild.name}**",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    recent_warns = []
    active_warns = [r for r in warn_records if r['is_active']]

    embed.add_field(name="📊 Summary", value=f"**{len(active_warns)}** active warnings", inline=True)
    embed.add_field(name="📈 Total", value=f"**{len(warn_records)}** total warnings", inline=True)
    embed.add_field(name="🏠 Server", value=f"**{ctx.guild.name}**", inline=True)

    for record in warn_records[:10]:
        created_at = record['created_at'].strftime('%m/%d/%Y %H:%M')
        moderator_id = record['moderator_id']
        reason = record['reason'][:50] + "..." if len(record['reason']) > 50 else record['reason']
        status = "<:GsWrong:1414561861352816753>   Removed" if not record['is_active'] else "<:GsRight:1414593140156792893>  Active"

        recent_warns.append(
            f"**#{record['id']}** Warning - {created_at}\n"
            f"By: <@{moderator_id}> | {status}\n"
            f"Reason: {reason}\n"
        )

    if recent_warns:
        embed.add_field(name="📝 Recent Warnings",
                       value="\n".join(recent_warns),
                       inline=False)

    embed.set_footer(text="🔥 Game Services Moderation System • Server-Specific Data")
    await ctx.send(embed=embed)

@bot.command(name="mutes", aliases=["mutelist"])
async def user_mutes(ctx, user: discord.Member = None):
    """Show mute history for a user"""
    if not user:
        user = ctx.author

    records = mod_db.get_user_record(user.id, ctx.guild.id)
    mute_records = [r for r in records if r['action_type'] == 'mute']

    if not mute_records:
        embed = discord.Embed(
            title="📋 No Mute History",
            description=f"{user.mention} has no mute history.",
            color=0xFFC916
        )
        embed.set_footer(text="🔥 Game Services Moderation System")
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title=f"🔇 Mute History for {user.display_name}",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    recent_mutes = []
    for record in mute_records[:10]:
        created_at = record['created_at'].strftime('%m/%d/%Y %H:%M')
        moderator_id = record['moderator_id']
        reason = record['reason'][:50] + "..." if len(record['reason']) > 50 else record['reason']
        status = "<:GsWrong:1414561861352816753>   Removed" if not record['is_active'] else "<:GsRight:1414593140156792893>  Active"

        recent_mutes.append(
            f"**#{record['id']}** Mute - {created_at}\n"
            f"By: <@{moderator_id}> | {status}\n"
            f"Reason: {reason}\n"
        )

    if recent_mutes:
        embed.add_field(name="📝 Recent Mutes",
                       value="\n".join(recent_mutes),
                       inline=False)

    embed.set_footer(text="🔥 Game Services Moderation System")
    await ctx.send(embed=embed)

@bot.command(name="bans", aliases=["ba"])
async def user_bans(ctx, user: discord.Member = None):
    """Show ban history for a user"""
    if not user:
        user = ctx.author

    records = mod_db.get_user_record(user.id, ctx.guild.id)
    ban_records = [r for r in records if r['action_type'] == 'ban']

    if not ban_records:
        embed = discord.Embed(
            title="📋 No Ban History",
            description=f"{user.mention} has no ban history.",
            color=0xFFC916
        )
        embed.set_footer(text="🔥 Game Services Moderation System")
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title=f"🔨 Ban History for {user.display_name}",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    recent_bans = []
    for record in ban_records[:10]:
        created_at = record['created_at'].strftime('%m/%d/%Y %H:%M')
        moderator_id = record['moderator_id']
        reason = record['reason'][:50] + "..." if len(record['reason']) > 50 else record['reason']
        status = "<:GsWrong:1414561861352816753>   Removed" if not record['is_active'] else "<:GsRight:1414593140156792893>  Active"

        recent_bans.append(
            f"**#{record['id']}** Ban - {created_at}\n"
            f"By: <@{moderator_id}> | {status}\n"
            f"Reason: {reason}\n"
        )

    if recent_bans:
        embed.add_field(name="📝 Recent Bans",
                       value="\n".join(recent_bans),
                       inline=False)

    embed.set_footer(text="🔥 Moderation System")
    await ctx.send(embed=embed)

@bot.command(name="gs.kicks", aliases=["kicks"])
async def user_kicks(ctx, user: discord.Member = None):
    """Show kick history for a user"""
    if not user:
        user = ctx.author

    records = mod_db.get_user_record(user.id, ctx.guild.id)
    kick_records = [r for r in records if r['action_type'] == 'kick']

    if not kick_records:
        embed = discord.Embed(
            title="📋 No Kick History",
            description=f"{user.mention} has no kick history.",
            color=0x00FF00
        )
        embed.set_footer(text="🔥 Game Services Moderation System")
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title=f"👢 Kick History for {user.display_name}",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    recent_kicks = []
    for record in kick_records[:10]:
        created_at = record['created_at'].strftime('%m/%d/%Y %H:%M')
        moderator_id = record['moderator_id']
        reason = record['reason'][:50] + "..." if len(record['reason']) > 50 else record['reason']

        recent_kicks.append(
            f"**#{record['id']}** Kick - {created_at}\n"
            f"By: <@{moderator_id}>\n"
            f"Reason: {reason}\n"
        )

    if recent_kicks:
        embed.add_field(name="📝 Recent Kicks",
                       value="\n".join(recent_kicks),
                       inline=False)

    embed.set_footer(text="🔥 Game Services Moderation System")
    await ctx.send(embed=embed)

# Roblox Server Commands
@bot.command(name="gagps", aliases=["gs.gagps"])
async def grow_a_garden_ps(ctx):
    """🌱 Get Grow-A-Garden Private Server link"""
    embed = discord.Embed(
        title="🌱 Grow-A-Garden Private Server",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(
        name="Private Server Link:",
        value="https://www.roblox.com/share?code=46f8e0e94513bc41a1bf7314925f5420&type=Server",
        inline=False
    )
    embed.set_footer(text="🔥 Game Services")
    await ctx.send(embed=embed)

@bot.command(name="sabps", aliases=["gs.sabps"])
async def steal_a_brainrot_ps(ctx):
    """" Get Steal-A-Brainrot Private Server link"""
    embed = discord.Embed(
        title="Steal-A-Brainrot Private Server",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(
        name="Private Server Link:(Stealing=Ban)",
        value="https://www.roblox.com/share?code=75f26e5ffe139f42807227d149126668&type=Server",
        inline=False
    )
    embed.set_footer(text="🔥 Game Services")
    await ctx.send(embed=embed)

@bot.command(name="tutorial", aliases=["gs.tutorial"])
async def invite_tutorial(ctx):
    """📚 Learn how to create your own invite link"""
    embed = discord.Embed(
        title="📚 Tutorial",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(
        name="How to generate your own invite link:",
        value="https://youtu.be/UkyljZT6lFg?si=G-C6biADCokHOM70",
        inline=False
    )
    embed.add_field(
        name="📝 What you'll learn:",
        value="• How to create non-vanity server invite links\n• Step-by-step guide\n• Easy to follow tutorial",
        inline=False
    )
    embed.set_footer(text="🔥 Game Services")
    await ctx.send(embed=embed)

@bot.command(name="secretsabps", aliases=["gs.secretsabps"])
async def mal_sabps(ctx):
    """Get Secret Steal-A-Brainrot Private Server link"""
    embed = discord.Embed(
        title="Secret Steal-A-Brainrot Private Server",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(
        name="Private Server Link:(Stealing=Ban)",
        value="https://www.roblox.com/share?code=9aa554d3133c214293a36fcf6b027ce3&type=Server",
        inline=False
    )
    embed.set_footer(text="🔥 Game Services")
    await ctx.send(embed=embed)
@bot.command(name="serverlinks", aliases=["gs.serverlinks"])
async def server_links(ctx):
    """🔗 Get all server invite links (Admin only)"""
    # Check if user has administrator permission
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("<:GsWrong:1414561861352816753>   You need administrator permissions to use this command.")
        return

    server_count = len(bot.guilds)

    embed = discord.Embed(
        title="🔗 Server Information & Links",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(
        name="📊 Bot Statistics",
        value=f"**{server_count}** servers connected",
        inline=False
    )

    server_info = ""
    for guild in bot.guilds[:10]:  # Limit to first 10 servers
        member_count = guild.member_count or 0
        try:
            # Try to create an invite
            text_channels = [channel for channel in guild.text_channels if channel.permissions_for(guild.me).create_instant_invite]
            if text_channels:
                invite = await text_channels[0].create_invite(max_age=0, max_uses=0)
                server_info += f"**{guild.name}** ({member_count} members)\n{invite.url}\n\n"
            else:
                server_info += f"**{guild.name}** ({member_count} members)\n*No invite permission*\n\n"
        except:
            server_info += f"**{guild.name}** ({member_count} members)\n*Cannot create invite*\n\n"

    if server_info:
        embed.add_field(
            name="🏰 Server Invites",
            value=server_info[:1020] + ("..." if len(server_info) > 1020 else ""),
            inline=False
        )

    if server_count > 10:
        embed.add_field(
            name="ℹ️ Note",
            value=f"Showing first 10 of {server_count} servers",
            inline=False
        )

    embed.set_footer(text="🔥 Game Services • Admin Command")
    await ctx.send(embed=embed)

@bot.command(name="chatguide", aliases=["gs.chatguide", "guide"])
async def send_chat_guide(ctx):
    """📋 Manually send the chat guide message (only works in designated channel)"""
    channel_id = ctx.channel.id

    # Only allow in the specific channel
    if channel_id != CHAT_GUIDE_CHANNEL_ID:
        await ctx.send("<:GsWrong:1414561861352816753>   This command only works in <#1370086532433838102>.")
        return

    current_time = discord.utils.utcnow()

    # Check cooldown to prevent spam (1 minute cooldown for manual command)
    if channel_id in chat_guide_cooldown and \
       (current_time - chat_guide_cooldown[channel_id]).total_seconds() < 60:
        remaining = 60 - (current_time - chat_guide_cooldown[channel_id]).total_seconds()
        await ctx.send(f"⏰ Chat guide message is on cooldown. Try again in {int(remaining)} seconds.")
        return

    try:
        await ctx.send(CHAT_GUIDE_MESSAGE)
        chat_guide_cooldown[channel_id] = current_time
        logger.info(f"Manually sent chat guide message in {ctx.channel.name} by {ctx.author}")
    except Exception as e:
        logger.error(f"Error manually sending chat guide message: {e}")
        await ctx.send("<:GsWrong:1414561861352816753>   Failed to send chat guide message.")

@bot.command(name="messagecounter", aliases=["gs.msgcount", "msgcount"])
async def message_counter_status(ctx):
    """📊 Check message counter status for this channel (Admin only)"""
    if not ctx.author.guild_permissions.manage_messages:
        await ctx.send("<:GsWrong:1414561861352816753>   You need manage messages permission to use this command.")
        return

    channel_id = ctx.channel.id
    message_count = channel_message_counts.get(channel_id, 0)
    remaining = CHAT_GUIDE_INTERVAL - (message_count % CHAT_GUIDE_INTERVAL)

    embed = discord.Embed(
        title="📊 Chat Guide Message Counter",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(
        name="💬 Messages in Channel",
        value=f"**{message_count}** total messages",
        inline=False
    )
    embed.add_field(
        name="⏰ Next Guide Message",
        value=f"In **{remaining}** messages",
        inline=False
    )
    embed.add_field(
        name="🔄 Interval",
        value=f"Every **{CHAT_GUIDE_INTERVAL}** messages",
        inline=False
    )

    if channel_id in chat_guide_cooldown:
        last_sent = chat_guide_cooldown[channel_id]
        time_since = discord.utils.utcnow() - last_sent
        embed.add_field(
            name="📅 Last Sent",
            value=f"{int(time_since.total_seconds() / 60)} minutes ago",
            inline=False
        )

    embed.set_footer(text="🔥 Game Services • Message Counter System")
    await ctx.send(embed=embed)

@bot.command(name="gs.history", aliases=["history"])
async def user_full_history(ctx, user: discord.Member = None):
    """Show complete moderation history for a user in this server"""
    if not user:
        user = ctx.author

    # Get user's record for this server only
    records = mod_db.get_user_record(user.id, ctx.guild.id)

    if not records:
        embed = discord.Embed(
            title="📋 Clean Record",
            description=f"{user.mention} has no moderation history in **{ctx.guild.name}**.",
            color=0xFFC916
        )
        embed.add_field(name="🏠 Server", value=f"**{ctx.guild.name}**", inline=True)
        embed.set_footer(text="🔥 Game Services Moderation System • Server-Specific Data")
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(
        title=f"📋 Complete Moderation History for {user.display_name}",
        description=f"Server: **{ctx.guild.name}**",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.set_thumbnail(url=user.display_avatar.url)

    # Count actions (active and inactive)
    warns = len([r for r in records if r['action_type'] == 'warn'])
    mutes = len([r for r in records if r['action_type'] == 'mute'])
    bans = len([r for r in records if r['action_type'] == 'ban'])
    kicks = len([r for r in records if r['action_type'] == 'kick'])

    # Count active actions
    active_warns = len([r for r in records if r['action_type'] == 'warn' and r['is_active']])
    active_mutes = len([r for r in records if r['action_type'] == 'mute' and r['is_active']])
    active_bans = len([r for r in records if r['action_type'] == 'ban' and r['is_active']])

    embed.add_field(name="📊 Total Actions",
                   value=f"Warnings: {warns}\nMutes: {mutes}\nBans: {bans}\nKicks: {kicks}",
                   inline=True)

    embed.add_field(name="⚡ Active Actions",
                   value=f"Warnings: {active_warns}\nMutes: {active_mutes}\nBans: {active_bans}\nKicks: 0",
                   inline=True)

    embed.add_field(name="🏠 Server",
                   value=f"**{ctx.guild.name}**\nID: {ctx.guild.id}",
                   inline=True)

    # Show recent actions (last 8)
    recent_actions = []
    for record in records[:8]:
        action_type = record['action_type'].title()
        created_at = record['created_at'].strftime('%m/%d/%Y %H:%M')
        moderator_id = record['moderator_id']
        reason = record['reason'][:45] + "..." if len(record['reason']) > 45 else record['reason']
        status = "<:GsWrong:1414561861352816753>   Removed" if not record['is_active'] else "<:GsRight:1414593140156792893>  Active"

        recent_actions.append(
            f"**#{record['id']}** {action_type} - {created_at}\n"
            f"By: <@{moderator_id}> | {status}\n"
            f"Reason: {reason}\n"
        )

    if recent_actions:
        embed.add_field(name="📝 Recent Actions",
                       value="\n".join(recent_actions),
                       inline=False)

    embed.set_footer(text="🔥 Game Services Moderation System • Server-Specific Data")
    await ctx.send(embed=embed)

@bot.command(name="gs.report", aliases=["report"])
async def report_user(ctx, user: discord.Member, *, reason="No reason provided"):
    """Report a user to moderators"""
    # Prevent self-reporting
    if user == ctx.author:
        await ctx.send("<:GsWrong:1414561861352816753>   You cannot report yourself.")
        return

    # Prevent reporting bots
    if user.bot:
        await ctx.send("<:GsWrong:1414561861352816753>   You cannot report bots.")
        return

    # Get the report channel
    report_channel = bot.get_channel(REPORT_CHANNEL_ID)
    if not report_channel:
        await ctx.send("<:GsWrong:1414561861352816753>   Report channel not found. Please contact an administrator.")
        return

    # Create report embed
    report_embed = discord.Embed(
        title="🚨 User Report Alert",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    report_embed.add_field(name="🎯 Reported User", value=f"{user.mention} ({user})\nID: {user.id}", inline=False)
    report_embed.add_field(name="👤 Reporter", value=f"{ctx.author.mention} ({ctx.author})\nID: {ctx.author.id}", inline=False)
    report_embed.add_field(name="📍 Channel", value=f"{ctx.channel.mention} ({ctx.channel.name})", inline=True)
    report_embed.add_field(name="🏠 Server", value=f"{ctx.guild.name}", inline=True)
    report_embed.add_field(name="📋 Reason", value=reason, inline=False)

    # Add user info
    now = discord.utils.utcnow()
    account_age = (now - user.created_at).days
    server_join = (now - user.joined_at).days if user.joined_at else "Unknown"
    report_embed.add_field(name="📊 User Info",
                          value=f"Account Age: {account_age} days\nServer Member: {server_join} days",
                          inline=True)

    report_embed.set_thumbnail(url=user.display_avatar.url)
    report_embed.set_footer(text=f"🔥 Game Services Report System • Report ID: {ctx.message.id}")

    # Create confirmation embed with warning
    confirm_embed = discord.Embed(
        title="🚨 Confirm Report Submission",
        description=f"You are about to report {user.mention} to the moderation team.",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    confirm_embed.add_field(name="📋 Reason", value=reason, inline=False)
    confirm_embed.add_field(name="⚠️ **WARNING**",
                           value="**FALSE REPORTS WILL GET YOU MUTED**\nOnly submit this report if you have a legitimate concern.",
                           inline=False)
    confirm_embed.add_field(name="❓ Are you sure?",
                           value="Click Submit Report to send this to staff, or Cancel to dismiss.",
                           inline=False)
    confirm_embed.set_footer(text="🔥 Game Services Report System")

    # Create view with confirmation buttons
    view = ReportConfirmationView(user, ctx.author, reason, report_channel, report_embed)
    await ctx.send(embed=confirm_embed, view=view)

# Invite tracking commands
@bot.command(name="invites", aliases=["inv", "gs.invites"])
async def show_invites(ctx, user: discord.Member = None):
    """Show invite statistics for a user"""
    target_user = user or ctx.author
    user_id = target_user.id

    if user_id not in user_invites:
        user_invites[user_id] = {'invites': 0, 'fake': 0, 'rejoins': 0, 'bonus': 0}

    data = user_invites[user_id]
    total = data['invites'] + data['bonus'] - data['fake'] - data['rejoins']

    embed = discord.Embed(
        title="📊 Invite Statistics",
        description=f"Invite data for {target_user.mention}",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )

    embed.add_field(name="<:GsRight:1414593140156792893>  Valid Invites", value=str(data['invites']), inline=True)
    embed.add_field(name="🚫 Fake Invites", value=str(data['fake']), inline=True)
    embed.add_field(name="🔄 Rejoins", value=str(data['rejoins']), inline=True)
    embed.add_field(name="🎁 Bonus Invites", value=str(data['bonus']), inline=True)
    embed.add_field(name="📈 Total Score", value=str(total), inline=True)
    embed.add_field(name="👤 User", value=f"{target_user} ({target_user.id})", inline=False)

    embed.set_thumbnail(url=target_user.display_avatar.url)
    embed.set_footer(text="🔥 Game Services Invite System")

    await ctx.send(embed=embed)

@bot.command(name="addinvite", aliases=["addinv"])
async def add_invite(ctx, user: discord.Member, amount: int = 1):
    """Add bonus invites to a user (Moderators only)"""
    if not ctx.author.guild_permissions.kick_members:
        await ctx.send("<:GsWrong:1414561861352816753>   You don't have permission to manage invites.")
        return

    if user.id not in user_invites:
        user_invites[user.id] = {'invites': 0, 'fake': 0, 'rejoins': 0, 'bonus': 0}

    user_invites[user.id]['bonus'] += amount

    embed = discord.Embed(
        title="<:GsRight:1414593140156792893>  Bonus Invites Added",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="👤 User", value=user.mention, inline=True)
    embed.add_field(name="🎁 Added", value=f"+{amount} bonus invites", inline=True)
    embed.add_field(name="👮 Moderator", value=ctx.author.mention, inline=True)
    embed.add_field(name="📊 New Bonus Total", value=str(user_invites[user.id]['bonus']), inline=False)
    embed.set_footer(text="🔥 Game Services Invite System")

    await ctx.send(embed=embed)

@bot.command(name="removeinvite", aliases=["reminv"])
async def remove_invite(ctx, user: discord.Member, amount: int = 1):
    """Remove bonus invites from a user (Moderators only)"""
    if not ctx.author.guild_permissions.kick_members:
        await ctx.send("<:GsWrong:1414561861352816753>   You don't have permission to manage invites.")
        return

    if user.id not in user_invites:
        user_invites[user.id] = {'invites': 0, 'fake': 0, 'rejoins': 0, 'bonus': 0}

    user_invites[user.id]['bonus'] = max(0, user_invites[user.id]['bonus'] - amount)

    embed = discord.Embed(
        title="➖ Bonus Invites Removed",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="👤 User", value=user.mention, inline=True)
    embed.add_field(name="🔻 Removed", value=f"-{amount} bonus invites", inline=True)
    embed.add_field(name="👮 Moderator", value=ctx.author.mention, inline=True)
    embed.add_field(name="📊 New Bonus Total", value=str(user_invites[user.id]['bonus']), inline=False)
    embed.set_footer(text="🔥 Game Services Invite System")

    await ctx.send(embed=embed)

@bot.command(name="invtop", aliases=["inviteleaderboard"])
async def invite_leaderboard(ctx):
    """Show top inviters"""
    if not user_invites:
        embed = discord.Embed(
            title="📊 Invite Leaderboard",
            description="No invite data available yet.",
            color=0xFFC916
        )
        await ctx.send(embed=embed)
        return

    # Calculate total scores and sort
    leaderboard = []
    for user_id, data in user_invites.items():
        total = data['invites'] + data['bonus'] - data['fake'] - data['rejoins']
        leaderboard.append((user_id, total, data))

    leaderboard.sort(key=lambda x: x[1], reverse=True)
    leaderboard = leaderboard[:10]  # Top 10

    embed = discord.Embed(
        title="🏆 Invite Leaderboard",
        description="Top 10 inviters in the server",
        color=0xFFC916,
        timestamp=discord.utils.utcnow()
    )

    for i, (user_id, total, data) in enumerate(leaderboard, 1):
        user = bot.get_user(user_id)
        user_name = user.display_name if user else f"User {user_id}"

        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."

        embed.add_field(
            name=f"{medal} {user_name}",
            value=f"**{total}** total invites\n<:GsRight:1414593140156792893>  {data['invites']} • 🚫 {data['fake']} • 🔄 {data['rejoins']} • 🎁 {data['bonus']}",
            inline=False
        )

    embed.set_footer(text="🔥 Game Services Invite System")
    await ctx.send(embed=embed)

# Message tracking commands

# --- Echo Command (Admins Only) ---
@bot.command(name="echo")
@commands.has_permissions(administrator=True)
async def echo_command(ctx, *, message: str = None):
    reference = ctx.message.reference
    try:
        await ctx.message.delete()  # delete the command message
    except discord.Forbidden:
        pass  # ignore if bot has no perms

    if not message and not reference:
        error = await ctx.send("<:GsWrong:1414561861352816753>   You must provide a message or reply to one.")
        await asyncio.sleep(5)
        await error.delete()
        return

    # Determine final message to send
    final_message = message or ""

    # Add user info if NOT in excluded server
    if ctx.guild and ctx.guild.id != 1370086525210984458:
        final_message = f"💬 {ctx.author} echoed:\n{final_message}"

    if reference:
        replied_message = await ctx.channel.fetch_message(reference.message_id)
        await replied_message.reply(final_message)
    else:
        await ctx.send(final_message)
# --- AnonymousEcho (Admins Only) ---
@bot.command(name="anonymousecho")
@commands.has_permissions(administrator=True)
async def echo_command(ctx, *, message: str = None):
    reference = ctx.message.reference
    try:
        await ctx.message.delete()  # delete the command message
    except discord.Forbidden:
        pass  # ignore if bot has no perms

    if not message and not reference:
        error = await ctx.send("<:GsWrong:1414561861352816753>   You must provide a message or reply to one.")
        await asyncio.sleep(5)
        await error.delete()
        return

    # Determine final message to send
    final_message = message or ""

    # Add user info if NOT in excluded server
    if ctx.guild and ctx.guild.id != 1370086525210984458:
        final_message = f"💬 Someone Anonymously Echoed:\n{final_message}"

    if reference:
        replied_message = await ctx.channel.fetch_message(reference.message_id)
        await replied_message.reply(final_message)
    else:
        await ctx.send(final_message)
# --- Fixed Message Command ---
@bot.command(name="arix")
async def arix_command(ctx):
    # The message you want to send (change this!)
    fixed_message = "wowowowow me arix <:CatSmirk:1411643056230498415>"

    # Send the fixed message
    await ctx.send(fixed_message)
# --- Fixed Message Command ---
@bot.command(name="mal")
async def mal_command(ctx):
    # The message you want to send (change this!)
    fixed_message = "<a:MonkeySpin:1410866007953637428> "

    # Send the fixed message
    await ctx.send(fixed_message)

# --- Fixed Message Command ---
@bot.command(name="sia")
async def sia_command(ctx):
    # The message you want to send (change this!)
    fixed_message = "hewooo <a:Excited:1390404098616197251>  "

    # Send the fixed message
    await ctx.send(fixed_message)

# --- Fixed Message Command ---
@bot.command(name="scyther")
async def scyther_command(ctx):
    # The message you want to send (change this!)
    fixed_message = "Hi Guys I Am Scytherino Yaperino <a:MonkeySpin:1410866007953637428>"

    # Send the fixed message
    await ctx.send(fixed_message)

# --- Auto Ticket Greeting ---
@bot.event
async def on_guild_channel_create(channel):
    # Only act on text channels
    if isinstance(channel, discord.TextChannel):
        if channel.name.lower().startswith("ticket"):
            try:
                await channel.send("**Hello, please be patient until staff respond to your ticket, meanwhile state why you made it.**")
            except Exception as e:
                print(f"Error sending ticket greeting: {e}")

# --- Fake Ban Command (gs.bam) ---
@bot.command(name="bam", aliases=["gs.bam"])
async def bam_command(ctx, member: discord.Member = None):
    if not member:
        error = await ctx.send("ℹ️ Usage: `gs.bam @user`")
        await error.delete(delay=5)
        return

    embed = discord.Embed(
        title="⚒️ Ban Hammer",
        description=f"Banned **{member.display_name}**",
        color=0xFFC916
    )
    embed.set_footer(text="🎮 Game Services")

    await ctx.send(embed=embed)
# --- Clear Command (mods/admins with Manage Messages) ---
@bot.command(name="clear", aliases=["gs.clear"])
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = None):
    # Validate input
    if amount is None or amount < 1:
        error = await ctx.send("⚠️ Usage: `gs.clear <number>` — number must be 1 or higher.")
        await error.delete(delay=5)
        return

    # We'll try to bulk delete `amount` messages *plus* the command message (if still present)
    limit = amount + 1

    try:
        # Prevent removing pinned messages
        deleted = await ctx.channel.purge(limit=limit, check=lambda m: not m.pinned)
        # Count deleted messages excluding the command message (if it was included)
        deleted_count = sum(1 for m in deleted if m.id != ctx.message.id)
        confirm = await ctx.send(f"<:GsRight:1414593140156792893>  Deleted {deleted_count} messages.")
        await confirm.delete(delay=5)

    except discord.Forbidden:
        # Bot lacks Manage Messages / Read Message History permissions
        error = await ctx.send("<:GsWrong:1414561861352816753>   I don't have permission to delete messages in this channel.")
        await error.delete(delay=5)

    except discord.HTTPException as e:
        # Bulk delete failed (e.g., messages older than 14 days cannot be bulk-deleted)
        logger.exception("Bulk delete failed", exc_info=e)
        err = await ctx.send("<:GsWrong:1414561861352816753>   Failed to delete messages. Note: Discord won't bulk-delete messages older than 14 days.")
        await err.delete(delay=8)

    except Exception as e:
        logger.exception("Unexpected error in clear command", exc_info=e)
        err = await ctx.send("<:GsWrong:1414561861352816753>   An unexpected error occurred while trying to clear messages.")
        await err.delete(delay=8)

# --- Fixed Message Command ---
@bot.command(name="aarav")
async def aarav_command(ctx):
    # The message you want to send (change this!)
    fixed_message = "Brri brri dicus bombicus- I mean hello !"

    # Send the fixed message
    await ctx.send(fixed_message)


# ---------------- gs.absence command ----------------
ABSENCE_ROLE_ID = 1374481044916408340

@bot.command(name="absence")
@commands.has_permissions(administrator=True)
async def absence(ctx, member: discord.Member, duration: str):
    """
    Usage: gs.absence @member 10m
    Only usable by administrators. Cannot target users with equal/higher role or the server owner.
    """
    # Protect server owner
    if member == ctx.guild.owner:
        await ctx.send("<:GsWrong:1414561861352816753>   You cannot mark the server owner absent.")
        return

    # Prevent targeting equal/higher role
    if member.top_role >= ctx.author.top_role:
        await ctx.send("<:GsWrong:1414561861352816753>   You cannot mark this user absent (they have equal or higher role).")
        return

    # Parse duration
    time_units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    try:
        unit = duration[-1].lower()
        amount = int(duration[:-1])
        seconds = amount * time_units[unit]
    except Exception:
        await ctx.send("Invalid time format. Use e.g. `10m`, `2h`, `1d`.")
        return

    role = ctx.guild.get_role(ABSENCE_ROLE_ID)
    if not role:
        await ctx.send("Absence role not found!")
        return

    try:
        await member.add_roles(role)
    except Exception as e:
        await ctx.send(f"Failed to add absence role: {e}")
        return

    # Plain text start message
    await ctx.send(f"📌 {member.mention} is now marked absent for **{duration}**. The role will be removed automatically.")

    # Schedule role removal
    async def remove_role_later():
        await asyncio.sleep(seconds)
        try:
            m = ctx.guild.get_member(member.id)
            if m and role in m.roles:
                await m.remove_roles(role)
                # Plain text end message
                await ctx.send(f"<:GsRight:1414593140156792893>  {m.mention}'s absence has ended.")
        except Exception:
            pass

    bot.loop.create_task(remove_role_later())

# ---------------- gs.dm command ----------------
@bot.command(name="dm")
async def dm(ctx, member: discord.Member, *, message: str):
    """
    Usage: gs.dm @member your message
    Only the user with ID 721063236371480717 can use this command.
    """
    # Check if the author is the allowed user mo
    allowed_ids = {721063236371480717, 1344727532972412938}  # <:GsRight:1414593140156792893>  two allowed users

    if ctx.author.id not in allowed_ids:
        await ctx.send("<:GsWrong:1414561861352816753>   You are not allowed to use this command.")
        return

    try:
        await member.send(message)
        await ctx.send(f"📩 Successfully sent DM to {member.mention}")
    except discord.Forbidden:
        await ctx.send(f"⚠️ I cannot DM {member.mention}. Their DMs might be closed.")
    except Exception as e:
        await ctx.send(f"<:GsWrong:1414561861352816753>   Failed to send DM: {e}")

# ---------------- Missing commands handlers ----------------
@bot.command(name="sabadminabuse")
async def axo_command(ctx):
    """Handle axo command"""
    await ctx.send("Next Steal A Brainrot Admin Abuse is at **Your time:** <t:1758394800:f> or <t:1758394800:R>")

@bot.command(name="sabadminabusedetails")
async def sabadmin_command(ctx):
    """Handle sabadminabusedetails command"""
    await ctx.send(
        """Next Steal A Brainrot Admin Abuse Will 100% have MEXICO EVENT  
This will be a fun event with a Pinata!  
Will include candy weapons and a chance of spawning a very rare brainrot....

**3 NEW BRAINROTS**  
- ??? (ADMIN SPAWNED)  
- To to to Sahur (SECRET)  
- Tictac Sahur (SECRET)  

**4 CRAFTABLE BRAINROTS**  
- Sigma Girl (LEGENDARY)  
- Elefanto Frigo (MYTHIC)  
- Dug dug dug (BRAINROT GOD)  
- ??? (SECRET)"""
    )

@bot.command(name="countryquiz", aliases=["cquiz"])
async def country_quiz(ctx):
    """Redirect to the correct countries quiz command"""
    await ctx.send("🌍 Use `gs.groupcountriesquiz` or `gs.countryguess` to play geography games!")   
    
# ---------------- Mal's Gws ----------------
@bot.command(name="giveawayprompt")
async def giveawayprompt_command(ctx):
    if not any(role.id == 1403093737323761746 for role in ctx.author.roles):
        await ctx.reply("<:GsWrong:1414561861352816753> You don't have permission to use this command.", mention_author=True)
        return

    # build the embed
    embed = discord.Embed(
        title="🎉 Giveaway Info",
        description=(
            "**1. Prize Details**\n"
            "● Prize: \n"
            "● Amount of Winners: \n\n"
            "**2. Duration**\n"
            "● Giveaway Length: \n"
            "● Claim Time (*Half of the duration +*)\n\n"
            "**3. Requirements**\n"
            "● Any specific requirements\n"
            "● Any bypassers"
        ),
        color=0xFFC916
    )
    embed.set_footer(text="🔥 Giveaways")

    # <:GsRight:1414593140156792893>  reply to the triggering message with embed
    await ctx.reply(embed=embed, mention_author=True)

import discord
from discord.ext import commands
from discord.ui import View, Button
import asyncio
import io
import datetime
import json
import os
import re

# ---------------- CONFIG ----------------
STAFF_ROLE_ID = 1394686620300476476   # Staff role
TICKET_CATEGORY_1 = 1372934736330096780  # Buying tickets category
TICKET_CATEGORY_2 = 1372934887186890903  # Support tickets category
LOG_CHANNEL_ID = 1414528231834386545     # Ticket logs channel
PANEL_ALLOWED_USER = 721063236371480717  # only this user can run gs.ticketpanel
GOLD = 0xFFC916
DB_FILE = "tickets.json"

# ---------------- Bot setup (safe create-if-missing) ----------------
try:
    bot  # if NameError -> not defined
except NameError:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    bot = commands.Bot(command_prefix=['gs.', 'gs '], intents=intents)

# ---------------- Persistent DB helpers ----------------
DB_LOCK = asyncio.Lock()
# structure: {"tickets": {"<channel_id>": {"creator_id": int|None, "claimer_id": int|None, "action_message_id": int|None, "created_at": iso}}, "panels": [{"channel_id": int, "message_id": int}, ...]}
_tickets_db = {"tickets": {}, "panels": []}

def load_db():
    global _tickets_db
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                _tickets_db = json.load(f)
        except Exception:
            _tickets_db = {"tickets": {}, "panels": []}
    else:
        _tickets_db = {"tickets": {}, "panels": []}

async def save_db():
    async with DB_LOCK:
        # make a safe write
        tmp = DB_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_tickets_db, f, indent=2)
        os.replace(tmp, DB_FILE)

load_db()

# ---------------- Utility: transcript & staff detection ----------------
async def make_transcript(channel: discord.TextChannel) -> discord.File:
    """Return a discord.File object containing the channel transcript."""
    transcript_lines = []
    async for msg in channel.history(limit=None, oldest_first=True):
        ts = msg.created_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        # include attachments info (simple)
        att_text = ""
        if msg.attachments:
            att_text = " [attachments: " + ", ".join(a.url for a in msg.attachments) + "]"
        # guard binary / big content by truncating if necessary
        content = msg.content or ""
        if len(content) > 3000:
            content = content[:3000] + "...[truncated]"
        transcript_lines.append(f"[{ts}] {msg.author} ({getattr(msg.author, 'id', 'unknown')}): {content}{att_text}")
    data = "\n".join(transcript_lines) or "(no messages)"
    return discord.File(io.BytesIO(data.encode("utf-8")), filename=f"{channel.name}-transcript.txt")

async def gather_staff_who_spoke(channel: discord.TextChannel, staff_role: discord.Role):
    """Return (set of Member, mention_string). Searches message history and finds staff who posted."""
    staff_members = set()
    async for msg in channel.history(limit=None):
        if msg.author.bot:
            continue
        # msg.author may be Member or User; use roles attr safely
        roles = getattr(msg.author, "roles", [])
        if staff_role in roles:
            staff_members.add(msg.author)
    mentions = ", ".join(m.mention for m in staff_members) if staff_members else "No staff replied."
    return staff_members, mentions

# ---------------- Persistent Views ----------------
class TicketView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Buying Tickets", emoji="<:GsBuying:1415290878964142110>",
                       style=discord.ButtonStyle.secondary, custom_id="panel_buy")
    async def buy_button(self, interaction: discord.Interaction, button: Button):
        await create_ticket(interaction, TICKET_CATEGORY_1, "buying")

    @discord.ui.button(label="Support Tickets", emoji="<:GsSupport:1415290793681490000>",
                       style=discord.ButtonStyle.secondary, custom_id="panel_support")
    async def support_button(self, interaction: discord.Interaction, button: Button):
        await create_ticket(interaction, TICKET_CATEGORY_2, "support")

class TicketActionView(View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.secondary, custom_id="ticket_close")
    async def close_btn(self, interaction: discord.Interaction, button: Button):
        # only staff
        guild = interaction.guild
        staff_role = guild.get_role(STAFF_ROLE_ID)
        if not staff_role or staff_role not in interaction.user.roles:
            return await interaction.response.send_message(embed=discord.Embed(
                description="<:GsWrong:1414561861352816753> You can’t use this.", color=0x000000), ephemeral=True)
        # show confirm
        await show_confirmation(interaction, action="close")

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.secondary, custom_id="ticket_delete")
    async def delete_btn(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        staff_role = guild.get_role(STAFF_ROLE_ID)
        if not staff_role or staff_role not in interaction.user.roles:
            return await interaction.response.send_message(embed=discord.Embed(
                description="<:GsWrong:1414561861352816753> You can’t use this.", color=0x000000), ephemeral=True)
        await show_confirmation(interaction, action="delete")

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.secondary, custom_id="ticket_claim")
    async def claim_btn(self, interaction: discord.Interaction, button: Button):
        guild = interaction.guild
        staff_role = guild.get_role(STAFF_ROLE_ID)
        if not staff_role or staff_role not in interaction.user.roles:
            return await interaction.response.send_message(embed=discord.Embed(
                description="<:GsWrong:1414561861352816753> You can’t use this.", color=0x000000), ephemeral=True)
        await show_confirmation(interaction, action="claim")

# helper to show the gold confirmation prompt (edits the same message)
async def show_confirmation(interaction: discord.Interaction, action: str):
    """
    action: "close" | "delete" | "claim"
    This edits the message the button was on into a confirmation embed (gold),
    with Yes/No buttons. On cancel it reverts to original embed + TicketActionView.
    """
    action_readable = {"close": "Close",
                       "delete": "Delete",
                       "claim": "Claim"}.get(action, action)

    confirm_embed = discord.Embed(
        title="Confirm action",
        description=f"Are you sure you want to **{action_readable}**?",
        color=GOLD
    )

    original_message = interaction.message
    original_embed = original_message.embeds[0] if original_message.embeds else None

    # If embed missing, try to recover from persistent DB (use stored action_message_id for this channel)
    if not original_embed:
        meta = _tickets_db.get("tickets", {}).get(str(interaction.channel.id))
        if meta and meta.get("action_message_id"):
            try:
                msg = await interaction.channel.fetch_message(meta["action_message_id"])
                if msg.embeds:
                    original_embed = msg.embeds[0]
            except Exception:
                original_embed = None

    class ConfirmView(View):
        def __init__(self, action, original_embed):
            super().__init__(timeout=30)
            self.action = action
            self.original_embed = original_embed

        @discord.ui.button(label="Yes", emoji="<:GsRight:1414593140156792893>",
                           style=discord.ButtonStyle.secondary, custom_id="confirm_yes")
        async def yes(self, yes_i: discord.Interaction, button: Button):
            # double-check staff
            guild = yes_i.guild
            staff_role = guild.get_role(STAFF_ROLE_ID)
            if not staff_role or staff_role not in yes_i.user.roles:
                return await yes_i.response.send_message(embed=discord.Embed(
                    description="<:GsWrong:1414561861352816753> You can’t use this.", color=0x000000), ephemeral=True)

            # perform the desired action on the channel where the button was pressed
            channel = yes_i.channel
            # fetch fresh channel object
            channel = guild.get_channel(channel.id)
            # perform
            if self.action == "close":
                await do_close_ticket(channel, yes_i.user)
                # confirm to the interactor and remove view
                await yes_i.response.edit_message(embed=discord.Embed(
                    description=f"<:GsRight:1414593140156792893> Ticket closed (user removed) by {yes_i.user.mention}.",
                    color=0x000000), view=None)
            elif self.action == "delete":
                await do_delete_ticket(channel, yes_i.user)
                await yes_i.response.edit_message(embed=discord.Embed(
                    description=f"<:GsRight:1414593140156792893> Ticket deleted by {yes_i.user.mention}.",
                    color=0x000000), view=None)
            elif self.action == "claim":
                await do_claim_ticket(channel, yes_i.user)
                await yes_i.response.edit_message(embed=discord.Embed(
                    description=f"<:GsRight:1414593140156792893> Ticket claimed by {yes_i.user.mention}.",
                    color=0x000000), view=None)
            else:
                await yes_i.response.edit_message(embed=discord.Embed(
                    description="Unknown action.", color=0x000000), view=None)

        @discord.ui.button(label="No", emoji="<:GsWrong:1414561861352816753>",
                           style=discord.ButtonStyle.secondary, custom_id="confirm_no")
        async def no(self, no_i: discord.Interaction, button: Button):
            # revert the original embed + view
            await no_i.response.edit_message(embed=self.original_embed or discord.Embed(
                description="Ticket actions", color=0x000000), view=TicketActionView())

    await interaction.response.edit_message(embed=confirm_embed, view=ConfirmView(action, original_embed))

# ---------------- Core action implementations ----------------
async def do_close_ticket(channel: discord.TextChannel, action_by: discord.Member):
    """Remove ticket creator's access (do not delete channel), rename to closed-..., produce transcript & log."""
    guild = channel.guild
    staff_role = guild.get_role(STAFF_ROLE_ID)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)

    # try to get creator and claimer from DB first
    meta = _tickets_db.get("tickets", {}).get(str(channel.id), {})
    creator_id = meta.get("creator_id")
    claimer_id = meta.get("claimer_id")

    # fallback to topic parsing if DB empty
    if not creator_id and channel.topic:
        parts = channel.topic.split(";")
        if parts and parts[0].isdigit():
            creator_id = int(parts[0])
        if len(parts) > 1 and parts[1].isdigit():
            claimer_id = int(parts[1])

    ticket_creator = guild.get_member(creator_id) if creator_id else None

    # collect staff who replied before changing perms
    staff_members, staff_mentions = await gather_staff_who_spoke(channel, staff_role)

    # create transcript
    transcript = await make_transcript(channel)

    # remove creator permissions (revoke view/send)
    if ticket_creator:
        try:
            await channel.set_permissions(ticket_creator, overwrite=discord.PermissionOverwrite(view_channel=False, send_messages=False))
        except Exception:
            pass

    # optionally rename channel to indicate closed
    try:
        if not channel.name.startswith("closed-"):
            await channel.edit(name=f"closed-{channel.name}")
    except Exception:
        pass

    # log embed + ping creators/staff in content to ensure they are notified (embeds don't always ping)
    embed = discord.Embed(
        title="<:GsTicketsStyle2:1415298853598396509>  Ticket Closed (user removed)",
        color=GOLD,
        timestamp=datetime.datetime.utcnow()
    )
    embed.add_field(name="Ticket Creator", value=(ticket_creator.mention if ticket_creator else "Unknown"), inline=False)
    embed.add_field(name="Closed By", value=action_by.mention, inline=False)
    embed.add_field(name="Staff Involved", value=(staff_mentions), inline=False)
    if log_channel:
        content_ping = ""
        if ticket_creator:
            content_ping += f"{ticket_creator.mention} "
        if staff_members:
            content_ping += " ".join(m.mention for m in staff_members)
        # send content ping and embed & transcript
        try:
            await log_channel.send(content=content_ping or None, embed=embed, file=transcript)
        except Exception:
            # fallback without content ping
            await log_channel.send(embed=embed, file=transcript)

    # mark closed in DB (do not delete entry so we can audit later)
    meta_key = str(channel.id)
    if meta_key in _tickets_db.get("tickets", {}):
        _tickets_db["tickets"][meta_key]["closed"] = True
        _tickets_db["tickets"][meta_key]["closed_at"] = datetime.datetime.utcnow().isoformat()
        await save_db()

async def do_delete_ticket(channel: discord.TextChannel, action_by: discord.Member):
    """Make transcript, log and delete channel."""
    guild = channel.guild
    staff_role = guild.get_role(STAFF_ROLE_ID)
    log_channel = guild.get_channel(LOG_CHANNEL_ID)

    # identify creator from DB first
    creator_id = None
    meta = _tickets_db.get("tickets", {}).get(str(channel.id), {})
    if meta:
        creator_id = meta.get("creator_id")

    # fallback to topic
    if not creator_id and channel.topic:
        parts = channel.topic.split(";")
        if parts and parts[0].isdigit():
            creator_id = int(parts[0])
    ticket_creator = guild.get_member(creator_id) if creator_id else None

    staff_members, staff_mentions = await gather_staff_who_spoke(channel, staff_role)
    transcript = await make_transcript(channel)

    embed = discord.Embed(
        title="<:GsTicketsStyle2:1415298853598396509>  Ticket Deleted",
        description=f"Deleted by {action_by.mention}",
        color=GOLD,
        timestamp=datetime.datetime.utcnow()
    )
    embed.add_field(name="User", value=(ticket_creator.mention if ticket_creator else "Unknown (topic missing)"), inline=False)
    embed.add_field(name="Staff Involved", value=staff_mentions, inline=False)
    if log_channel:
        content_ping = ""
        if ticket_creator:
            content_ping += f"{ticket_creator.mention} "
        if staff_members:
            content_ping += " ".join(m.mention for m in staff_members)
        try:
            await log_channel.send(content=content_ping or None, embed=embed, file=transcript)
        except Exception:
            await log_channel.send(embed=embed, file=transcript)

    # remove from DB (if present)
    meta_key = str(channel.id)
    if meta_key in _tickets_db.get("tickets", {}):
        del _tickets_db["tickets"][meta_key]
        await save_db()

    # delete after logging
    await channel.delete()

async def do_claim_ticket(channel: discord.TextChannel, claimer: discord.Member):
    """Give exclusive send permissions to claimer, others staff can view only."""
    guild = channel.guild
    staff_role = guild.get_role(STAFF_ROLE_ID)

    # find creator id from DB or topic
    meta_key = str(channel.id)
    meta = _tickets_db.get("tickets", {}).get(meta_key, {})
    creator_id = meta.get("creator_id")
    current_claimer = meta.get("claimer_id")

    if not creator_id and channel.topic:
        parts = channel.topic.split(";")
        if parts and parts[0].isdigit():
            creator_id = int(parts[0])
    # set staff role send_messages=False (view True)
    try:
        await channel.set_permissions(staff_role, view=True, send_messages=False)
    except Exception:
        pass
    # set claimer perms
    await channel.set_permissions(claimer, view=True, send_messages=True)

    # update channel.topic to include claimer id (creator;claimer)
    creator_part = str(creator_id) if creator_id else ""
    try:
        await channel.edit(topic=f"{creator_part};{claimer.id}")
    except Exception:
        pass

    # update DB
    _tickets_db.setdefault("tickets", {}).setdefault(meta_key, {})
    _tickets_db["tickets"][meta_key]["creator_id"] = creator_id
    _tickets_db["tickets"][meta_key]["claimer_id"] = claimer.id
    await save_db()

    # log claim in log channel
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    embed = discord.Embed(title="<:GsTicketsStyle2:1415298853598396509>  Ticket Claimed",
                          description=f"Claimed by {claimer.mention}",
                          color=GOLD,
                          timestamp=datetime.datetime.utcnow())
    if log_channel:
        await log_channel.send(embed=embed)

# ---------------- Create a ticket (stores creator id in DB & topic), posts ticket-action message inside ticket ----------------
async def create_ticket(interaction: discord.Interaction, category_id: int, ticket_type: str):
    guild = interaction.guild
    staff_role = guild.get_role(STAFF_ROLE_ID)
    category = guild.get_channel(category_id)
    if not staff_role or not category:
        return await interaction.response.send_message(embed=discord.Embed(
            description="<:GsWrong:1414561861352816753> Ticket system not set up properly. Contact an admin.",
            color=0x000000), ephemeral=True)

    # prepare overwrites
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        staff_role: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }

    # create channel and set topic to "creatorID;" (claimer blank)
    # sanitize name (keep your original style but avoid illegal chars)
    safe_name_user = re.sub(r"[^0-9a-zA-Z-_]", "", f"{interaction.user.name}")[:32]
    name_safe = f"{ticket_type}-ticket-{safe_name_user}-{interaction.user.discriminator}"
    ticket_channel = await guild.create_text_channel(
        name=name_safe,
        overwrites=overwrites,
        category=category,
        topic=f"{interaction.user.id};"  # creatorID ; claimerID (empty)
    )

    # send initial embed + ticket action buttons (persistent)
    embed = discord.Embed(
        title=f"{ticket_type.capitalize()} Ticket",
        description=f"{interaction.user.mention} this ticket has been created. Use the buttons below (staff only).",
        color=GOLD,
        timestamp=datetime.datetime.utcnow()
    )
    # send and capture message so we can persist its id
    action_msg = await ticket_channel.send(embed=embed, view=TicketActionView())

    # store ticket metadata to DB (persistent)
    _tickets_db.setdefault("tickets", {})[str(ticket_channel.id)] = {
        "creator_id": interaction.user.id,
        "claimer_id": None,
        "action_message_id": action_msg.id,
        "created_at": datetime.datetime.utcnow().isoformat()
    }
    await save_db()

    # respond to user
    await interaction.response.send_message(embed=discord.Embed(
        description=f"{ticket_type.capitalize()} Ticket created: {ticket_channel.mention} <:GsRight:1414593140156792893>",
        color=0x000000
    ), ephemeral=True)

# ---------------- Panel command (restricted to single user) ----------------
@bot.command(name="ticketpanel")
async def ticketpanel(ctx):
    if ctx.author.id != PANEL_ALLOWED_USER:
        return await ctx.send(embed=discord.Embed(
            description="<:GsWrong:1414561861352816753> You are not allowed to use this command.",
            color=0x000000
        ))
    embed = discord.Embed(
        title="<:GsTicketsStyle2:1415298853598396509>  GS Tickets",
        description=(
            "Choose the type of ticket you want to open below:\n\n"
            "<:GsBuying:1415290878964142110> **Buying Tickets** → For purchases and orders.\n\n"
            "<:GsSupport:1415290793681490000> **Support Tickets** → For help and general assistance."
        ),
        color=0x000000
    )
    embed.set_thumbnail(url="https://media.discordapp.net/attachments/1378099122497785976/1415323351878078474/image.png?format=webp&quality=lossless")
    embed.set_image(url="https://media.discordapp.net/attachments/1378099122497785976/1415309148697919581/image.png?format=webp&quality=lossless")
    panel_msg = await ctx.send(embed=embed, view=TicketView())

    # persist panel message so we can re-attach view after restarts
    _tickets_db.setdefault("panels", []).append({"channel_id": ctx.channel.id, "message_id": panel_msg.id})
    await save_db()

# ---------------- gs.delete command (same flow as Delete button) ----------------
@bot.command(name="delete")
async def delete_cmd(ctx):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if not staff_role or staff_role not in ctx.author.roles:
        return await ctx.send(embed=discord.Embed(description="<:GsWrong:1414561861352816753> You don’t have permission.", color=0x000000))

    if not ctx.channel.name.startswith(("buying-ticket-", "support-ticket-", "closed-support", "closed-buying")):
        return await ctx.send(embed=discord.Embed(description="<:GsWrong:1414561861352816753> This command can only be used in a ticket channel.", color=0x000000))

    # show confirmation inline (reusing show_confirmation by synthesizing an "interaction-like" edit)
    # easiest: send a new confirmation message for the command:
    confirm_embed = discord.Embed(title="Confirm delete", description="Are you sure you want to delete this ticket?", color=GOLD)
    class DeleteConfirm(View):
        @discord.ui.button(label="Yes", emoji="<:GsRight:1414593140156792893>", style=discord.ButtonStyle.secondary)
        async def yes(self, interaction: discord.Interaction, button: Button):
            staff_role_local = ctx.guild.get_role(STAFF_ROLE_ID)
            if staff_role_local not in interaction.user.roles:
                return await interaction.response.send_message("<:GsWrong:1414561861352816753> You can’t use this.", ephemeral=True)
            await do_delete_ticket(ctx.channel, interaction.user)
            await interaction.response.edit_message(embed=discord.Embed(description="Deleted.", color=0x000000), view=None)
        @discord.ui.button(label="No", emoji="<:GsWrong:1414561861352816753>", style=discord.ButtonStyle.secondary)
        async def no(self, interaction: discord.Interaction, button: Button):
            await interaction.response.edit_message(embed=discord.Embed(description="<:GsWrong:1414561861352816753> Action denied.", color=0x000000), view=None)

    await ctx.send(embed=confirm_embed, view=DeleteConfirm())

# ---------------- gs.claim command (with gold confirmation) ----------------
@bot.command(name="claim")
async def claim_cmd(ctx):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if not staff_role or staff_role not in ctx.author.roles:
        return await ctx.send(embed=discord.Embed(description="<:GsWrong:1414561861352816753> You don’t have permission.", color=0x000000))
    if not ctx.channel.name.startswith(("buying-ticket-", "support-ticket-")):
        return await ctx.send(embed=discord.Embed(description="<:GsWrong:1414561861352816753> This command can only be used in a ticket channel.", color=0x000000))

    confirm_embed = discord.Embed(title="Claim ticket", description=f"{ctx.author.mention}, do you want to claim this ticket?", color=GOLD)
    class ClaimConfirm(View):
        @discord.ui.button(label="Yes", emoji="<:GsRight:1414593140156792893>", style=discord.ButtonStyle.secondary)
        async def yes(self, interaction: discord.Interaction, button: Button):
            staff_role_local = ctx.guild.get_role(STAFF_ROLE_ID)
            if staff_role_local not in interaction.user.roles:
                return await interaction.response.send_message("<:GsWrong:1414561861352816753> You can’t use this.", ephemeral=True)
            await do_claim_ticket(ctx.channel, interaction.user)
            await interaction.response.edit_message(embed=discord.Embed(description=f"<:GsRight:1414593140156792893> Ticket claimed by {interaction.user.mention}.", color=0x000000), view=None)
        @discord.ui.button(label="No", emoji="<:GsWrong:1414561861352816753>", style=discord.ButtonStyle.secondary)
        async def no(self, interaction: discord.Interaction, button: Button):
            await interaction.response.edit_message(embed=discord.Embed(description="<:GsWrong:1414561861352816753> Claim cancelled.", color=0x000000), view=None)

    await ctx.send(embed=confirm_embed, view=ClaimConfirm())

# ---------------- gs.transfer @member (give claim to another staff) ----------------
@bot.command(name="transfer")
async def transfer_cmd(ctx, member: discord.Member):
    staff_role = ctx.guild.get_role(STAFF_ROLE_ID)
    if not staff_role or staff_role not in ctx.author.roles:
        return await ctx.send(embed=discord.Embed(description="<:GsWrong:1414561861352816753> You don’t have permission.", color=0x000000))
    if not ctx.channel.name.startswith(("buying-ticket-", "support-ticket-")):
        return await ctx.send(embed=discord.Embed(description="<:GsWrong:1414561861352816753> This command can only be used in a ticket channel.", color=0x000000))
    # target must be staff
    if staff_role not in member.roles:
        return await ctx.send(embed=discord.Embed(description="<:GsWrong:1414561861352816753> Target is not staff.", color=0x000000))

    # set staff role perms to view only, make member send_messages True
    await ctx.channel.set_permissions(staff_role, view=True, send_messages=False)
    await ctx.channel.set_permissions(member, view=True, send_messages=True)
    # update topic claimer part while preserving creator id
    creator_part = ""
    if ctx.channel.topic:
        parts = ctx.channel.topic.split(";")
        if parts and parts[0].isdigit():
            creator_part = parts[0]
    await ctx.channel.edit(topic=f"{creator_part};{member.id}")

    # update DB
    meta_key = str(ctx.channel.id)
    _tickets_db.setdefault("tickets", {}).setdefault(meta_key, {})
    _tickets_db["tickets"][meta_key]["claimer_id"] = member.id
    await save_db()

    await ctx.send(embed=discord.Embed(description=f"Ticket transferred to {member.mention}.", color=GOLD))

# ---------------- Register persistent views on_ready and reattach to messages ----------------
VIEWS_REGISTERED = False

@bot.event
async def on_ready():
    global VIEWS_REGISTERED
    if not VIEWS_REGISTERED:
        try:
            bot.add_view(TicketView())
            bot.add_view(TicketActionView())
            VIEWS_REGISTERED = True
            print(f"Registered persistent views as {bot.user}")
        except Exception as e:
            print("Failed to register persistent views on startup:", e)

    # re-attach views to existing messages (action messages + panel messages)
    # This helps the bot "remember" embeds and make buttons work after restart
    # Migrate any existing ticket channels (that use naming convention) into DB if missing
    try:
        # migrate channels that look like tickets and are not yet in DB
        for channel in bot.get_all_channels():
            if not isinstance(channel, discord.TextChannel):
                continue
            if channel.name.startswith(("buying-ticket-", "support-ticket-")):
                key = str(channel.id)
                if key not in _tickets_db.get("tickets", {}):
                    # try to infer creator/claimer from topic
                    creator_id = None
                    claimer_id = None
                    if channel.topic:
                        parts = channel.topic.split(";")
                        if parts and parts[0].isdigit():
                            creator_id = int(parts[0])
                        if len(parts) > 1 and parts[1].isdigit():
                            claimer_id = int(parts[1])
                    # try to find the bot's action message in recent history
                    action_msg_id = None
                    async for msg in channel.history(limit=200):
                        if msg.author == bot.user and msg.embeds:
                            action_msg_id = msg.id
                            break
                    _tickets_db.setdefault("tickets", {})[key] = {
                        "creator_id": creator_id,
                        "claimer_id": claimer_id,
                        "action_message_id": action_msg_id,
                        "created_at": datetime.datetime.utcnow().isoformat()
                    }
                    await save_db()

        # reattach views to action messages
        for ch_id, meta in list(_tickets_db.get("tickets", {}).items()):
            try:
                channel = bot.get_channel(int(ch_id))
                if not channel:
                    continue
                msg_id = meta.get("action_message_id")
                if not msg_id:
                    continue
                try:
                    msg = await channel.fetch_message(int(msg_id))
                    # attach the persistent view to this message so interactions work after restart
                    await msg.edit(view=TicketActionView())
                except Exception as e:
                    print(f"Could not reattach TicketActionView to message {msg_id} in channel {ch_id}:", e)
            except Exception:
                continue

        # reattach views to panel messages
        for panel in _tickets_db.get("panels", []):
            try:
                channel = bot.get_channel(int(panel.get("channel_id")))
                if not channel:
                    continue
                msg = await channel.fetch_message(int(panel.get("message_id")))
                await msg.edit(view=TicketView())
            except Exception as e:
                # don't crash startup on bad panels
                print("Could not reattach TicketView to panel message:", e)
    except Exception as e:
        print("Error during on_ready reattach/migrate:", e)

# ---------------- End of Ticket System block ----------------
# Keep your customizations (emojis, gold color, thumbnails), this version fixes:
#  - persistent views properly re-registered on_ready
#  - action / panel message ids stored on-disk so views can be re-attached after restart
#  - ticket creator/claimer metadata stored on-disk (tickets.json) and migrated from existing channel topics when possible
#  - show_confirmation will attempt to recover the original embed from the stored action message if the interaction message lacks it

# Note: run the bot as usual: bot.run("YOUR_TOKEN") in your main runner script.

# ---------------- Bot wrapper class ----------------
class DiscordBot:
    def __init__(self):
        self.bot = bot

    async def start(self, token):
        await self.bot.start(token)

    async def close(self):
        await self.bot.close()

# Load pet data immediately when module is imported
try:
    load_pet_data()
except Exception as e:
    logger.error(f"Failed to load pet data at module import: {e}")