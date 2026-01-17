# SorynTech Bot Suite 🤖

A comprehensive Discord bot suite featuring Robo Party tracking with an advanced cyberpunk-themed admin panel and real-time system monitoring.

## 🌐 Admin Panel Features

The bot includes a futuristic cyberpunk-themed web admin panel that displays real-time system status:

### Normal Status - "SorynTech Bot Suite - Online" 🟢
- Cyberpunk theme with animated particles
- Green/cyan color scheme with neon glow effects
- **Discord Status**: 🟢 Online
- **HTTP Status**: 200 OK
- Displays:
  - **System Uptime** (Time bot has been running)
  - **Bot Latency** (Current ping in milliseconds)
  - **Server Count** (Number of Discord servers)
  - **Server Time** (Current UTC time from bot's server)
  - **📊 Latency Monitor Graph** (Real-time 60-second latency history with animated visualization)
- **Auto-refresh**: Page refreshes every 30 seconds
- **GitHub Button**: Links to your GitHub profile

### Update Mode - "System Update - Maintenance" 🟡
- Orange/amber maintenance theme with rotating gears
- Animated gear icons across the screen
- **Discord Status**: 🟡 Idle (yellow/orange status)
- **HTTP Status**: 503 Service Unavailable
- **Bot remains fully functional** - only status page changes
- Message: "Bot is performing maintenance operations"
- Shows uptime and server time
- **GitHub Button**: Links to your GitHub profile
- **Activation**: Hidden command `!updating` (only works for user ID 447812883158532106)

All admin pages feature:
- Animated background effects (particles, gears)
- Glowing neon text and borders
- Real-time statistics
- Responsive design for mobile and desktop
- Custom animations and visual effects
- **GitHub profile link button** on every page
- Automatic table creation on first run

---

## 🎮 Command Categories

### 🎉 Robo Party Commands
| Command | Description | Required Permission |
|---------|-------------|---------------------|
| `/start` | Start tracking Robo Party (3-hour intervals) | None |
| `/done` | Mark party as complete and schedule next | None |
| `/adduser @user` | Add a user to receive party reminders | Administrator |

### 👑 Owner-Only Commands
| Command | Description | Activation Method |
|---------|-------------|-------------------|
| `!updating` | Toggle update mode on/off | Hidden text command (Owner ID: 447812883158532106) |

---

## ✅ Implemented Features

### Core Bot Features (3)
- [x] `/start` - Start Robo Party tracking with 3-hour intervals
- [x] `/done` - Mark party complete and schedule next one
- [x] `/adduser` - Add users to party notification system (Admin only)

### Owner Controls (1)
- [x] `!updating` - Toggle update mode remotely from any server with the bot

### Admin Panel (8 Features)
- [x] Real-time uptime display
- [x] Live latency monitoring with graph
- [x] Server count statistics
- [x] Server time display (UTC)
- [x] **Latency history graph** (60-second rolling window)
- [x] Update mode with Discord Idle status
- [x] Auto-refresh every 30 seconds
- [x] GitHub profile integration

### Technical Features (5)
- [x] **Automatic database table creation** on first run
- [x] Supabase PostgreSQL integration with connection pooling
- [x] Environment variable configuration (.env)
- [x] Embedded web server (aiohttp) in main.py
- [x] Discord status changes (Online/Idle based on mode)

---

## 🚧 Planned Features

### Robo Party Enhancements
- [ ] `/sleep <hours> <minutes>` - Pause tracking temporarily
- [ ] `/status` - Check current party status
- [ ] `/listusers` - List all users receiving reminders
- [ ] `/removeuser @user` - Remove user from reminders

### Admin Panel Enhancements
- [ ] User management interface
- [ ] Party history timeline
- [ ] Advanced statistics and charts
- [ ] System health monitoring
- [ ] Database query interface

### Additional Owner Commands
- [ ] Emergency shutdown mode
- [ ] Restart command
- [ ] Sleep mode toggle
- [ ] Advanced diagnostics

---

## 🎨 Key Features

### Admin Panel Aesthetics
- **Endpoint**: `http://your-bot-url/` or `http://your-bot-url/health`
- **Theme**: Cyberpunk/futuristic with neon green and orange accents
- **Real-time Updates**: Auto-refreshes every 30 seconds
- **Multiple States**: Normal (green) and Update (orange/amber)
- **Animated Effects**: Floating particles, rotating gears, glowing elements
- **GitHub Integration**: Direct link to developer profile
- **HTTP Status Codes**: 
  - Normal: 200 OK
  - Update Mode: 503 Service Unavailable

### Discord Presence Status
The bot automatically changes its Discord status:
- **🟢 Online**: Normal operation (green)
- **🟡 Idle**: Update mode (yellow/orange)

### Robo Party System
- **Interval**: Every 3 hours
- **Reminders**: 5 minutes before party is ready
- **Multi-User**: Support for multiple notification recipients
- **Main User**: Pre-configured (ID: 581677161006497824)
- **Tracking**: Complete party history in database

### Database Features
- **Auto-Creation**: Tables created automatically on first run
- **Connection Pooling**: Efficient Supabase PostgreSQL integration
- **Tables**:
  - `robo_party_users` - User registration and notification settings
  - `party_history` - Complete log of all parties completed
  - `admin_users` - Admin authentication (for future features)

### Latency Monitoring
- **Real-time Graph**: Displays last 60 latency measurements
- **Animated Canvas**: Custom-drawn graph with glow effects
- **Auto-updating**: New measurements every 30 seconds
- **Visual Design**: Cyberpunk-themed with green neon lines

### Security Features
- Owner-only commands (user ID: 447812883158532106)
- Hidden command syntax for sensitive operations
- Administrator permission checks
- Environment variable configuration

---

## 📊 Progress Statistics
- **Completed:** 17 features
- **In Progress:** 0 features
- **Planned:** 13 features
- **Total Roadmap:** 30 features

---

## 🛠️ Technical Details

### Built With
- **discord.py** - Discord API wrapper for bot functionality
- **aiohttp** - Embedded web server for admin panel
- **asyncpg** - PostgreSQL async driver with connection pooling
- **Python 3.9+** - Modern async Python
- **Supabase** - PostgreSQL database hosting

### Requirements
- Python 3.9 or higher
- Discord Bot Token
- Supabase PostgreSQL database
- Bot Permissions:
  - Send Messages
  - Read Message History
  - Manage Messages (optional, for future features)

### Configuration
The bot uses environment variables stored in a `.env` file:
```env
DISCORD_TOKEN=your_bot_token_here
DISCORD_CLIENT_ID=your_client_id_here
DATABASE_URL=postgresql://user:password@db.your-project.supabase.co:6543/postgres?pgbouncer=true
PORT=10000
```

### Database Schema
The bot automatically creates these tables on first run:

```sql
-- User notification settings
CREATE TABLE robo_party_users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    added_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

-- Party completion history
CREATE TABLE party_history (
    id SERIAL PRIMARY KEY,
    completed_at TIMESTAMP DEFAULT NOW(),
    completed_by BIGINT
);

-- Admin authentication (for future features)
CREATE TABLE admin_users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    password_hash TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Admin Panel Access
Once the bot is running, access the admin panel at:
- `http://localhost:10000/` (local development)
- `http://your-deployment-url/` (production - e.g., Render)

---

## 🚀 Setup Instructions

### Prerequisites
- Python 3.9+
- PostgreSQL database (Supabase recommended)
- Discord Bot Token

### 1. Clone the Repository
```bash
git clone <your-repo-url>
cd soryntech-bot-suite
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Set Up Supabase Database

1. Create a Supabase project at https://supabase.com
2. Get your connection string from Settings → Database
3. Use the **connection pooling** URL (port 6543) for better performance
4. **Tables will be created automatically** on first run!

### 4. Create Discord Bot

1. Go to https://discord.com/developers/applications
2. Click "New Application"
3. Go to "Bot" section and create a bot
4. Enable these Privileged Gateway Intents:
   - ✅ Server Members Intent
   - ✅ Message Content Intent
5. Copy the bot token and Client ID
6. Go to OAuth2 → URL Generator
7. Select scopes: `bot`, `applications.commands`
8. Select bot permissions: `Send Messages`, `Read Message History`
9. Use the generated URL to invite the bot to your server

### 5. Configure Environment Variables

Create a `.env` file in the root directory:

```bash
cp .env.example .env
```

Edit `.env` and add your credentials:

```env
DISCORD_TOKEN=your_discord_bot_token_here
DISCORD_CLIENT_ID=your_client_id_here
DATABASE_URL=postgresql://user:password@db.your-project.supabase.co:6543/postgres?pgbouncer=true
PORT=10000
```

### 6. Run the Bot

```bash
python main.py
```

The bot will:
1. Connect to Discord
2. Create database tables automatically
3. Start the web server on port 10000
4. Sync slash commands
5. Begin tracking latency

### 7. Access Admin Panel

Open your browser and go to:
- Local: `http://localhost:10000`
- Production: `http://your-deployment-url`

---

## 📝 Usage Examples

### Starting Robo Party Tracking
```
/start
```
Response: "🐝 Robo Party Tracker Started! Next party in approximately 3 hours."

### Completing a Party
```
/done
```
Response: "✅ Party Complete! Next party in 3 hours! 🎉"

### Adding a User (Admin Only)
```
/adduser @friend
```
Response: "✅ @friend added to party reminders!"

### Toggle Update Mode (Owner Only)
In your Discord server with the bot:
```
!updating
```
Response: "✅ Update mode **ENABLED** - Status page updated"

Run again to disable:
```
!updating
```
Response: "✅ Update mode **DISABLED** - Back to normal"

---

## 🎯 Main User Configuration

The bot is pre-configured with the main user:
- **User ID**: `581677161006497824`
- **Auto-added**: This user is automatically added to the database on first run
- **Notifications**: Will receive all Robo Party reminders

---

## 🔧 Deployment

### Deploying to Render

1. Create a new Web Service on Render
2. Connect your GitHub repository
3. Configure:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
4. Add environment variables:
   - `DISCORD_TOKEN`
   - `DISCORD_CLIENT_ID`
   - `DATABASE_URL`
   - `PORT` (Render provides this automatically)
5. Deploy!

### Deploying to Other Platforms

The bot works on any platform that supports:
- Python 3.9+
- Long-running processes
- Environment variables
- HTTP server on a specific port

Compatible with:
- Heroku
- Railway
- DigitalOcean
- AWS EC2
- Google Cloud Run
- Any VPS with Python

---

## 🔄 Recent Updates

### January 18, 2026 (LATEST)
- 🎨 Created cyberpunk-themed admin panel with neon effects
- 📊 Added real-time latency monitoring graph (60-second history)
- 🔧 Implemented `!updating` command for remote update mode toggle
- 🟡 Discord status changes to Idle when in update mode
- ⚙️ Automatic database table creation on first run
- 📈 Auto-refresh admin panel every 30 seconds
- 🎯 Integrated all features into single main.py file
- 🔗 Added GitHub profile button to all status pages
- ✨ Animated particle and gear effects on status pages

---

## 📝 Notes

- **Owner ID** is hardcoded: `447812883158532106`
- **Main User ID** is hardcoded: `581677161006497824`
- All slash commands sync automatically on bot startup
- Database tables created automatically - no manual setup needed
- `!updating` command is hidden (no slash command, no help text)
- Admin panel accessible at root URL (`/` or `/health`)
- Bot status changes automatically based on mode
- **Everything runs from main.py** - no separate files needed
- Latency tracked every 30 seconds for graph display
- Connection pooling enabled for database efficiency

---

## 🤝 Contributing

This is a personal project by SorynTech. If you have suggestions or find bugs, feel free to reach out!

**GitHub**: https://github.com/soryntech

---

## 📄 License

MIT License

Copyright (c) 2026 SorynTech

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

---

**Made with 💚 by SorynTech** 🤖
