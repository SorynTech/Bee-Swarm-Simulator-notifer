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
import secrets
import sys

load_dotenv()

# ==================== CONFIGURATION ====================
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
PORT = int(os.getenv('PORT', 10000))
OWNER_ID = 447812883158532106
ADMIN_USERNAME = os.getenv('ADMIN_USERNAME')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
SORYN_USERNAME = os.getenv('SORYN_USERNAME')
SORYN_PASSWORD = os.getenv('SORYN_PASSWORD')
SORYN_IP = os.getenv('SORYN_IP', '')

# Links
UPTIME_LINK = "https://stats.uptimerobot.com/EfwZKYIE1Q"
BOT_INVITE_LINK = "https://discord.com/oauth2/authorize?client_id=1462102727763951832"
RAT_FAVICON = "https://img.icons8.com/color/48/rat.png"

# ==================== BOT SETUP ====================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True  # Required for status checks
bot = commands.Bot(command_prefix='!', intents=intents)

# Global State
db_pool = None
bot_start_time = datetime.utcnow()
update_mode = False
sessions = {}
soryn_sessions = {}


# ==================== UTILS ====================

def check_auth(request):
    """Checks basic admin session."""
    session_id = request.cookies.get('session_id')
    return session_id in sessions


def check_soryn_auth(request):
    """Checks Soryn backend session."""
    session_id = request.cookies.get('soryn_session_id')
    return session_id in soryn_sessions


def check_soryn_ip(request):
    """Verifies the request comes from Soryn's IP."""
    if not SORYN_IP: return True  # If no IP set in env, allow all (risky but functional)

    # Handle different proxy headers if hosted on cloud (Render/Heroku/etc)
    if 'X-Forwarded-For' in request.headers:
        client_ip = request.headers['X-Forwarded-For'].split(',')[0].strip()
    else:
        client_ip = request.remote

    return client_ip == SORYN_IP


def get_holographic_css():
    """Returns the CSS style block."""
    return """
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700&family=Roboto+Mono:wght@400;700&display=swap');

        :root {
            --holo-cyan: #00f3ff;
            --holo-blue: #0066ff;
            --holo-bg: #050a14;
            --holo-panel: rgba(0, 20, 40, 0.9);
            --scanline: rgba(0, 255, 255, 0.03);
        }

        body {
            background-color: var(--holo-bg);
            color: #e0faff;
            font-family: 'Roboto Mono', monospace;
            margin: 0; padding: 20px;
            background-image: 
                linear-gradient(rgba(0, 20, 40, 0.9), rgba(0, 20, 40, 0.9)),
                repeating-linear-gradient(0deg, transparent, transparent 1px, var(--scanline) 1px, var(--scanline) 2px);
            min-height: 100vh;
        }

        h1, h2, h3 {
            font-family: 'Orbitron', sans-serif;
            text-transform: uppercase;
            color: var(--holo-cyan);
            text-shadow: 0 0 10px var(--holo-cyan);
        }

        .navbar {
            display: flex; justify-content: space-between; align-items: center;
            border-bottom: 2px solid var(--holo-blue); padding-bottom: 15px; margin-bottom: 30px;
        }

        .btn {
            background: rgba(0, 243, 255, 0.1);
            border: 1px solid var(--holo-cyan);
            color: var(--holo-cyan);
            padding: 10px 20px;
            font-family: 'Orbitron', sans-serif;
            cursor: pointer;
            text-decoration: none;
            display: inline-block;
            transition: 0.3s;
            margin-left: 10px;
        }
        .btn:hover { background: var(--holo-cyan); color: #000; box-shadow: 0 0 15px var(--holo-cyan); }

        .btn-danger { border-color: #ff3333; color: #ff3333; }
        .btn-danger:hover { background: #ff3333; color: #fff; box-shadow: 0 0 15px #ff3333; }

        .card {
            background: var(--holo-panel);
            border: 1px solid var(--holo-blue);
            padding: 20px; border-radius: 8px;
            box-shadow: 0 0 20px rgba(0, 102, 255, 0.2);
            margin-bottom: 20px;
        }

        /* Chart Styles */
        .user-row {
            display: flex; align-items: center; gap: 15px;
            padding: 12px;
            background: rgba(255, 255, 255, 0.02);
            border-bottom: 1px solid rgba(0, 243, 255, 0.1);
        }

        .user-info {
            width: 250px; /* Fixed width prevents overlap */
            display: flex; align-items: center; gap: 10px;
            flex-shrink: 0;
        }

        .user-avatar {
            width: 40px; height: 40px; border-radius: 50%;
            border: 2px solid var(--holo-cyan);
        }

        .user-names { display: flex; flex-direction: column; overflow: hidden; }
        .display-name { font-weight: bold; color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px; }
        .username-tag { font-size: 0.8em; color: #88aaff; }

        .bar-track {
            flex-grow: 1;
            background: rgba(0, 0, 0, 0.5);
            height: 28px;
            border-radius: 4px;
            overflow: hidden;
            display: flex;
            align-items: center;
        }

        .bar-fill {
            height: 100%;
            display: flex; align-items: center;
            padding-left: 10px;
            font-size: 0.8em; font-weight: bold;
            white-space: nowrap;
            transition: width 0.5s ease;
        }

        .status-details {
            width: 150px;
            text-align: right;
            font-size: 0.8em; color: #aaa;
            white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
            padding-left: 10px;
        }

        @media (max-width: 700px) {
            .status-details { display: none; }
            .user-info { width: 150px; }
        }
    </style>
    """


