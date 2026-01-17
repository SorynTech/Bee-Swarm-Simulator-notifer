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


# ==================== DATABASE SETUP ====================

async def init_db():
    """Initialize database connection and create tables"""
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10)
    
    async with db_pool.acquire() as conn:
        # Create tables if they don't exist
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS robo_party_users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                added_at TIMESTAMP DEFAULT NOW(),
                is_active BOOLEAN DEFAULT TRUE
            )
        ''')
        
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS party_history (
                id SERIAL PRIMARY KEY,
                completed_at TIMESTAMP DEFAULT NOW(),
                completed_by BIGINT
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
        
        # Add main user if not exists
        await conn.execute('''
            INSERT INTO robo_party_users (user_id, username)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO NOTHING
        ''', 581677161006497824, 'Main User')
    
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
    """Get bee emoji as SVG favicon"""
    return '''data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">🐝</text></svg>'''


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
    <title>SorynTech Bot Suite - Login</title>
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
        <p class="subtitle">SorynTech Bot Suite</p>
        
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
    <title>SorynTech Bot Suite - Status</title>
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
            <h1 class="title">SORYNTECH BOT SUITE</h1>
            <p class="subtitle">Advanced Discord Bot Management System</p>
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
    <title>SorynTech Bot Suite - Updating</title>
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


async def start_web_server():
    """Start the web server"""
    app = web.Application()
    app.router.add_get('/', lambda r: web.HTTPFound('/dashboard'))
    app.router.add_get('/login', login_page)
    app.router.add_post('/login', login_submit)
    app.router.add_get('/logout', logout)
    app.router.add_get('/dashboard', health_check)
    app.router.add_get('/health', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    
    print(f"🌐 Web server started on port {PORT}")
    print(f"🔐 Admin login required - use credentials from .env")


# ==================== BOT EVENTS ====================

@bot.event
async def on_ready():
    """Bot startup event"""
    global bot_start_time
    bot_start_time = datetime.utcnow()
    
    print(f'🤖 Logged in as {bot.user} (ID: {bot.user.id})')
    print(f'📊 Connected to {len(bot.guilds)} servers')
    
    # Initialize database
    await init_db()
    
    # Sync commands
    try:
        synced = await bot.tree.sync()
        print(f'✅ Synced {len(synced)} slash commands')
    except Exception as e:
        print(f'❌ Failed to sync commands: {e}')
    
    # Start web server
    await start_web_server()
    
    # Start latency tracking
    bot.loop.create_task(track_latency())
    
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
    """Get all active users to ping"""
    async with db_pool.acquire() as conn:
        rows = await conn.fetch('''
            SELECT user_id FROM robo_party_users
            WHERE is_active = TRUE
        ''')
        return [row['user_id'] for row in rows]


async def send_party_reminder():
    """Send party reminder to all registered users"""
    user_ids = await get_ping_users()
    
    for guild in bot.guilds:
        for user_id in user_ids:
            member = guild.get_member(user_id)
            if member:
                try:
                    await member.send(
                        f"🤖🎉 **ROBO PARTY ALERT!** 🎉🤖\n\n"
                        f"Your Robo Party is available in approximately 5 minutes!\n"
                        f"Get ready to party! 🐝✨"
                    )
                except discord.Forbidden:
                    pass


@bot.tree.command(name="start", description="Start tracking Robo Party")
async def start_tracking(interaction: discord.Interaction):
    """Start party tracking"""
    party_state['active'] = True
    party_state['next_party_time'] = datetime.utcnow() + timedelta(seconds=ROBO_PARTY_INTERVAL)
    party_state['reminder_sent'] = False
    
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
    
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO party_history (completed_by)
            VALUES ($1)
        ''', interaction.user.id)
    
    party_state['next_party_time'] = datetime.utcnow() + timedelta(seconds=ROBO_PARTY_INTERVAL)
    party_state['reminder_sent'] = False
    
    await interaction.response.send_message(
        f"✅ **Party Complete!**\n\nNext party in 3 hours! 🎉",
        ephemeral=True
    )


@bot.tree.command(name="adduser", description="Add user to party reminders (Admin only)")
async def add_user(interaction: discord.Interaction, user: discord.User):
    """Add user to notifications"""
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⚠️ Admin only!", ephemeral=True)
        return
    
    async with db_pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO robo_party_users (user_id, username)
            VALUES ($1, $2)
            ON CONFLICT (user_id) 
            DO UPDATE SET username = $2, is_active = TRUE
        ''', user.id, str(user))
    
    await interaction.response.send_message(
        f"✅ {user.mention} added to party reminders!",
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
        await ctx.send("✅ Update mode **ENABLED** - Status page updated")
    else:
        await bot.change_presence(status=discord.Status.online, activity=discord.Game(name="SorynTech Bot Suite"))
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
    
    print("🚀 Starting SorynTech Bot Suite...")
    print(f"🔐 Admin authentication enabled for user: {ADMIN_USERNAME}")
    bot.run(DISCORD_TOKEN)
