import discord
from discord import app_commands
import json
import os
import requests
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
    with open("database.json", "r") as f:
        return json.load(f)

def save_db(data):
    with open("database.json", "w") as f:
        json.dump(data, f, indent=4)

def get_user(data, uid):
    uid = str(uid)
    if uid not in data["users"]:
        data["users"][uid] = {"coins": 10000, "wins": 0, "bets": 0}
    return data["users"][uid]

def is_admin(uid):
    return uid == ADMIN_ID

def is_banned(data, uid):
    return str(uid) in data.get("banned_users", [])

def is_betting_open(match):
    if match.get("status") != "upcoming":
        return False
    mt = datetime.fromisoformat(match["time"])
    if mt.tzinfo is None:
        mt = IST.localize(mt)
    return datetime.now(IST) < mt + timedelta(minutes=15)

def has_already_bet(data, mid, uid):
    for b in data["bets"].get(mid, []):
        if b["user"] == uid:
            return True
    return False

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
    if not name:
        return None
    return TEAM_MAP.get(name.strip(), name.strip())

def is_ipl_match(match):
    for field in [match.get("name", ""), match.get("series", ""), match.get("seriesName", "")]:
        f = field.lower()
        if "indian premier league" in f or "ipl" in f:
            return True
    return False

# ===== KEEP ALIVE =====
app = Flask("")

@app.route("/")
def home():
    return "Alive"

def run():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    Thread(target=run).start()

# ===== MATCH SCHEDULE =====
def get_schedule():
    return [
        ("2026-04-01", "LSG", "DC", "19:30"),
        ("2026-04-02", "KKR", "SRH", "19:30"),
        ("2026-04-03", "CSK", "PBKS", "19:30"),
        ("2026-04-04", "DC", "MI", "15:30"),
        ("2026-04-04", "GT", "RR", "19:30"),
        ("2026-04-05", "SRH", "LSG", "15:30"),
        ("2026-04-05", "RCB", "CSK", "19:30"),
        ("2026-04-06", "KKR", "PBKS", "19:30"),
        ("2026-04-07", "RR", "MI", "19:30"),
        ("2026-04-08", "DC", "GT", "19:30"),
        ("2026-04-09", "KKR", "LSG", "19:30"),
        ("2026-04-10", "RR", "RCB", "19:30"),
        ("2026-04-11", "PBKS", "SRH", "15:30"),
        ("2026-04-11", "CSK", "DC", "19:30"),
        ("2026-04-12", "LSG", "GT", "15:30"),
        ("2026-04-12", "MI", "RCB", "19:30"),
        ("2026-04-13", "SRH", "RR", "19:30"),
        ("2026-04-14", "CSK", "KKR", "19:30"),
        ("2026-04-15", "RCB", "LSG", "19:30"),
        ("2026-04-16", "MI", "PBKS", "19:30"),
        ("2026-04-17", "GT", "KKR", "19:30"),
        ("2026-04-18", "RCB", "DC", "15:30"),
        ("2026-04-18", "SRH", "CSK", "19:30"),
        ("2026-04-19", "KKR", "RR", "15:30"),
    ]

# ===== BET UI =====
class ConfirmView(discord.ui.View):
    def __init__(self, mid, team, amt):
        super().__init__(timeout=30)
        self.mid = mid
        self.team = team
        self.amt = amt

    @discord.ui.button(label="Confirm Bet", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, btn: discord.ui.Button):
        data = load_db()

        if is_banned(data, interaction.user.id):
            return await interaction.response.edit_message(content="You are banned.", view=None)

        if not is_betting_open(data["matches"].get(self.mid, {})):
            return await interaction.response.edit_message(content="Betting is closed.", view=None)

        if has_already_bet(data, self.mid, interaction.user.id):
            return await interaction.response.edit_message(content="You already bet on this match.", view=None)

        u = get_user(data, interaction.user.id)
        if self.amt > u["coins"]:
            return await interaction.response.edit_message(
                content=f"Not enough coins. You have **{u['coins']}**.",
                view=None
            )

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
            content=f"Placed **{self.amt}** coins on **{self.team}**.",
            view=None
        )

