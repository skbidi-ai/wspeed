# Overview

This is a Discord bot with triple functionality: it monitors a specific channel for messages containing "WFL" (Want For Less - a trading term) and reacts with custom emojis, tracks pet values from a dedicated values channel, and provides a pet weight calculator command. The bot includes a Flask web server for uptime monitoring and health checks, making it suitable for deployment on platforms that require HTTP endpoints to keep services alive.

# User Preferences

Preferred communication style: Simple, everyday language.

# Recent Changes

## August 19, 2025 - Successfully Migrated from Replit Agent to Replit
- **MIGRATION COMPLETE**: Successfully migrated Discord bot project from Replit Agent environment to standard Replit environment
- **Dependencies Installed**: All required Python packages installed via uv package manager (discord.py, flask, psycopg2-binary, python-dateutil)
- **Database Setup**: PostgreSQL database created with proper environment variables (DATABASE_URL, PGPORT, PGUSER, etc.)
- **Discord Token Configuration**: DISCORD_TOKEN secret properly configured in environment variables
- **Bot Connection Verified**: Discord bot successfully connected and actively processing messages
- **Pet Database Active**: Bot scanning Discord channels and updating pet database in real-time (103+ pets tracked)
- **Flask Server Running**: Web server operational on port 5000 for uptime monitoring
- **All Features Operational**: WFL reactions, pet value tracking, weight calculator, moderation system all working
- **Migration Benefits**: Enhanced security with proper client/server separation, better environment management, and Replit compatibility

## August 22, 2025 - Successfully Migrated from Replit Agent to Replit
- **MIGRATION COMPLETE**: Successfully migrated Discord bot project from Replit Agent environment to standard Replit environment
- **Dependencies Installed**: All required Python packages installed via uv package manager (discord.py, flask, psycopg2-binary, python-dateutil)
- **Database Setup**: PostgreSQL database created with proper environment variables (DATABASE_URL, PGPORT, PGUSER, etc.)
- **Discord Token Configuration**: DISCORD_TOKEN secret properly configured in environment variables
- **Bot Connection Verified**: Discord bot successfully connected and actively processing messages
- **Pet Database Active**: Bot scanning Discord channels and updating pet database in real-time (103+ pets tracked)
- **Flask Server Running**: Web server operational on port 5000 for uptime monitoring
- **All Features Operational**: WFL reactions, pet value tracking, weight calculator, moderation system all working
- **Migration Benefits**: Enhanced security with proper client/server separation, better environment management, and Replit compatibility

## August 14, 2025 - Complete Bot Enhancement and Admin Protection Update
- Successfully migrated project from Replit Agent to standard Replit environment
- FIXED: Pet similarity matching algorithm causing incorrect search results (t-rex vs turtle issue)
- Enhanced pet search error messages with helpful examples and suggestions
- Increased similarity threshold from 20% to 50% for more accurate matching
- Bot now properly handles non-existent pets with clear, actionable error messages
- FIXED: Auto-pick feature now works for all scenarios - automatically selects best match even when multiple pets have same percentage
- FIXED: Removed "lossless" prefix from appearing in pet names during value scanning
- Enhanced auto-selection with 5-point threshold and always picks first match when tied
- Installed all required dependencies: discord.py, flask, psycopg2-binary, python-dateutil
- Created PostgreSQL database with moderation system tables
- Configured Discord bot token in environment variables
- Updated moderation commands with gs. prefix and improved styling:
  - gs.warn @user reason - Warn a user with confirmation
  - gs.mute @user duration reason - Mute user with Discord timeout
  - gs.ban @user duration reason - Ban user with optional duration
  - gs.kick @user reason - Kick user from server
  - gs.unmute @user reason - Remove timeout from user
  - gs.removewarn action_id reason - Remove/revoke moderation actions
- Added separate history commands:
  - gs.warns @user - Show warning history only
  - gs.mutes @user - Show mute history only 
  - gs.bans @user - Show ban history only
  - gs.kicks @user - Show kick history only
  - gs.history @user - Show complete moderation history
- Enhanced DM notifications with Game Services branding and appeal process
- Added comprehensive user reporting system:
  - gs.report @user reason - Members can report users to moderation team
  - **WARNING: "FALSE REPORTS WILL GET YOU MUTED"** prominently displayed
  - Two-step confirmation process with Submit/Cancel buttons
  - Reports sent to dedicated channel (1403179951431094404) with detailed user information
  - Staff can Approve/Deny reports with permission checks
  - When approved, staff get quick action buttons: Warn, Mute (5m/10m/20m), Kick
  - All actions logged to database with DM notifications and appeal process
  - Prevents self-reporting and bot reporting with validation
  - Beautiful gold-styled embeds with account age and server join information
- Added comprehensive invite tracking system:
  - Automatic invite detection with fake invite filtering (accounts < 7 days)
  - Rejoin detection and tracking
  - Bonus invite management (addinvite/removeinvite commands)
  - Invite leaderboard (invtop) with top 10 users
  - Individual invite stats (invites command) showing valid/fake/rejoins/bonus
