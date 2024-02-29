import discord
from discord.ext import commands
import os
import aiosqlite
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv('DISCORD_BOT_TOKEN') # Ensure to set this properly in your environment
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix='/', intents=intents)

invites_before = {}

async def db_setup():
    async with aiosqlite.connect('invite_tracker.db') as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS users (
                            user_id INTEGER PRIMARY KEY,
                            invite_code TEXT,
                            score INTEGER DEFAULT 0,
                            invited_code TEXT
                        );''')
        await db.commit()

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')
    await db_setup()
    global invites_before
    for guild in bot.guilds:
        members = await guild.fetch_members(limit=None).flatten()
        async with aiosqlite.connect('invite_tracker.db') as db:
            for member in members:
                await db.execute('''INSERT OR IGNORE INTO users (user_id) VALUES (?)''', (member.id,))
            await db.commit()
        # Populate invites_before for each guild on bot startup
        invites_before[guild.id] = {invite.code: invite.uses for invite in await guild.invites()}

@bot.slash_command(name='createinvite', description='Create or retrieve your personal invite link')
async def create_invite(interaction: discord.Interaction):
    async with aiosqlite.connect('invite_tracker.db') as db:
        cursor = await db.execute('SELECT invite_code FROM users WHERE user_id = ?', (interaction.user.id,))
        invite_code = await cursor.fetchone()
        if invite_code and invite_code[0]:
            await interaction.response.send_message(f'Your invite link: https://discord.gg/{invite_code[0]}', ephemeral=True)
        else:
            # Adjusted to handle the case where the system_channel might be None
            channel = interaction.guild.text_channels[0] if interaction.guild.system_channel is None else interaction.guild.system_channel
            invite = await channel.create_invite(max_age=86400, unique=True)
            await db.execute('UPDATE users SET invite_code = ? WHERE user_id = ?', (invite.code, interaction.user.id))
            await db.commit()
            await interaction.response.send_message(f'Your invite link: {invite.url}', ephemeral=True)

@bot.slash_command(name='invitebalance', description='Display how many points a particular user has based on joins')
@commands.has_permissions(administrator=True)
async def invite_balance(interaction: discord.Interaction, member: discord.Member):
    async with aiosqlite.connect('invite_tracker.db') as db:
        cursor = await db.execute('SELECT score FROM users WHERE user_id = ?', (member.id,))
        score = await cursor.fetchone()
        if score:
            await interaction.response.send_message(f'{member.display_name} has {score[0]} points.', ephemeral=True)
        else:
            await interaction.response.send_message(f'{member.display_name} has 0 points.', ephemeral=True)

@bot.slash_command(name='leaderboard', description='Display only users that have a balance of >0 and list them highest to lowest')
@commands.has_permissions(administrator=True)
async def leaderboard(interaction: discord.Interaction):
    leaderboard_message = "Invite Leaderboard:\n"
    async with aiosqlite.connect('invite_tracker.db') as db:
        cursor = await db.execute('SELECT user_id, score FROM users WHERE score > 0 ORDER BY score DESC')
        leaderboard = await cursor.fetchall()
        for rank, (user_id, score) in enumerate(leaderboard, start=1):
            user = await bot.fetch_user(user_id)
            leaderboard_message += f"{rank}. {user.display_name} - {score} Points\n"
    await interaction.response.send_message(leaderboard_message, ephemeral=True)

@bot.slash_command(name='inviter', description='Displays who invited the person to the server')
@commands.has_permissions(administrator=True)
async def inviter(interaction: discord.Interaction, member: discord.Member):
    async with aiosqlite.connect('invite_tracker.db') as db:
        # Fetch the invite code used by the member
        cursor = await db.execute('SELECT invited_code FROM users WHERE user_id = ?', (member.id,))
        invited_code = await cursor.fetchone()
        
        if invited_code and invited_code[0]:
            # Fetch the user who created the invite
            cursor = await db.execute('SELECT user_id FROM users WHERE invite_code = ?', (invited_code[0],))
            inviter_id = await cursor.fetchone()
            
            if inviter_id:
                inviter_user = await bot.fetch_user(inviter_id[0])
                await interaction.response.send_message(f'{member.display_name} was invited by {inviter_user.display_name}', ephemeral=True)
            else:
                await interaction.response.send_message("Inviter information not found.", ephemeral=True)
        else:
            await interaction.response.send_message("No invite information found for this user.", ephemeral=True)

@bot.event
async def on_member_join(member):
    global invites_before
    guild_id = member.guild.id

    if guild_id not in invites_before:
        invites_before[guild_id] = {invite.code: invite.uses for invite in await member.guild.invites()}
    
    invites_after = await member.guild.invites()
    used_invite = None

    for invite in invites_after:
        before_uses = invites_before[guild_id].get(invite.code, 0)
        if invite.uses > before_uses:
            used_invite = invite
            break

    if used_invite:
        async with aiosqlite.connect('invite_tracker.db') as db:
            # Update the inviter's score
            await db.execute('''UPDATE users SET score = score + 1 
                                WHERE invite_code = ?''', (used_invite.code,))
            # Record the invite code used by the new member
            await db.execute('''UPDATE users SET invited_code = ? 
                                WHERE user_id = ?''', (used_invite.code, member.id))
            await db.commit()

    invites_before[guild_id] = {invite.code: invite.uses for invite in invites_after}

bot.run(TOKEN) # Make sure to set this properly in your environment
