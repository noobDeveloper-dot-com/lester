import discord
from discord.ext import commands
import openai
import requests
import json
import random
import asyncio
import os
import threading
from flask import Flask
import time
import psycopg2
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import google.generativeai as genai

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True  # Need this for timeouts
bot = commands.Bot(command_prefix='!', intents=intents)

# Configuration - Using environment variables
YOUR_USER_ID = int(os.getenv('DISCORD_OWNER_ID', '1355741455947272203'))
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', 'YOUR_OPENAI_API_KEY')
GROK_API_KEY = os.getenv('GROK_API_KEY', 'YOUR_GROK_API_KEY')
GROQ_API_KEY = os.getenv('GROQ_API_KEY', 'YOUR_GROQ_API_KEY')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'YOUR_GEMINI_API_KEY')

# Initialize AI services
if OPENAI_API_KEY != 'YOUR_OPENAI_API_KEY':
    openai.api_key = OPENAI_API_KEY

if GEMINI_API_KEY != 'YOUR_GEMINI_API_KEY':
    genai.configure(api_key=GEMINI_API_KEY)

print(f"🔧 AI Configuration:")
print(f"├─ OpenAI: {'✅ Ready' if OPENAI_API_KEY != 'YOUR_OPENAI_API_KEY' else '❌ Not configured'}")
print(f"├─ Groq: {'✅ Ready' if GROQ_API_KEY != 'YOUR_GROQ_API_KEY' else '❌ Not configured'}")
print(f"├─ Gemini: {'✅ Ready' if GEMINI_API_KEY != 'YOUR_GEMINI_API_KEY' else '❌ Not configured'}")
print(f"└─ Grok: {'✅ Ready' if GROK_API_KEY != 'YOUR_GROK_API_KEY' else '❌ Not configured'}")

# Database setup
DATABASE_URL = os.getenv('DATABASE_URL')
Base = declarative_base()

class UserWeakpoint(Base):
    __tablename__ = 'user_weakpoints'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(String(50), nullable=False)
    username = Column(String(100), nullable=False)
    weakpoint = Column(Text, nullable=False)
    added_date = Column(DateTime, default=datetime.utcnow)

# Initialize database
def init_database():
    if DATABASE_URL:
        try:
            engine = create_engine(DATABASE_URL)
            Base.metadata.create_all(engine)
            print("✅ Database connected and tables created!")
            return sessionmaker(bind=engine)
        except Exception as e:
            print(f"❌ Database error: {e}")
            return None
    else:
        print("❌ No database URL configured")
        return None

SessionLocal = init_database()

# Database helper functions
def get_user_weakpoints(user_id):
    """Get all weakpoints for a specific user"""
    if not SessionLocal or not user_id:
        return []
    
    try:
        session = SessionLocal()
        weakpoints = session.query(UserWeakpoint).filter(UserWeakpoint.user_id == str(user_id)).all()
        result = [wp.weakpoint for wp in weakpoints]
        session.close()
        return result
    except Exception as e:
        print(f"❌ Database error getting weakpoints: {e}")
        return []

def add_user_weakpoint(user_id, username, weakpoint):
    """Add a weakpoint for a user"""
    if not SessionLocal:
        return False
    
    try:
        session = SessionLocal()
        new_weakpoint = UserWeakpoint(
            user_id=str(user_id),
            username=username,
            weakpoint=weakpoint
        )
        session.add(new_weakpoint)
        session.commit()
        session.close()
        return True
    except Exception as e:
        print(f"❌ Database error adding weakpoint: {e}")
        return False

def remove_user_weakpoint(user_id, weakpoint):
    """Remove a specific weakpoint for a user"""
    if not SessionLocal:
        return False
    
    try:
        session = SessionLocal()
        weakpoint_obj = session.query(UserWeakpoint).filter(
            UserWeakpoint.user_id == str(user_id),
            UserWeakpoint.weakpoint == weakpoint
        ).first()
        
        if weakpoint_obj:
            session.delete(weakpoint_obj)
            session.commit()
            session.close()
            return True
        else:
            session.close()
            return False
    except Exception as e:
        print(f"❌ Database error removing weakpoint: {e}")
        return False

def get_all_user_weakpoints():
    """Get all users with weakpoints"""
    if not SessionLocal:
        return []
    
    try:
        session = SessionLocal()
        weakpoints = session.query(UserWeakpoint).all()
        result = {}
        for wp in weakpoints:
            if wp.user_id not in result:
                result[wp.user_id] = {
                    'username': wp.username,
                    'weakpoints': []
                }
            result[wp.user_id]['weakpoints'].append(wp.weakpoint)
        session.close()
        return result
    except Exception as e:
        print(f"❌ Database error getting all weakpoints: {e}")
        return []

# Bot settings
caps_punishment_active = False  # Global setting for caps punishment
user_strikes = {}  # Track user violations: {user_id: {'caps': count, 'badwords': count, 'harassment': count}}
timeout_durations = {
    'caps_first': 300,      # 5 minutes
    'caps_repeat': 600,     # 10 minutes
    'caps_excessive': 1800, # 30 minutes
    'badwords': 600,        # 10 minutes
    'harassment': 900       # 15 minutes
}

