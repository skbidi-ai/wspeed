from flask import Flask, jsonify, request, render_template
import logging
import datetime
import os
import json
from fixed_bot import BASE_WEIGHTS, PET_DATABASE, save_pet_data
import copy
import asyncio
import discord

logger = logging.getLogger(__name__)

def create_app():
    """Create and configure Flask application"""
    app = Flask(__name__)
    
    # Store bot start time
    start_time = datetime.datetime.utcnow()
    
    # Discord notification helper
    def notify_discord(pet_name, action, old_values=None, new_values=None):
        """Schedule Discord notification"""
        try:
            import threading
            from fixed_bot import bot
            
            def send_notification():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(_send_discord_notification(pet_name, action, old_values, new_values))
                    loop.close()
                except Exception as e:
                    logger.error(f"Error in notification thread: {e}")
            
            thread = threading.Thread(target=send_notification)
            thread.daemon = True
            thread.start()
        except Exception as e:
            logger.error(f"Failed to schedule Discord notification: {e}")
    
    async def _send_discord_notification(pet_name, action, old_values=None, new_values=None):
        """Send pet update notification to Discord channel"""
        try:
            from fixed_bot import bot
            channel_id = 1414528231834386545
            channel = bot.get_channel(channel_id)
            
            if not channel:
                logger.warning(f"Could not find Discord channel {channel_id}")
                return
            
            embed = discord.Embed(
                title="🐾 Pet Database Update",
                color=0xFFC916,
                timestamp=datetime.datetime.utcnow()
            )
            
            if action == "added":
                embed.add_field(
                    name="➕ New Pet Added",
                    value=f"**{pet_name}**",
                    inline=False
                )
                if new_values:
                    embed.add_field(
                        name="📊 Pet Details",
                        value=f"**Value:** {new_values.get('value', 'N/A')}\n**Demand:** {new_values.get('demand', 'N/A')}\n**Trend:** {new_values.get('trend', 'N/A')}\n**Tier:** {new_values.get('tier', 'N/A')}",
                        inline=True
                    )
            elif action == "updated":
                embed.add_field(
                    name="✏️ Pet Updated",
                    value=f"**{pet_name}**",
                    inline=False
                )
                
                changes = []
                if old_values and new_values:
                    for field, new_val in new_values.items():
                        old_val = old_values.get(field, 'N/A')
                        if old_val != new_val:
                            changes.append(f"**{field.title()}:** {old_val} → {new_val}")
                
                if changes:
                    embed.add_field(
                        name="📈 Changes Made",
                        value="\n".join(changes),
                        inline=False
                    )
            elif action == "deleted":
                embed.add_field(
                    name="🗑️ Pet Deleted",
                    value=f"**{pet_name}**",
                    inline=False
                )
                if old_values:
                    embed.add_field(
                        name="📊 Previous Details",
                        value=f"**Value:** {old_values.get('value', 'N/A')}\n**Demand:** {old_values.get('demand', 'N/A')}\n**Trend:** {old_values.get('trend', 'N/A')}\n**Tier:** {old_values.get('tier', 'N/A')}",
                        inline=True
                    )
            
            embed.set_footer(text="🌐 Updated via Admin Website")
            await channel.send(embed=embed)
            logger.info(f"Sent Discord notification for {action} action on {pet_name}")
            
        except Exception as e:
            logger.error(f"Failed to send Discord notification: {e}")
    
    @app.route('/')
    def home():
        """Serve the main website with all three tabs"""
        return render_template('index.html')
    
    @app.route('/health')
    def health_check():
        """Basic health check endpoint"""
        return jsonify({
            'status': 'healthy',
            'service': 'Discord WFL Bot',
            'timestamp': datetime.datetime.utcnow().isoformat(),
            'uptime_seconds': (datetime.datetime.utcnow() - start_time).total_seconds()
        })
    
    @app.route('/uptime')
    def uptime():
        """Uptime monitoring endpoint"""
        uptime_delta = datetime.datetime.utcnow() - start_time
        uptime_seconds = uptime_delta.total_seconds()
        
        return jsonify({
            'status': 'online',
            'uptime_seconds': uptime_seconds,
            'uptime_human': str(uptime_delta),
            'start_time': start_time.isoformat(),
            'current_time': datetime.datetime.utcnow().isoformat()
        })
    
    @app.route('/status')
    def status():
        """Detailed status endpoint"""
        return jsonify({
            'bot_name': 'Discord WFL Bot',
            'version': '1.0.0',
            'status': 'running',
            'monitoring_channel': '1401169397850308708',
            'reaction_emojis': [':W1:', ':F1:', ':L1:'],
            'uptime_seconds': (datetime.datetime.utcnow() - start_time).total_seconds(),
            'environment': {
                'python_version': os.sys.version.split()[0],
                'discord_token_configured': bool(os.getenv('DISCORD_TOKEN'))
            }
        })
    
    @app.route('/calculate', methods=['POST'])
    def calculate_weight():
        """Calculate pet weights based on age and current weight"""
        try:
            data = request.json
            current_age = data.get('age')
            current_weight = data.get('weight')
            
            if not current_age or not current_weight:
                return jsonify({'error': 'Age and weight are required'}), 400
                
            if current_age < 1 or current_age > 100:
                return jsonify({'error': 'Age must be between 1 and 100'}), 400
                
            if current_weight <= 0:
                return jsonify({'error': 'Weight must be greater than 0'}), 400
            
            # Calculate base weight ratio
            current_base_weight = BASE_WEIGHTS.get(current_age, 1.0)
            weight_ratio = current_weight / current_base_weight
            
            # Calculate predictions for all ages
            predictions = {}
            for age in range(1, 101):
                base_weight = BASE_WEIGHTS.get(age, 1.0)
                predicted_weight = round(base_weight * weight_ratio, 2)
                predictions[age] = predicted_weight
            
            return jsonify({
                'current_age': current_age,
                'current_weight': current_weight,
                'predictions': predictions
            })
            
        except Exception as e:
            logger.error(f'Error in weight calculation: {e}')
            return jsonify({'error': 'Calculation failed'}), 500
    
    @app.route('/calculate-values', methods=['POST'])
    def calculate_values():
        """Calculate pet value predictions (elvebredd-style)"""
        try:
            data = request.json
            pet_name = data.get('pet_name', '')
            current_value = data.get('current_value', 0)
            demand = data.get('demand', 'Medium')
            trend = data.get('trend', 'Stable')
            tier = data.get('tier', 'Common')
            time_horizon = data.get('time_horizon', 30)
            
            # Value calculation logic (elvebredd-style)
            multipliers = {
                'demand': {
                    'Terrible': 0.7,
                    'Low': 0.85, 
                    'Medium': 1.0,
                    'High': 1.3,
                    'Extremely High': 1.6
                },
                'trend': {
                    'Dropping': 0.8,
                    'Stable': 1.0,
                    'Rising': 1.2
                },
                'tier': {
                    'Common': 0.9,
                    'Uncommon': 1.0,
                    'Rare': 1.1,
                    'Epic': 1.25,
                    'Legendary': 1.5,
                    'Divine': 1.8
                }
            }
            
            # Calculate base multiplier
            demand_mult = multipliers['demand'].get(demand, 1.0)
            trend_mult = multipliers['trend'].get(trend, 1.0)
            tier_mult = multipliers['tier'].get(tier, 1.0)
            
            # Time factor (compound effect over time)
            daily_change = (trend_mult - 1) * 0.1  # 10% of trend effect per month
            time_mult = (1 + daily_change) ** (time_horizon / 30)
            
            # Calculate predicted value
            total_mult = demand_mult * trend_mult * tier_mult * time_mult
            predicted_value = round(current_value * total_mult)
            
            # Determine prediction trend
            if predicted_value > current_value * 1.1:
                prediction_trend = 'positive'
            elif predicted_value < current_value * 0.9:
                prediction_trend = 'negative'
            else:
                prediction_trend = 'neutral'
            
            # Investment rating
            if total_mult >= 1.5:
                investment_rating = '⭐⭐⭐ Excellent'
            elif total_mult >= 1.2:
                investment_rating = '⭐⭐ Good'
            elif total_mult >= 1.0:
                investment_rating = '⭐ Fair'
            else:
                investment_rating = '❌ Poor'
            
            # Generate analysis
            change_pct = round((predicted_value - current_value) / current_value * 100, 1)
            if change_pct > 0:
                analysis = f"Based on {demand} demand and {trend.lower()} trend, {pet_name} is expected to increase by {change_pct}% over {time_horizon} days. The {tier} tier provides additional value stability."
            elif change_pct < 0:
                analysis = f"Market analysis suggests {pet_name} may decrease by {abs(change_pct)}% over {time_horizon} days due to {demand.lower()} demand and {trend.lower()} market conditions."
            else:
                analysis = f"{pet_name} is expected to maintain stable value over {time_horizon} days with current market conditions."
            
            return jsonify({
                'pet_name': pet_name,
                'current_value': current_value,
                'predicted_value': predicted_value,
                'time_horizon': time_horizon,
                'demand': demand,
                'trend': trend,
                'tier': tier,
                'prediction_trend': prediction_trend,
                'investment_rating': investment_rating,
                'analysis': analysis,
                'change_percentage': change_pct
            })
            
        except Exception as e:
            logger.error(f'Error in value calculation: {e}')
            return jsonify({'error': 'Value calculation failed'}), 500
    
    @app.route('/pet-list')
    def get_pet_list():
        """Get list of pets for frontend"""
        try:
            pets_list = []
            for key, pet in PET_DATABASE.items():
                pets_list.append({
                    'name': pet['name'],
                    'value': pet['value'],
                    'demand': pet['demand'],
                    'trend': pet['trend'],
                    'tier': pet['tier'],
                    'obtainement': pet.get('obtainement', ''),
                    'image_url': pet.get('image_url', '')
                })
            return jsonify(pets_list)
        except Exception as e:
            logger.error(f'Error getting pet list: {e}')
            return jsonify({'error': 'Failed to load pets'}), 500
    
    @app.route('/admin/pets', methods=['GET'])
    def get_all_pets():
        """Get all pets data for admin panel"""
        try:
            return jsonify({
                'pets': PET_DATABASE,
                'count': len(PET_DATABASE)
            })
        except Exception as e:
            logger.error(f'Error getting pets data: {e}')
            return jsonify({'error': 'Failed to load pets data'}), 500
    
    @app.route('/admin/pets', methods=['POST'])
    def add_new_pet():
        """Add a new pet to the database"""
        try:
            data = request.json
            name = data.get('name', '').strip()
            
            if not name:
                return jsonify({'error': 'Pet name is required'}), 400
            
            # Create pet key (lowercase, underscores)
            pet_key = name.lower().replace(' ', '_').replace('-', '_')
            
            # Check if pet already exists
            if pet_key in PET_DATABASE:
                return jsonify({'error': f'Pet {name} already exists'}), 400
            
            # Create new pet entry
            new_pet = {
                'name': name,
                'value': data.get('value', '0 Mimic Value'),
                'demand': data.get('demand', 'Medium'),
                'trend': data.get('trend', 'Stable'),
                'tier': data.get('tier', 'Common'),
                'obtainement': data.get('obtainement', 'Unknown'),
                'image_url': data.get('image_url', ''),
                'last_updated': datetime.datetime.utcnow().isoformat(),
                'message_id': None
            }
            
            # Add to database
            PET_DATABASE[pet_key] = new_pet
            
            # Save to file
            save_pet_data()
            
            # Send Discord notification
            notify_discord(name, "added", None, new_pet)
            
            logger.info(f'Added new pet: {name} ({pet_key})')
            return jsonify({'message': f'Pet {name} added successfully', 'key': pet_key})
            
        except Exception as e:
            logger.error(f'Error adding pet: {e}')
            return jsonify({'error': 'Failed to add pet'}), 500
    
    @app.route('/admin/pets/<pet_key>', methods=['PUT'])
    def update_pet(pet_key):
        """Update an existing pet"""
        try:
            if pet_key not in PET_DATABASE:
                return jsonify({'error': 'Pet not found'}), 404
            
            data = request.json
            pet = PET_DATABASE[pet_key]
            
            # Store old values for notification
            old_values = copy.deepcopy(pet)
            
            # Update only provided fields
            updatable_fields = ['value', 'demand', 'trend', 'tier', 'obtainement', 'image_url']
            for field in updatable_fields:
                if field in data:
                    pet[field] = data[field]
            
            pet['last_updated'] = datetime.datetime.utcnow().isoformat()
            
            # Save to file
            save_pet_data()
            
            # Send Discord notification with changes
            notify_discord(pet["name"], "updated", old_values, data)
            
            logger.info(f'Updated pet: {pet["name"]} ({pet_key})')
            return jsonify({'message': f'Pet {pet["name"]} updated successfully'})
            
        except Exception as e:
            logger.error(f'Error updating pet: {e}')
            return jsonify({'error': 'Failed to update pet'}), 500
    
    @app.route('/admin/pets/<pet_key>', methods=['DELETE'])
    def delete_pet(pet_key):
        """Delete a pet from the database"""
        try:
            if pet_key not in PET_DATABASE:
                return jsonify({'error': 'Pet not found'}), 404
            
            # Store pet data for notification before deleting
            deleted_pet = copy.deepcopy(PET_DATABASE[pet_key])
            pet_name = deleted_pet['name']
            
            del PET_DATABASE[pet_key]
            
            # Save to file
            save_pet_data()
            
            # Send Discord notification
            notify_discord(pet_name, "deleted", deleted_pet, None)
            
            logger.info(f'Deleted pet: {pet_name} ({pet_key})')
            return jsonify({'message': f'Pet {pet_name} deleted successfully'})
            
        except Exception as e:
            logger.error(f'Error deleting pet: {e}')
            return jsonify({'error': 'Failed to delete pet'}), 500
    
    @app.route('/ping')
    def ping():
        """Simple ping endpoint for monitoring"""
        return jsonify({
            'status': 'pong',
            'timestamp': datetime.datetime.utcnow().isoformat(),
            'bot_active': True
        })
    
    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 errors"""
        return jsonify({'error': 'Endpoint not found'}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 errors"""
        logger.error(f'Internal server error: {error}')
        return jsonify({'error': 'Internal server error'}), 500
    
    # Add request logging
    @app.before_request
    def log_request():
        from flask import request
        logger.info(f'Incoming request: {request.method} {request.path} from {request.remote_addr}')
    
    return app
