import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
from aiohttp import web
import asyncio
import asyncpg
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import json
import traceback
from collections import deque
import time
import hashlib
import secrets

load_dotenv()

# Configuration
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
PORT = int(os.getenv('PORT', 10000))
OWNER_ID = 447812883158532106
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
SORYN_USERNAME = os.getenv('SORYN_USERNAME')
SORYN_PASSWORD = os.getenv('SORYN_PASSWORD')
SORYN_IP = os.getenv('SORYN_IP', '')  # Allowed IP for Soryn backend

# Bot setup with proper intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # Member intent for user info
intents.presences = True  # Presence intent for status/activity tracking
bot = commands.Bot(command_prefix='!', intents=intents)

# Global state
db_pool = None
bot_start_time = datetime.now(timezone.utc)
update_mode = False
soryn_sleep = False  # Soryn sleep mode
latency_history = deque(maxlen=60)  # Store last 60 latency measurements
sessions = {}  # Simple session storage
soryn_sessions = {}  # Soryn admin session storage
console_logs = deque(maxlen=100)  # Store last 100 console logs


def log_to_console(message, level="INFO"):
    """Add message to console logs with timestamp"""
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    console_logs.append({
        'timestamp': timestamp,
        'level': level,
        'message': message
    })
    print(f"[{timestamp}] [{level}] {message}")