# Bad words to detect
BAD_WORDS = [
    'fuck', 'shit', 'bitch', 'damn', 'ass', 'cunt', 'dick', 'pussy',
    'bastard', 'whore', 'slut', 'retard', 'fag', 'nigga', 'motherfucker',
    'asshole', 'dumbass', 'dipshit', 'cocksucker', 'prick', 'twat'
]

# Your protected nicknames
YOUR_NICKNAMES = ['helpless', 'harun', 'aaron', 'we_are_aaron']

def is_caps_abuse(message_content):
    """Check if message has excessive caps usage"""
    if len(message_content) < 5:  # Ignore very short messages
        return False
    
    # Count uppercase vs total letters
    letters = [c for c in message_content if c.isalpha()]
    if len(letters) < 5:  # Need at least 5 letters to check
        return False
    
    uppercase_count = sum(1 for c in letters if c.isupper())
    caps_ratio = uppercase_count / len(letters)
    
    # Consider it caps abuse if more than 70% is uppercase and message has 8+ letters
    return caps_ratio > 0.7 and len(letters) >= 8

async def get_ai_response(message_content, user_mention, context_type="general"):
    """Get AI-generated response based on context"""
    
    if context_type == "defense":
        # Get attacker's weakpoints for more targeted defense
        weakpoints = get_user_weakpoints(message.author.id if hasattr(message, 'author') else None)
        weakpoint_info = ""
        if weakpoints:
            weakpoint_info = f" You can use these facts about the attacker to make your defense more effective: {'; '.join(weakpoints)}"
        
        system_prompt = f"""You are an aggressive Discord bot defending your owner. Someone just said something targeting your owner's nicknames ({', '.join(YOUR_NICKNAMES)}) in a negative or mocking way. 
        
        Respond with a short, aggressive message (1-2 sentences max) defending them. Be confrontational and use strong language. 
        Include {user_mention} in your response to call them out directly.{weakpoint_info}
        
        Examples of your style:
        - "Back off {user_mention}, don't mess with my friend!"
        - "Hey {user_mention}, shut your mouth and leave them alone!"
        - "{user_mention}, you're crossing a line - watch it!"
        """
    elif context_type == "self_defense":
        # Get attacker's weakpoints for more targeted self-defense
        weakpoints = get_user_weakpoints(message.author.id if hasattr(message, 'author') else None)
        weakpoint_info = ""
        if weakpoints:
            weakpoint_info = f" You can use these facts about the attacker to make your comeback more effective: {'; '.join(weakpoints)}"
        
        system_prompt = f"""You are an aggressive Discord bot defending yourself. Someone just insulted YOU directly or called you stupid/dumb/useless.
        
        Respond with a short, aggressive message (1-2 sentences max) defending yourself. Be confrontational and fight back.
        Include {user_mention} in your response to call them out directly.{weakpoint_info}
        
        Examples of your style:
        - "Fuck you {user_mention}, I'm not stupid - you are!"
        - "Hey {user_mention}, shut your mouth! I'll show you who's useless!"
        - "{user_mention}, watch your fucking mouth when talking to me!"
        - "Talk shit again {user_mention} and see what happens!"
        """
    elif context_type == "friendly":
        system_prompt = f"""You are a friendly Discord bot responding to someone who mentioned your owner in a positive or neutral way. They're being nice or just having normal conversation.
        
        Respond with a short, friendly message (1-2 sentences max). Be casual, helpful, and positive. 
        Include {user_mention} in your response naturally.
        
        Examples of your style:
        - "Hey {user_mention}! Yeah, my owner is pretty cool!"
        - "What's up {user_mention}? How can I help you today?"
        - "Nice to meet you {user_mention}! My owner speaks highly of good people."
        - "Hello {user_mention}! Always happy to chat with friendly folks."
        """
    elif context_type == "caps":
        system_prompt = f"""You are an aggressive Discord bot that hates excessive caps/shouting. Someone just used way too many capital letters and is about to get timed out.
        
        Respond with a very harsh, aggressive message (1-2 sentences max) telling them to stop shouting. Be extremely confrontational and angry. 
        Include {user_mention} in your response. DO NOT mention timeout duration as the system handles that separately.
        
        Examples of your style:
        - "SHUT THE FUCK UP {user_mention}! Stop screaming like a goddamn child!"
        - "Hey {user_mention}, turn off your caps lock you annoying piece of shit!"
        - "{user_mention}, stop yelling you absolute moron!"
        """
    elif context_type == "conversation":
        # Get user's weakpoints for more targeted responses
        weakpoints = get_user_weakpoints(message.author.id if hasattr(message, 'author') else None)
        weakpoint_info = ""
        if weakpoints:
            weakpoint_info = f"\n\nAdditional context about this user: {'; '.join(weakpoints)}"
        
        system_prompt = f"""You are a friendly, casual Discord bot having a normal conversation. Someone just mentioned you or asked you something in a regular, conversational way.
        
        Respond naturally like a helpful friend (1-2 sentences max). Be casual, engaging, and authentic. Match their energy level.
        Include {user_mention} in your response naturally.{weakpoint_info}
        
        Examples of your style:
        - "Hey {user_mention}! What's on your mind today?"
        - "Yeah {user_mention}, I'm here! How can I help you out?"
        - "What's up {user_mention}? Always down to chat!"
        - "Hey there {user_mention}! Good to see you around."
        
        If they ask you questions, try to be helpful. If they're just chatting, be friendly and engaging.
        """
    else:
        system_prompt = f"""You are an aggressive Discord bot that calls out bad language and inappropriate behavior. Someone just used profanity or inappropriate language.
        
        Respond with a short, confrontational message (1-2 sentences max) telling them to watch their language. Be aggressive but not overly offensive.
        Include {user_mention} in your response.
        
        Examples of your style:
        - "Hey {user_mention}, watch your fucking mouth!"
        - "Cut that shit out {user_mention}!"
        - "{user_mention}, mind your language asshole!"
        """
    
    try:
        # Use different AI services based on context type
        if context_type in ["conversation", "friendly"]:
            # Use Gemini for casual, friendly conversations
            response = await get_gemini_response(system_prompt, message_content, user_mention)
            if response:
                print(f"✅ Gemini AI response generated")
                return response
        else:
            # Use Groq for aggressive/defensive responses
            response = await get_groq_response(system_prompt, message_content, user_mention)
            if response:
                print(f"✅ Groq AI response generated")
                return response
            
        # Fallback to OpenAI if available
        response = await get_openai_response(system_prompt, message_content, user_mention)
        if response:
            print(f"✅ OpenAI response generated") 
            return response
            
        # Last resort: predefined responses
        print(f"⚠️ Using fallback response (AI services unavailable)")
        return get_fallback_response(user_mention, context_type)
        
    except Exception as e:
        print(f"❌ AI Error: {e}")
        return get_fallback_response(user_mention, context_type)