- Added message tracking system:
  - Daily, weekly, and monthly message counting with automatic resets
  - Message statistics command (gs.m) showing user activity
  - Message leaderboards (msgtop daily/weekly/monthly) 
  - Last message timestamp tracking
- All embeds now use consistent gold color scheme (0xFFC916)
- Added comprehensive game filtering to prevent false pet detections:
  - Filters out Wordbomb, Trivia, and other Discord game messages
  - Enhanced message validation requiring pet-related keywords
  - Fixed issues with random words being counted as pets
- Implemented <:GsWrong:1414561861352816753>   reaction system for incorrect pet value searches
- Added admin protection to automoderation system:
  - Users with manage_guild or administrator permissions bypass automod
  - Prevents accidental moderation of server administrators
- Fixed all image handling issues:
  - Only assigns images to single-pet messages to avoid confusion
  - Proper Discord CDN URL formatting with size parameters
  - Multi-pet messages skip image assignment entirely
- Bot is now fully operational with all features working:
  - WFL reactions in target channel
  - Pet value tracking and database (71 pets loaded with proper filtering)
  - Pet weight calculator commands
  - Complete moderation system with admin protection
  - User reporting system with channel integration
  - Comprehensive invite tracking with fake detection
  - Message activity tracking and leaderboards
  - Auto-pick pet matching with 50% similarity threshold
  - Game message filtering and validation
  - Flask server for uptime monitoring on port 5000

# System Architecture

## Bot Architecture
- **Discord.py Framework**: Uses the discord.py library with commands extension for Discord API interaction
- **Event-Driven Design**: Implements `on_ready` and `on_message` event handlers to respond to Discord events
- **Regex Pattern Matching**: Uses compiled regex patterns for case-insensitive "WFL" detection in messages
- **Rate Limiting**: Built-in cooldown system to prevent spam reactions (1-second cooldown between reactions)

## Multi-Threading Design
- **Dual Service Architecture**: Runs Discord bot and Flask server concurrently using Python threading
- **Thread Separation**: Discord bot runs in a daemon thread while Flask server runs in the main thread
- **Error Isolation**: Each service has independent error handling to prevent cascading failures

## Web Server Component
- **Flask Framework**: Lightweight web server for HTTP endpoints
- **Health Monitoring**: Multiple endpoints (`/`, `/uptime`, `/status`) for different monitoring needs
- **Uptime Tracking**: Tracks bot start time and calculates running duration
- **JSON API**: All endpoints return structured JSON responses for easy integration with monitoring tools

## Configuration Management
- **Environment Variables**: Uses `DISCORD_TOKEN` environment variable for secure token storage
- **Channel Configuration**: 
  - WFL reactions channel: 1401169397850308708
  - Pet values monitoring channel: 1391477739680301187
- **Logging System**: Comprehensive logging to both file (`bot.log`) and console with timestamp formatting
- **Data Storage**: Pet values stored in `pet_values.json` file

## Message Processing Pipeline
1. **Message Filtering**: Ignores bot messages and filters by target channel
2. **Pattern Detection**: Searches for "WFL" pattern using case-insensitive regex
3. **Rate Limiting**: Checks cooldown before processing reactions
4. **Reaction Application**: Adds custom server emojis (:W1:, :F1:, :L1:) to matching messages

## Command System
- **Pet Weight Calculator**: `!petweight` command calculates pet weight predictions
- **Pet Value Lookup**: `!petvalue` (aliases: `!v`, `!value`, `!val`) command looks up pet values from database
- **Pet Database Listing**: `!petlist` command shows all pets in the database with pagination
- **Command Processing**: Uses discord.py commands extension for structured command handling
- **Input Validation**: Validates age (1-100) and weight (>0) parameters for weight calculations
- **Flexible Output**: Shows weight progression or specific target age predictions
- **Weight Formula**: Uses predefined formula with base weights from age 1-100

## Pet Values System
- **Automatic Scanning**: Scans pet values channel on startup for existing pet data
- **Real-time Monitoring**: Monitors pet values channel (1391477739680301187) for new pet information
- **Pattern Matching**: Uses multiple regex patterns to extract pet name, value, and demand from messages
- **Database Storage**: Stores pet data in JSON file with automatic saving
- **Search Functionality**: Supports exact and partial matching for pet names
- **Data Persistence**: Pet values persist between bot restarts

# External Dependencies

## Discord Integration
- **Discord API**: Primary integration through discord.py library for bot functionality
- **Discord Gateway**: Real-time message event streaming from Discord servers
- **Bot Permissions**: Requires message content intent and reaction permissions

## Python Libraries
- **discord.py**: Core Discord bot framework with commands extension
- **Flask**: Web framework for HTTP server functionality
- **threading**: Standard library for concurrent execution
- **logging**: Built-in logging system for monitoring and debugging
- **re**: Regular expression library for pattern matching
- **os**: Environment variable access
- **datetime**: Timestamp and uptime calculations

## Deployment Requirements
- **Environment Variables**: `DISCORD_TOKEN` must be configured
- **Port Access**: Requires access to port 8000 for Flask server
- **File System**: Needs write access for `bot.log` file creation
- **Network Access**: Requires outbound HTTPS for Discord API communication