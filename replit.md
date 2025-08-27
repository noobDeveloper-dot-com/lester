# Overview

Discord Defense Bot is a Python-based Discord bot that automatically monitors chat messages for profanity and provides defensive responses when protected users are mentioned. The bot features a dual-architecture system with both Discord bot functionality and a real-time web dashboard for monitoring bot performance and statistics.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Bot Architecture
The application uses a modular Python architecture built around the discord.py library. The main bot logic is encapsulated in a `DiscordBot` class that handles message monitoring, profanity detection, and automated responses. The bot operates with configurable word lists and response templates, allowing runtime modification of behavior through owner commands.

## Web Dashboard
A Flask-based web application runs concurrently with the Discord bot using Python threading. The web interface provides real-time monitoring capabilities through REST API endpoints that serve bot statistics and configuration data. The dashboard uses Bootstrap for responsive UI and includes auto-refreshing statistics displays.

## Configuration Management
Environment-based configuration system using a dedicated `Config` class that validates required settings. Critical configuration includes Discord bot tokens, owner IDs, and web application secrets loaded from environment variables with fallback defaults.

## Message Processing
Event-driven message handling that scans incoming Discord messages against configurable word lists. The system implements pattern matching for profanity detection and nickname-based user protection with customizable response templates.

## Concurrent Execution
The application runs both Discord bot and web server concurrently using asyncio for the Discord client and threading for the Flask application. This allows real-time monitoring while maintaining bot responsiveness.

# External Dependencies

## Discord Integration
- **discord.py**: Primary Discord API client library for bot functionality
- **Discord Developer Portal**: Bot token generation and permission management

## Web Framework
- **Flask**: Lightweight web framework for monitoring dashboard
- **Bootstrap 5.1.3**: Frontend CSS framework (CDN)
- **Font Awesome 6.0.0**: Icon library (CDN)

## Runtime Environment
- **Python asyncio**: Asynchronous execution for Discord client
- **Python threading**: Concurrent web server execution
- **Environment variables**: Configuration management for tokens and secrets

## Development Tools
- **Python logging**: Built-in logging system for monitoring and debugging
- **dotenv support**: Environment file loading for local development