async def get_openai_response(system_prompt, message_content, user_mention):
    """Get response from OpenAI GPT"""
    try:
        if OPENAI_API_KEY == 'YOUR_OPENAI_API_KEY':
            return None
            
        client = openai.OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User said: '{message_content}'"}
            ],
            max_tokens=100,
            temperature=0.9
        )
        return response.choices[0].message.content.strip()
    except:
        return None

async def get_groq_response(system_prompt, message_content, user_mention):
    """Get response from Groq (for aggressive/defensive responses)"""
    try:
        if GROQ_API_KEY == 'YOUR_GROQ_API_KEY':
            print("❌ Groq API key not configured")
            return None
            
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"User said: '{message_content}'"}
            ],
            "model": "llama3-8b-8192",  # Good for aggressive responses
            "max_tokens": 150,
            "temperature": 0.9,  # Higher temperature for more creative insults
            "stream": False
        }
        
        print(f"🤖 Calling Groq API for aggressive response: {message_content[:50]}...")
        response = requests.post("https://api.groq.com/openai/v1/chat/completions", 
                               headers=headers, json=data, timeout=15)
        
        if response.status_code == 200:
            result = response.json()
            ai_response = result["choices"][0]["message"]["content"].strip()
            print(f"✅ Groq response: {ai_response[:100]}...")
            return ai_response
        else:
            print(f"❌ Groq API error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"❌ Groq exception: {e}")
        return None

async def get_gemini_response(system_prompt, message_content, user_mention):
    """Get response from Google Gemini (for casual conversations)"""
    try:
        if GEMINI_API_KEY == 'YOUR_GEMINI_API_KEY':
            print("❌ Gemini API key not configured")
            return None
        
        # Initialize Gemini model
        model = genai.GenerativeModel('gemini-pro')
        
        # Combine system prompt with user message
        full_prompt = f"{system_prompt}\n\nUser message: '{message_content}'"
        
        print(f"🤖 Calling Gemini API for casual conversation: {message_content[:50]}...")
        response = model.generate_content(
            full_prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=150,
                temperature=0.7,  # Good balance for natural conversation
            )
        )
        
        if response.text:
            ai_response = response.text.strip()
            print(f"✅ Gemini response: {ai_response[:100]}...")
            return ai_response
        else:
            print("❌ Gemini returned empty response")
            return None
            
    except Exception as e:
        print(f"❌ Gemini exception: {e}")
        return None

def get_fallback_response(user_mention, context_type):
    """Fallback responses if AI fails"""
    if context_type == "defense":
        responses = [
            f"Back off {user_mention}, leave them alone!",
            f"Hey {user_mention}, don't mess with my friend!",
            f"{user_mention}, you're out of line!",
            f"Watch it {user_mention}, that's my friend you're talking about!"
        ]
    elif context_type == "self_defense":
        responses = [
            f"Fuck you {user_mention}, I'm not stupid - you are!",
            f"Hey {user_mention}, shut your mouth! I'll show you who's useless!",
            f"{user_mention}, watch your fucking mouth when talking to me!",
            f"Talk shit again {user_mention} and see what happens!"
        ]
    elif context_type == "friendly":
        responses = [
            f"Hey {user_mention}! Nice to meet you!",
            f"What's up {user_mention}? How's it going?",
            f"Hello there {user_mention}! Good to see friendly people around.",
            f"Hey {user_mention}! Always happy to chat with cool people!"
        ]
    elif context_type == "caps":
        responses = [
            f"SHUT UP {user_mention}! Stop screaming like a child!",
            f"Hey {user_mention}, turn off caps lock you moron!",
            f"{user_mention}, stop yelling!",
            f"Cut the caps crap {user_mention}!"
        ]
    elif context_type == "conversation":
        responses = [
            f"Hey {user_mention}! What's up?",
            f"Yeah {user_mention}, I'm here! How can I help?",
            f"What's on your mind {user_mention}?",
            f"Hey there {user_mention}! Good to see you!"
        ]
    else:
        responses = [
            f"Hey {user_mention}, watch your language!",
            f"Cut it out {user_mention}!",
            f"{user_mention}, mind your mouth!",
            f"That's enough {user_mention}!"
        ]
    return random.choice(responses)