def hash_password(password):
    """Hash password with SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()


def check_auth(request):
    """Check if user is authenticated"""
    session_id = request.cookies.get('session_id')
    return session_id in sessions


# 4. Fix create_session function (around line 68):
def create_session():
    """Create a new session"""
    session_id = secrets.token_hex(32)
    sessions[session_id] = {
        'created_at': datetime.now(timezone.utc),
        'authenticated': True
    }
    return session_id


def check_soryn_auth(request):
    """Check if user is authenticated as Soryn"""
    session_id = request.cookies.get('soryn_session_id')
    return session_id in soryn_sessions


def check_soryn_ip(request):
    """Check if request is from allowed Soryn IP"""
    if not SORYN_IP:
        return True  # No IP restriction if not set
    
    # Get client IP (handles proxy headers)
    client_ip = request.headers.get('X-Forwarded-For', request.remote).split(',')[0].strip()
    return client_ip == SORYN_IP


# 5. Fix create_soryn_session function (around line 90):
def create_soryn_session():
    """Create a new Soryn admin session"""
    session_id = secrets.token_hex(32)
    soryn_sessions[session_id] = {
        'created_at': datetime.now(timezone.utc),
        'authenticated': True
    }
    return session_id


# ==================== DATABASE SETUP ====================

# 6. Fix init_db function to disable statement cache (CRITICAL FIX):
async def init_db():
    """Initialize database connection and create tables"""
    global db_pool
    log_to_console("Initializing database connection...")
    # Fix for pgbouncer compatibility - disable prepared statement cache
    db_pool = await asyncpg.create_pool(
        DATABASE_URL, 
        min_size=1, 
        max_size=10,
        statement_cache_size=0  # ADD THIS LINE
    )
    
    async with db_pool.acquire() as conn:
        log_to_console("Creating/verifying database tables...")
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS robo_party_users (
                user_id BIGINT NOT NULL,
                username TEXT,
                guild_id BIGINT NOT NULL,
                channel_id BIGINT,
                added_at TIMESTAMP DEFAULT NOW(),
                is_active BOOLEAN DEFAULT TRUE,
                PRIMARY KEY (user_id, guild_id)
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS party_history (
                id SERIAL PRIMARY KEY,
                completed_at TIMESTAMP DEFAULT NOW(),
                completed_by BIGINT,
                guild_id BIGINT
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS admin_users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                password_hash TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        
        # Check if main user exists first (FIX for duplicate insert)
        existing_user = await conn.fetchval(
            'SELECT user_id FROM robo_party_users WHERE user_id = $1',
            581677161006497824
        )
        
        if not existing_user:
            await conn.execute('''
                INSERT INTO robo_party_users (user_id, username, is_active)
                VALUES ($1, $2, TRUE)
            ''', 581677161006497824, 'Main User')
    
    log_to_console("✅ Database initialized and tables created", "SUCCESS")

# ==================== WEB SERVER & ADMIN PANEL ====================

async def create_html_response(html_content, status=200):
    """Create HTML response"""
    return web.Response(
        text=html_content,
        content_type='text/html',
        status=status
    )


def get_bee_favicon():
    """Get bee emoji as base64 encoded SVG favicon"""
    # Properly encoded SVG to prevent display issues
    import base64
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">🐝</text></svg>'
    svg_bytes = svg.encode('utf-8')
    svg_base64 = base64.b64encode(svg_bytes).decode('utf-8')
    return f'data:image/svg+xml;base64,{svg_base64}'


def get_rat_favicon():
    """Get rat emoji as base64 encoded SVG favicon"""
    # Properly encoded SVG to prevent display issues
    import base64
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">🐀</text></svg>'
    svg_bytes = svg.encode('utf-8')
    svg_base64 = base64.b64encode(svg_bytes).decode('utf-8')
    return f'data:image/svg+xml;base64,{svg_base64}'


# 7. Fix get_uptime function (around line 180):
def get_uptime():
    """Get bot uptime as formatted string"""
    delta = datetime.now(timezone.utc) - bot_start_time
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if days > 0:
        return f"{days}d {hours}h {minutes}m {seconds}s"
    elif hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    else:
        return f"{minutes}m {seconds}s"

async def get_user_status_info(user_id):
    """Get detailed user status information including online status, activity, and profile picture"""
    status_info = {
        'status': 'Offline',
        'status_emoji': '⚫',
        'activity': None,
        'display_name': f'User {user_id}',
        'avatar_url': 'https://cdn.discordapp.com/embed/avatars/0.png'
    }
    
    # Try to find the user in any guild the bot is in
    member = None
    user_obj = None
    
    for guild in bot.guilds:
        member = guild.get_member(user_id)
        if member:
            break
    
    # If not found in guilds, try to fetch user directly
    if not member:
        try:
            user_obj = await bot.fetch_user(user_id)
        except:
            return status_info
    
    # Get user or member object
    target = member if member else user_obj
    
    if target:
        # Get display name - USING GLOBAL DISPLAY NAME
        if hasattr(target, 'global_name') and target.global_name:
            status_info['display_name'] = target.global_name
        else:
            status_info['display_name'] = target.name
        
        # Get avatar URL
        if target.avatar:
            status_info['avatar_url'] = str(target.avatar.url)
        elif hasattr(target, 'default_avatar'):
            status_info['avatar_url'] = str(target.default_avatar.url)
        else:
            # Fallback for default avatar
            default_num = (user_id >> 22) % 6
            status_info['avatar_url'] = f'https://cdn.discordapp.com/embed/avatars/{default_num}.png'
        
        # Get status (only available for members in guilds with presence intent)
        if member:
            status_map = {
                discord.Status.online: ('🟢', 'Online'),
                discord.Status.idle: ('🟡', 'Idle'),
                discord.Status.dnd: ('🔴', 'Do Not Disturb'),
                discord.Status.offline: ('⚫', 'Offline')
            }
            status_info['status_emoji'], status_info['status'] = status_map.get(
                member.status, ('⚫', 'Offline')
            )
            
            # Get activity/game - check all activities and prioritize the most relevant
            if member.activities:
                activity_list = []
                for activity in member.activities:
                    if isinstance(activity, discord.Game):
                        activity_list.append(f"🎮 Playing {activity.name}")
                    elif isinstance(activity, discord.Streaming):
                        activity_list.append(f"📺 Streaming {activity.name}")
                    elif isinstance(activity, discord.Spotify):
                        activity_list.append(f"🎵 Listening to {activity.title}")
                    elif isinstance(activity, discord.CustomActivity):
                        if activity.name:
                            activity_list.append(f"💬 {activity.name}")
                    elif isinstance(activity, discord.Activity):
                        if activity.type == discord.ActivityType.watching:
                            activity_list.append(f"📺 Watching {activity.name}")
                        elif activity.type == discord.ActivityType.listening:
                            activity_list.append(f"🎵 Listening to {activity.name}")
                        elif activity.type == discord.ActivityType.playing:
                            activity_list.append(f"🎮 Playing {activity.name}")
                
                # Set the first non-custom activity, or the custom status if that's all we have
                if activity_list:
                    status_info['activity'] = activity_list[0]
    
    return status_info
async def login_page(request):
    """Admin login page"""
    error = request.query.get('error', '')
    
    html = f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bee Swarm Notifier - Login</title>
    <link rel="icon" href="{get_bee_favicon()}" type="image/svg+xml">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Orbitron:wght@700;900&display=swap');
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Space Mono', monospace;
            background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 50%, #0a0e27 100%);
            color: #00ff88;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            position: relative;
        }}
        
        .particles {{
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            overflow: hidden;
            z-index: 0;
        }}
        
        .particle {{
            position: absolute;
            width: 2px;
            height: 2px;
            background: #00ff88;
            border-radius: 50%;
            opacity: 0.3;
            animation: float linear infinite;
        }}
        
        @keyframes float {{
            0% {{
                transform: translateY(100vh) translateX(0);
                opacity: 0;
            }}
            10% {{
                opacity: 0.3;
            }}
            90% {{
                opacity: 0.3;
            }}
            100% {{
                transform: translateY(-100vh) translateX(100px);
                opacity: 0;
            }}
        }}
        
        .login-container {{
            background: rgba(10, 14, 39, 0.9);
            border: 2px solid #00ff88;
            border-radius: 20px;
            padding: 3rem;
            max-width: 450px;
            width: 90%;
            position: relative;
            z-index: 1;
            box-shadow: 0 0 50px rgba(0, 255, 136, 0.3);
        }}
        
        .bee-icon {{
            text-align: center;
            font-size: 4rem;
            margin-bottom: 1.5rem;
            animation: buzz 2s ease-in-out infinite;
        }}
        
        @keyframes buzz {{
            0%, 100% {{ transform: translateX(0) rotate(0deg); }}
            25% {{ transform: translateX(-5px) rotate(-5deg); }}
            75% {{ transform: translateX(5px) rotate(5deg); }}
        }}
        
        .title {{
            font-family: 'Orbitron', sans-serif;
            font-size: 2rem;
            font-weight: 900;
            color: #00ff88;
            text-shadow: 0 0 20px #00ff88;
            margin-bottom: 0.5rem;
            text-align: center;
        }}
        
        .subtitle {{
            text-align: center;
            color: #00ffcc;
            opacity: 0.8;
            margin-bottom: 2rem;
        }}
        
        .error-message {{
            background: rgba(255, 68, 68, 0.1);
            border: 1px solid #ff4444;
            color: #ff6666;
            padding: 1rem;
            border-radius: 10px;
            margin-bottom: 1.5rem;
            text-align: center;
        }}
        
        .form-group {{
            margin-bottom: 1.5rem;
        }}
        
        label {{
            display: block;
            color: #00ffcc;
            margin-bottom: 0.5rem;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        input {{
            width: 100%;
            padding: 1rem;
            background: rgba(0, 255, 136, 0.05);
            border: 2px solid rgba(0, 255, 136, 0.3);
            border-radius: 10px;
            color: #00ff88;
            font-family: 'Space Mono', monospace;
            font-size: 1rem;
            transition: all 0.3s ease;
        }}
        
        input:focus {{
            outline: none;
            border-color: #00ff88;
            box-shadow: 0 0 20px rgba(0, 255, 136, 0.2);
        }}
        
        .login-button {{
            width: 100%;
            padding: 1rem;
            background: linear-gradient(135deg, #00ff88 0%, #00ffcc 100%);
            border: none;
            border-radius: 10px;
            color: #0a0e27;
            font-family: 'Orbitron', sans-serif;
            font-size: 1.1rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 2px;
        }}
        
        .login-button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(0, 255, 136, 0.4);
        }}
        
        .login-button:active {{
            transform: translateY(0);
        }}
        
        .footer-text {{
            text-align: center;
            color: #00ffcc;
            opacity: 0.5;
            margin-top: 2rem;
            font-size: 0.85rem;
             }} 
        .user-activity {{
            font-size: 0.9rem;
            color: #4dd0ff;
            margin: 0.5rem 0;
            padding: 0.4rem 0.8rem;
            background: rgba(0, 212, 255, 0.1);
            border-left: 3px solid #00d4ff;
            border-radius: 4px;
            display: inline-block;
        }}
    </style>
</head>
<body>
    <div class="particles" id="particles"></div>
    
    <div class="login-container">
        <div class="bee-icon">🐝</div>
        <h1 class="title">ADMIN LOGIN</h1>
        <p class="subtitle">Bee Swarm Notifier</p>
        
        {"<div class='error-message'>⚠️ Invalid credentials. Please try again.</div>" if error else ""}
        
        <form method="POST" action="/login">
            <div class="form-group">
                <label for="username">Username</label>
                <input type="text" id="username" name="username" required autocomplete="username">
            </div>
            
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" required autocomplete="current-password">
            </div>
            
            <button type="submit" class="login-button">Access Dashboard</button>
        </form>
        
        <p class="footer-text">🐝 Secured Admin Panel</p>
    </div>
    
    <script>
        // Create particle animation
        const particlesContainer = document.getElementById('particles');
        for (let i = 0; i < 50; i++) {{
            const particle = document.createElement('div');
            particle.className = 'particle';
            particle.style.left = Math.random() * 100 + '%';
            particle.style.animationDuration = (Math.random() * 10 + 5) + 's';
            particle.style.animationDelay = Math.random() * 5 + 's';
            particlesContainer.appendChild(particle);
        }}
    </script>
</body>
</html>
    '''
    
    return await create_html_response(html)


async def login_submit(request):
    """Handle login form submission"""
    data = await request.post()
    username = data.get('username', '')
    password = data.get('password', '')
    
    # Check credentials
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        session_id = create_session()
        
        response = web.HTTPFound('/dashboard')
        response.set_cookie('session_id', session_id, httponly=True, max_age=86400)  # 24 hours
        return response
    else:
        raise web.HTTPFound('/login?error=invalid')


async def logout(request):
    """Handle logout"""
    session_id = request.cookies.get('session_id')
    if session_id in sessions:
        del sessions[session_id]
    
    response = web.HTTPFound('/login')
    response.del_cookie('session_id')
    return response


async def health_check(request):
    """Main admin panel page"""
    # Check authentication
    if not check_auth(request):
        raise web.HTTPFound('/login')
    
    if update_mode:
        return await update_page(request)
    
    uptime = get_uptime()
    server_count = len(bot.guilds)
    latency_ms = round(bot.latency * 1000, 2)
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    
    # Get latency history for graph
    latency_data = list(latency_history) if latency_history else [latency_ms]
    latency_json = json.dumps(latency_data)
    
    html = f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bee Swarm Notifier - Status</title>
    <link rel="icon" href="{get_bee_favicon()}" type="image/svg+xml">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Orbitron:wght@400;700;900&display=swap');
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Space Mono', monospace;
            background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 50%, #0a0e27 100%);
            color: #00ff88;
            min-height: 100vh;
            overflow-x: hidden;
            position: relative;
        }}
        
        /* Animated background particles */
        .particles {{
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            overflow: hidden;
            z-index: 0;
        }}
        
        .particle {{
            position: absolute;
            width: 2px;
            height: 2px;
            background: #00ff88;
            border-radius: 50%;
            opacity: 0.3;
            animation: float linear infinite;
        }}
        
        @keyframes float {{
            0% {{
                transform: translateY(100vh) translateX(0);
                opacity: 0;
            }}
            10% {{
                opacity: 0.3;
            }}
            90% {{
                opacity: 0.3;
            }}
            100% {{
                transform: translateY(-100vh) translateX(100px);
                opacity: 0;
            }}
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
            position: relative;
            z-index: 1;
        }}
        
        .header {{
            text-align: center;
            margin-bottom: 3rem;
            padding: 2rem;
            background: rgba(0, 255, 136, 0.05);
            border: 2px solid #00ff88;
            border-radius: 16px;
            position: relative;
            overflow: hidden;
        }}
        
        .header::before {{
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: linear-gradient(45deg, transparent, rgba(0, 255, 136, 0.1), transparent);
            animation: scan 3s linear infinite;
        }}
        
        @keyframes scan {{
            0% {{ transform: translateX(-100%) translateY(-100%) rotate(0deg); }}
            100% {{ transform: translateX(100%) translateY(100%) rotate(360deg); }}
        }}
        
        .title {{
            font-family: 'Orbitron', sans-serif;
            font-size: 3.5rem;
            font-weight: 900;
            color: #00ff88;
            text-shadow: 0 0 20px #00ff88, 0 0 40px #00ff88;
            margin-bottom: 0.5rem;
            position: relative;
            z-index: 1;
        }}
        
        .subtitle {{
            font-size: 1.2rem;
            color: #00ffcc;
            opacity: 0.8;
            position: relative;
            z-index: 1;
        }}
        
        .status-indicator {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            margin-top: 1rem;
            padding: 0.75rem 1.5rem;
            background: rgba(0, 255, 136, 0.1);
            border: 1px solid #00ff88;
            border-radius: 50px;
            position: relative;
            z-index: 1;
        }}
        
        .status-dot {{
            width: 12px;
            height: 12px;
            background: #00ff88;
            border-radius: 50%;
            animation: pulse 2s ease-in-out infinite;
        }}
        
        @keyframes pulse {{
            0%, 100% {{
                transform: scale(1);
                box-shadow: 0 0 10px #00ff88;
            }}
            50% {{
                transform: scale(1.2);
                box-shadow: 0 0 20px #00ff88, 0 0 40px #00ff88;
            }}
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 2rem;
            margin-bottom: 3rem;
        }}
        
        .stat-card {{
            background: rgba(10, 14, 39, 0.8);
            border: 2px solid #00ff88;
            border-radius: 16px;
            padding: 2rem;
            position: relative;
            overflow: hidden;
            transition: all 0.3s ease;
        }}
        
        .stat-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0, 255, 136, 0.3);
            border-color: #00ffcc;
        }}
        
        .stat-card::before {{
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(0, 255, 136, 0.1), transparent);
            transition: 0.5s;
        }}
        
        .stat-card:hover::before {{
            left: 100%;
        }}
        
        .stat-icon {{
            font-size: 2.5rem;
            margin-bottom: 1rem;
        }}
        
        .stat-label {{
            font-size: 0.9rem;
            color: #00ffcc;
            margin-bottom: 0.5rem;
            text-transform: uppercase;
            letter-spacing: 2px;
        }}
        
        .stat-value {{
            font-family: 'Orbitron', sans-serif;
            font-size: 2rem;
            font-weight: 700;
            color: #00ff88;
            text-shadow: 0 0 10px #00ff88;
        }}
        
        .graph-container {{
            background: rgba(10, 14, 39, 0.8);
            border: 2px solid #00ff88;
            border-radius: 16px;
            padding: 2rem;
            margin-bottom: 2rem;
        }}
        
        .graph-title {{
            font-family: 'Orbitron', sans-serif;
            font-size: 1.5rem;
            color: #00ff88;
            margin-bottom: 1.5rem;
            text-transform: uppercase;
            letter-spacing: 2px;
        }}
        
        #latencyGraph {{
            width: 100%;
            height: 300px;
        }}
        
        .footer {{
            text-align: center;
            padding: 2rem;
            color: #00ffcc;
            opacity: 0.7;
            border-top: 1px solid rgba(0, 255, 136, 0.2);
        }}
        
        .logout-button {{
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 0.75rem 1.5rem;
            background: rgba(255, 68, 68, 0.1);
            border: 1px solid #ff4444;
            border-radius: 8px;
            color: #ff6666;
            text-decoration: none;
            transition: all 0.3s ease;
            font-weight: 600;
            z-index: 1000;
        }}
        
        .logout-button:hover {{
            background: rgba(255, 68, 68, 0.2);
            box-shadow: 0 0 20px rgba(255, 68, 68, 0.3);
            transform: translateY(-2px);
        }}
        
        .soryn-sleep-banner {{
            background: linear-gradient(135deg, rgba(139, 69, 19, 0.9) 0%, rgba(101, 67, 33, 0.9) 100%);
            border: 2px solid #8B4513;
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            text-align: center;
            box-shadow: 0 4px 20px rgba(139, 69, 19, 0.4);
            animation: sleepPulse 3s ease-in-out infinite;
        }}
        
        @keyframes sleepPulse {{
            0%, 100% {{
                box-shadow: 0 4px 20px rgba(139, 69, 19, 0.4);
            }}
            50% {{
                box-shadow: 0 4px 30px rgba(139, 69, 19, 0.6), 0 0 50px rgba(139, 69, 19, 0.3);
            }}
        }}
        
        .soryn-sleep-title {{
            font-family: 'Orbitron', sans-serif;
            font-size: 1.5rem;
            font-weight: 700;
            color: #D2691E;
            margin-bottom: 0.5rem;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.75rem;
        }}
        
        .soryn-sleep-message {{
            color: #CD853F;
            font-size: 1rem;
            opacity: 0.95;
        }}
        
        .github-link {{
            display: inline-block;
            margin-top: 1rem;
            padding: 0.75rem 1.5rem;
            background: rgba(0, 255, 136, 0.1);
            border: 1px solid #00ff88;
            border-radius: 8px;
            color: #00ff88;
            text-decoration: none;
            transition: all 0.3s ease;
        }}
        
        .github-link:hover {{
            background: rgba(0, 255, 136, 0.2);
            box-shadow: 0 0 20px rgba(0, 255, 136, 0.3);
            transform: translateY(-2px);
        }}
        
        @media (max-width: 768px) {{
            .title {{
                font-size: 2rem;
            }}
            
            .stats-grid {{
                grid-template-columns: 1fr;
            }}
        }}
    </style>
</head>
<body>
    <a href="/logout" class="logout-button">🚪 Logout</a>
    <div class="particles" id="particles"></div>
    
    <div class="container">
        <div class="header">
            <h1 class="title">BEE SWARM NOTIFIER</h1>
            <p class="subtitle">Robo Party Tracking System</p>
            <div class="status-indicator">
                <div class="status-dot"></div>
                <span>🟢 ONLINE - ALL SYSTEMS OPERATIONAL</span>
            </div>
        </div>
        
        {f'''<div class="soryn-sleep-banner">
            <div class="soryn-sleep-title">
                <span>🐀</span>
                <span>SORYN THE RAT IS SLEEPING</span>
                <span>💤</span>
            </div>
            <div class="soryn-sleep-message">
                The bot will not be updated during this time
            </div>
        </div>''' if soryn_sleep else ''}
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-icon">⏱️</div>
                <div class="stat-label">System Uptime</div>
                <div class="stat-value">{uptime}</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">📡</div>
                <div class="stat-label">Bot Latency</div>
                <div class="stat-value">{latency_ms} ms</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">🌐</div>
                <div class="stat-label">Server Count</div>
                <div class="stat-value">{server_count}</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">🕐</div>
                <div class="stat-label">Server Time</div>
                <div class="stat-value" style="font-size: 1.2rem;">{current_time}</div>
            </div>
        </div>
        
        <div class="graph-container">
            <h2 class="graph-title">📊 Latency Monitor</h2>
            <canvas id="latencyGraph"></canvas>
        </div>
        
        <div class="footer">
            <p>🤖 SorynTech Bot Suite v1.0 - Powered by discord.py</p>
            <a href="https://github.com/soryntech" target="_blank" class="github-link">
                <svg width="20" height="20" fill="currentColor" viewBox="0 0 24 24" style="vertical-align: middle; margin-right: 8px;">
                    <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
                </svg>
                Visit GitHub
            </a>
        </div>
    </div>
    
    <script>
        // Create particle animation
        const particlesContainer = document.getElementById('particles');
        for (let i = 0; i < 50; i++) {{
            const particle = document.createElement('div');
            particle.className = 'particle';
            particle.style.left = Math.random() * 100 + '%';
            particle.style.animationDuration = (Math.random() * 10 + 5) + 's';
            particle.style.animationDelay = Math.random() * 5 + 's';
            particlesContainer.appendChild(particle);
        }}
        
        // Latency graph
        const canvas = document.getElementById('latencyGraph');
        const ctx = canvas.getContext('2d');
        
        // Set canvas size
        canvas.width = canvas.offsetWidth;
        canvas.height = 300;
        
        const latencyData = {latency_json};
        
        function drawGraph() {{
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            
            const padding = 40;
            const graphWidth = canvas.width - padding * 2;
            const graphHeight = canvas.height - padding * 2;
            
            // Draw grid
            ctx.strokeStyle = 'rgba(0, 255, 136, 0.1)';
            ctx.lineWidth = 1;
            
            for (let i = 0; i <= 5; i++) {{
                const y = padding + (graphHeight / 5) * i;
                ctx.beginPath();
                ctx.moveTo(padding, y);
                ctx.lineTo(canvas.width - padding, y);
                ctx.stroke();
            }}
            
            // Draw axes
            ctx.strokeStyle = '#00ff88';
            ctx.lineWidth = 2;
            ctx.beginPath();
            ctx.moveTo(padding, padding);
            ctx.lineTo(padding, canvas.height - padding);
            ctx.lineTo(canvas.width - padding, canvas.height - padding);
            ctx.stroke();
            
            // Draw data
            if (latencyData.length > 0) {{
                const maxLatency = Math.max(...latencyData, 100);
                const minLatency = Math.min(...latencyData, 0);
                const range = maxLatency - minLatency || 100;
                
                ctx.strokeStyle = '#00ff88';
                ctx.lineWidth = 3;
                ctx.beginPath();
                
                latencyData.forEach((value, index) => {{
                    const x = padding + (graphWidth / (latencyData.length - 1 || 1)) * index;
                    const normalizedValue = (value - minLatency) / range;
                    const y = canvas.height - padding - (normalizedValue * graphHeight);
                    
                    if (index === 0) {{
                        ctx.moveTo(x, y);
                    }} else {{
                        ctx.lineTo(x, y);
                    }}
                }});
                
                ctx.stroke();
                
                // Draw glow effect
                ctx.shadowBlur = 20;
                ctx.shadowColor = '#00ff88';
                ctx.stroke();
                ctx.shadowBlur = 0;
                
                // Draw points
                latencyData.forEach((value, index) => {{
                    const x = padding + (graphWidth / (latencyData.length - 1 || 1)) * index;
                    const normalizedValue = (value - minLatency) / range;
                    const y = canvas.height - padding - (normalizedValue * graphHeight);
                    
                    ctx.fillStyle = '#00ff88';
                    ctx.beginPath();
                    ctx.arc(x, y, 4, 0, Math.PI * 2);
                    ctx.fill();
                }});
            }}
            
            // Draw labels
            ctx.fillStyle = '#00ffcc';
            ctx.font = '12px Space Mono';
            ctx.textAlign = 'right';
            
            const maxLatency = Math.max(...latencyData, 100);
            for (let i = 0; i <= 5; i++) {{
                const value = Math.round(maxLatency * (1 - i / 5));
                const y = padding + (graphHeight / 5) * i;
                ctx.fillText(value + ' ms', padding - 10, y + 4);
            }}
        }}
        
        drawGraph();
        
        // Resize handler
        window.addEventListener('resize', () => {{
            canvas.width = canvas.offsetWidth;
            canvas.height = 300;
            drawGraph();
        }});
        
        // Auto-refresh every 30 seconds
        setTimeout(() => {{
            location.reload();
        }}, 30000);
    </script>
</body>
</html>
    '''
    
    return await create_html_response(html)


async def update_page(request):
    """Update mode page"""
    # Check authentication
    if not check_auth(request):
        raise web.HTTPFound('/login')
    
    uptime = get_uptime()
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    
    html = f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bee Swarm Notifier - Updating</title>
    <link rel="icon" href="{get_bee_favicon()}" type="image/svg+xml">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Orbitron:wght@700;900&display=swap');
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Space Mono', monospace;
            background: linear-gradient(135deg, #1a0a0a 0%, #2d1810 50%, #1a0a0a 100%);
            color: #ff9500;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            position: relative;
        }}
        
        .gears {{
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            overflow: hidden;
            z-index: 0;
            opacity: 0.1;
        }}
        
        .gear {{
            position: absolute;
            font-size: 100px;
            animation: rotate 10s linear infinite;
        }}
        
        @keyframes rotate {{
            from {{ transform: rotate(0deg); }}
            to {{ transform: rotate(360deg); }}
        }}
        
        .container {{
            text-align: center;
            position: relative;
            z-index: 1;
            padding: 3rem;
            background: rgba(45, 24, 16, 0.8);
            border: 3px solid #ff9500;
            border-radius: 20px;
            max-width: 800px;
        }}
        
        .spinner {{
            width: 120px;
            height: 120px;
            margin: 0 auto 2rem;
            position: relative;
        }}
        
        .spinner::before {{
            content: '⚙️';
            font-size: 120px;
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            animation: spin 2s linear infinite;
        }}
        
        @keyframes spin {{
            from {{ transform: translate(-50%, -50%) rotate(0deg); }}
            to {{ transform: translate(-50%, -50%) rotate(360deg); }}
        }}
        
        .title {{
            font-family: 'Orbitron', sans-serif;
            font-size: 3rem;
            font-weight: 900;
            color: #ff9500;
            text-shadow: 0 0 20px #ff9500, 0 0 40px #ff9500;
            margin-bottom: 1rem;
        }}
        
        .message {{
            font-size: 1.5rem;
            color: #ffb347;
            margin-bottom: 2rem;
        }}
        
        .status-indicator {{
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 1rem 2rem;
            background: rgba(255, 149, 0, 0.1);
            border: 2px solid #ff9500;
            border-radius: 50px;
            margin-bottom: 2rem;
        }}
        
        .status-dot {{
            width: 15px;
            height: 15px;
            background: #ff9500;
            border-radius: 50%;
            animation: pulse 1.5s ease-in-out infinite;
        }}
        
        @keyframes pulse {{
            0%, 100% {{
                transform: scale(1);
                box-shadow: 0 0 10px #ff9500;
            }}
            50% {{
                transform: scale(1.3);
                box-shadow: 0 0 25px #ff9500, 0 0 50px #ff9500;
            }}
        }}
        
        .info-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
            margin-top: 2rem;
        }}
        
        .info-item {{
            background: rgba(255, 149, 0, 0.05);
            padding: 1rem;
            border-radius: 10px;
            border: 1px solid rgba(255, 149, 0, 0.3);
        }}
        
        .info-label {{
            font-size: 0.9rem;
            color: #ffb347;
            margin-bottom: 0.5rem;
        }}
        
        .info-value {{
            font-family: 'Orbitron', sans-serif;
            font-size: 1.3rem;
            color: #ff9500;
        }}
        
        .github-link {{
            display: inline-block;
            margin-top: 2rem;
            padding: 1rem 2rem;
            background: rgba(255, 149, 0, 0.1);
            border: 2px solid #ff9500;
            border-radius: 10px;
            color: #ff9500;
            text-decoration: none;
            transition: all 0.3s ease;
        }}
        
        .github-link:hover {{
            background: rgba(255, 149, 0, 0.2);
            box-shadow: 0 0 20px rgba(255, 149, 0, 0.5);
            transform: translateY(-3px);
        }}
        
        .logout-button {{
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 0.75rem 1.5rem;
            background: rgba(255, 68, 68, 0.1);
            border: 1px solid #ff4444;
            border-radius: 8px;
            color: #ff6666;
            text-decoration: none;
            transition: all 0.3s ease;
            font-weight: 600;
            z-index: 1000;
        }}
        
        .logout-button:hover {{
            background: rgba(255, 68, 68, 0.2);
            box-shadow: 0 0 20px rgba(255, 68, 68, 0.3);
            transform: translateY(-2px);
        }}
    </style>
</head>
<body>
    <a href="/logout" class="logout-button">🚪 Logout</a>
    <div class="gears">
        <div class="gear" style="top: 10%; left: 10%; animation-duration: 8s;">⚙️</div>
        <div class="gear" style="top: 20%; right: 15%; animation-duration: 12s; animation-direction: reverse;">⚙️</div>
        <div class="gear" style="bottom: 15%; left: 20%; animation-duration: 10s;">⚙️</div>
        <div class="gear" style="bottom: 25%; right: 10%; animation-duration: 15s; animation-direction: reverse;">⚙️</div>
    </div>
    
    <div class="container">
        <div class="spinner"></div>
        <h1 class="title">SYSTEM UPDATE</h1>
        <p class="message">Bot is performing maintenance operations</p>
        
        <div class="status-indicator">
            <div class="status-dot"></div>
            <span>🟡 UPDATE MODE - MAINTENANCE IN PROGRESS</span>
        </div>
        
        <div class="info-grid">
            <div class="info-item">
                <div class="info-label">Uptime</div>
                <div class="info-value">{uptime}</div>
            </div>
            <div class="info-item">
                <div class="info-label">Server Time</div>
                <div class="info-value" style="font-size: 1rem;">{current_time}</div>
            </div>
        </div>
        
        <a href="https://github.com/soryntech" target="_blank" class="github-link">
            <svg width="20" height="20" fill="currentColor" viewBox="0 0 24 24" style="vertical-align: middle; margin-right: 8px;">
                <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z"/>
            </svg>
            Visit GitHub
        </a>
    </div>
    
    <script>
        // Auto-refresh every 30 seconds
        setTimeout(() => {{
            location.reload();
        }}, 30000);
    </script>
</body>
</html>
    '''
    
    return await create_html_response(html, status=503)


async def soryn_forbidden(request):
    """Custom 403 page for unauthorized Soryn access - Rat and Bee themed"""
    rat_favicon = get_rat_favicon()
    html = f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>403 - Access Forbidden</title>
    <link rel="icon" href="{rat_favicon}" type="image/svg+xml">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Orbitron:wght@700;900&display=swap');
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Space Mono', monospace;
            min-height: 100vh;
            display: flex;
            overflow: hidden;
        }}
        
        .split {{
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
            overflow: hidden;
        }}
        
        .shark-side {{
            background: linear-gradient(135deg, #001f3f 0%, #003d7a 100%);
            color: #00d4ff;
        }}
        
        .bee-side {{
            background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);
            color: #00ff88;
        }}
        
        .icon-float {{
            position: absolute;
            font-size: 5rem;
            animation: float 3s ease-in-out infinite;
        }}
        
        .shark-icon {{
            top: 10%;
            left: 50%;
            transform: translateX(-50%);
        }}
        
        .bee-icon {{
            top: 10%;
            left: 50%;
            transform: translateX(-50%);
        }}
        
        @keyframes float {{
            0%, 100% {{ transform: translateX(-50%) translateY(0); }}
            50% {{ transform: translateX(-50%) translateY(-20px); }}
        }}
        
        .content {{
            text-align: center;
            z-index: 1;
            padding: 2rem;
        }}
        
        .error-code {{
            font-family: 'Orbitron', sans-serif;
            font-size: 8rem;
            font-weight: 900;
            margin-bottom: 1rem;
            text-shadow: 0 0 30px currentColor;
            animation: pulse 2s ease-in-out infinite;
        }}
        
        @keyframes pulse {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.7; }}
        }}
        
        .error-title {{
            font-family: 'Orbitron', sans-serif;
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 1rem;
            text-transform: uppercase;
        }}
        
        .error-message {{
            font-size: 1.1rem;
            opacity: 0.8;
            margin-bottom: 2rem;
            line-height: 1.6;
        }}
        
        .divider {{
            width: 4px;
            background: linear-gradient(to bottom, #00d4ff 0%, #00ff88 100%);
            box-shadow: 0 0 20px #00d4ff, 0 0 20px #00ff88;
            position: relative;
        }}
        
        .back-button {{
            display: inline-block;
            padding: 1rem 2rem;
            background: rgba(255, 255, 255, 0.1);
            border: 2px solid currentColor;
            border-radius: 10px;
            color: inherit;
            text-decoration: none;
            font-weight: 700;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        .back-button:hover {{
            background: rgba(255, 255, 255, 0.2);
            box-shadow: 0 0 20px currentColor;
            transform: translateY(-2px);
        }}
        
        @media (max-width: 768px) {{
            body {{
                flex-direction: column;
            }}
            
            .divider {{
                width: 100%;
                height: 4px;
                background: linear-gradient(to right, #00d4ff 0%, #00ff88 100%);
            }}
            
            .error-code {{
                font-size: 5rem;
            }}
            
            .error-title {{
                font-size: 1.5rem;
            }}
        }}
    </style>
</head>
<body>
    <div class="split shark-side">
        <div class="icon-float shark-icon">🐀</div>
        <div class="content">
            <div class="error-code">403</div>
            <div class="error-title">Access Forbidden</div>
            <div class="error-message">
                This area is restricted to<br>
                authorized personnel only.<br>
                <strong>IP address not authorized.</strong>
            </div>
            <a href="/" class="back-button">← Return Home</a>
        </div>
    </div>
    
    <div class="divider"></div>
    
    <div class="split bee-side">
        <div class="icon-float bee-icon">🐝</div>
        <div class="content">
            <div class="error-code">403</div>
            <div class="error-title">Access Denied</div>
            <div class="error-message">
                Your location is not permitted<br>
                to access this backend.<br>
                <strong>Please contact the administrator.</strong>
            </div>
            <a href="/" class="back-button">← Return Home</a>
        </div>
    </div>
</body>
</html>
    '''
    
    return await create_html_response(html, status=403)


async def soryn_login_page(request):
    """Soryn admin login page - shark themed"""
    # Check IP restriction
    if not check_soryn_ip(request):
        return await soryn_forbidden(request)
    
    error = request.query.get('error', '')
    
    html = f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Soryn Backend - Login</title>
    <link rel="icon" href="{get_rat_favicon()}" type="image/svg+xml">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Orbitron:wght@700;900&display=swap');
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Space Mono', monospace;
            background: linear-gradient(135deg, #001f3f 0%, #003d7a 50%, #001f3f 100%);
            color: #00d4ff;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
            position: relative;
        }}
        
        .ocean-bg {{
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            overflow: hidden;
            z-index: 0;
        }}
        
        .shark {{
            position: absolute;
            font-size: 60px;
            animation: swimShark linear infinite;
        }}
        
        @keyframes swimShark {{
            0% {{
                left: -100px;
                top: var(--swim-y);
            }}
            100% {{
                left: 110%;
                top: var(--swim-y);
            }}
        }}
        
        .login-container {{
            background: rgba(0, 31, 63, 0.95);
            border: 3px solid #00d4ff;
            border-radius: 20px;
            padding: 3rem;
            max-width: 450px;
            width: 90%;
            position: relative;
            z-index: 1;
            box-shadow: 0 0 50px rgba(0, 212, 255, 0.5);
        }}
        
        .shark-icon {{
            text-align: center;
            font-size: 5rem;
            margin-bottom: 1.5rem;
            animation: swimBounce 3s ease-in-out infinite;
        }}
        
        @keyframes swimBounce {{
            0%, 100% {{ transform: translateY(0) rotate(0deg); }}
            25% {{ transform: translateY(-10px) rotate(-3deg); }}
            75% {{ transform: translateY(10px) rotate(3deg); }}
        }}
        
        .title {{
            font-family: 'Orbitron', sans-serif;
            font-size: 2.2rem;
            font-weight: 900;
            color: #00d4ff;
            text-shadow: 0 0 20px #00d4ff, 0 0 40px #00d4ff;
            margin-bottom: 0.5rem;
            text-align: center;
        }}
        
        .subtitle {{
            text-align: center;
            color: #4dd0ff;
            opacity: 0.9;
            margin-bottom: 2rem;
            font-size: 0.95rem;
        }}
        
        .warning {{
            background: rgba(255, 68, 68, 0.15);
            border: 2px solid #ff4444;
            color: #ff8888;
            padding: 1rem;
            border-radius: 10px;
            margin-bottom: 1.5rem;
            text-align: center;
            font-size: 0.9rem;
        }}
        
        .error-message {{
            background: rgba(255, 68, 68, 0.2);
            border: 1px solid #ff4444;
            color: #ff6666;
            padding: 1rem;
            border-radius: 10px;
            margin-bottom: 1.5rem;
            text-align: center;
        }}
        
        .form-group {{
            margin-bottom: 1.5rem;
        }}
        
        label {{
            display: block;
            color: #4dd0ff;
            margin-bottom: 0.5rem;
            font-size: 0.9rem;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        input {{
            width: 100%;
            padding: 1rem;
            background: rgba(0, 212, 255, 0.05);
            border: 2px solid rgba(0, 212, 255, 0.3);
            border-radius: 10px;
            color: #00d4ff;
            font-family: 'Space Mono', monospace;
            font-size: 1rem;
            transition: all 0.3s ease;
        }}
        
        input:focus {{
            outline: none;
            border-color: #00d4ff;
            box-shadow: 0 0 20px rgba(0, 212, 255, 0.3);
        }}
        
        .login-button {{
            width: 100%;
            padding: 1rem;
            background: linear-gradient(135deg, #00d4ff 0%, #0080ff 100%);
            border: none;
            border-radius: 10px;
            color: #001f3f;
            font-family: 'Orbitron', sans-serif;
            font-size: 1.1rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 2px;
        }}
        
        .login-button:hover {{
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(0, 212, 255, 0.5);
        }}
        
        .footer-text {{
            text-align: center;
            color: #4dd0ff;
            opacity: 0.6;
            margin-top: 2rem;
            font-size: 0.8rem;
        }}
    </style>
</head>
<body>
    <div class="ocean-bg" id="ocean"></div>
    
    <div class="login-container">
        <div class="shark-icon">🐀</div>
        <h1 class="title">SORYN BACKEND</h1>
        <p class="subtitle">Administrative Control Panel</p>
        
        <div class="warning">
            ⚠️ <strong>AUTHORIZED PERSONNEL ONLY</strong><br>
            Unauthorized access is prohibited
        </div>
        
        {"<div class='error-message'>❌ Invalid credentials. Access denied.</div>" if error else ""}
        
        <form method="POST" action="/STBS/login">
            <div class="form-group">
                <label for="username">Soryn Username</label>
                <input type="text" id="username" name="username" required autocomplete="username">
            </div>
            
            <div class="form-group">
                <label for="password">Soryn Password</label>
                <input type="password" id="password" name="password" required autocomplete="current-password">
            </div>
            
            <button type="submit" class="login-button">Access Backend</button>
        </form>
        
        <p class="footer-text">🐀 Soryn Tech Backend v2.0</p>
    </div>
    
    <script>
        // Animated rats
        const ocean = document.getElementById('ocean');
        for (let i = 0; i < 5; i++) {{
            const shark = document.createElement('div');
            shark.className = 'shark';
            shark.textContent = '🐀';
            shark.style.setProperty('--swim-y', (Math.random() * 80 + 10) + '%');
            shark.style.animationDuration = (Math.random() * 15 + 10) + 's';
            shark.style.animationDelay = (Math.random() * 5) + 's';
            ocean.appendChild(shark);
        }}
    </script>
</body>
</html>
    '''
    
    return await create_html_response(html)


async def soryn_login_submit(request):
    """Handle Soryn login form submission"""
    # Check IP restriction
    if not check_soryn_ip(request):
        return await soryn_forbidden(request)
    
    data = await request.post()
    username = data.get('username', '')
    password = data.get('password', '')
    
    # Check Soryn credentials
    if username == SORYN_USERNAME and password == SORYN_PASSWORD:
        session_id = create_soryn_session()
        
        response = web.HTTPFound('/STBS')
        response.set_cookie('soryn_session_id', session_id, httponly=True, max_age=86400)
        return response
    else:
        raise web.HTTPFound('/STBS/login?error=invalid')


async def soryn_logout(request):
    """Handle Soryn logout"""
    session_id = request.cookies.get('soryn_session_id')
    if session_id in soryn_sessions:
        del soryn_sessions[session_id]
    
    response = web.HTTPFound('/STBS/login')
    response.del_cookie('soryn_session_id')
    return response


async def soryn_admin_panel(request):
    """Soryn backend admin panel - shark themed, NOT affected by maintenance"""
    # Check IP restriction first
    if not check_soryn_ip(request):
        return await soryn_forbidden(request)
    
    # Check Soryn authentication
    if not check_soryn_auth(request):
        raise web.HTTPFound('/STBS/login')
    
    uptime = get_uptime()
    server_count = len(bot.guilds)
    latency_ms = round(bot.latency * 1000, 2)
    current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    
    # Get user statistics
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval('SELECT COUNT(*) FROM robo_party_users')
        active_users = await conn.fetchval('SELECT COUNT(*) FROM robo_party_users WHERE is_active = TRUE')
        
        # Count active parties (users who have run /start)
        active_parties_count = len(user_party_states)
        
        # Get all users for notification list with enhanced info
        users = await conn.fetch('''
            SELECT user_id, username, guild_id, channel_id, is_active, added_at
            FROM robo_party_users
            ORDER BY added_at DESC
        ''')
    
    # Enhance user data with server and channel names
# Enhance user data with server, channel names, and status info
    enhanced_users = []
    for user in users:
        user_dict = dict(user)
        
        # Get guild name
        if user['guild_id']:
            guild = bot.get_guild(user['guild_id'])
            user_dict['guild_name'] = guild.name if guild else f"Unknown Server ({user['guild_id']})"
        else:
            user_dict['guild_name'] = "Not set"
        
        # Get channel name
        if user['channel_id']:
            channel = bot.get_channel(user['channel_id'])
            user_dict['channel_name'] = f"#{channel.name}" if channel else f"Unknown Channel ({user['channel_id']})"
        else:
            user_dict['channel_name'] = "Not set"
        
        # Get user status and activity information
        status_info = await get_user_status_info(user['user_id'])
        user_dict['display_name'] = status_info['display_name']
        user_dict['status'] = status_info['status']
        user_dict['status_emoji'] = status_info['status_emoji']
        user_dict['activity'] = status_info['activity']
        user_dict['avatar_url'] = status_info['avatar_url']  # Add avatar URL
        
        enhanced_users.append(user_dict)
    
    users = enhanced_users
    
    # Get guild information
    guild_info = []
    for guild in bot.guilds:
        try:
            # Try to get guild icon
            icon_url = str(guild.icon.url) if guild.icon else "https://cdn.discordapp.com/embed/avatars/0.png"
            guild_info.append({
                'name': guild.name,
                'id': guild.id,
                'member_count': guild.member_count,
                'icon': icon_url
            })
        except:
            pass
    
    # Get next party time - show soonest upcoming party
    next_party = "No active trackers"
    if user_party_states:
        # Find the soonest next party time
        now = datetime.now(timezone.utc)
        upcoming_times = [state['next_party_time'] for state in user_party_states.values() 
                         if state.get('next_party_time') and state['next_party_time'] > now]
        
        if upcoming_times:
            soonest = min(upcoming_times)
            time_left = soonest - now
            hours = int(time_left.total_seconds() // 3600)
            minutes = int((time_left.total_seconds() % 3600) // 60)
            next_party = f"{hours}h {minutes}m"
    
# Prepare user data for chart
    user_chart_data = json.dumps([1 if u['is_active'] else 0 for u in users])
    user_labels = json.dumps([
        u['display_name'][:20] + '...' if len(u.get('display_name', '')) > 20 
        else u.get('display_name', f'User {u["user_id"]}') 
        for u in users
    ])
    
    # Prepare active users list with enhanced status
    active_user_list = []
    testing_user_list = []
    OWNER_ID = 447812883158532106
    
    for user in users:
        if user['is_active']:
            user_id = user['user_id']
            guild_id = user.get('guild_id')
            
            # Determine user's party tracking status
            key = (guild_id, user_id) if guild_id else None
            party_status = "Inactive"  # Default
            next_party_display = None
            is_testing = False
            
            if key and key in user_party_states:
                user_state = user_party_states[key]
                now = datetime.now(timezone.utc)
                
                # Check if sleeping
                if user_state.get('sleep_until') and now < user_state['sleep_until']:
                    time_left = user_state['sleep_until'] - now
                    hours = int(time_left.total_seconds() // 3600)
                    minutes = int((time_left.total_seconds() % 3600) // 60)
                    party_status = f"Sleeping ({hours}h {minutes}m)"
                
                # Check if testing (owner with party time < 5 minutes away)
                elif user_id == OWNER_ID and user_state.get('next_party_time'):
                    time_until = user_state['next_party_time'] - now
                    if 0 < time_until.total_seconds() < 600:  # Less than 10 minutes
                        party_status = "Testing"
                        is_testing = True
                        next_party_display = user_state['next_party_time']
                    else:
                        party_status = "Active"
                        next_party_display = user_state['next_party_time']
                
                # Regular active state
                elif user_state.get('next_party_time'):
                    party_status = "Active"
                    next_party_display = user_state['next_party_time']
            
            user_info = {
                'user_id': user['user_id'],
                'display_name': user['display_name'],
                'avatar_url': user['avatar_url'],
                'status': user['status'],
                'status_emoji': user['status_emoji'],
                'activity': user['activity'],
                'party_status': party_status,
                'next_party_time': next_party_display,
                'guild_name': user.get('guild_name', 'Unknown'),
                'channel_name': user.get('channel_name', 'Unknown')
            }
            
            # Separate testing users from regular users
            if is_testing:
                testing_user_list.append(user_info)
            else:
                active_user_list.append(user_info)
    
    html = f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Soryn Backend - Control Panel</title>
    <link rel="icon" href="{get_rat_favicon()}" type="image/svg+xml">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Orbitron:wght@400;700;900&display=swap');
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: 'Space Mono', monospace;
            background: linear-gradient(135deg, #001f3f 0%, #003d7a 50%, #001f3f 100%);
            color: #00d4ff;
            min-height: 100vh;
            overflow-x: hidden;
        }}
        
        .ocean-bg {{
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            overflow: hidden;
            z-index: 0;
            opacity: 0.3;
        }}
        
        .bubble {{
            position: absolute;
            bottom: -50px;
            width: 20px;
            height: 20px;
            background: rgba(0, 212, 255, 0.2);
            border-radius: 50%;
            animation: riseBubble linear infinite;
        }}
        
        @keyframes riseBubble {{
            0% {{
                bottom: -50px;
                opacity: 0;
            }}
            10% {{
                opacity: 0.5;
            }}
            90% {{
                opacity: 0.5;
            }}
            100% {{
                bottom: 110vh;
                opacity: 0;
            }}
        }}
        
        .navbar {{
            background: rgba(0, 31, 63, 0.95);
            border-bottom: 2px solid #00d4ff;
            padding: 1.5rem 2rem;
            position: sticky;
            top: 0;
            z-index: 1000;
            box-shadow: 0 4px 20px rgba(0, 212, 255, 0.3);
        }}
        
        .nav-content {{
            max-width: 1400px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        .nav-brand {{
            display: flex;
            align-items: center;
            gap: 1rem;
        }}
        
        .shark-icon {{
            font-size: 2.5rem;
            animation: swimBounce 3s ease-in-out infinite;
        }}
        
        @keyframes swimBounce {{
            0%, 100% {{ transform: translateY(0) rotate(0deg); }}
            25% {{ transform: translateY(-5px) rotate(-3deg); }}
            75% {{ transform: translateY(5px) rotate(3deg); }}
        }}
        
        .nav-title {{
            font-family: 'Orbitron', sans-serif;
            font-size: 1.8rem;
            font-weight: 900;
            color: #00d4ff;
            text-shadow: 0 0 15px #00d4ff;
        }}
        
        .nav-buttons {{
            display: flex;
            gap: 1rem;
        }}
        
        .btn {{
            padding: 0.75rem 1.5rem;
            border-radius: 8px;
            font-family: 'Space Mono', monospace;
            font-weight: 600;
            text-decoration: none;
            transition: all 0.3s ease;
            border: none;
            cursor: pointer;
            font-size: 0.9rem;
        }}
        
        .btn-maintenance {{
            background: {"rgba(255, 149, 0, 0.2)" if update_mode else "rgba(0, 212, 255, 0.1)"};
            border: 2px solid {"#ff9500" if update_mode else "#00d4ff"};
            color: {"#ff9500" if update_mode else "#00d4ff"};
        }}
        
        .btn-maintenance:hover {{
            background: {"rgba(255, 149, 0, 0.3)" if update_mode else "rgba(0, 212, 255, 0.2)"};
            box-shadow: 0 0 15px {"rgba(255, 149, 0, 0.4)" if update_mode else "rgba(0, 212, 255, 0.4)"};
        }}
        
        .btn-sleep {{
            background: {"rgba(255, 204, 0, 0.2)" if soryn_sleep else "rgba(139, 69, 19, 0.1)"};
            border: 2px solid {"#ffcc00" if soryn_sleep else "#8B4513"};
            color: {"#ffcc00" if soryn_sleep else "#D2691E"};
        }}
        
        .btn-sleep:hover {{
            background: {"rgba(255, 204, 0, 0.3)" if soryn_sleep else "rgba(139, 69, 19, 0.2)"};
            box-shadow: 0 0 15px {"rgba(255, 204, 0, 0.4)" if soryn_sleep else "rgba(139, 69, 19, 0.4)"};
        }}
        
        .btn-logout {{
            background: rgba(255, 68, 68, 0.1);
            border: 2px solid #ff4444;
            color: #ff6666;
        }}
        
        .btn-logout:hover {{
            background: rgba(255, 68, 68, 0.2);
            box-shadow: 0 0 15px rgba(255, 68, 68, 0.4);
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 2rem;
            position: relative;
            z-index: 1;
        }}
        
        .status-banner {{
            background: {"rgba(255, 149, 0, 0.15)" if update_mode else "rgba(0, 255, 136, 0.1)"};
            border: 2px solid {"#ff9500" if update_mode else "#00ff88"};
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            text-align: center;
        }}
        
        .status-text {{
            font-size: 1.2rem;
            color: {"#ff9500" if update_mode else "#00ff88"};
            font-weight: 700;
        }}
        
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }}
        
        .stat-card {{
            background: rgba(0, 31, 63, 0.8);
            border: 2px solid #00d4ff;
            border-radius: 16px;
            padding: 2rem;
            transition: all 0.3s ease;
        }}
        
        .stat-card:hover {{
            transform: translateY(-5px);
            box-shadow: 0 10px 30px rgba(0, 212, 255, 0.4);
        }}
        
        .stat-icon {{
            font-size: 2.5rem;
            margin-bottom: 1rem;
        }}
        
        .stat-label {{
            font-size: 0.9rem;
            color: #4dd0ff;
            margin-bottom: 0.5rem;
            text-transform: uppercase;
            letter-spacing: 1px;
        }}
        
        .stat-value {{
            font-family: 'Orbitron', sans-serif;
            font-size: 2rem;
            font-weight: 700;
            color: #00d4ff;
            text-shadow: 0 0 10px #00d4ff;
        }}
        
        .section {{
            background: rgba(0, 31, 63, 0.8);
            border: 2px solid #00d4ff;
            border-radius: 16px;
            padding: 2rem;
            margin-bottom: 2rem;
        }}
        
        .section-title {{
            font-family: 'Orbitron', sans-serif;
            font-size: 1.5rem;
            color: #00d4ff;
            margin-bottom: 1.5rem;
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }}
        
        .user-list {{
            display: flex;
            flex-direction: column;
            gap: 1rem;
            max-height: 400px;
            overflow-y: auto;
        }}
        
        .user-item {{
            background: rgba(0, 212, 255, 0.05);
            border: 1px solid rgba(0, 212, 255, 0.3);
            border-radius: 10px;
            padding: 1rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        
        .user-info {{
            flex: 1;
        }}
        
        .user-name {{
            font-weight: 600;
            color: #00d4ff;
            margin-bottom: 0.25rem;
        }}
        
        .user-meta {{
            font-size: 0.85rem;
            color: #4dd0ff;
            opacity: 0.7;
        }}
        
        .user-status {{
            padding: 0.5rem 1rem;
            border-radius: 6px;
            font-size: 0.85rem;
            font-weight: 600;
        }}
        
        .status-active {{
            background: rgba(0, 255, 136, 0.2);
            color: #00ff88;
            border: 1px solid #00ff88;
        }}
        
        .status-inactive {{
            background: rgba(255, 68, 68, 0.2);
            color: #ff6666;
            border: 1px solid #ff4444;
        }}
        
        .user-activity {{
            font-size: 0.9rem;
            color: #4dd0ff;
            margin: 0.5rem 0;
            padding: 0.4rem 0.8rem;
            background: rgba(0, 212, 255, 0.1);
            border-left: 3px solid #00d4ff;
            border-radius: 4px;
            display: inline-block;
        }}
        
        /* Active Users Section Styles */
        .active-users-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 1.5rem;
        }}
        
        .active-user-card {{
            background: rgba(0, 212, 255, 0.05);
            border: 2px solid rgba(0, 212, 255, 0.3);
            border-radius: 12px;
            padding: 1.5rem;
            display: flex;
            gap: 1rem;
            transition: all 0.3s ease;
        }}
        
        .active-user-card:hover {{
            transform: translateY(-3px);
            box-shadow: 0 5px 20px rgba(0, 212, 255, 0.4);
            border-color: #00d4ff;
        }}
        
        .user-avatar {{
            width: 80px;
            height: 80px;
            border-radius: 50%;
            border: 3px solid #00d4ff;
            object-fit: cover;
            flex-shrink: 0;
        }}
        
        .user-details {{
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }}
        
        .user-name-row {{
            font-size: 1.1rem;
            color: #00d4ff;
            font-weight: 600;
        }}
        
        .user-status-text {{
            font-size: 0.9rem;
            color: #4dd0ff;
            opacity: 0.8;
        }}
        
        .user-activity-badge {{
            background: rgba(0, 212, 255, 0.15);
            border-left: 3px solid #00d4ff;
            padding: 0.5rem;
            border-radius: 4px;
            font-size: 0.85rem;
            color: #4dd0ff;
        }}
        
        .party-status-indicator {{
            padding: 0.4rem 0.8rem;
            border-radius: 6px;
            font-size: 0.85rem;
            font-weight: 600;
            margin: 0.3rem 0;
        }}
        
        .party-status-indicator.active {{
            background: rgba(0, 255, 136, 0.15);
            border: 1px solid rgba(0, 255, 136, 0.5);
            color: #00ff88;
        }}
        
        .party-status-indicator.inactive {{
            background: rgba(255, 68, 68, 0.15);
            border: 1px solid rgba(255, 68, 68, 0.5);
            color: #ff6666;
        }}
        
        .party-status-indicator.sleeping {{
            background: rgba(255, 204, 0, 0.15);
            border: 1px solid rgba(255, 204, 0, 0.5);
            color: #ffcc00;
        }}
        
        .party-status-indicator.testing {{
            background: rgba(138, 43, 226, 0.15);
            border: 1px solid rgba(138, 43, 226, 0.5);
            color: #ba55d3;
            animation: testingPulse 2s ease-in-out infinite;
        }}
        
        @keyframes testingPulse {{
            0%, 100% {{
                box-shadow: 0 0 5px rgba(138, 43, 226, 0.3);
            }}
            50% {{
                box-shadow: 0 0 15px rgba(138, 43, 226, 0.6);
            }}
        }}
        
        .testing-card {{
            border: 2px solid rgba(138, 43, 226, 0.4);
            background: linear-gradient(135deg, rgba(138, 43, 226, 0.05) 0%, rgba(75, 0, 130, 0.05) 100%);
        }}
        
        .user-location {{
            font-size: 0.8rem;
            color: #4dd0ff;
            opacity: 0.7;
        }}

        
        .guilds-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
            gap: 1.5rem;
        }}
        
        .guild-card {{
            background: rgba(0, 212, 255, 0.05);
            border: 1px solid rgba(0, 212, 255, 0.3);
            border-radius: 12px;
            padding: 1.5rem;
            text-align: center;
            transition: all 0.3s ease;
        }}
        
        .guild-card:hover {{
            transform: translateY(-3px);
            box-shadow: 0 5px 20px rgba(0, 212, 255, 0.3);
        }}
        
        .guild-icon {{
            width: 80px;
            height: 80px;
            border-radius: 50%;
            margin-bottom: 1rem;
            border: 2px solid #00d4ff;
        }}
        
        .guild-name {{
            font-weight: 600;
            color: #00d4ff;
            margin-bottom: 0.5rem;
        }}
        
        .guild-members {{
            font-size: 0.85rem;
            color: #4dd0ff;
        }}
        
        .console-log {{
            background: rgba(0, 0, 0, 0.5);
            border: 1px solid rgba(0, 212, 255, 0.3);
            border-radius: 10px;
            padding: 1rem;
            max-height: 500px;
            overflow-y: auto;
            font-family: 'Space Mono', monospace;
            font-size: 0.85rem;
        }}
        
        .log-entry {{
            padding: 0.5rem;
            margin-bottom: 0.25rem;
            border-left: 3px solid #00d4ff;
            background: rgba(0, 212, 255, 0.03);
            border-radius: 4px;
            display: flex;
            gap: 0.75rem;
            align-items: flex-start;
        }}
        
        .log-entry:hover {{
            background: rgba(0, 212, 255, 0.08);
        }}
        
        .log-time {{
            color: #4dd0ff;
            opacity: 0.7;
            flex-shrink: 0;
        }}
        
        .log-level {{
            font-weight: 700;
            flex-shrink: 0;
            min-width: 70px;
        }}
        
        .log-message {{
            color: #00d4ff;
            flex: 1;
        }}
        
        .log-info {{
            border-left-color: #00d4ff;
        }}
        
        .log-info .log-level {{
            color: #00d4ff;
        }}
        
        .log-success {{
            border-left-color: #00ff88;
        }}
        
        .log-success .log-level {{
            color: #00ff88;
        }}
        
        .log-warning {{
            border-left-color: #ff9500;
        }}
        
        .log-warning .log-level {{
            color: #ff9500;
        }}
        
        .log-error {{
            border-left-color: #ff4444;
        }}
        
        .log-error .log-level {{
            color: #ff4444;
        }}
        
        canvas {{
            max-width: 100%;
            height: 300px !important;
        }}
        
        ::-webkit-scrollbar {{
            width: 8px;
        }}
        
        ::-webkit-scrollbar-track {{
            background: rgba(0, 31, 63, 0.5);
        }}
        
        ::-webkit-scrollbar-thumb {{
            background: #00d4ff;
            border-radius: 4px;
        }}
        
        ::-webkit-scrollbar-thumb:hover {{
            background: #4dd0ff;
        }}
        
        .maintenance-indicator {{
            position: fixed;
            top: 80px;
            right: 20px;
            background: rgba(255, 149, 0, 0.95);
            border: 3px solid #ff9500;
            border-radius: 12px;
            padding: 1.5rem;
            box-shadow: 0 8px 32px rgba(255, 149, 0, 0.5);
            z-index: 9999;
            animation: slideInRight 0.5s ease-out, pulseBorder 2s infinite;
            max-width: 300px;
        }}
        
        @keyframes slideInRight {{
            from {{
                transform: translateX(400px);
                opacity: 0;
            }}
            to {{
                transform: translateX(0);
                opacity: 1;
            }}
        }}
        
        @keyframes pulseBorder {{
            0%, 100% {{
                box-shadow: 0 8px 32px rgba(255, 149, 0, 0.5);
            }}
            50% {{
                box-shadow: 0 8px 32px rgba(255, 149, 0, 0.8), 0 0 50px rgba(255, 149, 0, 0.4);
            }}
        }}
        
        .maintenance-indicator-title {{
            font-family: 'Orbitron', sans-serif;
            font-size: 1.2rem;
            font-weight: 700;
            color: #fff;
            margin-bottom: 0.5rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        
        .maintenance-indicator-text {{
            color: #fff;
            font-size: 0.9rem;
            opacity: 0.95;
        }}
        
        @media (max-width: 768px) {{
            .maintenance-indicator {{
                top: auto;
                bottom: 20px;
                right: 20px;
                left: 20px;
            }}
        }}
    </style>
</head>
<body>
    <div class="ocean-bg" id="ocean"></div>
    
    {f'''<div class="maintenance-indicator">
        <div class="maintenance-indicator-title">
            <span>⚠️</span>
            <span>MAINTENANCE ACTIVE</span>
        </div>
        <div class="maintenance-indicator-text">
            Public admin panel is showing<br>maintenance mode to users.
        </div>
    </div>''' if update_mode else ''}
    
    <nav class="navbar">
        <div class="nav-content">
            <div class="nav-brand">
                <div class="shark-icon">🐀</div>
                <div class="nav-title">SORYN BACKEND</div>
            </div>
            <div class="nav-buttons">
                <form method="POST" action="/STBS/toggle-maintenance" style="display: inline;">
                    <button type="submit" class="btn btn-maintenance">
                        {"🟢 DISABLE MAINTENANCE" if update_mode else "🟡 ENABLE MAINTENANCE"}
                    </button>
                </form>
                <form method="POST" action="/STBS/toggle-soryn-sleep" style="display: inline;">
                    <button type="submit" class="btn btn-sleep">
                        {"☀️ WAKE UP" if soryn_sleep else "💤 SLEEP MODE"}
                    </button>
                </form>
                <a href="/STBS/logout" class="btn btn-logout">🚪 Logout</a>
            </div>
        </div>
    </nav>
    
    <div class="container">
        {"<div class='status-banner'><div class='status-text'>🟡 MAINTENANCE MODE ACTIVE</div></div>" if update_mode else ""}
        
        <div class="stats-grid">
            <div class="stat-card">
                <div class="stat-icon">⏱️</div>
                <div class="stat-label">System Uptime</div>
                <div class="stat-value">{uptime}</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">📡</div>
                <div class="stat-label">Bot Latency</div>
                <div class="stat-value">{latency_ms} ms</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">🌐</div>
                <div class="stat-label">Server Count</div>
                <div class="stat-value">{server_count}</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">✅</div>
                <div class="stat-label">Active Users</div>
                <div class="stat-value">{active_users}</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">👥</div>
                <div class="stat-label">Notified Users</div>
                <div class="stat-value">{active_users}/{total_users}</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">⏰</div>
                <div class="stat-label">Next Party</div>
                <div class="stat-value" style="font-size: 1.3rem;">{next_party}</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">🎉</div>
                <div class="stat-label">Users with Parties Active</div>
                <div class="stat-value">{active_parties_count}/{active_users}</div>
            </div>
        </div>
        
        <div class="section">
            <h2 class="section-title">
                <span>👤</span>
                Active Users ({len(active_user_list)})
            </h2>
            <div class="active-users-grid">
                {"".join([f'''
                <div class="active-user-card">
                    <img src="{u['avatar_url']}" alt="{u['display_name']}" class="user-avatar" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'">
                    <div class="user-details">
                        <div class="user-name-row">
                            {u['status_emoji']} <strong>{u['display_name']}</strong>
                        </div>
                        <div class="user-status-text">{u['status']}</div>
                        {f'<div class="user-activity-badge">{u["activity"]}</div>' if u.get('activity') and u['activity'] is not None and str(u['activity']).strip() else ''}
                        <div class="party-status-indicator {u['party_status'].lower().split()[0]}">
                            {
                                "✅ Active: " + u['next_party_time'].strftime('%H:%M UTC') if u['party_status'] == "Active" and u.get('next_party_time') else
                                "❌ Inactive" if u['party_status'] == "Inactive" else
                                "💤 " + u['party_status'] if "Sleeping" in u['party_status'] else
                                u['party_status']
                            }
                        </div>
                        <div class="user-location">
                            📍 {u['guild_name']} → {u['channel_name']}
                        </div>
                    </div>
                </div>
                ''' for u in active_user_list]) if active_user_list else '<p style="text-align: center; color: #4dd0ff; padding: 2rem;">No active users currently registered.</p>'}
            </div>
        </div>
        
        {'''
        <div class="section">
            <h2 class="section-title">
                <span>🧪</span>
                Testing Mode
            </h2>
            <div class="active-users-grid">
                ''' + "".join([f'''
                <div class="active-user-card testing-card">
                    <img src="{u['avatar_url']}" alt="{u['display_name']}" class="user-avatar" onerror="this.src='https://cdn.discordapp.com/embed/avatars/0.png'">
                    <div class="user-details">
                        <div class="user-name-row">
                            {u['status_emoji']} <strong>{u['display_name']}</strong>
                        </div>
                        <div class="user-status-text">{u['status']}</div>
                        {f'<div class="user-activity-badge">{u["activity"]}</div>' if u.get('activity') and u['activity'] is not None and str(u['activity']).strip() else ''}
                        <div class="party-status-indicator testing">
                            🧪 Testing: {u['next_party_time'].strftime('%H:%M UTC') if u.get('next_party_time') else 'Soon'}
                        </div>
                        <div class="user-location">
                            📍 {u['guild_name']} → {u['channel_name']}
                        </div>
                    </div>
                </div>
                ''' for u in testing_user_list]) + '''
            </div>
        </div>
        ''' if testing_user_list else ''}
        
        <div class="section">
            <h2 class="section-title">
                <span>📊</span>
                Notification Statistics
            </h2>
            <canvas id="userChart"></canvas>
        </div>
        
        <div class="section">
            <h2 class="section-title">
                <span>👥</span>
                Registered Users ({total_users})
            </h2>
            <div class="user-list">
                {"".join([f'''
                <div class="user-item">
                    <div class="user-info">
                        <div class="user-name">
                            {u['status_emoji']} {u.get('display_name', f'User #{u["user_id"]}')} 
                            <span style="opacity: 0.6; font-size: 0.85em;">(ID: {u["user_id"]})</span>
                        </div>
                        {f'<div class="user-activity">{u["activity"]}</div>' if u.get('activity') else ''}
                        <div class="user-meta">
                            📍 Server: <strong>{u['guild_name']}</strong> | 
                            💬 Channel: <strong>{u['channel_name']}</strong><br>
                            🆔 Guild ID: {u["guild_id"] or "Not set"} | 
                            🆔 Channel ID: {u["channel_id"] or "Not set"}<br>
                            📅 Added: {u["added_at"].strftime('%Y-%m-%d %H:%M UTC') if u.get("added_at") else "Unknown"}
                        </div>
                    </div>
                    <div class="user-status {"status-active" if u["is_active"] else "status-inactive"}">
                        {"✅ ACTIVE" if u["is_active"] else "❌ INACTIVE"}
                    </div>
                </div>
                ''' for u in users])}
            </div>
        </div>
        
        <div class="section">
            <h2 class="section-title">
                <span>🌐</span>
                Connected Servers ({len(guild_info)})
            </h2>
            <div class="guilds-grid">
                {"".join([f'''
                <div class="guild-card">
                    <img src="{g['icon']}" alt="{g['name']}" class="guild-icon">
                    <div class="guild-name">{g['name']}</div>
                    <div class="guild-members">👥 {g['member_count']} members</div>
                    <div class="user-meta">ID: {g['id']}</div>
                </div>
                ''' for g in guild_info])}
            </div>
        </div>
        
        <div class="section">
            <h2 class="section-title">
                <span>📟</span>
                Console Logs (Last 100)
            </h2>
            <div class="console-log" id="consoleLog">
                {"".join([f'''
                <div class="log-entry log-{log['level'].lower()}">
                    <span class="log-time">[{log['timestamp']}]</span>
                    <span class="log-level">[{log['level']}]</span>
                    <span class="log-message">{log['message']}</span>
                </div>
                ''' for log in reversed(list(console_logs))])}
            </div>
        </div>
    </div>
    
    <script>
        // Create bubbles
        const ocean = document.getElementById('ocean');
        for (let i = 0; i < 30; i++) {{
            const bubble = document.createElement('div');
            bubble.className = 'bubble';
            bubble.style.left = Math.random() * 100 + '%';
            bubble.style.width = (Math.random() * 20 + 10) + 'px';
            bubble.style.height = bubble.style.width;
            bubble.style.animationDuration = (Math.random() * 8 + 6) + 's';
            bubble.style.animationDelay = Math.random() * 5 + 's';
            ocean.appendChild(bubble);
        }}
        

        // User notification chart - IMPROVED VERSION
        const ctx = document.getElementById('userChart').getContext('2d');
        const userLabels = {user_labels};
        const userData = {user_chart_data};
        
        ctx.canvas.height = 400;
        
        const padding = 60;
        const graphWidth = ctx.canvas.width - padding * 2;
        const graphHeight = ctx.canvas.height - padding * 2;
        const barSpacing = 15;
        const barWidth = Math.min(60, (graphWidth - (userLabels.length - 1) * barSpacing) / userLabels.length);
        const maxBarHeight = graphHeight - 80; // Leave room for rotated labels
        
        // Clear canvas
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        
        // Draw title
        ctx.fillStyle = '#00d4ff';
        ctx.font = 'bold 16px Space Mono';
        ctx.textAlign = 'center';
        ctx.fillText('User Status Overview', ctx.canvas.width / 2, 30);
        
        // Draw bars
        userLabels.forEach((label, index) => {{
            const x = padding + index * (barWidth + barSpacing);
            const isActive = userData[index] === 1;
            const height = isActive ? maxBarHeight * 0.75 : maxBarHeight * 0.25;
            const y = padding + maxBarHeight - height;
            
            // Draw bar with gradient
            const gradient = ctx.createLinearGradient(x, y, x, y + height);
            if (isActive) {{
                gradient.addColorStop(0, '#00ff88');
                gradient.addColorStop(1, '#00cc66');
            }} else {{
                gradient.addColorStop(0, '#ff4444');
                gradient.addColorStop(1, '#cc0000');
            }}
            
            ctx.fillStyle = gradient;
            ctx.fillRect(x, y, barWidth, height);
            
            // Draw bar border
            ctx.strokeStyle = isActive ? '#00ff88' : '#ff4444';
            ctx.lineWidth = 2;
            ctx.strokeRect(x, y, barWidth, height);
            
            // Draw status icon on bar
            ctx.fillStyle = '#fff';
            ctx.font = '20px Arial';
            ctx.textAlign = 'center';
            ctx.fillText(isActive ? '✓' : '✗', x + barWidth / 2, y + height / 2 + 7);
            
            // Draw rotated label
            ctx.save();
            ctx.translate(x + barWidth / 2, padding + maxBarHeight + 10);
            ctx.rotate(-Math.PI / 4);
            ctx.fillStyle = '#00d4ff';
            ctx.font = '12px Space Mono';
            ctx.textAlign = 'right';
            ctx.fillText(label, 0, 0);
            ctx.restore();
        }});
        
        // Draw legend
        const legendY = 50;
        const legendX = ctx.canvas.width - 150;
        
        // Active legend
        ctx.fillStyle = '#00ff88';
        ctx.fillRect(legendX, legendY, 20, 20);
        ctx.strokeStyle = '#00ff88';
        ctx.lineWidth = 2;
        ctx.strokeRect(legendX, legendY, 20, 20);
        ctx.fillStyle = '#00d4ff';
        ctx.font = '14px Space Mono';
        ctx.textAlign = 'left';
        ctx.fillText('Active', legendX + 30, legendY + 15);
        
        // Inactive legend
        ctx.fillStyle = '#ff4444';
        ctx.fillRect(legendX, legendY + 30, 20, 20);
        ctx.strokeStyle = '#ff4444';
        ctx.strokeRect(legendX, legendY + 30, 20, 20);
        ctx.fillStyle = '#00d4ff';
        ctx.fillText('Inactive', legendX + 30, legendY + 45);

        
        // Auto-refresh every 30 seconds
        setTimeout(() => {{
            location.reload();
        }}, 30000);
    </script>
</body>
</html>
    '''
    
    return await create_html_response(html)


async def toggle_maintenance_mode(request):
    """Toggle maintenance mode from Soryn panel"""
    # Check Soryn authentication
    if not check_soryn_auth(request):
        raise web.HTTPFound('/STBS/login')
    
    global update_mode
    update_mode = not update_mode
    
    # Change bot status
    if update_mode:
        await bot.change_presence(status=discord.Status.idle, activity=discord.Game(name="🔧 Updating..."))
        log_to_console("🟡 Maintenance mode ENABLED via Soryn web panel", "WARNING")
    else:
        await bot.change_presence(status=discord.Status.online, activity=discord.Game(name="Bee Swarm Simulator"))
        log_to_console("🟢 Maintenance mode DISABLED via Soryn web panel", "SUCCESS")
    
    # Redirect back to Soryn panel
    raise web.HTTPFound('/STBS')


async def toggle_soryn_sleep_web(request):
    """Toggle Soryn sleep mode from Soryn panel"""
    # Check Soryn authentication
    if not check_soryn_auth(request):
        raise web.HTTPFound('/STBS/login')
    
    global soryn_sleep
    soryn_sleep = not soryn_sleep
    
    if soryn_sleep:
        log_to_console("💤 Soryn sleep mode ENABLED via web panel", "WARNING")
    else:
        log_to_console("☀️ Soryn sleep mode DISABLED via web panel", "SUCCESS")
    
    # Redirect back to Soryn panel
    raise web.HTTPFound('/STBS')


async def start_web_server():
    """Start the web server"""
    app = web.Application()
    app.router.add_get('/', lambda r: web.HTTPFound('/dashboard'))
    app.router.add_get('/login', login_page)
    app.router.add_post('/login', login_submit)
    app.router.add_get('/logout', logout)
    app.router.add_get('/dashboard', health_check)
    app.router.add_get('/health', health_check)
    
    # Soryn backend routes
    app.router.add_get('/STBS', soryn_admin_panel)
    app.router.add_get('/STBS/login', soryn_login_page)
    app.router.add_post('/STBS/login', soryn_login_submit)
    app.router.add_get('/STBS/logout', soryn_logout)
    app.router.add_post('/STBS/toggle-maintenance', toggle_maintenance_mode)
    app.router.add_post('/STBS/toggle-soryn-sleep', toggle_soryn_sleep_web)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    print(f"🌐 Web server started on port {PORT}")
    print(f"🔐 Admin login required - use credentials from .env")
    print(f"🦈 Soryn backend available at /STBS")


# ==================== BOT EVENTS ====================

# Notification checker task
@tasks.loop(minutes=1)
async def notification_checker():
    """Check for users who need party reminders - per-guild, per-user tracking"""
    log_to_console("⏰ Notification checker running...", "DEBUG")
    
    now = datetime.now(timezone.utc)
    notifications_sent = 0
    
    # Check each user's party state (guild_id, user_id) tuples
    for (guild_id, user_id), state in list(user_party_states.items()):
        # Check if user is in sleep mode
        if state.get('sleep_until'):
            if now < state['sleep_until']:
                # Still sleeping, skip this user
                continue
            else:
                # Wake up time has passed
                log_to_console(f"☀️ Sleep time ended for user {user_id} in guild {guild_id}", "SUCCESS")
                state['sleep_until'] = None
        
        # Check if it's time to send reminder for this user
        next_party_time = state.get('next_party_time')
        
        if next_party_time and now >= next_party_time:
            # Time to send notification to this user!
            try:
                # Get user's channel from database
                async with db_pool.acquire() as conn:
                    result = await conn.fetchrow(
                        'SELECT channel_id FROM robo_party_users WHERE user_id = $1 AND guild_id = $2 AND is_active = TRUE',
                        user_id, guild_id
                    )
                
                if result:
                    channel_id = result['channel_id']
                    channel = bot.get_channel(channel_id)
                    
                    if channel:
                        OWNER_ID = 447812883158532106
                        
                        # Check if this is a test notification (owner with time < 10 minutes)
                        time_until = next_party_time - now
                        is_test = (user_id == OWNER_ID and time_until.total_seconds() < 600)
                        
                        if is_test:
                            # Test notification for owner
                            await channel.send(f"⚠️ <@{user_id}> Your Test notification is here")
                        else:
                            # Regular party notification with more lively messages
                            messages = [
                                f"🎉 <@{user_id}> Party time! Your Robo Party is ready to roll!",
                                f"🤖 <@{user_id}> Beep boop! Time to party - your Robo Party awaits!",
                                f"⚡ <@{user_id}> Get ready! Your Robo Party is starting now!",
                                f"🎊 <@{user_id}> Hey! Your Robo Party is ready - let's go!",
                                f"✨ <@{user_id}> Robo Party time! Get in there and have fun!"
                            ]
                            import random
                            message = random.choice(messages)
                            await channel.send(message)
                        
                        log_to_console(f"✅ Sent party notification to user {user_id} in guild {guild_id}", "SUCCESS")
                        notifications_sent += 1
                        
                        # Schedule next party for this user (3 hours later)
                        state['next_party_time'] = now + timedelta(seconds=ROBO_PARTY_INTERVAL)
                        log_to_console(
                            f"⏰ Next party for user {user_id} (guild {guild_id}): {state['next_party_time'].strftime('%Y-%m-%d %H:%M:%S UTC')}",
                            "INFO"
                        )
                    else:
                        log_to_console(f"❌ Channel {channel_id} not found for user {user_id}", "ERROR")
                else:
                    log_to_console(f"⚠️ User {user_id} not found in guild {guild_id} or inactive", "WARNING")
            except Exception as e:
                log_to_console(f"❌ Error sending notification to user {user_id} in guild {guild_id}: {e}", "ERROR")
    
    if notifications_sent > 0:
        log_to_console(f"📬 Sent {notifications_sent} party notification(s) this cycle", "INFO")


@notification_checker.before_loop
async def before_notification_checker():
    """Wait for bot to be ready before starting notification checker"""
    log_to_console("⏰ Notification checker waiting for bot to be ready...", "INFO")
    await bot.wait_until_ready()
    log_to_console("✅ Notification checker ready to start", "SUCCESS")


@bot.event
async def on_ready():
    """Bot startup event"""
    global bot_start_time
    bot_start_time = datetime.now(timezone.utc)
    
    log_to_console(f"🤖 Bot logged in as {bot.user} (ID: {bot.user.id})", "SUCCESS")
    log_to_console(f"📊 Connected to {len(bot.guilds)} servers", "INFO")
    print(f'🤖 Logged in as {bot.user} (ID: {bot.user.id})')
    print(f'📊 Connected to {len(bot.guilds)} servers')
    
    await init_db()
    
    try:
        synced = await bot.tree.sync()
        log_to_console(f"✅ Synced {len(synced)} slash commands", "SUCCESS")
        print(f'✅ Synced {len(synced)} slash commands')
    except Exception as e:
        log_to_console(f"❌ Failed to sync commands: {e}", "ERROR")
        print(f'❌ Failed to sync commands: {e}')
    
    await start_web_server()
    bot.loop.create_task(track_latency())
    
    # Start notification checker
    if not notification_checker.is_running():
        log_to_console("⏰ Starting notification checker task...", "INFO")
        notification_checker.start()
        log_to_console("✅ Notification checker task started", "SUCCESS")
    
    # Set bot presence to "Playing Bee Swarm Simulator"
    await bot.change_presence(
        status=discord.Status.online,
        activity=discord.Game(name="Bee Swarm Simulator")
    )
    log_to_console("🎮 Bot status set to 'Playing Bee Swarm Simulator'", "SUCCESS")
    
    log_to_console("✨ Bot is ready and operational!", "SUCCESS")
    print('✨ Bot is ready!')


async def track_latency():
    """Track latency over time"""
    while True:
        await asyncio.sleep(120)  # Update every 2 minutes
        latency_ms = round(bot.latency * 1000, 2)
        latency_history.append(latency_ms)


# ==================== ROBO PARTY BOT COMMANDS ====================

ROBO_PARTY_INTERVAL = 3 * 60 * 60  # 3 hours
REMINDER_ADVANCE = 5 * 60  # 5 minutes

# Per-guild, per-user party tracking
user_party_states = {}
# Structure: {(guild_id, user_id): {'next_party_time': datetime, 'sleep_until': datetime}}
# This ensures each user in each server has their own independent tracking


async def get_ping_users():
    """Get all active users with their channels to ping"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT user_id, guild_id, channel_id FROM robo_party_users
            WHERE is_active = TRUE AND channel_id IS NOT NULL
        ''')
        return [(row['user_id'], row['guild_id'], row['channel_id']) for row in rows]


# 13. Fix the start_tracking command to use timezone-aware datetime:
@bot.tree.command(name="start", description="Start tracking your Robo Party in this server")
async def start_tracking(interaction: discord.Interaction):
    """Start party tracking for this user in this guild"""
    user_id = interaction.user.id
    guild_id = interaction.guild_id
    
    if not guild_id:
        await interaction.response.send_message(
            "❌ This command can only be used in a server!",
            ephemeral=True
        )
        return
    
    # Check if user has been added via /adduser first
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(
            'SELECT channel_id, is_active FROM robo_party_users WHERE user_id = $1 AND guild_id = $2',
            user_id, guild_id
        )
    
    if not result:
        await interaction.response.send_message(
            "⚠️ You need to be added to the party tracker first!\n"
            "Ask an admin to run `/adduser @you #channel`",
            ephemeral=True
        )
        return
    
    if not result['is_active']:
        await interaction.response.send_message(
            "⚠️ Your party tracking has been deactivated.\n"
            "Ask an admin to re-add you with `/adduser`",
            ephemeral=True
        )
        return
    
    # Use composite key (guild_id, user_id)
    key = (guild_id, user_id)
    
    # Initialize or update this user's party state in this guild
    if key not in user_party_states:
        user_party_states[key] = {}
    
    next_party = datetime.now(timezone.utc) + timedelta(seconds=ROBO_PARTY_INTERVAL)
    user_party_states[key]['next_party_time'] = next_party
    user_party_states[key]['sleep_until'] = None
    
    log_to_console(f"▶️ Party tracking started by {interaction.user.name} (ID: {user_id}) in guild {interaction.guild.name} (ID: {guild_id})", "INFO")
    log_to_console(f"⏰ Next party scheduled for: {next_party.strftime('%Y-%m-%d %H:%M:%S UTC')}", "INFO")
    
    await interaction.response.send_message(
        f"🐝 **Your Robo Party Tracker Started!**\n\n"
        f"Next party: <t:{int(next_party.timestamp())}:R>\n"
        f"You'll be pinged when it's ready!",
        ephemeral=True
    )

# 14. Fix party_done command:
@bot.tree.command(name="done", description="Mark your party as complete in this server")
async def party_done(interaction: discord.Interaction):
    """Mark party complete for this user in this guild"""
    user_id = interaction.user.id
    guild_id = interaction.guild_id
    
    if not guild_id:
        await interaction.response.send_message(
            "❌ This command can only be used in a server!",
            ephemeral=True
        )
        return
    
    key = (guild_id, user_id)
    
    # Check if user has an active party state in this guild
    if key not in user_party_states:
        await interaction.response.send_message(
            "⚠️ You haven't started party tracking in this server yet! Use `/start` first.",
            ephemeral=True
        )
        return
    
    log_to_console(f"✅ Party marked complete by {interaction.user.name} (ID: {user_id}) in guild {interaction.guild.name}", "SUCCESS")
    
    # Schedule next party for this user in this guild
    next_party = datetime.now(timezone.utc) + timedelta(seconds=ROBO_PARTY_INTERVAL)
    user_party_states[key]['next_party_time'] = next_party
    
    log_to_console(f"⏰ Next party for user {user_id} in guild {guild_id}: {next_party.strftime('%Y-%m-%d %H:%M:%S UTC')}", "INFO")
    
    await interaction.response.send_message(
        f"✅ **Party Complete!**\n\nNext party: <t:{int(next_party.timestamp())}:R>",
        ephemeral=True
    )



@bot.tree.command(name="adduser", description="Add user to party reminders in a specific channel (Admin only)")
async def add_user(interaction: discord.Interaction, user: discord.User, channel: discord.TextChannel):
    """Add user to notifications in specified channel"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⚠️ Admin only!", ephemeral=True)
        return
    
    log_to_console(f"📝 Adding user {user.name} ({user.id}) to notifications in #{channel.name} (guild {interaction.guild_id})", "INFO")
    
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO robo_party_users (user_id, username, guild_id, channel_id, is_active)
            VALUES ($1, $2, $3, $4, TRUE)
            ON CONFLICT (user_id, guild_id) 
            DO UPDATE SET username = $2, channel_id = $4, is_active = TRUE
        ''', user.id, str(user), interaction.guild_id, channel.id)
    
    log_to_console(f"✅ User {user.name} added to guild {interaction.guild.name} - will be notified in #{channel.name}", "SUCCESS")
    
    await interaction.response.send_message(
        f"✅ {user.mention} added to party tracker in {channel.mention}!\n"
        f"They need to run `/start` to begin tracking.",
        ephemeral=True
    )

