import discord
from discord import app_commands
import json, os, requests
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv
from flask import Flask
from threading import Thread

# ===== ENV =====
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
CRICKET_API_KEY = os.getenv("CRICKET_API_KEY")
CHANNEL_ID = int(os.getenv("CHANNEL_ID"))

IST = pytz.timezone("Asia/Kolkata")

# ===== DISCORD =====
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ===== DATABASE =====
def load_db():
    if not os.path.exists("database.json"):
        with open("database.json", "w") as f:
            json.dump({"users": {}, "bets": {}, "matches": {}, "banned_users": []}, f)
    with open("database.json") as f:
        return json.load(f)

def save_db(data):
    with open("database.json", "w") as f:
        json.dump(data, f, indent=4)

def get_user(data, uid):
    uid = str(uid)
    if uid not in data["users"]:
        data["users"][uid] = {"coins": 10000, "wins": 0, "bets": 0}
    return data["users"][uid]

def is_admin(uid): return uid == ADMIN_ID
def is_banned(data, uid): return str(uid) in data.get("banned_users", [])

# ===== TEAM NAME MAPPING =====
TEAM_MAP = {
    "Royal Challengers Bengaluru": "RCB",
    "Royal Challengers Bangalore": "RCB",
    "Chennai Super Kings": "CSK",
    "Mumbai Indians": "MI",
    "Kolkata Knight Riders": "KKR",
    "Sunrisers Hyderabad": "SRH",
    "Rajasthan Royals": "RR",
    "Delhi Capitals": "DC",
    "Punjab Kings": "PBKS",
    "Lucknow Super Giants": "LSG",
    "Gujarat Titans": "GT",
}

def normalize_team(name):
    if name is None:
        return None
    return TEAM_MAP.get(name.strip(), name.strip())

# ===== KEEP ALIVE =====
app = Flask('')

@app.route('/')
def home():
    return "Alive"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    Thread(target=run).start()

# ===== MATCH SCHEDULE =====
def get_schedule():
    return [
        ("2026-03-30", "RR",   "CSK",  "19:30"),
        ("2026-03-31", "PBKS", "GT",   "19:30"),
        ("2026-04-01", "LSG",  "DC",   "19:30"),
        ("2026-04-02", "KKR",  "SRH",  "19:30"),
        ("2026-04-03", "CSK",  "PBKS", "19:30"),
        ("2026-04-04", "DC",   "MI",   "15:30"),
        ("2026-04-04", "GT",   "RR",   "19:30"),
        ("2026-04-05", "SRH",  "LSG",  "15:30"),
        ("2026-04-05", "RCB",  "CSK",  "19:30"),
        ("2026-04-06", "KKR",  "PBKS", "19:30"),
        ("2026-04-07", "RR",   "MI",   "19:30"),
        ("2026-04-08", "DC",   "GT",   "19:30"),
        ("2026-04-09", "KKR",  "LSG",  "19:30"),
        ("2026-04-10", "RR",   "RCB",  "19:30"),
        ("2026-04-11", "PBKS", "SRH",  "15:30"),
        ("2026-04-11", "CSK",  "DC",   "19:30"),
        ("2026-04-12", "LSG",  "GT",   "15:30"),
        ("2026-04-12", "MI",   "RCB",  "19:30"),
        ("2026-04-13", "SRH",  "RR",   "19:30"),
        ("2026-04-14", "CSK",  "KKR",  "19:30"),
        ("2026-04-15", "RCB",  "LSG",  "19:30"),
        ("2026-04-16", "MI",   "PBKS", "19:30"),
        ("2026-04-17", "GT",   "KKR",  "19:30"),
        ("2026-04-18", "RCB",  "DC",   "15:30"),
        ("2026-04-18", "SRH",  "CSK",  "19:30"),
        ("2026-04-19", "KKR",  "RR",   "15:30"),
    ]