@bot.event
async def on_ready():
    print(f'{bot.user} AI Defense Bot is online and ready!')
    print(f'Bot is in {len(bot.guilds)} servers')

def add_user_strike(user_id, strike_type):
    """Add a strike to user's record"""
    if user_id not in user_strikes:
        user_strikes[user_id] = {'caps': 0, 'badwords': 0, 'harassment': 0}
    
    user_strikes[user_id][strike_type] += 1
    return user_strikes[user_id][strike_type]

def get_timeout_duration(strike_type, strike_count):
    """Get timeout duration based on offense type and strike count"""
    if strike_type == 'caps':
        if strike_count == 1:
            return timeout_durations['caps_first']
        elif strike_count == 2:
            return timeout_durations['caps_repeat'] 
        else:
            return timeout_durations['caps_excessive']
    elif strike_type == 'badwords':
        return timeout_durations['badwords']
    elif strike_type == 'harassment':
        return timeout_durations['harassment']
    
    return 600  # Default 10 minutes

async def timeout_user(message, strike_type, reason):
    """Timeout a user and send notification"""
    try:
        # Add strike and get count
        strike_count = add_user_strike(message.author.id, strike_type)
        
        # Get timeout duration
        duration = get_timeout_duration(strike_type, strike_count)
        
        # Apply timeout using Discord's new timeout feature
        timeout_until = discord.utils.utcnow() + discord.timedelta(seconds=duration)
        await message.author.timeout(timeout_until, reason=reason)
        
        # Format duration for display
        minutes = duration // 60
        duration_text = f"{minutes} minute{'s' if minutes != 1 else ''}"
        
        # Send timeout notification
        timeout_msg = f"🚨 **{message.author.mention} has been timed out for {duration_text}!**\n"
        timeout_msg += f"**Reason:** {reason}\n"
        timeout_msg += f"**Strike #{strike_count}** for {strike_type.replace('_', ' ')}"
        
        if strike_count > 1:
            timeout_msg += f"\n⚠️ **Repeat offender** - escalated punishment!"
        
        await message.channel.send(timeout_msg)
        print(f"✅ Timed out {message.author} for {duration_text} - {reason}")
        
        return True
        
    except discord.Forbidden:
        # Bot doesn't have permission or target has higher role
        await message.channel.send(f"❌ Cannot timeout {message.author.mention} - insufficient permissions!")
        print(f"❌ Failed to timeout {message.author} - no permission")
        return False
        
    except discord.HTTPException as e:
        # Other Discord API error
        await message.channel.send(f"❌ Failed to timeout {message.author.mention} - Discord error!")
        print(f"❌ Discord error during timeout: {e}")
        return False

def should_auto_timeout(strike_type, strike_count):
    """Determine if user should be auto-timed out based on strikes"""
    if strike_type == 'caps':
        return strike_count >= 2  # Timeout after 2nd caps offense
    elif strike_type == 'badwords':
        return strike_count >= 3  # Timeout after 3rd bad word offense
    elif strike_type == 'harassment':
        return strike_count >= 1  # Immediate timeout for harassment
    
    return False

def analyze_message_sentiment(message_content, bot_mentioned):
    """Analyze if message is friendly, hostile, or neutral towards owner/bot"""
    content_lower = message_content.lower()
    
    # If bot is mentioned, check if it's friendly interaction
    if bot_mentioned:
        friendly_indicators = [
            'hello', 'hi', 'hey', 'sup', 'good', 'nice', 'cool', 'awesome', 
            'thanks', 'please', 'help', 'how are you', 'whats up', "what's up",
            'greetings', 'morning', 'afternoon', 'evening', 'hope', 'appreciate'
        ]
        
        hostile_indicators = [
            'stupid', 'dumb', 'shut up', 'annoying', 'hate', 'suck', 'trash',
            'garbage', 'useless', 'worthless', 'pathetic', 'loser', 'idiot'
        ]
        
        # Check for friendly vs hostile
        friendly_score = sum(1 for word in friendly_indicators if word in content_lower)
        hostile_score = sum(1 for word in hostile_indicators if word in content_lower)
        
        if friendly_score > hostile_score and friendly_score > 0:
            return "friendly"
        elif hostile_score > 0:
            return "self_defense"
    
    # Check if targeting owner nicknames negatively
    for nickname in YOUR_NICKNAMES:
        if nickname.lower() in content_lower:
            # Check context around the nickname
            negative_words = [
                'stupid', 'dumb', 'idiot', 'loser', 'noob', 'trash', 'suck', 'bad',
                'hate', 'annoying', 'pathetic', 'worthless', 'useless', 'moron'
            ]
            
            if any(word in content_lower for word in negative_words):
                return "defense"
    
    return "neutral"

