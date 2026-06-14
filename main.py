import discord
from discord.ext import commands
import re
from collections import defaultdict
import time
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Configuration personnalisable (vous pouvez modifier ces valeurs)
MESSAGE_LIMIT = 5          # nombre max de messages autorisés
TIME_WINDOW = 1           # dans les X secondes
IGNORED_ROLES = ["Owner"]  # rôles ignorés par la modération
WHITELISTED_DOMAINS = ["youtube.com", "youtu.be", "twitter.com", "x.com", "discord.com/channels", "tenors.com"]  # liens autorisés
LOG_CHANNEL_ID = 1515765003846811670  # remplacez par l'ID de votre salon de logs

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="+", intents=intents)

# Structure pour le stockage du spam : { user_id: [(timestamp, message_content), ...] }
user_messages = defaultdict(list)

# Expression régulière pour détecter les liens discord.gg ou discord.com/invite
DISCORD_INVITE_PATTERN = re.compile(r"(?:https?://)?(?:www\.)?(?:discord\.(?:gg|com/invite)|discordapp\.com/invite)/[a-zA-Z0-9]+")
URL_PATTERN = re.compile(r"(https?://[^\s]+)")

async def log_mod_action(action, user, channel, reason=None):
    """Envoie un message dans le salon de logs"""
    log_channel = bot.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(title="Action de modération", color=discord.Color.orange())
        embed.add_field(name="Action", value=action, inline=False)
        embed.add_field(name="Utilisateur", value=user.mention, inline=True)
        embed.add_field(name="Salon", value=channel.mention, inline=True)
        if reason:
            embed.add_field(name="Raison", value=reason, inline=False)
        embed.timestamp = discord.utils.utcnow()
        await log_channel.send(embed=embed)

async def apply_sanction(member, reason, duration_seconds=None):
    """Applique un timeout ou une autre sanction selon la gravité"""
    try:
        if duration_seconds:
            await member.timeout(discord.utils.utcnow() + datetime.timedelta(seconds=duration_seconds), reason=reason)
            await member.send(f"Vous avez été mis en timeout pour `{duration_seconds//60}` minutes. Raison : {reason}")
        else:
            # En cas de récidive plus grave, on peut expulser (à décommenter avec précaution)
            # await member.kick(reason=reason)
            await member.send(f"Vous avez été averti. Raison : {reason}")
    except:
        pass

@bot.event
async def on_ready():
    status =  bot.get_channel(1515798621860266024)
    print(f"{bot.user} est connecté et protège le serveur !")
    await status.send("Mise en marche du Bot")

@bot.event
async def on_message(message):
    # Ignorer les messages du bot lui-même
    if message.author.bot:
        return

    # Vérifier si l'utilisateur a un rôle ignoré
    author_roles = [role.name for role in message.author.roles]
    if any(role in IGNORED_ROLES for role in author_roles):
        await bot.process_commands(message)
        return

    # ---------- Anti-spam ----------
    now = time.time()
    user_messages[message.author.id].append((now, message.content))
    # Garder seulement les messages dans la fenêtre de temps
    user_messages[message.author.id] = [msg for msg in user_messages[message.author.id] if now - msg[0] <= TIME_WINDOW]

    if len(user_messages[message.author.id]) > MESSAGE_LIMIT:
        await message.delete()
        await log_mod_action("Suppression pour spam", message.author, message.channel, f"{MESSAGE_LIMIT} messages en {TIME_WINDOW}s")
        # Appliquer un timeout de 1 minute
        await apply_sanction(message.author, f"Spam : {MESSAGE_LIMIT} messages en {TIME_WINDOW} secondes", duration_seconds=60)
        return

    # ---------- Anti-publicité non autorisée ----------
    content = message.content.lower()
    # 1) Détecter les invitations Discord
    if DISCORD_INVITE_PATTERN.search(content):
        await message.delete()
        await log_mod_action("Suppression d'invite Discord", message.author, message.channel, "Invitation non autorisée")
        await apply_sanction(message.author, "Envoi d'invitation Discord non autorisée", duration_seconds=300)
        return

    # 2) Détecter les liens URL
    urls = URL_PATTERN.findall(content)
    if urls:
        # Vérifier si chaque lien est dans la whitelist
        allowed = True
        for url in urls:
            domain = re.sub(r"https?://(www\.)?", "", url).split('/')[0].split('?')[0]
            # Pour discord.com/channels, on accepte les liens internes
            if "discord.com/channels" in url:
                continue
            if not any(whitelisted in domain for whitelisted in WHITELISTED_DOMAINS):
                allowed = False
                break

        if not allowed:
            await message.delete()
            await log_mod_action("Suppression de lien publicitaire", message.author, message.channel, f"Lien non autorisé : {urls[0]}")
            await message.send("Message supprimer")
            #await apply_sanction(message.author, "Publication de lien non autorisé", duration_seconds=120)
            return

    await bot.process_commands(message)

# Commande pour ajouter un domaine à la whitelist (admin uniquement)
@bot.command(name="add_domain")
@commands.has_permissions(administrator=True)
async def add_domain(ctx, domain: str):
    global WHITELISTED_DOMAINS
    if domain not in WHITELISTED_DOMAINS:
        WHITELISTED_DOMAINS.append(domain)
        await ctx.send(f"Domaine `{domain}` ajouté à la liste blanche.")
        # Optionnel : sauvegarder dans un fichier pour persistance
    else:
        await ctx.send(f"`{domain}` est déjà dans la liste.")

# Commande pour lister les domaines autorisés
@bot.command(name="whitelist")
@commands.has_permissions(administrator=True)
async def show_whitelist(ctx):
    domains = "\n".join(WHITELISTED_DOMAINS)
    await ctx.send(f"**Domaines autorisés :**\n```{domains}```")

# Commande pour retirer un domaine
@bot.command(name="remove_domain")
@commands.has_permissions(administrator=True)
async def remove_domain(ctx, domain: str):
    global WHITELISTED_DOMAINS
    if domain in WHITELISTED_DOMAINS:
        WHITELISTED_DOMAINS.remove(domain)
        await ctx.send(f"Domaine `{domain}` retiré de la liste blanche.")
    else:
        await ctx.send(f"`{domain}` n'est pas dans la liste.")

# Gestion des erreurs de permissions
@add_domain.error
@remove_domain.error
@show_whitelist.error
async def admin_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("Vous devez être administrateur pour utiliser cette commande.", delete_after=5)

# Lancer le bot
if __name__ == "__main__":
    import datetime  # pour le timeout
    bot.run(TOKEN)