# ===== BET UI =====
class ConfirmView(discord.ui.View):
    def __init__(self, mid, team, amt):
        super().__init__(timeout=30)
        self.mid = mid
        self.team = team
        self.amt = amt

    @discord.ui.button(label="✅ Confirm Bet", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, btn: discord.ui.Button):
        data = load_db()
        if is_banned(data, interaction.user.id):
            return await interaction.response.edit_message(content="🚫 You are banned from betting.", view=None)

        u = get_user(data, interaction.user.id)
        if self.amt > u["coins"]:
            return await interaction.response.edit_message(content="❌ Not enough coins.", view=None)

        u["coins"] -= self.amt
        u["bets"] += 1
        data["bets"].setdefault(self.mid, [])
        data["bets"][self.mid].append({
            "user": interaction.user.id,
            "team": self.team,
            "amount": self.amt
        })
        save_db(data)
        await interaction.response.edit_message(
            content=f"✅ Bet of **{self.amt}** coins on **{self.team}** placed!", view=None
        )


class BetModal(discord.ui.Modal, title="Place Your Bet"):
    amount = discord.ui.TextInput(label="Enter Amount (100 - 5000)", placeholder="e.g. 500")

    def __init__(self, mid, team):
        super().__init__()
        self.mid = mid
        self.team = team

    async def on_submit(self, interaction: discord.Interaction):
        data = load_db()

        if is_banned(data, interaction.user.id):
            return await interaction.response.send_message("🚫 You are banned from betting.", ephemeral=True)

        u = get_user(data, interaction.user.id)

        try:
            amt = int(self.amount.value)
        except ValueError:
            return await interaction.response.send_message("❌ Invalid amount. Enter a number.", ephemeral=True)

        if amt < 100 or amt > 5000:
            return await interaction.response.send_message("❌ Amount must be between 100 and 5000.", ephemeral=True)

        if amt > u["coins"]:
            return await interaction.response.send_message(
                f"❌ Not enough coins. You have **{u['coins']}** coins.", ephemeral=True
            )

        await interaction.response.send_message(
            f"Confirm bet of **{amt}** coins on **{self.team}**?",
            view=ConfirmView(self.mid, self.team, amt),
            ephemeral=True
        )


class BetView(discord.ui.View):
    def __init__(self, mid, t1, t2):
        super().__init__(timeout=None)
        self.mid = mid
        self.t1 = t1
        self.t2 = t2

    @discord.ui.button(label="Team 1", style=discord.ButtonStyle.primary)
    async def b1(self, interaction: discord.Interaction, btn: discord.ui.Button):
        self.b1.label = self.t1
        await interaction.response.send_modal(BetModal(self.mid, self.t1))

    @discord.ui.button(label="Team 2", style=discord.ButtonStyle.success)
    async def b2(self, interaction: discord.Interaction, btn: discord.ui.Button):
        self.b2.label = self.t2
        await interaction.response.send_modal(BetModal(self.mid, self.t2))

# ===== AUTO MATCH POST =====
async def scheduler():
    await client.wait_until_ready()
    while True:
        data = load_db()
        ch = client.get_channel(CHANNEL_ID)
        now = datetime.now(IST)

        for idx, (d, t1, t2, tm) in enumerate(get_schedule()):
            mt = IST.localize(datetime.strptime(f"{d} {tm}", "%Y-%m-%d %H:%M"))
            mid = f"M{idx}"

            if mt - timedelta(hours=3) <= now <= mt - timedelta(hours=2, minutes=55):
                if mid not in data["matches"]:
                    embed = discord.Embed(
                        title="🏏 IPL Match Betting Open!",
                        description=f"**{t1}** vs **{t2}**",
                        color=discord.Color.orange()
                    )
                    embed.add_field(name="⏰ Start Time", value=mt.strftime("%I:%M %p IST"))
                    embed.add_field(name="💰 Bet Range", value="100 – 5000 coins")
                    embed.set_footer(text="Click a button below to place your bet!")

                    view = BetView(mid, t1, t2)
                    view.b1.label = t1
                    view.b2.label = t2

                    await ch.send(embed=embed, view=view)
                    data["matches"][mid] = {
                        "team1": t1, "team2": t2,
                        "time": mt.isoformat(),
                        "status": "upcoming",
                        "winner": None
                    }
                    save_db(data)

        await discord.utils.sleep_until(now + timedelta(minutes=5))