class BetModal(discord.ui.Modal, title="Place Your Bet"):
    amount = discord.ui.TextInput(
        label="Enter Amount (min 1 coin)",
        placeholder="e.g. 500",
        min_length=1,
        max_length=10
    )

    def __init__(self, mid, team):
        super().__init__()
        self.mid = mid
        self.team = team

    async def on_submit(self, interaction: discord.Interaction):
        data = load_db()

        if is_banned(data, interaction.user.id):
            return await interaction.response.send_message("You are banned.", ephemeral=True)

        if not is_betting_open(data["matches"].get(self.mid, {})):
            return await interaction.response.send_message("Betting is closed.", ephemeral=True)

        if has_already_bet(data, self.mid, interaction.user.id):
            return await interaction.response.send_message("You already bet on this match.", ephemeral=True)

        u = get_user(data, interaction.user.id)

        try:
            amt = int(self.amount.value)
        except ValueError:
            return await interaction.response.send_message("Enter a valid number.", ephemeral=True)

        if amt < 1:
            return await interaction.response.send_message("Minimum bet is 1 coin.", ephemeral=True)

        if amt > u["coins"]:
            return await interaction.response.send_message(
                f"Not enough coins. You have **{u['coins']}**.",
                ephemeral=True
            )

        await interaction.response.send_message(
            f"Confirm **{amt}** coins on **{self.team}**?",
            view=ConfirmView(self.mid, self.team, amt),
            ephemeral=True
        )

class BetView(discord.ui.View):
    def __init__(self, mid, t1, t2):
        super().__init__(timeout=None)
        self.mid = mid
        self.t1 = t1
        self.t2 = t2
        self.children[0].label = f"{t1}"
        self.children[1].label = f"{t2}"

    @discord.ui.button(label="Team 1", style=discord.ButtonStyle.primary)
    async def b1(self, interaction: discord.Interaction, btn: discord.ui.Button):
        data = load_db()
        if not is_betting_open(data["matches"].get(self.mid, {})):
            return await interaction.response.send_message("Betting is closed.", ephemeral=True)
        if has_already_bet(data, self.mid, interaction.user.id):
            return await interaction.response.send_message("You already bet on this match.", ephemeral=True)
        await interaction.response.send_modal(BetModal(self.mid, self.t1))

    @discord.ui.button(label="Team 2", style=discord.ButtonStyle.success)
    async def b2(self, interaction: discord.Interaction, btn: discord.ui.Button):
        data = load_db()
        if not is_betting_open(data["matches"].get(self.mid, {})):
            return await interaction.response.send_message("Betting is closed.", ephemeral=True)
        if has_already_bet(data, self.mid, interaction.user.id):
            return await interaction.response.send_message("You already bet on this match.", ephemeral=True)
        await interaction.response.send_modal(BetModal(self.mid, self.t2))

# ===== AUTO MATCH POST =====
async def scheduler():
    await client.wait_until_ready()
    while True:
        data = load_db()
        ch = client.get_channel(CHANNEL_ID)
        now = datetime.now(IST)
        schedule = get_schedule()

        for idx, (d, t1, t2, tm) in enumerate(schedule):
            mt = IST.localize(datetime.strptime(f"{d} {tm}", "%Y-%m-%d %H:%M"))
            mid = f"M{idx}"

            if mt - timedelta(hours=3) <= now <= mt - timedelta(hours=2, minutes=55):
                if mid not in data["matches"]:
                    day_matches = [x for x in schedule if x[0] == d]
                    match_num = next(i + 1 for i, x in enumerate(day_matches) if x[1] == t1 and x[2] == t2)
                    total_day = len(day_matches)
                    deadline = mt + timedelta(minutes=15)

                    embed = discord.Embed(
                        title=f"IPL 2026 - Match #{idx + 1}",
                        description=f"**{t1} vs {t2}**",
                        color=discord.Color.orange()
                    )
                    embed.add_field(
                        name="Date",
                        value=datetime.strptime(d, "%Y-%m-%d").strftime("%B %d, %Y"),
                        inline=True
                    )
                    embed.add_field(name="Starts", value=mt.strftime("%I:%M %p IST"), inline=True)
                    embed.add_field(name="Bet", value="Min 1 coin - max all your coins", inline=True)
                    if total_day == 2:
                        embed.add_field(name="Today", value=f"Match {match_num} of 2", inline=True)
                    embed.add_field(name="Payout", value="Win = **2x** your bet", inline=True)
                    embed.set_footer(
                        text=f"Betting closes {deadline.strftime('%I:%M %p IST')} | 1 bet per user"
                    )

                    await ch.send(embed=embed, view=BetView(mid, t1, t2))
                    data["matches"][mid] = {
                        "team1": t1,
                        "team2": t2,
                        "time": mt.isoformat(),
                        "status": "upcoming",
                        "winner": None
                    }
                    save_db(data)
                    print(f"[SCHEDULER] Posted: {t1} vs {t2}")

        await discord.utils.sleep_until(now + timedelta(minutes=5))