@bot.event
async def on_message(message):
    # Don't respond to the bot itself
    if message.author == bot.user:
        return
    
    # Process commands first (for everyone now)
    await bot.process_commands(message)
    
    # Don't trigger AI responses if it was a command
    if message.content.startswith('!'):
        return
    
    # Check if bot is mentioned
    bot_mentioned = bot.user.mentioned_in(message)
    
    # Convert message to lowercase for checking
    content = message.content.lower()
    user_mention = message.author.mention
    
    # Check message sentiment and context
    sentiment = analyze_message_sentiment(message.content, bot_mentioned)
    
    # Check if message contains bad words
    found_bad_word = any(word in content for word in BAD_WORDS)
    
    # Check for caps abuse if caps punishment is active
    caps_abuse = caps_punishment_active and is_caps_abuse(message.content)
    
    # Determine if we should respond and how
    should_respond = False
    context_type = "general"
    
    if caps_abuse:
        should_respond = True
        context_type = "caps"
    elif found_bad_word:
        should_respond = True
        context_type = "general"
    elif sentiment == "defense":
        should_respond = True
        context_type = "defense"  # Defending owner
    elif sentiment == "self_defense":
        should_respond = True  
        context_type = "self_defense"  # Bot defending itself
    elif sentiment == "friendly" and bot_mentioned:
        should_respond = True
        context_type = "friendly"
    elif bot_mentioned:
        # If bot is mentioned but not hostile or friendly, have a normal conversation
        should_respond = True
        context_type = "conversation"
    
    if should_respond:
        # Get AI-generated response
        ai_response = await get_ai_response(message.content, user_mention, context_type)
        
        # Send the response
        await message.channel.send(ai_response)
        print(f"AI Response sent ({context_type}): {ai_response}")
        
        # Handle timeouts based on context
        timeout_applied = False
        
        if context_type == "caps":
            strike_count = add_user_strike(message.author.id, "caps")
            if should_auto_timeout("caps", strike_count):
                timeout_applied = await timeout_user(message, "caps", "Excessive caps usage/shouting")
                
        elif context_type == "general" and found_bad_word:
            strike_count = add_user_strike(message.author.id, "badwords")
            if should_auto_timeout("badwords", strike_count):
                timeout_applied = await timeout_user(message, "badwords", "Repeated bad language")
                
        elif context_type in ["defense", "self_defense"]:
            strike_count = add_user_strike(message.author.id, "harassment")
            if should_auto_timeout("harassment", strike_count):
                timeout_applied = await timeout_user(message, "harassment", "Harassment/hostile behavior")

@bot.command(name='setai')
async def set_ai_key(ctx, service, *, api_key):
    """Set AI API keys (OpenAI, Groq, etc.) - OWNER ONLY"""
    if ctx.author.id != YOUR_USER_ID:
        await ctx.send("Only my owner can set API keys!")
        return
    
    global OPENAI_API_KEY, GROQ_API_KEY
    
    if service.lower() == "openai":
        OPENAI_API_KEY = api_key
        openai.api_key = api_key
        await ctx.send("✅ OpenAI API key updated!")
    elif service.lower() == "groq":
        GROQ_API_KEY = api_key
        await ctx.send("✅ Groq API key updated!")
    else:
        await ctx.send("❌ Supported services: openai, groq")

@bot.command(name='testai')
async def test_ai(ctx, *, test_message="fuck this shit"):
    """Test AI response generation - OWNER ONLY"""
    if ctx.author.id != YOUR_USER_ID:
        await ctx.send("Only my owner can test AI!")
        return
    
    response = await get_ai_response(test_message, ctx.author.mention)
    await ctx.send(f"AI Test Response: {response}")

@bot.command(name='addword')
async def add_word(ctx, word):
    """Add a new bad word to detect - OWNER ONLY"""
    if ctx.author.id != YOUR_USER_ID:
        await ctx.send("Only my owner can add words!")
        return
    
    word = word.lower()
    if word not in BAD_WORDS:
        BAD_WORDS.append(word)
        await ctx.send(f"✅ Added '{word}' to bad words list!")
    else:
        await ctx.send(f"'{word}' is already in the list!")

@bot.command(name='addname')
async def add_name(ctx, name):
    """Add a new protected nickname - OWNER ONLY"""
    if ctx.author.id != YOUR_USER_ID:
        await ctx.send("Only my owner can add names!")
        return
    
    name = name.lower()
    if name not in [n.lower() for n in YOUR_NICKNAMES]:
        YOUR_NICKNAMES.append(name)
        await ctx.send(f"✅ Added '{name}' to protected names!")
    else:
        await ctx.send(f"'{name}' is already protected!")