# ==================== DISCORD EVENTS ====================

@bot.event
async def on_ready():
    global bot_start_time
    bot_start_time = datetime.utcnow()

    # Initialize DB
    global db_pool
    if DATABASE_URL:
        try:
            db_pool = await asyncpg.create_pool(DATABASE_URL)
            async with db_pool.acquire() as conn:
                await conn.execute('''
                                   CREATE TABLE IF NOT EXISTS users
                                   (
                                       user_id
                                       BIGINT
                                       PRIMARY
                                       KEY,
                                       username
                                       TEXT,
                                       is_asleep
                                       BOOLEAN
                                       DEFAULT
                                       FALSE,
                                       last_active
                                       TIMESTAMP
                                   )
                                   ''')
                # Migration safety
                try:
                    await conn.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS is_asleep BOOLEAN DEFAULT FALSE')
                except:
                    pass
            print("✅ Database Connected")
        except Exception as e:
            print(f"❌ Database Error: {e}")

    # Set Initial Status
    await bot.change_presence(activity=discord.Game(name="Bee Swarm Simulator"))
    print(f'🚀 Logged in as {bot.user}')

    # Start Web Server
    asyncio.create_task(start_web_server())


@bot.tree.command(name="sleep", description="Mark yourself as asleep/inactive")
async def sleep_cmd(interaction: discord.Interaction, asleep: bool = True):
    """Toggles your sleep status in the backend."""
    if not db_pool:
        return await interaction.response.send_message("❌ Database unavailable.", ephemeral=True)

    async with db_pool.acquire() as conn:
        await conn.execute('''
                           INSERT INTO users (user_id, username, is_asleep)
                           VALUES ($1, $2, $3) ON CONFLICT (user_id) DO
                           UPDATE SET is_asleep = $3, username = $2
                           ''', interaction.user.id, interaction.user.name, asleep)

    status = "ASLEEP 💤" if asleep else "AWAKE ☀️"
    await interaction.response.send_message(f"✅ Status updated: **{status}**", ephemeral=True)


@bot.tree.command(name="invite", description="Get the invite link")
async def invite(interaction: discord.Interaction):
    await interaction.response.send_message(f"Here is my invite link: {BOT_INVITE_LINK}", ephemeral=True)