# ===== RESULT SYSTEM =====
def fetch_ipl_matches():
    try:
        r = requests.get(
            f"https://api.cricapi.com/v1/matches?apikey={CRICKET_API_KEY}",
            timeout=10
        ).json()

        if r.get("status") != "success":
            print(f"[API] Bad response - status: {r.get('status')}")
            return []

        all_matches = r.get("data", [])
        ipl_only = [m for m in all_matches if is_ipl_match(m)]
        print(f"[API] {len(all_matches)} total matches fetched - {len(ipl_only)} IPL")
        return ipl_only

    except Exception as e:
        print(f"[API ERROR] {e}")
        return []

def find_winner(ipl_data, t1, t2):
    for m in ipl_data:
        api_teams = [normalize_team(t) for t in m.get("teams", [])]
        if t1 in api_teams and t2 in api_teams:
            raw = m.get("winner", "")
            print(f"[RESULT] Match: {m.get('name')} | Winner: '{raw}'")
            if raw and raw.strip():
                return normalize_team(raw)
            return None
    print(f"[RESULT] {t1} vs {t2} not in IPL data yet")
    return None

def format_match_line(mid, match):
    mt = datetime.fromisoformat(match["time"])
    if mt.tzinfo is None:
        mt = IST.localize(mt)
    return f"{mid} - {match['team1']} vs {match['team2']} ({mt.strftime('%b %d, %I:%M %p IST')})"

async def process_results(force=False, match_id=None):
    data = load_db()
    ch = client.get_channel(CHANNEL_ID)
    now = datetime.now(IST)

    pending = []
    skipped = []

    for mid, m in data["matches"].items():
        if match_id and mid != match_id:
            continue
        if m["status"] != "upcoming":
            continue

        mt = datetime.fromisoformat(m["time"])
        if mt.tzinfo is None:
            mt = IST.localize(mt)

        if now > mt + timedelta(hours=7):
            print(f"[RESULT] 7 hours passed, no result for {m['team1']} vs {m['team2']}")
            m["status"] = "done"
            m["winner"] = None
            save_db(data)
            skipped.append((mid, "No result after 7 hours"))
            continue

        if force or (mt + timedelta(hours=3, minutes=30) <= now <= mt + timedelta(hours=7)):
            pending.append((mid, m))
        else:
            skipped.append((mid, "Result window has not opened yet"))

    if not pending:
        return {"checked": 0, "posted": 0, "posted_matches": [], "skipped": skipped}

    print(f"[RESULT] {len(pending)} match(es) to check - making 1 API call")
    ipl_data = fetch_ipl_matches()
    posted_matches = []

    for mid, m in pending:
        winner = find_winner(ipl_data, m["team1"], m["team2"])

        if not winner:
            print(f"[RESULT] No winner yet for {m['team1']} vs {m['team2']}")
            continue

        winners = []
        for b in data["bets"].get(mid, []):
            u = get_user(data, b["user"])
            if b["team"] == winner:
                coins = b["amount"] * 2
                u["coins"] += coins
                u["wins"] += 1
                winners.append((b["user"], coins))

        winners.sort(key=lambda x: x[1], reverse=True)

        total_bets = len(data["bets"].get(mid, []))
        embed = discord.Embed(
            title="Match Result",
            description=f"**{m['team1']}** vs **{m['team2']}**",
            color=discord.Color.green()
        )
        embed.add_field(name="Winner", value=f"**{winner}**", inline=True)
        embed.add_field(name="Total Bets", value=str(total_bets), inline=True)

        if winners:
            top = ""
            medals = ["🥇", "🥈", "🥉"]
            for idx, (uid, amt) in enumerate(winners[:3]):
                top += f"{medals[idx]} <@{uid}> +**{amt}** coins\n"
            embed.add_field(name="Top Winners", value=top, inline=False)
            embed.set_footer(
                text=f"All {len(winners)} winner(s) paid 2x | {total_bets - len(winners)} lost their bet"
            )
        else:
            embed.add_field(name="No Winners", value="Nobody bet on the winning team.", inline=False)

        if ch:
            await ch.send(embed=embed)

        m["status"] = "done"
        m["winner"] = winner
        save_db(data)
        posted_matches.append((mid, winner, len(winners), total_bets))
        print(f"[RESULT] Winner posted: {winner}")

    return {
        "checked": len(pending),
        "posted": len(posted_matches),
        "posted_matches": posted_matches,
        "skipped": skipped
    }