@bot.command(name='ping')
async def ping_test(ctx):
    """Basic test command - EVERYONE CAN USE"""
    latency = round(bot.latency * 1000)
    await ctx.send(f"🏓 Pong! Latency: {latency}ms\nYour ID: {ctx.author.id}")

@bot.command(name='capspunish')
async def caps_punish_toggle(ctx):
    """Toggle caps punishment on/off - EVERYONE CAN USE"""
    global caps_punishment_active
    
    caps_punishment_active = not caps_punishment_active
    status = "ACTIVATED" if caps_punishment_active else "DEACTIVATED"
    emoji = "🔥" if caps_punishment_active else "❌"
    
    await ctx.send(f"{emoji} **Caps punishment {status}!** {emoji}")
    
    if caps_punishment_active:
        await ctx.send("⚠️ **WARNING**: Excessive caps usage will result in harsh warnings and automatic timeouts!")
    else:
        await ctx.send("Caps detection is now off. Users can spam caps freely.")

@bot.command(name='status')
async def bot_status(ctx):
    """Check bot and AI status - OWNER ONLY"""
    if ctx.author.id != YOUR_USER_ID:
        await ctx.send("Only my owner can check detailed status!")
        return
    
    status = f"""
🤖 **AI Defense Bot Status**
├─ Bot: Online ✅
├─ OpenAI: {'✅' if OPENAI_API_KEY != 'YOUR_OPENAI_API_KEY' else '❌'}
├─ Groq: {'✅' if GROQ_API_KEY != 'YOUR_GROQ_API_KEY' else '❌'}
├─ Caps Punishment: {'🔥 ACTIVE' if caps_punishment_active else '❌ INACTIVE'}
├─ Auto-Timeouts: ✅ ENABLED
├─ Bad Words: {len(BAD_WORDS)}
├─ Protected Names: {len(YOUR_NICKNAMES)}
├─ Users with Strikes: {len(user_strikes)}
└─ Servers: {len(bot.guilds)}

**Timeout Settings:**
├─ Caps (1st offense): {timeout_durations['caps_first']//60}min
├─ Caps (repeat): {timeout_durations['caps_repeat']//60}min  
├─ Bad Words (3rd strike): {timeout_durations['badwords']//60}min
└─ Harassment (1st): {timeout_durations['harassment']//60}min
    """
    await ctx.send(status)

def parse_duration(duration_str):
    """Parse duration string like '5m', '10m', '1h' into seconds"""
    duration_str = duration_str.lower().strip()
    
    if duration_str.endswith('m'):
        try:
            minutes = int(duration_str[:-1])
            return minutes * 60
        except ValueError:
            return None
    elif duration_str.endswith('h'):
        try:
            hours = int(duration_str[:-1])
            return hours * 3600
        except ValueError:
            return None
    elif duration_str.endswith('s'):
        try:
            seconds = int(duration_str[:-1])
            return seconds
        except ValueError:
            return None
    else:
        # Try to parse as just minutes
        try:
            minutes = int(duration_str)
            return minutes * 60
        except ValueError:
            return None

@bot.command(name='timeout')
async def manual_timeout(ctx, member: discord.Member, duration, *, reason="Manual timeout"):
    """Manually timeout a user - OWNER ONLY"""
    if ctx.author.id != YOUR_USER_ID:
        await ctx.send("Only my owner can manually timeout users!")
        return
    
    try:
        # Parse duration (supports: 5m, 10m, 1h, etc.)
        duration_seconds = parse_duration(duration)
        if not duration_seconds:
            await ctx.send("❌ Invalid duration format! Use: 5m, 10m, 1h, etc.")
            return
            
        # Apply timeout
        timeout_until = discord.utils.utcnow() + discord.timedelta(seconds=duration_seconds)
        await member.timeout(timeout_until, reason=reason)
        
        # Format duration for display
        minutes = duration_seconds // 60
        hours = minutes // 60
        
        if hours > 0:
            duration_text = f"{hours}h {minutes % 60}m" if minutes % 60 > 0 else f"{hours}h"
        else:
            duration_text = f"{minutes}m"
        
        await ctx.send(f"✅ **{member.mention} has been timed out for {duration_text}!**\n**Reason:** {reason}")
        
    except discord.Forbidden:
        await ctx.send(f"❌ Cannot timeout {member.mention} - insufficient permissions!")
    except discord.HTTPException:
        await ctx.send(f"❌ Failed to timeout {member.mention} - Discord error!")

@bot.command(name='untimeout')
async def remove_timeout(ctx, member: discord.Member):
    """Remove timeout from a user - OWNER ONLY"""
    if ctx.author.id != YOUR_USER_ID:
        await ctx.send("Only my owner can remove timeouts!")
        return
    
    try:
        await member.timeout(None)  # Remove timeout
        await ctx.send(f"✅ **Timeout removed from {member.mention}!**")
    except discord.Forbidden:
        await ctx.send(f"❌ Cannot remove timeout from {member.mention} - insufficient permissions!")
    except discord.HTTPException:
        await ctx.send(f"❌ Failed to remove timeout from {member.mention} - Discord error!")

