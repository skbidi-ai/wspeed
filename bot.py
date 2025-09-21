import discord
from discord.ext import commands
import logging
import asyncio
import re

logger = logging.getLogger(__name__)

class DiscordBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='gs.', intents=intents)
        
        # Target channel ID
        self.target_channel_id = 1401169397850308708
        
        # WFL pattern (case-insensitive)
        self.wfl_pattern = re.compile(r'\bwfl\b', re.IGNORECASE)
        
        # Rate limiting
        self.last_reaction_time = {}
        self.reaction_cooldown = 1  # 1 second cooldown between reactions
        
        # Pet weight formula - base weights at each age
        self.base_weights = {
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
        


    async def on_ready(self):
        """Called when the bot is ready"""
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Bot is in {len(self.guilds)} guilds')
        
        # Verify target channel exists
        target_channel = self.get_channel(self.target_channel_id)
        if target_channel:
            logger.info(f'Monitoring channel: {target_channel.name} ({target_channel.id})')
        else:
            logger.warning(f'Target channel {self.target_channel_id} not found')

    async def on_message(self, message):
        """Handle incoming messages"""
        # Ignore bot messages
        if message.author.bot:
            return
        
        # Process commands first
        await self.process_commands(message)
        
        # Check if message is in target channel for WFL reactions
        if message.channel.id != self.target_channel_id:
            return
        
        # Check if message contains "wfl" (case-insensitive)
        if not self.wfl_pattern.search(message.content):
            return
        
        # Rate limiting check
        current_time = asyncio.get_event_loop().time()
        if (message.channel.id in self.last_reaction_time and 
            current_time - self.last_reaction_time[message.channel.id] < self.reaction_cooldown):
            logger.debug(f'Rate limit: Skipping reaction for message {message.id}')
            return
        
        self.last_reaction_time[message.channel.id] = current_time
        
        # React with W, F, L emojis
        await self.add_wfl_reactions(message)

    async def add_wfl_reactions(self, message):
        """Add W, F, L reactions to a message"""
        reactions = ['W1', 'F1', 'L1']  # Custom server emojis for W, F, L
        
        try:
            for emoji_name in reactions:
                # Try to find the custom emoji in the server
                emoji = discord.utils.get(message.guild.emojis, name=emoji_name)
                if emoji:
                    await message.add_reaction(emoji)
                    logger.info(f'Added reaction :{emoji_name}: to message {message.id} in {message.channel.name}')
                else:
                    logger.warning(f'Custom emoji :{emoji_name}: not found in server {message.guild.name}')
                # Small delay between reactions to avoid rate limits
                await asyncio.sleep(0.5)
                
        except discord.HTTPException as e:
            if e.status == 429:  # Rate limited
                logger.warning(f'Rate limited while adding reactions to message {message.id}')
            else:
                logger.error(f'HTTP error adding reactions to message {message.id}: {e}')
        except discord.Forbidden:
            logger.error(f'Missing permissions to add reactions to message {message.id}')
        except discord.NotFound:
            logger.error(f'Message {message.id} not found when trying to add reactions')
        except Exception as e:
            logger.error(f'Unexpected error adding reactions to message {message.id}: {e}')

    async def on_error(self, event, *args, **kwargs):
        """Handle errors"""
        logger.error(f'Error in event {event}', exc_info=True)

    async def on_command_error(self, ctx, error):
        """Handle command errors"""
        logger.error(f'Command error: {error}', exc_info=True)

    def calculate_weight_multiplier(self, current_age, current_weight):
        """Calculate the multiplier based on current age and weight"""
        if current_age not in self.base_weights:
            return None
        
        base_weight_at_current_age = self.base_weights[current_age]
        multiplier = current_weight / base_weight_at_current_age
        return multiplier

    def predict_weights(self, current_age, current_weight, target_ages=None):
        """Predict weights for specified ages based on current data"""
        multiplier = self.calculate_weight_multiplier(current_age, current_weight)
        if multiplier is None:
            return None
        
        if target_ages is None:
            target_ages = list(range(1, 101))
        
        predictions = {}
        for age in target_ages:
            if age in self.base_weights:
                predicted_weight = self.base_weights[age] * multiplier
                predictions[age] = round(predicted_weight, 2)
        
        return predictions

    @commands.command()
    async def petweight(self, ctx, current_age: int, current_weight: float, target_age: int = None):
        """Calculate pet weight at different ages
        Usage: gs.petweight <current_age> <current_weight> [target_age]
        Example: gs.petweight 5 2.5 10
        """
        try:
            # Validate input
            if current_age < 1 or current_age > 100:
                await ctx.send("<:GsWrong:1414561861352816753>   Age must be between 1 and 100")
                return
            
            if current_weight <= 0:
                await ctx.send("<:GsWrong:1414561861352816753>   Weight must be greater than 0")
                return
            
            # If target_age is specified, calculate for that age only
            if target_age is not None:
                if target_age < 1 or target_age > 100:
                    await ctx.send("<:GsWrong:1414561861352816753>   Target age must be between 1 and 100")
                    return
                
                predictions = self.predict_weights(current_age, current_weight, [target_age])
                if predictions is None:
                    await ctx.send("<:GsWrong:1414561861352816753>   Invalid age provided")
                    return
                
                predicted_weight = predictions[target_age]
                
                embed = discord.Embed(
                    title=" Pet Weight Prediction",
                    color=0x4CAF50
                )
                embed.add_field(
                    name="Current Info",
                    value=f"Age: {current_age} | Weight: {current_weight} kg",
                    inline=False
                )
                embed.add_field(
                    name=f"Predicted Weight at Age {target_age}",
                    value=f"**{predicted_weight} kg**",
                    inline=False
                )
                
                await ctx.send(embed=embed)
            
            else:
                # Show weight progression for key ages
                predictions = self.predict_weights(current_age, current_weight)
                if predictions is None:
                    await ctx.send("<:GsWrong:1414561861352816753>   Invalid age provided")
                    return
                
                # Show current age + next 10 ages
                key_ages = []
                for age in range(current_age, min(current_age + 50, 101)):
                    if age in predictions:
                        key_ages.append(age)
                
                # If we don't have 10 ages ahead, show some before
                if len(key_ages) < 10:
                    for age in range(max(1, current_age - 5), current_age):
                        if age in predictions and age not in key_ages:
                            key_ages.insert(0, age)
                
                key_ages = sorted(key_ages)[:50]  # Limit to 10 ages
                
                embed = discord.Embed(
                    title="🐾 Pet Weight Progression",
                    color=0x2196F3
                )
                embed.add_field(
                    name="Current Info",
                    value=f"Age: {current_age} | Weight: {current_weight} kg",
                    inline=False
                )
                
                weight_text = ""
                for age in key_ages:
                    marker = " ← **Current**" if age == current_age else ""
                    weight_text += f"Age {age}: {predictions[age]} kg{marker}\n"
                
                embed.add_field(
                    name="GS Pet Weight Predictions",
                    value=weight_text,
                    inline=False
                )
                embed.add_field(
                    name="💡 Tip",
                    value="Use `gs.petweight <age> <weight> <target_age>` to predict weight at a specific age",
                    inline=False
                )
                
                await ctx.send(embed=embed)
                
        except ValueError:
            await ctx.send("<:GsWrong:1414561861352816753>   Please provide valid numbers for age and weight")
        except Exception as e:
            logger.error(f"Error in petweight command: {e}")
            await ctx.send("<:GsWrong:1414561861352816753>   An error occurred while calculating weights")

    async def close(self):
        """Clean shutdown"""
        logger.info('Shutting down Discord bot...')
        await super().close()