# ===== RESULT SYSTEM =====
def get_winner(t1, t2):
    try:
        r = requests.get(
            f"https://api.cricapi.com/v1/currentMatches?apikey={CRICKET_API_KEY}",
            timeout=10
        ).json()
        for m in r.get("data", []):
            api_teams = [normalize_team(t) for t in m.get("teams", [])]
            if t1 in api_teams and t2 in api_teams:
                raw_winner = m.get("winner")
                if raw_winner:
                    return normalize_team(raw_winner)
    except Exception as e:
        print(f"API error: {e}")
    return None

async def result_loop():
    await client.wait_until_ready()
    while True:
        data = load_db()
        ch = client.get_channel(CHANNEL_ID)
        now = datetime.now(IST)

        for mid, m in data["matches"].items():
            if m["status"] != "upcoming":
                continue
            mt = datetime.fromisoformat(m["time"])

            if now >= mt + timedelta(hours=4):
                winner = get_winner(m["team1"], m["team2"])
                if not winner:
                    continue

                winners = []
                for b in data["bets"].get(mid, []):
                    u = get_user(data, b["user"])
                    if b["team"] == winner:
                        coins = b["amount"] * 2
                        u["coins"] += coins
                        u["wins"] += 1
                        winners.append((b["user"], coins))

                msg = f"🏆 Match result: **{m['team1']} vs {m['team2']}**\n🥇 Winner: **{winner}**\n\n"
                for idx, (uid, amt) in enumerate(winners[:3]):
                    msg += f"{['🥇','🥈','🥉'][idx]} <@{uid}> +{amt} coins\n"

                await ch.send(msg)
                m["status"] = "done"
                m["winner"] = winner
                save_db(data)

        await discord.utils.sleep_until(now + timedelta(minutes=5))

# ===== USER COMMANDS =====
@tree.command(name="balance", description="Check your current coin balance")
async def balance(interaction: discord.Interaction):
    u = get_user(load_db(), interaction.user.id)
    await interaction.response.send_message(f"💰 You have **{u['coins']}** coins.", ephemeral=True)


@tree.command(name="leaderboard", description="View the top 3 richest users")
async def leaderboard(interaction: discord.Interaction):
    data = load_db()
    users = sorted(data["users"].items(), key=lambda x: x[1]["coins"], reverse=True)
    msg = "🏆 **Leaderboard**\n\n"
    for idx, (uid, u) in enumerate(users[:3]):
        msg += f"{['🥇','🥈','🥉'][idx]} <@{uid}> — {u['coins']} coins\n"
    await interaction.response.send_message(msg, ephemeral=True)


@tree.command(name="history", description="View your bet history with win/loss status")
async def history(interaction: discord.Interaction):
    data = load_db()
    msg = "📜 **Your Bet History**\n\n"
    found = False
    for mid, bets in data["bets"].items():
        match = data["matches"].get(mid, {})
        for bet in bets:
            if bet["user"] == interaction.user.id:
                found = True
                t1 = match.get("team1", "?")
                t2 = match.get("team2", "?")
                if match.get("status") == "done":
                    stored_winner = match.get("winner")
                    status = "✅ Won" if stored_winner and bet["team"] == stored_winner else "❌ Lost"
                else:
                    status = "⏳ Pending"
                msg += f"**{t1} vs {t2}** | {bet['team']} | {bet['amount']} coins | {status}\n"
    await interaction.response.send_message(msg if found else "You have no bets yet.", ephemeral=True)


@tree.command(name="help", description="Show all available commands")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 IPL Betting Bot — Help", color=discord.Color.blue())
    embed.add_field(
        name="👤 User Commands",
        value=(
            "`/balance` — Check your coin balance\n"
            "`/leaderboard` — Top 3 richest users\n"
            "`/history` — Your bets with win/loss status\n"
            "`/help` — Show this menu"
        ),
        inline=False
    )
    embed.add_field(
        name="🔧 Admin Commands",
        value=(
            "`/setbalance @user amount` — Set a user's coins\n"
            "`/addbalance @user amount` — Add coins to a user\n"
            "`/removebalance @user amount` — Remove coins from a user\n"
            "`/resetbalance @user` — Reset user to 10,000 coins\n"
            "`/userinfo @user` — View user stats\n"
            "`/banuser @user` — Ban user from betting\n"
            "`/unbanuser @user` — Unban a user\n"
            "`/stats` — Server-wide stats\n"
            "`/setannouncement message` — Post an announcement"
        ),
        inline=False
    )
    embed.set_footer(text="Bet range: 100–5000 coins  |  Starting balance: 10,000 coins")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ===== ADMIN COMMANDS =====
