import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from aiohttp import web
import asyncio
import asyncpg
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
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

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix='!', intents=intents)

# Global state
db_pool = None
bot_start_time = datetime.utcnow()
update_mode = False
latency_history = deque(maxlen=60)  # Store last 60 latency measurements
sessions = {}  # Simple session storage
soryn_sessions = {}  # Soryn admin session storage
console_logs = deque(maxlen=100)  # Store last 100 console logs


def log_to_console(message, level="INFO"):
    """Add message to console logs with timestamp"""
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    console_logs.append({
        'timestamp': timestamp,
        'level': level,
        'message': message
    })
    # Also print to actual console
    print(f"[{timestamp}] [{level}] {message}")


def hash_password(password):
    """Hash password with SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()


def check_auth(request):
    """Check if user is authenticated"""
    session_id = request.cookies.get('session_id')
    return session_id in sessions


def create_session():
    """Create a new session"""
    session_id = secrets.token_hex(32)
    sessions[session_id] = {
        'created_at': datetime.utcnow(),
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


def create_soryn_session():
    """Create a new Soryn admin session"""
    session_id = secrets.token_hex(32)
    soryn_sessions[session_id] = {
        'created_at': datetime.utcnow(),
        'authenticated': True
    }
    return session_id


# ==================== DATABASE SETUP ====================

async def init_db():
    """Initialize database connection and create tables"""
    global db_pool
    log_to_console("Initializing database connection...")
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    
    async with db_pool.acquire() as conn:
        # Create tables if they don't exist
        log_to_console("Creating/verifying database tables...")
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS robo_party_users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                guild_id BIGINT,
                channel_id BIGINT,
                added_at TIMESTAMP DEFAULT NOW(),
                is_active BOOLEAN DEFAULT TRUE
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
        
        # Add main user if not exists (will need to be updated with actual guild/channel)
        await conn.execute('''
            INSERT INTO robo_party_users (user_id, username, is_active)
            VALUES ($1, $2, TRUE)
            ON CONFLICT (user_id) DO NOTHING
        ''', 581677161006497824, 'Main User')
    
    log_to_console("✅ Database initialized and tables created", "SUCCESS")
    print("✅ Database initialized and tables created")


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


def get_uptime():
    """Get bot uptime as formatted string"""
    delta = datetime.utcnow() - bot_start_time
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    if days > 0:
        return f"{days}d {hours}h {minutes}m {seconds}s"
    elif hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    else:
        return f"{minutes}m {seconds}s"


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
    current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    
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
    current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    
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
    """Custom 403 page for unauthorized Soryn access - Shark and Bee themed"""
    html = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>403 - Access Forbidden</title>
    <link rel="icon" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMDAgMTAwIj48dGV4dCB5PSIuOWVtIiBmb250LXNpemU9IjkwIj7wn6aIPC90ZXh0Pjwvc3ZnPg==" type="image/svg+xml">
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Orbitron:wght@700;900&display=swap');
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Space Mono', monospace;
            min-height: 100vh;
            display: flex;
            overflow: hidden;
        }
        
        .split {
            flex: 1;
            display: flex;
            align-items: center;
            justify-content: center;
            position: relative;
            overflow: hidden;
        }
        
        .shark-side {
            background: linear-gradient(135deg, #001f3f 0%, #003d7a 100%);
            color: #00d4ff;
        }
        
        .bee-side {
            background: linear-gradient(135deg, #0a0e27 0%, #1a1f3a 100%);
            color: #00ff88;
        }
        
        .icon-float {
            position: absolute;
            font-size: 5rem;
            animation: float 3s ease-in-out infinite;
        }
        
        .shark-icon {
            top: 10%;
            left: 50%;
            transform: translateX(-50%);
        }
        
        .bee-icon {
            top: 10%;
            left: 50%;
            transform: translateX(-50%);
        }
        
        @keyframes float {
            0%, 100% { transform: translateX(-50%) translateY(0); }
            50% { transform: translateX(-50%) translateY(-20px); }
        }
        
        .content {
            text-align: center;
            z-index: 1;
            padding: 2rem;
        }
        
        .error-code {
            font-family: 'Orbitron', sans-serif;
            font-size: 8rem;
            font-weight: 900;
            margin-bottom: 1rem;
            text-shadow: 0 0 30px currentColor;
            animation: pulse 2s ease-in-out infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }
        
        .error-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 2rem;
            font-weight: 700;
            margin-bottom: 1rem;
            text-transform: uppercase;
        }
        
        .error-message {
            font-size: 1.1rem;
            opacity: 0.8;
            margin-bottom: 2rem;
            line-height: 1.6;
        }
        
        .divider {
            width: 4px;
            background: linear-gradient(to bottom, #00d4ff 0%, #00ff88 100%);
            box-shadow: 0 0 20px #00d4ff, 0 0 20px #00ff88;
            position: relative;
        }
        
        .back-button {
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
        }
        
        .back-button:hover {
            background: rgba(255, 255, 255, 0.2);
            box-shadow: 0 0 20px currentColor;
            transform: translateY(-2px);
        }
        
        @media (max-width: 768px) {
            body {
                flex-direction: column;
            }
            
            .divider {
                width: 100%;
                height: 4px;
                background: linear-gradient(to right, #00d4ff 0%, #00ff88 100%);
            }
            
            .error-code {
                font-size: 5rem;
            }
            
            .error-title {
                font-size: 1.5rem;
            }
        }
    </style>
</head>
<body>
    <div class="split shark-side">
        <div class="icon-float shark-icon">🦈</div>
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
    <link rel="icon" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMDAgMTAwIj48dGV4dCB5PSIuOWVtIiBmb250LXNpemU9IjkwIj7wn6aIPC90ZXh0Pjwvc3ZnPg==" type="image/svg+xml">
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
        <div class="shark-icon">🦈</div>
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
        
        <p class="footer-text">🦈 Soryn Tech Backend v1.0</p>
    </div>
    
    <script>
        // Animated sharks
        const ocean = document.getElementById('ocean');
        for (let i = 0; i < 5; i++) {{
            const shark = document.createElement('div');
            shark.className = 'shark';
            shark.textContent = '🦈';
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
    current_time = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    
    # Get user statistics
    async with db_pool.acquire() as conn:
        total_users = await conn.fetchval('SELECT COUNT(*) FROM robo_party_users')
        active_users = await conn.fetchval('SELECT COUNT(*) FROM robo_party_users WHERE is_active = TRUE')
        total_parties = await conn.fetchval('SELECT COUNT(*) FROM party_history')
        
        # Get all users for notification list with enhanced info
        users = await conn.fetch('''
            SELECT user_id, username, guild_id, channel_id, is_active, added_at
            FROM robo_party_users
            ORDER BY added_at DESC
        ''')
    
    # Enhance user data with server and channel names
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
    
    # Get next party time
    next_party = "Not active"
    if party_state['active'] and party_state['next_party_time']:
        time_left = party_state['next_party_time'] - datetime.utcnow()
        hours = int(time_left.total_seconds() // 3600)
        minutes = int((time_left.total_seconds() % 3600) // 60)
        next_party = f"{hours}h {minutes}m"
    
    # Prepare user data for chart
    user_chart_data = json.dumps([1 if u['is_active'] else 0 for u in users])
    user_labels = json.dumps([u['username'][:15] + '...' if len(u.get('username', '')) > 15 else u.get('username', f'User {u["user_id"]}') for u in users])
    
    html = f'''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Soryn Backend - Control Panel</title>
    <link rel="icon" href="data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAxMDAgMTAwIj48dGV4dCB5PSIuOWVtIiBmb250LXNpemU9IjkwIj7wn6aIPC90ZXh0Pjwvc3ZnPg==" type="image/svg+xml">
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
                <div class="shark-icon">🦈</div>
                <div class="nav-title">SORYN BACKEND</div>
            </div>
            <div class="nav-buttons">
                <form method="POST" action="/STBS/toggle-maintenance" style="display: inline;">
                    <button type="submit" class="btn btn-maintenance">
                        {"🟢 DISABLE MAINTENANCE" if update_mode else "🟡 ENABLE MAINTENANCE"}
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
                <div class="stat-icon">👥</div>
                <div class="stat-label">Active Users</div>
                <div class="stat-value">{active_users}/{total_users}</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">⏰</div>
                <div class="stat-label">Next Party</div>
                <div class="stat-value" style="font-size: 1.3rem;">{next_party}</div>
            </div>
            
            <div class="stat-card">
                <div class="stat-icon">🎉</div>
                <div class="stat-label">Total Parties</div>
                <div class="stat-value">{total_parties}</div>
            </div>
        </div>
        
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
                        <div class="user-name">{u.get('username', f'User #{u["user_id"]}')} (ID: {u["user_id"]})</div>
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
        
        // User notification chart
        const ctx = document.getElementById('userChart').getContext('2d');
        const userLabels = {user_labels};
        const userData = {user_chart_data};
        
        ctx.canvas.height = 300;
        
        const barWidth = Math.max(30, ctx.canvas.width / userLabels.length - 10);
        const maxHeight = 250;
        
        // Draw bars
        userLabels.forEach((label, index) => {{
            const x = 40 + index * (barWidth + 10);
            const isActive = userData[index] === 1;
            const height = isActive ? maxHeight * 0.8 : maxHeight * 0.3;
            const y = ctx.canvas.height - 40 - height;
            
            // Draw bar
            ctx.fillStyle = isActive ? '#00ff88' : '#ff4444';
            ctx.fillRect(x, y, barWidth, height);
            
            // Draw label
            ctx.save();
            ctx.translate(x + barWidth/2, ctx.canvas.height - 20);
            ctx.rotate(-Math.PI/4);
            ctx.fillStyle = '#00d4ff';
            ctx.font = '12px Space Mono';
            ctx.textAlign = 'right';
            ctx.fillText(label, 0, 0);
            ctx.restore();
        }});
        
        // Draw legend
        ctx.fillStyle = '#00ff88';
        ctx.fillRect(ctx.canvas.width - 150, 20, 20, 20);
        ctx.fillStyle = '#00d4ff';
        ctx.font = '14px Space Mono';
        ctx.fillText('Active', ctx.canvas.width - 120, 35);
        
        ctx.fillStyle = '#ff4444';
        ctx.fillRect(ctx.canvas.width - 150, 50, 20, 20);
        ctx.fillStyle = '#00d4ff';
        ctx.fillText('Inactive', ctx.canvas.width - 120, 65);
        
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
        await bot.change_presence(status=discord.Status.online, activity=discord.Game(name="Bee Swarm Notifier"))
        log_to_console("🟢 Maintenance mode DISABLED via Soryn web panel", "SUCCESS")
    
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
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    print(f"🌐 Web server started on port {PORT}")
    print(f"🔐 Admin login required - use credentials from .env")
    print(f"🦈 Soryn backend available at /STBS")


# ==================== BOT EVENTS ====================

@bot.event
async def on_ready():
    """Bot startup event"""
    global bot_start_time
    bot_start_time = datetime.utcnow()
    
    log_to_console(f"🤖 Bot logged in as {bot.user} (ID: {bot.user.id})", "SUCCESS")
    log_to_console(f"📊 Connected to {len(bot.guilds)} servers", "INFO")
    print(f'🤖 Logged in as {bot.user} (ID: {bot.user.id})')
    print(f'📊 Connected to {len(bot.guilds)} servers')
    
    # Initialize database
    await init_db()
    
    # Sync commands
    try:
        synced = await bot.tree.sync()
        log_to_console(f"✅ Synced {len(synced)} slash commands", "SUCCESS")
        print(f'✅ Synced {len(synced)} slash commands')
    except Exception as e:
        log_to_console(f"❌ Failed to sync commands: {e}", "ERROR")
        print(f'❌ Failed to sync commands: {e}')
    
    # Start web server
    await start_web_server()
    
    # Start latency tracking
    bot.loop.create_task(track_latency())
    
    log_to_console("✨ Bot is ready and operational!", "SUCCESS")
    print('✨ Bot is ready!')


async def track_latency():
    """Track latency over time"""
    while True:
        await asyncio.sleep(30)  # Update every 30 seconds
        latency_ms = round(bot.latency * 1000, 2)
        latency_history.append(latency_ms)


# ==================== ROBO PARTY BOT COMMANDS ====================

ROBO_PARTY_INTERVAL = 3 * 60 * 60  # 3 hours
REMINDER_ADVANCE = 5 * 60  # 5 minutes

party_state = {
    'active': False,
    'next_party_time': None,
    'sleep_until': None,
    'reminder_sent': False
}


async def get_ping_users():
    """Get all active users with their channels to ping"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT user_id, guild_id, channel_id FROM robo_party_users
            WHERE is_active = TRUE AND channel_id IS NOT NULL
        ''')
        return [(row['user_id'], row['guild_id'], row['channel_id']) for row in rows]


async def send_party_reminder():
    """Send party reminder to channels"""
    user_data = await get_ping_users()
    log_to_console(f"Sending party reminders to {len(user_data)} users...", "INFO")
    
    success_count = 0
    fail_count = 0
    
    for user_id, guild_id, channel_id in user_data:
        try:
            channel = bot.get_channel(channel_id)
            if channel:
                await channel.send(
                    f"<@{user_id}> 🤖🎉 **ROBO PARTY ALERT!** 🎉🤖\n\n"
                    f"Your Robo Party is available in approximately 5 minutes!\n"
                    f"Get ready to party! 🐝✨"
                )
                log_to_console(f"✅ Sent notification to user {user_id} in channel #{channel.name}", "SUCCESS")
                success_count += 1
            else:
                log_to_console(f"❌ Channel {channel_id} not found for user {user_id}", "ERROR")
                fail_count += 1
        except Exception as e:
            log_to_console(f"❌ Failed to send notification to channel {channel_id}: {e}", "ERROR")
            fail_count += 1
    
    log_to_console(f"Party reminders complete: {success_count} sent, {fail_count} failed", "INFO")


@bot.tree.command(name="start", description="Start tracking Robo Party")
async def start_tracking(interaction: discord.Interaction):
    """Start party tracking"""
    party_state['active'] = True
    party_state['next_party_time'] = datetime.utcnow() + timedelta(seconds=ROBO_PARTY_INTERVAL)
    party_state['reminder_sent'] = False
    
    log_to_console(f"▶️ Party tracking started by {interaction.user.name} in {interaction.guild.name}", "INFO")
    log_to_console(f"⏰ Next party scheduled for: {party_state['next_party_time'].strftime('%Y-%m-%d %H:%M:%S UTC')}", "INFO")
    
    await interaction.response.send_message(
        f"🐝 **Robo Party Tracker Started!**\n\n"
        f"Next party in approximately 3 hours.\n"
        f"You'll be pinged 5 minutes before!",
        ephemeral=True
    )


@bot.tree.command(name="done", description="Mark party as complete")
async def party_done(interaction: discord.Interaction):
    """Mark party complete"""
    if not party_state['active']:
        await interaction.response.send_message(
            "⚠️ Party tracking not active! Use `/start` first.",
            ephemeral=True
        )
        return
    
    log_to_console(f"✅ Party marked complete by {interaction.user.name}", "SUCCESS")
    
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO party_history (completed_by, guild_id)
            VALUES ($1, $2)
        ''', interaction.user.id, interaction.guild_id)
    
    party_state['next_party_time'] = datetime.utcnow() + timedelta(seconds=ROBO_PARTY_INTERVAL)
    party_state['reminder_sent'] = False
    
    log_to_console(f"⏰ Next party scheduled for: {party_state['next_party_time'].strftime('%Y-%m-%d %H:%M:%S UTC')}", "INFO")
    
    await interaction.response.send_message(
        f"✅ **Party Complete!**\n\nNext party in 3 hours! 🎉",
        ephemeral=True
    )


@bot.tree.command(name="adduser", description="Add user to party reminders in a specific channel (Admin only)")
async def add_user(interaction: discord.Interaction, user: discord.User, channel: discord.TextChannel):
    """Add user to notifications in specified channel"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⚠️ Admin only!", ephemeral=True)
        return
    
    log_to_console(f"📝 Adding user {user.name} ({user.id}) to notifications in #{channel.name}", "INFO")
    
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO robo_party_users (user_id, username, guild_id, channel_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id) 
            DO UPDATE SET username = $2, guild_id = $3, channel_id = $4, is_active = TRUE
        ''', user.id, str(user), interaction.guild_id, channel.id)
    
    log_to_console(f"✅ User {user.name} added - will be notified in #{channel.name} on server {interaction.guild.name}", "SUCCESS")
    
    await interaction.response.send_message(
        f"✅ {user.mention} will be notified in {channel.mention}!",
        ephemeral=True
    )


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
        await bot.change_presence(status=discord.Status.online, activity=discord.Game(name="Bee Swarm Notifier"))
        log_to_console("🟢 Maintenance mode DISABLED via Discord command", "SUCCESS")
        await ctx.send("✅ Update mode **DISABLED** - Back to normal")
    
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