# 9. ADD THE /sleep COMMAND - Add this after the party_done command:

@bot.tree.command(name="sleep", description="Pause your party notifications in this server until a specified time")
@app_commands.describe(
    hours="Number of hours to sleep (optional)",
    minutes="Number of minutes to sleep (optional)",
    until="Wake up time in HH:MM format UTC (optional)"
)
async def sleep_command(
    interaction: discord.Interaction, 
    hours: int = 0, 
    minutes: int = 0,
    until: str = None
):
    """Put party tracker to sleep for this user in this guild"""
    user_id = interaction.user.id
    guild_id = interaction.guild_id
    
    if not guild_id:
        await interaction.response.send_message(
            "❌ This command can only be used in a server!",
            ephemeral=True
        )
        return
    
    key = (guild_id, user_id)
    
    # Check if user has started tracking in this guild
    if key not in user_party_states:
        await interaction.response.send_message(
            "⚠️ You haven't started party tracking in this server yet! Use `/start` first.",
            ephemeral=True
        )
        return
    
    try:
        if until:
            # Parse HH:MM format
            time_parts = until.split(':')
            if len(time_parts) != 2:
                await interaction.response.send_message(
                    "❌ Invalid time format! Use HH:MM (e.g., 14:30)",
                    ephemeral=True
                )
                return
            
            target_hour = int(time_parts[0])
            target_minute = int(time_parts[1])
            
            if not (0 <= target_hour <= 23 and 0 <= target_minute <= 59):
                await interaction.response.send_message(
                    "❌ Invalid time! Hours must be 0-23, minutes 0-59",
                    ephemeral=True
                )
                return
            
            now = datetime.now(timezone.utc)
            wake_time = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
            
            # If time has passed today, set for tomorrow
            if wake_time <= now:
                wake_time += timedelta(days=1)
            
            user_party_states[key]['sleep_until'] = wake_time
            time_until_wake = wake_time - now
            hours_until = int(time_until_wake.total_seconds() // 3600)
            minutes_until = int((time_until_wake.total_seconds() % 3600) // 60)
            
            log_to_console(
                f"💤 Sleep mode activated by {interaction.user.name} (ID: {user_id}) in guild {guild_id} until {wake_time.strftime('%H:%M UTC')} "
                f"({hours_until}h {minutes_until}m)",
                "INFO"
            )
            
            await interaction.response.send_message(
                f"💤 **Your Party Tracker Sleeping**\n\n"
                f"Notifications paused until **{wake_time.strftime('%H:%M UTC')}**\n"
                f"({hours_until}h {minutes_until}m from now)\n\n"
                f"Sleep well! 🌙",
                ephemeral=True
            )
        
        elif hours > 0 or minutes > 0:
            # Calculate sleep duration
            sleep_duration = timedelta(hours=hours, minutes=minutes)
            wake_time = datetime.now(timezone.utc) + sleep_duration
            user_party_states[key]['sleep_until'] = wake_time
            
            log_to_console(
                f"💤 Sleep mode activated by {interaction.user.name} (ID: {user_id}) in guild {guild_id} for {hours}h {minutes}m",
                "INFO"
            )
            
            await interaction.response.send_message(
                f"💤 **Your Party Tracker Sleeping**\n\n"
                f"Notifications paused for **{hours}h {minutes}m**\n"
                f"Wake up at: {wake_time.strftime('%H:%M UTC')}\n\n"
                f"Sleep well! 🌙",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                "❌ Please specify either:\n"
                "• Duration: `/sleep hours:2 minutes:30`\n"
                "• Wake time: `/sleep until:14:30`",
                ephemeral=True
            )
    
    except ValueError:
        await interaction.response.send_message(
            "❌ Invalid input! Please check your numbers.",
            ephemeral=True
        )


@bot.command(name='test')
async def test_notification(ctx):
    """Test command for owner to verify notifications work - prefix command"""
    OWNER_ID = 447812883158532106
    
    if ctx.author.id != OWNER_ID:
        await ctx.send("❌ This command is owner-only!")
        return
    
    user_id = ctx.author.id
    guild_id = ctx.guild.id if ctx.guild else None
    
    if not guild_id:
        await ctx.send("❌ This command can only be used in a server!")
        return
    
    # Check if user is in database
    async with db_pool.acquire() as conn:
        result = await conn.fetchrow(
            'SELECT channel_id FROM robo_party_users WHERE user_id = $1 AND guild_id = $2',
            user_id, guild_id
        )
    
    if not result:
        await ctx.send("⚠️ You need to be added via `/adduser` first!")
        return
    
    # Set party time to 5 minutes from now
    key = (guild_id, user_id)
    test_time = datetime.now(timezone.utc) + timedelta(minutes=5)
    
    if key not in user_party_states:
        user_party_states[key] = {}
    
    user_party_states[key]['next_party_time'] = test_time
    user_party_states[key]['sleep_until'] = None
    
    log_to_console(f"🧪 TEST: Party notification scheduled for {ctx.author.name} in 5 minutes", "INFO")
    
    await ctx.send(
        f"🧪 **Test Mode Activated**\n\n"
        f"You will be pinged in **5 minutes** at <t:{int(test_time.timestamp())}:T>\n"
        f"Watch this channel for your notification!"
    )


@bot.tree.command(name="help", description="View all available commands and how to use the bot")
async def help_command(interaction: discord.Interaction):
    """Show help information for users"""
    embed = discord.Embed(
        title="🐝 Bee Swarm Notifier - Help",
        description="Track your Robo Party cooldowns and get reminded when it's ready!",
        color=discord.Color.gold()
    )
    
    embed.add_field(
        name="📝 Getting Started",
        value=(
            "**1.** Ask an admin to add you: `/adduser @you`\n"
            "**2.** Party will start automatically every 3 hours\n"
            "**3.** You'll be pinged when your party is ready!"
        ),
        inline=False
    )
    
    embed.add_field(
        name="🎮 User Commands",
        value=(
            "`/start` - Start party tracking (if not active)\n"
            "`/done` - Mark your party as complete\n"
            "`/sleep` - Pause notifications temporarily\n"
            "`/help` - Show this help message"
        ),
        inline=False
    )
    
    embed.add_field(
        name="💤 Sleep Mode",
        value=(
            "Pause notifications when you're away:\n"
            "• `/sleep hours:2 minutes:30` - Sleep for duration\n"
            "• `/sleep until:14:30` - Sleep until specific time (UTC)\n"
            "• Bot auto-wakes when sleep time ends"
        ),
        inline=False
    )
    
    embed.add_field(
        name="⏰ Party Cooldown",
        value=(
            "• Parties occur every **3 hours**\n"
            "• Notifications sent to your registered channel\n"
            "• Use `/done` after completing your party"
        ),
        inline=False
    )
    
    embed.add_field(
        name="👑 Admin Commands",
        value=(
            "`/adduser @user` - Add user to party tracker\n"
            "(Admin/Owner only)"
        ),
        inline=False
    )
    
    embed.set_footer(text="🐝 Bee Swarm Notifier | Made by SorynTech")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    log_to_console(f"📖 Help command used by {interaction.user.name}", "INFO")


# 10. UPDATE send_party_reminder to check sleep mode:
# ==================== OWNER COMMANDS ====================

@bot.command(name='updating')
async def toggle_update_mode(ctx):
    """Toggle update mode (Owner only, hidden command)"""
    if ctx.author.id != OWNER_ID:
        return
    
    global update_mode
    update_mode = not update_mode
    
    # Change bot status
    if update_mode:
        await bot.change_presence(status=discord.Status.idle, activity=discord.Game(name="🔧 Updating..."))
        log_to_console("🟡 Maintenance mode ENABLED via Discord command", "WARNING")
        await ctx.send("✅ Update mode **ENABLED** - Status page updated")
    else:
        await bot.change_presence(status=discord.Status.online, activity=discord.Game(name="Bee Swarm Simulator"))
        log_to_console("🟢 Maintenance mode DISABLED via Discord command", "SUCCESS")
        await ctx.send("✅ Update mode **DISABLED** - Back to normal")
    
    # Delete command message for privacy
    try:
        await ctx.message.delete()
    except:
        pass


@bot.command(name='soryn-sleep')
async def toggle_soryn_sleep(ctx):
    """Toggle Soryn sleep mode (Owner only, hidden command)"""
    if ctx.author.id != OWNER_ID:
        return
    
    global soryn_sleep
    soryn_sleep = not soryn_sleep
    
    if soryn_sleep:
        log_to_console("💤 Soryn sleep mode ENABLED - Admin panel will show sleep banner", "WARNING")
        await ctx.send("✅ Soryn sleep mode **ENABLED** 🐀💤\nAdmin panel will show sleep banner.")
    else:
        log_to_console("☀️ Soryn sleep mode DISABLED - Admin panel back to normal", "SUCCESS")
        await ctx.send("✅ Soryn sleep mode **DISABLED** 🐀☀️\nAdmin panel back to normal.")
    
    # Delete command message for privacy
    try:
        await ctx.message.delete()
    except:
        pass


# ==================== MAIN ====================

if __name__ == '__main__':
    if not DISCORD_TOKEN:
        print("❌ Error: DISCORD_TOKEN not found in .env file")
        exit(1)
    
    if not DATABASE_URL:
        print("❌ Error: DATABASE_URL not found in .env file")
        exit(1)
    
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        print("❌ Error: ADMIN_USERNAME and ADMIN_PASSWORD required in .env file")
        print("   Add these to your .env file to enable admin panel access")
        exit(1)
    
    if not SORYN_USERNAME or not SORYN_PASSWORD:
        print("❌ Error: SORYN_USERNAME and SORYN_PASSWORD required in .env file")
        print("   Add these to your .env file to enable Soryn backend access")
        exit(1)
    
    print("🚀 Starting Bee Swarm Notifier...")
    print(f"🔐 Admin authentication enabled for user: {ADMIN_USERNAME}")
    print(f"🦈 Soryn backend authentication enabled for user: {SORYN_USERNAME}")
    bot.run(DISCORD_TOKEN)