@tree.command(name="setbalance", description="Set a user's coin balance to an exact value")
async def setbalance(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    data = load_db()
    get_user(data, user.id)["coins"] = amount
    save_db(data)
    await interaction.response.send_message(f"✅ Set **{user.name}**'s balance to {amount} coins.", ephemeral=True)


@tree.command(name="addbalance", description="Add coins to a user's balance")
async def addbalance(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    data = load_db()
    get_user(data, user.id)["coins"] += amount
    save_db(data)
    await interaction.response.send_message(f"✅ Added {amount} coins to **{user.name}**.", ephemeral=True)


@tree.command(name="removebalance", description="Remove coins from a user's balance")
async def removebalance(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    data = load_db()
    u = get_user(data, user.id)
    u["coins"] = max(0, u["coins"] - amount)
    save_db(data)
    await interaction.response.send_message(f"✅ Removed {amount} coins from **{user.name}**.", ephemeral=True)


@tree.command(name="resetbalance", description="Reset a user's balance to 10,000 coins")
async def resetbalance(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    data = load_db()
    get_user(data, user.id)["coins"] = 10000
    save_db(data)
    await interaction.response.send_message(f"✅ Reset **{user.name}**'s balance to 10,000 coins.", ephemeral=True)


@tree.command(name="userinfo", description="View a user's coins, wins and total bets")
async def userinfo(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    u = get_user(load_db(), user.id)
    await interaction.response.send_message(
        f"👤 **{user.name}**\n"
        f"💰 Coins: {u['coins']}\n"
        f"🏆 Wins: {u['wins']}\n"
        f"🎯 Total Bets: {u['bets']}",
        ephemeral=True
    )


@tree.command(name="banuser", description="Ban a user from placing bets")
async def banuser(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    data = load_db()
    if str(user.id) not in data["banned_users"]:
        data["banned_users"].append(str(user.id))
        save_db(data)
        await interaction.response.send_message(f"🚫 **{user.name}** has been banned.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ **{user.name}** is already banned.", ephemeral=True)


@tree.command(name="unbanuser", description="Unban a user so they can bet again")
async def unbanuser(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    data = load_db()
    if str(user.id) in data["banned_users"]:
        data["banned_users"].remove(str(user.id))
        save_db(data)
        await interaction.response.send_message(f"✅ **{user.name}** has been unbanned.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ **{user.name}** is not banned.", ephemeral=True)


@tree.command(name="stats", description="View server-wide bot statistics")
async def stats(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    data = load_db()
    total_users = len(data["users"])
    total_bets = sum(len(b) for b in data["bets"].values())
    total_matches = len(data["matches"])
    total_coins = sum(u["coins"] for u in data["users"].values())
    await interaction.response.send_message(
        f"📊 **Server Stats**\n"
        f"👥 Users: {total_users}\n"
        f"🎯 Total Bets: {total_bets}\n"
        f"🏏 Matches Tracked: {total_matches}\n"
        f"💰 Coins in Circulation: {total_coins}",
        ephemeral=True
    )


@tree.command(name="setannouncement", description="Post an announcement to the bot channel")
async def announce(interaction: discord.Interaction, message: str):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("❌ Admin only.", ephemeral=True)
    await client.get_channel(CHANNEL_ID).send(f"📢 {message}")
    await interaction.response.send_message("✅ Announcement sent.", ephemeral=True)

# ===== READY =====
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    print(f"Commands in tree: {len(tree.get_commands())}")
    try:
        # Try global sync instead of guild sync
        synced = await tree.sync()
        print(f"Synced {len(synced)} commands globally")
        for cmd in synced:
            print(f"  ✅ /{cmd.name}")
    except discord.errors.HTTPException as e:
        print(f"HTTP {e.status}: {e.code} - {e.text}")
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}")
    client.loop.create_task(scheduler())
    client.loop.create_task(result_loop())

# ===== RUN =====
keep_alive()
client.run(TOKEN)
