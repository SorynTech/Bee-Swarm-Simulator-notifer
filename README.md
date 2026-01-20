# 🐝 Bee Swarm Notifier

**Automatic Robo Party tracking and notifications for Bee Swarm Simulator**

Part of the SorynTech Bot Suite 🦈

---

## Features

### 🎮 For Users
- **Automatic Party Reminders** - Get pinged every 3 hours when your Robo Party is ready
- **Sleep Mode** - Pause notifications when you're away or sleeping
- **Simple Commands** - Easy-to-use slash commands
- **Help System** - `/help` shows all available commands

### 👑 For Admins
- **User Management** - Add users to the party tracker
- **Web Dashboard** - Monitor bot status and statistics
- **Party Control** - Start/stop party tracking system

### 🦈 For Owner (Soryn)
- **Soryn Backend Panel** - Full control at `/STBS`
- **Maintenance Mode** - Pause bot updates with one click
- **Sleep Mode Toggle** - Show availability status to admins
- **Real-time Monitoring** - Track all bot activity

---

## Quick Start

### User Setup
1. Ask an admin to add you: `/adduser @you`
2. Party tracking starts automatically
3. You'll be pinged every 3 hours: "@You Your robo Party is ready"
4. After completing your party, run `/done`

### Admin Setup
1. Add users: `/adduser @user`
2. Start tracking: `/start`
3. Monitor via web dashboard: `/dashboard`

---

## Commands

### User Commands
- `/help` - Show all available commands and usage
- `/done` - Mark your party as complete
- `/sleep` - Pause notifications temporarily
  - `/sleep hours:2 minutes:30` - Sleep for a duration
  - `/sleep until:14:30` - Sleep until specific time (UTC)

### Admin Commands
- `/start` - Start party tracking (if not active)
- `/adduser @user` - Add user to party tracker
- Access dashboard at `/dashboard` (login required)

### Owner Commands
- `!soryn-sleep` - Toggle Soryn sleep mode (Discord)
- Web panel sleep toggle button (Soryn backend)
- Maintenance mode toggle (Soryn backend)

---

## Web Dashboard

### Public Routes
- `/` - Redirects to dashboard
- `/health` - Public health check

### Admin Dashboard (`/dashboard`)
**Login Required**
- Bot statistics and uptime
- User tracking status
- Active users count
- Real-time monitoring

### Soryn Backend (`/STBS`)
**Owner Only**
- Full system control
- Maintenance mode toggle
- Soryn sleep mode toggle
- Advanced statistics
- Active users with profile pictures
- Notification statistics

---

## Technical Details

### Party System
- **Cooldown:** 3 hours between parties
- **Notification:** "@User Your robo Party is ready"
- **Auto-scheduling:** Automatically sets next party time
- **Sleep support:** Pause notifications via `/sleep`

### Notification System
- Checks every 1 minute for pending notifications
- Sends to user's registered channel
- Respects sleep mode settings
- Auto-resumes after sleep ends

### Sleep Modes
**User Sleep Mode:**
- Command: `/sleep`
- Pauses party notifications
- Auto-wakes when time expires
- Per-user setting

**Soryn Sleep Mode:**
- Command: `!soryn-sleep` or web button
- Shows banner on admin panel
- Visual indicator only
- Does not affect notifications

---

## Database

### Tables
- `robo_party_users` - User tracking and channel assignments
- Stores: user_id, guild_id, channel_id, is_active

### Features
- PostgreSQL database
- Connection pooling
- Automatic migrations
- Data persistence

---

## Installation

### Requirements
```
discord.py >= 2.0.0
aiohttp
asyncpg
python-dotenv
```

### Environment Variables
```env
DISCORD_TOKEN=your_bot_token_here
DATABASE_URL=your_postgresql_url_here
PORT=10000
ADMIN_USERNAME=admin
ADMIN_PASSWORD=secure_password
SORYN_USERNAME=soryn
SORYN_PASSWORD=secure_password
SORYN_IP=optional_ip_whitelist
```

### Setup
1. Install dependencies: `pip install -r requirements.txt`
2. Create `.env` file with your credentials
3. Run the bot: `python main.py`
4. Enable intents in Discord Developer Portal:
   - Server Members Intent
   - Presence Intent
   - Message Content Intent