async def result_loop():
    await client.wait_until_ready()
    while True:
        await process_results()
        await discord.utils.sleep_until(datetime.now(IST) + timedelta(minutes=15))

# ===== USER COMMANDS =====
@tree.command(name="balance", description="Check your current coin balance")
async def balance(interaction: discord.Interaction):
    u = get_user(load_db(), interaction.user.id)
    await interaction.response.send_message(f"You have **{u['coins']}** coins.", ephemeral=True)

@tree.command(name="leaderboard", description="View the top 3 richest users")
async def leaderboard(interaction: discord.Interaction):
    data = load_db()
    users = sorted(data["users"].items(), key=lambda x: x[1]["coins"], reverse=True)
    msg = "**Leaderboard**\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for idx, (uid, u) in enumerate(users[:3]):
        msg += f"{medals[idx]} <@{uid}> - **{u['coins']}** coins\n"
    await interaction.response.send_message(msg, ephemeral=True)

@tree.command(name="history", description="View your bet history with win/loss status")
async def history(interaction: discord.Interaction):
    data = load_db()
    msg = "**Your Bet History**\n\n"
    found = False

    for mid, bets in data["bets"].items():
        match = data["matches"].get(mid, {})
        for bet in bets:
            if bet["user"] == interaction.user.id:
                found = True
                t1 = match.get("team1", "?")
                t2 = match.get("team2", "?")
                if match.get("status") == "done":
                    w = match.get("winner")
                    status = "No Result" if w is None else ("Won" if bet["team"] == w else "Lost")
                else:
                    status = "Pending"
                msg += f"**{t1} vs {t2}** | {bet['team']} | {bet['amount']} coins | {status}\n"

    await interaction.response.send_message(msg if found else "You have no bets yet.", ephemeral=True)

@tree.command(name="help", description="Show all available commands")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="IPL Betting Bot - Help", color=discord.Color.blue())
    embed.add_field(
        name="User Commands",
        value=(
            "`/balance` - Check your coin balance\n"
            "`/leaderboard` - Top 3 richest users\n"
            "`/history` - Your bets with win/loss status\n"
            "`/help` - Show this menu"
        ),
        inline=False
    )
    embed.add_field(
        name="Admin Commands",
        value=(
            "`/setbalance @user amount` - Set a user's coins\n"
            "`/addbalance @user amount` - Add coins to a user\n"
            "`/removebalance @user amount` - Remove coins from a user\n"
            "`/resetbalance @user` - Reset user to 10,000 coins\n"
            "`/userinfo @user` - View user stats\n"
            "`/banuser @user` - Ban user from betting\n"
            "`/unbanuser @user` - Unban a user\n"
            "`/stats` - Server-wide stats\n"
            "`/setannouncement message` - Post an announcement\n"
            "`/checkresult [match_id]` - Force a result check\n"
            "`/matchbets [match_id]` - View who bet how much"
        ),
        inline=False
    )
    embed.set_footer(text="Min bet: 1 coin | Max: full balance | Win = 2x | 1 bet per match")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ===== ADMIN COMMANDS =====
