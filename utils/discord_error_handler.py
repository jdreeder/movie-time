import discord
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class DiscordErrorHandler:
    """Handles formatting and sending user-friendly error messages to Discord."""
    
    @staticmethod
    async def send_error(
        interaction: discord.Interaction,
        error_title: str,
        error_details: str,
        technical_details: Optional[str] = None,
        ephemeral: bool = True
    ):
        """
        Send a formatted error message to Discord.
        
        Args:
            interaction: Discord interaction object
            error_title: Short, user-friendly error title
            error_details: Explanation of what went wrong
            technical_details: Optional technical info for debugging
            ephemeral: Whether message is visible only to command user
        """
        embed = discord.Embed(
            title=f"❌ {error_title}",
            description=error_details,
            color=discord.Color.red()
        )
        
        if technical_details:
            embed.add_field(
                name="Technical Details",
                value=f"```{technical_details[:1000]}```",  # Limit length
                inline=False
            )
        
        embed.set_footer(text="If this persists, please contact an administrator.")
        
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
        except Exception as e:
            logger.error(f"Failed to send error message to Discord: {e}")
    
    @staticmethod
    async def send_warning(
        interaction: discord.Interaction,
        warning_title: str,
        warning_details: str,
        ephemeral: bool = True
    ):
        """Send a formatted warning message to Discord."""
        embed = discord.Embed(
            title=f"⚠️ {warning_title}",
            description=warning_details,
            color=discord.Color.orange()
        )
        
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
        except Exception as e:
            logger.error(f"Failed to send warning message to Discord: {e}")
    
    @staticmethod
    async def send_success(
        interaction: discord.Interaction,
        success_title: str,
        success_details: str,
        ephemeral: bool = False
    ):
        """Send a formatted success message to Discord."""
        embed = discord.Embed(
            title=f"✅ {success_title}",
            description=success_details,
            color=discord.Color.green()
        )
        
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=ephemeral)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
        except Exception as e:
            logger.error(f"Failed to send success message to Discord: {e}")


# Predefined error messages for common scenarios
class ErrorMessages:
    """Common error messages with user-friendly explanations."""
    
    SCRAPING_FAILED = {
        'title': "Failed to Load Movie",
        'details': (
            "I couldn't retrieve information from Letterboxd for this movie.\n\n"
            "**Possible reasons:**\n"
            "• The URL might be invalid or incorrectly formatted\n"
            "• Letterboxd might be blocking automated requests\n"
            "• The movie page doesn't exist\n\n"
            "**What to try:**\n"
            "• Double-check the URL is correct\n"
            "• Wait a few minutes and try again\n"
            "• Try a different movie"
        )
    }
    
    CHANNEL_INVALID = {
        'title': "Invalid Voice Channel",
        'details': (
            "The configured voice channel for movie events is invalid.\n\n"
            "**What to do:**\n"
            "• Use `/config stream_channel:<your-voice-channel>` to set a valid voice channel\n"
            "• Make sure the bot has permission to create events in that channel"
        )
    }
    
    MOVIE_NIGHT_NOT_FOUND = {
        'title': "Movie Night Not Found",
        'details': (
            "The specified movie night doesn't exist.\n\n"
            "**What to do:**\n"
            "• Use `/view_all_movie_nights` to see available movie nights\n"
            "• Create a new movie night with `/create_movie_night`"
        )
    }
    
    NO_MOVIES_PROVIDED = {
        'title': "No Movies Provided",
        'details': (
            "You didn't provide any movie URLs.\n\n"
            "**Example usage:**\n"
            "`/add_movies movie_urls:https://letterboxd.com/film/the-prestige/`\n\n"
            "You can add multiple movies separated by spaces or commas."
        )
    }
    
    DISCORD_EVENT_FAILED = {
        'title': "Failed to Create Discord Event",
        'details': (
            "The movie was saved but I couldn't create the Discord event.\n\n"
            "**Possible reasons:**\n"
            "• Bot doesn't have 'Manage Events' permission\n"
            "• Voice channel is invalid or inaccessible\n"
            "• Discord API is experiencing issues\n\n"
            "**What to do:**\n"
            "• Check bot permissions in Server Settings\n"
            "• Verify the voice channel configuration with `/config`"
        )
    }
    
    RATE_LIMITED = {
        'title': "Rate Limited",
        'details': (
            "Too many requests were made too quickly.\n\n"
            "**What to do:**\n"
            "• Wait 2-5 minutes before trying again\n"
            "• Add movies one at a time if adding multiple"
        )
    }