---

## Configuration

### Party Interval
```python
ROBO_PARTY_INTERVAL = 3 * 60 * 60  # 3 hours
```

### Status Check Frequency
```python
await asyncio.sleep(120)  # Every 2 minutes
```

### Notification Check
```python
@tasks.loop(minutes=1)  # Every 1 minute
```

---

## Features Breakdown

### v2.1 Features
✅ Presences intent for user status tracking
✅ Global display names (not server nicknames)
✅ Avatar URLs in Active Users section
✅ Bot status: "Playing Bee Swarm Simulator"
✅ Separated stats: Active Users + Notified Users
✅ Active Users section with profile pictures
✅ Sleep status indicators
✅ Reduced status checks (every 2 minutes)
✅ Soryn sleep mode with web toggle
✅ `/help` command for users
✅ Automatic notification system
✅ Clean notification message

### v2.0 Features (Base)
✅ Channel-based notifications
✅ Soryn backend panel with shark theme
✅ Database migration support
✅ Dual authentication system
✅ Maintenance mode
✅ `/sleep` command for notifications
✅ Full rebranding to "Bee Swarm Notifier"

---

## Web Interface

### Login Page
- Shark-themed background with swimming rats
- Secure authentication
- Session management

### Admin Dashboard
- Clean, modern UI
- Real-time statistics
- User status monitoring
- Soryn sleep banner (when active)

### Soryn Backend
- Rat favicon and theme
- Advanced controls
- Maintenance toggle
- Sleep mode toggle
- Active users with avatars
- Rarity distribution (from previous features)

---

## Security

### Authentication
- HTTP Basic Auth for admin dashboard
- Separate Soryn credentials for backend
- Session-based login system
- IP whitelist option for Soryn backend

### Password Protection
- SHA-256 password hashing
- Environment variable storage
- No hardcoded credentials

---

## Logging

### Console Output
All actions are logged with timestamps and levels:
- `SUCCESS` - Green: Successful operations
- `INFO` - Blue: General information
- `WARNING` - Yellow: Important notices
- `ERROR` - Red: Errors and failures
- `DEBUG` - Gray: Detailed debugging

### Log Examples
```
[2026-01-20 12:00:00 UTC] [INFO] ⏰ Notification checker running...
[2026-01-20 15:00:00 UTC] [INFO] 🔔 Party time reached! Sending notifications...
[2026-01-20 15:00:01 UTC] [SUCCESS] ✅ Sent notification to user 123456
```

---

## Deployment

### Render.com
- Automatic deployment from GitHub
- PostgreSQL database included
- Environment variables in dashboard
- Automatic health checks

### Port Configuration
Default: `10000`
Override: Set `PORT` environment variable

---

## Support

### Common Issues

**Notifications not sending:**
- Check if party tracking is active (`/start`)
- Verify user is added (`/adduser @user`)
- Check sleep mode status
- Review console logs

**Bot offline:**
- Check Discord token is valid
- Verify intents are enabled in Developer Portal
- Check database connection

**Web dashboard not loading:**
- Verify PORT is correct
- Check admin credentials
- Ensure web server started (console logs)

---

## Credits

**Developer:** SorynTech
**Version:** 2.1
**Discord Bot:** Bee Swarm Notifier
**Backend Theme:** Rat (🐀)
**Frontend Theme:** Bee (🐝)

---

## License

Private bot for personal use.

---

## Changelog

### v2.1 (Latest)
- Added automatic notification system (checks every minute)
- Added `/help` command for users
- Updated notification message: "@User Your robo Party is ready"
- Added Soryn sleep mode web toggle button
- Implemented presences intent for user status
- Added global display names support
- Added avatar URLs to Active Users section
- Changed bot status to "Playing Bee Swarm Simulator"
- Split stats cards: Active Users (count) + Notified Users (X/Y)
- Reduced status checks from 30s to 2 minutes
- Confirmed 3-hour party interval

### v2.0
- Initial Bee Swarm Notifier release
- Channel-based notifications
- Soryn backend panel
- Database system
- Web dashboard
- Sleep command
- Party tracking system

---

**Made with 🦈 by SorynTech**