@tree.command(name="setbalance", description="Set a user's coin balance to an exact value")
async def setbalance(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("Admin only.", ephemeral=True)
    data = load_db()
    get_user(data, user.id)["coins"] = amount
    save_db(data)
    await interaction.response.send_message(f"Set **{user.name}** to **{amount}** coins.", ephemeral=True)

@tree.command(name="addbalance", description="Add coins to a user's balance")
async def addbalance(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("Admin only.", ephemeral=True)
    data = load_db()
    get_user(data, user.id)["coins"] += amount
    save_db(data)
    await interaction.response.send_message(f"Added **{amount}** coins to **{user.name}**.", ephemeral=True)

@tree.command(name="removebalance", description="Remove coins from a user's balance")
async def removebalance(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("Admin only.", ephemeral=True)
    data = load_db()
    u = get_user(data, user.id)
    u["coins"] = max(0, u["coins"] - amount)
    save_db(data)
    await interaction.response.send_message(f"Removed **{amount}** coins from **{user.name}**.", ephemeral=True)

@tree.command(name="resetbalance", description="Reset a user's balance to 10,000 coins")
async def resetbalance(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("Admin only.", ephemeral=True)
    data = load_db()
    get_user(data, user.id)["coins"] = 10000
    save_db(data)
    await interaction.response.send_message(f"Reset **{user.name}** to **10,000** coins.", ephemeral=True)

@tree.command(name="userinfo", description="View a user's coins, wins and total bets")
async def userinfo(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("Admin only.", ephemeral=True)
    u = get_user(load_db(), user.id)
    embed = discord.Embed(title=f"{user.name}", color=discord.Color.blue())
    embed.add_field(name="Coins", value=u["coins"], inline=True)
    embed.add_field(name="Wins", value=u["wins"], inline=True)
    embed.add_field(name="Total Bets", value=u["bets"], inline=True)
    embed.set_thumbnail(url=user.display_avatar.url)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="banuser", description="Ban a user from placing bets")
async def banuser(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("Admin only.", ephemeral=True)
    data = load_db()
    if str(user.id) not in data["banned_users"]:
        data["banned_users"].append(str(user.id))
        save_db(data)
        await interaction.response.send_message(f"**{user.name}** banned.", ephemeral=True)
    else:
        await interaction.response.send_message(f"**{user.name}** is already banned.", ephemeral=True)

@tree.command(name="unbanuser", description="Unban a user so they can bet again")
async def unbanuser(interaction: discord.Interaction, user: discord.Member):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("Admin only.", ephemeral=True)
    data = load_db()
    if str(user.id) in data["banned_users"]:
        data["banned_users"].remove(str(user.id))
        save_db(data)
        await interaction.response.send_message(f"**{user.name}** unbanned.", ephemeral=True)
    else:
        await interaction.response.send_message(f"**{user.name}** is not banned.", ephemeral=True)

@tree.command(name="stats", description="View server-wide bot statistics")
async def stats(interaction: discord.Interaction):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("Admin only.", ephemeral=True)
    data = load_db()
    embed = discord.Embed(title="Server Stats", color=discord.Color.gold())
    embed.add_field(name="Users", value=len(data["users"]), inline=True)
    embed.add_field(name="Total Bets", value=sum(len(b) for b in data["bets"].values()), inline=True)
    embed.add_field(name="Matches Tracked", value=len(data["matches"]), inline=True)
    embed.add_field(name="Completed", value=sum(1 for m in data["matches"].values() if m["status"] == "done"), inline=True)
    embed.add_field(name="Coins in Circulation", value=sum(u["coins"] for u in data["users"].values()), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="checkresult", description="Force a result check for one match or all pending matches")
async def checkresult(interaction: discord.Interaction, match_id: str = None):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("Admin only.", ephemeral=True)

    data = load_db()
    if match_id and match_id not in data["matches"]:
        available = "\n".join(format_match_line(mid, match) for mid, match in sorted(data["matches"].items()))
        return await interaction.response.send_message(
            f"Match ID not found.\n\nAvailable matches:\n{available or 'No matches found.'}",
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True)
    result = await process_results(force=True, match_id=match_id)

    lines = [
        f"Checked: **{result['checked']}** match(es)",
        f"Results posted: **{result['posted']}**",
    ]

    if result["posted_matches"]:
        posted_lines = [
            f"{mid} - Winner: **{winner}** | Winners paid: **{winner_count}**/{total_bets}"
            for mid, winner, winner_count, total_bets in result["posted_matches"]
        ]
        lines.append("Posted:\n" + "\n".join(posted_lines))

    if result["skipped"]:
        skipped_lines = [f"{mid} - {reason}" for mid, reason in result["skipped"][:10]]
        lines.append("Skipped:\n" + "\n".join(skipped_lines))

    await interaction.followup.send("\n\n".join(lines), ephemeral=True)

@tree.command(name="matchbets", description="Show all bets placed on a match")
async def matchbets(interaction: discord.Interaction, match_id: str = None):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("Admin only.", ephemeral=True)

    data = load_db()

    if not data["matches"]:
        return await interaction.response.send_message("No matches have been posted yet.", ephemeral=True)

    if not match_id:
        available = "\n".join(format_match_line(mid, match) for mid, match in sorted(data["matches"].items()))
        return await interaction.response.send_message(
            f"Send the command again with a match ID.\n\nAvailable matches:\n{available}",
            ephemeral=True
        )

    match = data["matches"].get(match_id)
    if not match:
        available = "\n".join(format_match_line(mid, m) for mid, m in sorted(data["matches"].items()))
        return await interaction.response.send_message(
            f"Match ID not found.\n\nAvailable matches:\n{available}",
            ephemeral=True
        )

    bets = data["bets"].get(match_id, [])
    title = f"{match_id} - {match['team1']} vs {match['team2']}"

    if not bets:
        return await interaction.response.send_message(f"**{title}**\nNo bets placed yet.", ephemeral=True)

    total_amount = sum(b["amount"] for b in bets)
    lines = [
        f"<@{b['user']}> - **{b['team']}** - **{b['amount']}** coins"
        for b in sorted(bets, key=lambda x: x["amount"], reverse=True)
    ]
    message = (
        f"**{title}**\n"
        f"Total bets: **{len(bets)}**\n"
        f"Total amount: **{total_amount}** coins\n\n"
        + "\n".join(lines)
    )
    await interaction.response.send_message(message[:1900], ephemeral=True)

@tree.command(name="setannouncement", description="Post an announcement to the bot channel")
async def announce(interaction: discord.Interaction, message: str):
    if not is_admin(interaction.user.id):
        return await interaction.response.send_message("Admin only.", ephemeral=True)
    embed = discord.Embed(title="Announcement", description=message, color=discord.Color.red())
    await client.get_channel(CHANNEL_ID).send(embed=embed)
    await interaction.response.send_message("Sent.", ephemeral=True)

# ===== READY =====
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")
    print("RUNNING FILE:", __file__)
    print("ALL COMMANDS:", [cmd.name for cmd in tree.get_commands()])

    try:
        GUILD_ID = 1459211477268299938
        guild = discord.Object(id=GUILD_ID)

        tree.copy_global_to(guild=guild)
        synced = await tree.sync(guild=guild)

        print(f"Synced {len(synced)} commands to guild {GUILD_ID}")
        for cmd in synced:
            print(f"  /{cmd.name}")
    except Exception as e:
        print(f"SYNC ERROR: {e}")

    client.loop.create_task(scheduler())
    client.loop.create_task(result_loop())


# ===== RUN =====
keep_alive()
client.run(TOKEN)