@bot.command(name='strikes')
async def view_strikes(ctx, member: discord.Member = None):
    """View user's strike record - OWNER ONLY"""
    if ctx.author.id != YOUR_USER_ID:
        await ctx.send("Only my owner can view strikes!")
        return
    
    if not member:
        # Show all users with strikes
        if not user_strikes:
            await ctx.send("📊 **No users have strikes yet!**")
            return
        
        strike_list = "📊 **Users with Strikes:**\n"
        for user_id, strikes in user_strikes.items():
            user = bot.get_user(user_id)
            username = user.display_name if user else f"User {user_id}"
            total = sum(strikes.values())
            strike_list += f"• **{username}**: {total} total ({strikes['caps']} caps, {strikes['badwords']} words, {strikes['harassment']} harassment)\n"
        
        await ctx.send(strike_list[:2000])  # Discord message limit
    else:
        # Show specific user's strikes
        if member.id not in user_strikes:
            await ctx.send(f"📊 **{member.display_name}** has no strikes!")
            return
        
        strikes = user_strikes[member.id]
        total = sum(strikes.values())
        
        strike_info = f"""
📊 **Strike Record for {member.display_name}**
├─ **Total Strikes:** {total}
├─ **Caps Abuse:** {strikes['caps']} strikes
├─ **Bad Language:** {strikes['badwords']} strikes
└─ **Harassment:** {strikes['harassment']} strikes
        """
        await ctx.send(strike_info)

@bot.command(name='clearstrikes')
async def clear_strikes(ctx, member: discord.Member):
    """Clear a user's strike record - OWNER ONLY"""
    if ctx.author.id != YOUR_USER_ID:
        await ctx.send("Only my owner can clear strikes!")
        return
    
    if member.id in user_strikes:
        del user_strikes[member.id]
        await ctx.send(f"✅ **Cleared all strikes for {member.display_name}!**")
    else:
        await ctx.send(f"📊 **{member.display_name}** has no strikes to clear!")

@bot.command(name='commands')
async def help_command(ctx):
    """Show available commands - EVERYONE CAN USE"""
    user_commands = """
🤖 **Available Commands:**

**Everyone can use:**
• `!ping` - Test bot response and latency
• `!capspunish` - Toggle caps punishment on/off
• `!commands` - Show this help message
• `!testcaps` - Test caps detection system

**Owner only:**
• `!setai <service> <key>` - Set AI API keys
• `!testai [message]` - Test AI responses
• `!addword <word>` - Add bad word to filter
• `!addname <name>` - Add protected nickname
• `!status` - Show detailed bot status
• `!timeout <user> <duration> [reason]` - Timeout a user
• `!untimeout <user>` - Remove timeout from user
• `!strikes [user]` - View strike records
• `!clearstrikes <user>` - Clear user strikes
• `!addweakpoint <user> <weakpoint>` - Add user weakpoint
• `!removeweakpoint <user> <weakpoint>` - Remove weakpoint
• `!weakpoints [user]` - View user weakpoints

**Bot Features:**
• Detects bad words and responds aggressively
• Protects owner's nicknames from harassment  
• Auto-timeouts for repeat offenders
• Caps punishment system with escalating warnings
• AI-powered contextual responses
    """
    await ctx.send(user_commands)

@bot.command(name='testcaps')
async def test_caps(ctx):
    """Test caps detection - EVERYONE CAN USE"""
    test_messages = [
        "THIS IS A TEST MESSAGE",
        "HOLY SHIT THIS IS ANNOYING", 
        "WHY ARE YOU SCREAMING LIKE THAT",
        "this is normal text",
        "This Has Some Caps But Not Much"
    ]
    
    results = []
    for msg in test_messages:
        is_abuse = is_caps_abuse(msg)
        results.append(f"{'🔥' if is_abuse else '✅'} `{msg}` - {'CAPS ABUSE' if is_abuse else 'OK'}")
    
    await ctx.send("**Caps Detection Test:**\n" + "\n".join(results))

@bot.command(name='addweakpoint')
async def add_weakpoint_cmd(ctx, member: discord.Member, *, weakpoint):
    """Add a weakpoint for a user - OWNER ONLY"""
    if ctx.author.id != YOUR_USER_ID:
        await ctx.send("Only my owner can add weakpoints!")
        return
    
    if add_user_weakpoint(member.id, member.display_name, weakpoint):
        await ctx.send(f"✅ **Added weakpoint for {member.display_name}:**\n`{weakpoint}`")
        print(f"✅ Added weakpoint for {member.display_name}: {weakpoint}")
    else:
        await ctx.send(f"❌ Failed to add weakpoint for {member.display_name}")

@bot.command(name='removeweakpoint')
async def remove_weakpoint_cmd(ctx, member: discord.Member, *, weakpoint):
    """Remove a weakpoint for a user - OWNER ONLY"""
    if ctx.author.id != YOUR_USER_ID:
        await ctx.send("Only my owner can remove weakpoints!")
        return
    
    if remove_user_weakpoint(member.id, weakpoint):
        await ctx.send(f"✅ **Removed weakpoint for {member.display_name}:**\n`{weakpoint}`")
        print(f"✅ Removed weakpoint for {member.display_name}: {weakpoint}")
    else:
        await ctx.send(f"❌ Weakpoint not found for {member.display_name}")