@bot.tree.command(name="stbs", description="Soryn Tech Control Panel")
async def stbs_cmd(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("⛔ Access Denied", ephemeral=True)

    # Provide a direct link or simple status
    embed = discord.Embed(title="Soryn Tech Backend", description="Use the web interface to manage the bot.",
                          color=discord.Color.blue())
    embed.add_field(name="Status", value="Maintenance" if update_mode else "Active")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ==================== WEB ROUTES ====================

async def home_page(request):
    """The public landing page."""
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Soryn Tech</title>
        <link rel="icon" type="image/png" href="{RAT_FAVICON}">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        {get_holographic_css()}
    </head>
    <body>
        <div class="navbar">
            <h1>🐀 Soryn Tech</h1>
            <div>
                <a href="/login" class="btn">Admin</a>
                <a href="{UPTIME_LINK}" target="_blank" class="btn">Uptime</a>
            </div>
        </div>
        <div class="card">
            <h2>System Status</h2>
            <h3 style="color: {'#ff3333' if update_mode else '#00ff00'}">
                {'⚠️ MAINTENANCE MODE' if update_mode else '✅ ONLINE'}
            </h3>
            <p>Activity: {'Watching Soryn Fix Code' if update_mode else 'Playing Bee Swarm Simulator'}</p>
            <p>Ping: {round(bot.latency * 1000)}ms</p>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')


async def soryn_backend(request):
    """The /STBS page (Soryn Backend)."""
    # 1. IP Check
    if not check_soryn_ip(request):
        return web.Response(text="⛔ 403 Forbidden: Unauthorized IP Address", status=403)

    # 2. Session Check
    if not check_soryn_auth(request):
        return web.HTTPFound('/STBS/login')

    # 3. Fetch Data
    users_data = []
    if db_pool:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM users ORDER BY is_asleep ASC, last_active DESC NULLS LAST")
            for row in rows:
                uid = row['user_id']
                is_asleep = row['is_asleep']

                # Get Discord Member Info
                member = None
                for guild in bot.guilds:
                    m = guild.get_member(uid)
                    if m:
                        member = m
                        break

                display_name = member.display_name if member else row['username']
                username = member.name if member else row['username']
                avatar = str(member.display_avatar.url) if member else "https://cdn.discordapp.com/embed/avatars/0.png"

                # Determine Visuals
                discord_status = str(member.status) if member else "offline"

                status_text = "OFFLINE"
                status_color = "#555"
                score = 10

                if is_asleep:
                    status_text = "SLEEPING"
                    status_color = "#9b59b6"  # Purple
                    score = 40
                elif discord_status == "online":
                    status_text = "ONLINE"
                    status_color = "#00ff00"
                    score = 100
                elif discord_status == "idle":
                    status_text = "IDLE"
                    status_color = "#f1c40f"  # Yellow
                    score = 80
                elif discord_status == "dnd":
                    status_text = "DND"
                    status_color = "#e74c3c"  # Red
                    score = 70

                activity_name = ""
                if member and member.activity:
                    if member.activity.type == discord.ActivityType.playing:
                        activity_name = f"Playing {member.activity.name}"
                    elif member.activity.type == discord.ActivityType.custom:
                        activity_name = member.activity.name or "Custom Status"
                    else:
                        activity_name = member.activity.name

                users_data.append({
                    'name': display_name,
                    'user': username,
                    'avatar': avatar,
                    'status': status_text,
                    'color': status_color,
                    'score': score,
                    'activity': activity_name
                })

    # 4. Render Page
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Soryn Backend</title>
        <link rel="icon" type="image/png" href="{RAT_FAVICON}">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        {get_holographic_css()}
    </head>
    <body>
        <div class="navbar">
            <h1>🐀 Soryn Backend</h1>
            <div>
                <form action="/STBS/restart" method="POST" style="display:inline;">
                    <button type="submit" class="btn btn-danger">FORCE RESTART</button>
                </form>

                <form action="/STBS/toggle" method="POST" style="display:inline;">
                    <button type="submit" class="btn">
                        {'DISABLE UPDATE MODE' if update_mode else 'ENABLE UPDATE MODE'}
                    </button>
                </form>

                <a href="{UPTIME_LINK}" target="_blank" class="btn">Uptime</a>
            </div>
        </div>

        <div class="card">
            <h2>Live User Matrix</h2>
            <div style="display: flex; flex-direction: column;">
    """

    for u in users_data:
        html += f"""
        <div class="user-row">
            <div class="user-info">
                <img src="{u['avatar']}" class="user-avatar">
                <div class="user-names">
                    <span class="display-name" title="{u['name']}">{u['name']}</span>
                    <span class="username-tag">@{u['user']}</span>
                </div>
            </div>
            <div class="bar-track">
                <div class="bar-fill" style="width: {u['score']}%; background: {u['color']}; color: {'#fff' if u['status'] in ['DND', 'SLEEPING', 'OFFLINE'] else '#000'}">
                    {u['status']}
                </div>
            </div>
            <div class="status-details">
                {u['activity']}
            </div>
        </div>
        """

    html += """
            </div>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')


async def stbs_toggle(request):
    """Toggle Update Mode via POST."""
    if not check_soryn_auth(request) or not check_soryn_ip(request):
        return web.Response(status=403)

    global update_mode
    update_mode = not update_mode

    if update_mode:
        await bot.change_presence(status=discord.Status.dnd,
                                  activity=discord.Activity(type=discord.ActivityType.watching,
                                                            name="Soryn Fix my code"))
    else:
        await bot.change_presence(status=discord.Status.online, activity=discord.Game(name="Bee Swarm Simulator"))

    return web.HTTPFound('/STBS')


async def stbs_restart(request):
    """Force Restart via POST."""
    if not check_soryn_auth(request) or not check_soryn_ip(request):
        return web.Response(status=403)

    print("🔴 RESTART TRIGGERED BY SORYN")
    await bot.close()
    sys.exit(0)


# ==================== LOGIN ROUTES ====================

async def login_page(request):
    # Standard Admin Login
    return web.Response(text=f"""
        <html><head>{get_holographic_css()}</head><body>
        <div class="container" style="margin-top:100px; max-width:400px; margin-left:auto; margin-right:auto;">
            <div class="card">
                <h2>Admin Access</h2>
                <form action="/login" method="POST">
                    <input type="text" name="u" placeholder="Username" style="width:90%; padding:10px; margin-bottom:10px;">
                    <input type="password" name="p" placeholder="Password" style="width:90%; padding:10px; margin-bottom:10px;">
                    <button class="btn" style="width:100%">LOGIN</button>
                </form>
            </div>
        </div>
        </body></html>
    """, content_type='text/html')


async def login_post(request):
    data = await request.post()
    if data.get('u') == ADMIN_USERNAME and data.get('p') == ADMIN_PASSWORD:
        sid = secrets.token_hex(16)
        sessions[sid] = True
        r = web.HTTPFound('/admin')
        r.set_cookie('session_id', sid)
        return r
    return web.HTTPFound('/login')


async def admin_page(request):
    if not check_auth(request): return web.HTTPFound('/login')
    # Simple Admin Page
    return web.Response(text=f"""
        <html><head>{get_holographic_css()}</head><body>
        <div class="navbar"><h1>Admin Panel</h1><a href="/logout" class="btn">Logout</a></div>
        <div class="card">
            <p>Bot Status: <strong>{'MAINTENANCE' if update_mode else 'ONLINE'}</strong></p>
            <p>Servers: {len(bot.guilds)}</p>
        </div>
        </body></html>
    """, content_type='text/html')


async def stbs_login_page(request):
    # Soryn Backend Login
    return web.Response(text=f"""
        <html><head>{get_holographic_css()}</head><body>
        <div class="container" style="margin-top:100px; max-width:400px; margin-left:auto; margin-right:auto;">
            <div class="card" style="border-color: #ff0000;">
                <h2 style="color: #ff0000;">RESTRICTED ACCESS</h2>
                <form action="/STBS/login" method="POST">
                    <input type="text" name="u" placeholder="Soryn ID" style="width:90%; padding:10px; margin-bottom:10px;">
                    <input type="password" name="p" placeholder="Passcode" style="width:90%; padding:10px; margin-bottom:10px;">
                    <button class="btn btn-danger" style="width:100%">AUTHENTICATE</button>
                </form>
            </div>
        </div>
        </body></html>
    """, content_type='text/html')


async def stbs_login_post(request):
    data = await request.post()
    if data.get('u') == SORYN_USERNAME and data.get('p') == SORYN_PASSWORD:
        sid = secrets.token_hex(16)
        soryn_sessions[sid] = True
        r = web.HTTPFound('/STBS')
        r.set_cookie('soryn_session_id', sid)
        return r
    return web.HTTPFound('/STBS/login')


# ==================== MAIN ====================

async def start_web_server():
    app = web.Application()
    app.add_routes([
        web.get('/', home_page),
        web.get('/login', login_page),
        web.post('/login', login_post),
        web.get('/admin', admin_page),

        # Soryn Routes
        web.get('/STBS', soryn_backend),
        web.get('/STBS/login', stbs_login_page),
        web.post('/STBS/login', stbs_login_post),
        web.post('/STBS/toggle', stbs_toggle),
        web.post('/STBS/restart', stbs_restart),
    ])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', PORT)
    await site.start()
    print(f"🌍 Web running on port {PORT}")


@bot.command()
@commands.is_owner()
async def sync(ctx):
    """Syncs commands manually."""
    await bot.tree.sync()
    await ctx.send("Synced!")


if __name__ == '__main__':
    try:
        bot.run(DISCORD_TOKEN)
    except KeyboardInterrupt:
        pass