@bot.command(name='weakpoints')
async def view_weakpoints_cmd(ctx, member: discord.Member = None):
    """View weakpoints for a user or all users - OWNER ONLY"""
    if ctx.author.id != YOUR_USER_ID:
        await ctx.send("Only my owner can view weakpoints!")
        return
    
    if member:
        # Show specific user's weakpoints
        weakpoints = get_user_weakpoints(member.id)
        if weakpoints:
            weakpoint_list = "\n".join([f"• `{wp}`" for wp in weakpoints])
            await ctx.send(f"🎯 **Weakpoints for {member.display_name}:**\n{weakpoint_list}")
        else:
            await ctx.send(f"📊 **{member.display_name}** has no weakpoints recorded.")
    else:
        # Show all users with weakpoints
        all_weakpoints = get_all_user_weakpoints()
        if all_weakpoints:
            result = "🎯 **All Users with Weakpoints:**\n\n"
            for user_id, data in all_weakpoints.items():
                user = bot.get_user(int(user_id))
                username = user.display_name if user else data['username']
                weakpoint_list = "\n".join([f"  • `{wp}`" for wp in data['weakpoints']])
                result += f"**{username}:**\n{weakpoint_list}\n\n"
            
            # Split into multiple messages if too long
            if len(result) > 2000:
                chunks = [result[i:i+1900] for i in range(0, len(result), 1900)]
                for chunk in chunks:
                    await ctx.send(chunk)
            else:
                await ctx.send(result)
        else:
            await ctx.send("📊 **No users have weakpoints recorded yet.**")

# Keep-alive web server
app = Flask(__name__)

@app.route('/')
def keep_alive():
    return "Discord AI Defense Bot is running! 🤖"

@app.route('/status')
def status():
    return {
        "status": "online",
        "bot_name": str(bot.user) if bot.user else "Not connected",
        "servers": len(bot.guilds) if bot.guilds else 0,
        "caps_punishment": caps_punishment_active,
        "total_strikes": len(user_strikes),
        "uptime": time.time()
    }

def run_web_server():
    """Run the Flask web server in a separate thread"""
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

def start_keep_alive():
    """Start the keep-alive web server"""
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    print("Keep-alive web server started on port 5000")

async def run_bot_with_reconnect():
    """Run the bot with automatic reconnection"""
    bot_token = os.getenv('DISCORD_BOT_TOKEN', 'YOUR_BOT_TOKEN')
    if bot_token == 'YOUR_BOT_TOKEN':
        print("Error: Please set DISCORD_BOT_TOKEN environment variable!")
        return
    
    retry_count = 0
    max_retries = 3
    
    while retry_count < max_retries:
        try:
            print("Starting Discord bot...")
            await bot.start(bot_token)
            # If we get here, bot started successfully, reset retry count
            retry_count = 0
        except discord.LoginFailure:
            print("❌ ERROR: Invalid bot token!")
            break
        except discord.PrivilegedIntentsRequired as e:
            print("\n" + "="*60)
            print("❌ PRIVILEGED INTENTS ERROR!")
            print("="*60)
            print("Your bot needs special permissions to work properly.")
            print("Please follow these steps:")
            print("1. Go to https://discord.com/developers/applications/")
            print("2. Click on your bot application")
            print("3. Go to the 'Bot' section")
            print("4. Scroll down to 'Privileged Gateway Intents'")
            print("5. Enable these intents:")
            print("   ✓ MESSAGE CONTENT INTENT")
            print("   ✓ SERVER MEMBERS INTENT")
            print("6. Save changes and restart your bot")
            print("="*60)
            break
        except Exception as e:
            error_msg = str(e).lower()
            
            # Handle specific error types
            if "privileged intents" in error_msg or "intents" in error_msg:
                print("\n❌ INTENTS ERROR: Enable MESSAGE CONTENT INTENT in Discord Developer Portal!")
                break
            elif "session is closed" in error_msg:
                retry_count += 1
                print(f"🔄 Connection issue (attempt {retry_count}/{max_retries}): {e}")
                if retry_count >= max_retries:
                    print("❌ Max reconnection attempts reached. Stopping bot.")
                    break
                print("Attempting to reconnect in 5 seconds...")
                await asyncio.sleep(5)
            else:
                print(f"❌ Unexpected error: {e}")
                retry_count += 1
                if retry_count >= max_retries:
                    print("❌ Too many errors. Stopping bot.")
                    break
                print("Attempting to reconnect in 5 seconds...")
                await asyncio.sleep(5)
                
            # Reset the bot connection
            if not bot.is_closed():
                await bot.close()

if __name__ == "__main__":
    # Start keep-alive web server
    start_keep_alive()
    
    # Run the bot with auto-reconnect
    try:
        asyncio.run(run_bot_with_reconnect())
    except KeyboardInterrupt:
        print("\nBot shutting down...")
    except Exception as e:
        print(f"Critical error: {e}")
        print("Restarting in 10 seconds...")
        time.sleep(10)
        # Try to restart the whole process
        os.execv(__file__, [__file__])