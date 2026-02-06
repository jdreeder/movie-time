import discord, re, logging
from utils.discord_error_handler import DiscordErrorHandler, ErrorMessages
from datetime import datetime
from bot_core.discord_events import DiscordEvents
from bot_core.discord_actions import create_header_embed, create_movie_embed, post_now_playing, generate_help_pages
from bot_core.helpers import TimeZones, parse_date, parse_start_time, utc_to_local_timestamp, round_to_next_quarter_hour_timestamp
import pytz 

logger = logging.getLogger(__name__)

class MovieCommands:
    def __init__(self, movie_night_manager, movie_night_service, movie_event_manager, discord_token, ping_role_id=None, announcement_channel_id=None):
        self.movie_night_manager = movie_night_manager
        self.movie_night_service = movie_night_service
        self.movie_event_manager = movie_event_manager
        self.announcement_channel_id = announcement_channel_id
        self.ping_role_id  = ping_role_id
        self.discord_events = DiscordEvents(discord_token)
        self.server_timezone = TimeZones.UTC
        logger.info("MovieCommands initialized")
    
    def parse_movie_urls(self, movie_urls):
        if isinstance(movie_urls, str):
            movie_urls = list(filter(None, re.split(r'[,\t\s]+', movie_urls)))
        elif not isinstance(movie_urls, list):
            movie_urls = []
        logger.info(f"Parsed movie URLs: {movie_urls}")
        return movie_urls

    async def create_movie_night(self, interaction, title: str, description: str, server_timezone_enum: TimeZones, start_time: str = None, start_date: str = None):
        try:
            server_timezone = pytz.timezone(server_timezone_enum.value)
            current_local_datetime = datetime.now(tz=server_timezone)
            parsed_date = parse_date(start_date) if start_date else current_local_datetime.date()

            if parsed_date < current_local_datetime.date():
                await interaction.response.send_message("The specified date must be in the future.")
                return
            if start_date and not start_time:
                await interaction.response.send_message("A start time must be specified for future dates.")
                return
            
            if start_time:
                parsed_time_unix = parse_start_time(start_time, server_timezone_enum, date_str=start_date)
            else:
                parsed_time_unix = int(current_local_datetime.timestamp())

            rounded_time_unix = round_to_next_quarter_hour_timestamp(parsed_time_unix)
            movie_night_id = self.movie_night_manager.create_movie_night(title, description, rounded_time_unix)
            await interaction.response.send_message(f"Movie Night created with ID: {movie_night_id}")
            logger.info(f"Created Movie Night with ID: {movie_night_id}")
        except Exception as e:
            logger.error(f"Error in create_movie_night: {e}")
            raise e

    async def remove_movie_event_command(self, interaction, movie_event_id=None):
        try:
            if movie_event_id is None:
                movie_event_id = self.movie_event_manager.find_last_movie_event()
                
            if movie_event_id is None:
                await interaction.response.send_message("No movie event found to remove.")
                return
            
            discord_event_id, result_message = self.movie_event_manager.remove_movie_event(movie_event_id)
            
            if discord_event_id: 
                await self.discord_events.delete_event(guild_id=interaction.guild.id,event_id=discord_event_id)
            
            await interaction.response.send_message(result_message)
            logger.info(f"Removed movie event: {movie_event_id}")
        except Exception as e:
            logger.error(f"Error in remove_movie_event_command: {e}")
            raise e

    async def add_movies(self, interaction, movie_urls: str or list, movie_night_id: int = None):
        try:
            await interaction.response.defer()
            movie_urls = self.parse_movie_urls(movie_urls)
            
            if not movie_urls:
                await DiscordErrorHandler.send_warning(
                    interaction,
                    ErrorMessages.NO_MOVIES_PROVIDED['title'],
                    ErrorMessages.NO_MOVIES_PROVIDED['details']
                )
                return
            
            logger.debug(f"Starting to add {len(movie_urls)} movies to movie night ID: {movie_night_id}")
            updated_movie_night_id = await self.process_movie_urls(interaction, movie_urls, movie_night_id)
            
            if updated_movie_night_id is not None:
                logger.info(f"Successfully processed movies for movie night ID {updated_movie_night_id}")
            else:
                logger.info(f"Failed to process movies (no valid movie night ID)")
        except Exception as e:
            logger.error(f"Unexpected error in add_movies: {e}", exc_info=True)
            await DiscordErrorHandler.send_error(
                interaction,
                "Unexpected Error",
                "Something went wrong while adding movies. The error has been logged.",
                technical_details=str(e)
            )

    async def process_movie_urls(self, interaction, movie_urls: list, movie_night_id: int = None):
        added_movies = []
        discord_event_ids = []
        failed_movies = []
        
        try:
            if movie_night_id is None:
                movie_night_id = self.movie_night_manager.get_most_recent_movie_night_id()
                if movie_night_id is None:
                    await DiscordErrorHandler.send_warning(
                        interaction,
                        ErrorMessages.MOVIE_NIGHT_NOT_FOUND['title'],
                        ErrorMessages.MOVIE_NIGHT_NOT_FOUND['details']
                    )
                    return None

            for movie_url in movie_urls:
                logger.debug(f"Processing movie URL: {movie_url}")
                result = await self.movie_night_service.add_movie_to_movie_night(movie_night_id, movie_url)
                
                # Check if result is an error dictionary
                if isinstance(result, dict) and 'error' in result:
                    error_type = result['error']
                    failed_movies.append({'url': movie_url, 'error': result})
                    
                    # Map error types to user messages
                    if error_type == 'SCRAPING_FAILED':
                        error_info = ErrorMessages.SCRAPING_FAILED
                    elif error_type == 'CHANNEL_INVALID':
                        error_info = ErrorMessages.CHANNEL_INVALID
                    elif error_type == 'DISCORD_EVENT_FAILED':
                        error_info = ErrorMessages.DISCORD_EVENT_FAILED
                    elif error_type == 'MOVIE_NIGHT_NOT_FOUND':
                        error_info = ErrorMessages.MOVIE_NIGHT_NOT_FOUND
                    else:
                        error_info = {
                            'title': "Error Adding Movie",
                            'details': result.get('message', 'Unknown error occurred')
                        }
                    
                    await DiscordErrorHandler.send_error(
                        interaction,
                        error_info['title'],
                        f"{error_info['details']}\n\n**Failed URL:**\n`{movie_url}`",
                        technical_details=result.get('technical')
                    )
                    
                    # For critical errors, stop processing
                    if error_type in ['CHANNEL_INVALID', 'MOVIE_NIGHT_NOT_FOUND']:
                        logger.error(f"Critical error {error_type}, stopping movie processing")
                        raise Exception(f"Critical error: {error_type}")
                    
                    continue  # Skip to next movie for non-critical errors
                
                # Success case
                if result and isinstance(result, tuple):
                    movie_event_id, discord_event_id = result
                    added_movies.append(movie_event_id)
                    if discord_event_id:
                        discord_event_ids.append(discord_event_id)
                    
                    await interaction.followup.send(
                        f'✅ Added movie `{movie_url}` to Movie Night (Event ID: {movie_event_id})'
                    )
                else:
                    failed_movies.append({'url': movie_url, 'error': 'Unknown result format'})

            # Summary message
            if added_movies and failed_movies:
                await interaction.followup.send(
                    f"⚠️ **Summary:** {len(added_movies)} movie(s) added successfully, "
                    f"{len(failed_movies)} failed."
                )
            elif added_movies:
                await DiscordErrorHandler.send_success(
                    interaction,
                    "All Movies Added",
                    f"Successfully added {len(added_movies)} movie(s) to Movie Night #{movie_night_id}"
                )
            
            logger.info(f"Processed {len(movie_urls)} movies: {len(added_movies)} successful, {len(failed_movies)} failed")
            return movie_night_id
            
        except Exception as e:
            # Clean up any movies that were added before the error
            logger.error(f"Exception in process_movie_urls, rolling back {len(added_movies)} movies", exc_info=True)
            
            for movie_id in added_movies:
                self.movie_event_manager.remove_movie_event(movie_id)

            for event_id in discord_event_ids:
                await self.discord_events.delete_event(guild_id=interaction.guild.id, event_id=event_id)
            
            await DiscordErrorHandler.send_error(
                interaction,
                "Error Processing Movies",
                f"An error occurred while processing movies. All changes have been rolled back.\n\n"
                f"**Movies processed before error:** {len(added_movies)}",
                technical_details=str(e)
            )
            
            return movie_night_id

    async def post_movie_night(self, interaction, movie_night_id: int = None):
        await interaction.response.defer()

        if not movie_night_id:
            movie_night_id = self.movie_night_manager.get_most_recent_movie_night_id()
            if not movie_night_id:
                logger.info("No recent Movie Night found.")
                await interaction.followup.send("No recent Movie Night found.")
                return

        try:
            movie_night = self.movie_night_manager.get_movie_night(movie_night_id)
            if not movie_night:
                logger.info(f"No Movie Night found with ID: {movie_night_id}")
                await interaction.followup.send(f"No Movie Night found with ID: {movie_night_id}")
                return

            announcement_channel = interaction.guild.get_channel(self.announcement_channel_id)
            if not announcement_channel:
                logger.info("Announcement channel is not configured.")
                await interaction.followup.send("Announcement channel is not configured.")
                return

            if movie_night.discord_post_id:
                try:
                    existing_post_ids = movie_night.discord_post_id.split(',')
                    for post_id in existing_post_ids:
                        try:
                            await announcement_channel.fetch_message(int(post_id))
                        except discord.NotFound:
                            logger.info(f"Post with ID {post_id} not found. Proceeding with reposting.")
                            raise discord.NotFound

                    message_links = [f"https://discord.com/channels/{interaction.guild.id}/{self.announcement_channel_id}/{post_id}" for post_id in existing_post_ids]
                    await interaction.followup.send(f"Movie Night already posted: {' | '.join(message_links)}")
                    logger.info(f"Movie Night already posted. ID: {movie_night_id}")
                    return
                except discord.NotFound:
                    for post_id in existing_post_ids:
                        try:
                            msg = await announcement_channel.fetch_message(int(post_id))
                            await msg.delete()
                        except discord.NotFound:
                            continue
                    self.movie_night_manager.update_movie_night_post_ids(movie_night_id, "")

            header_embed = create_header_embed(interaction, movie_night, self.ping_role_id)
            movie_embeds = [create_movie_embed(event, index, len(movie_night.events)) for index, event in enumerate(movie_night.events)]
            new_post_ids = []

            for i in range(0, len(movie_embeds), 10):
                embeds_to_post = [header_embed] + movie_embeds[i:i+10] if i == 0 else movie_embeds[i:i+10]
                message = await announcement_channel.send(embeds=embeds_to_post)
                new_post_ids.append(str(message.id))
                logger.info(f"Posted or updated movie night details with message ID {message.id}")

            self.movie_night_manager.update_movie_night_post_ids(movie_night_id, ",".join(new_post_ids))
            await interaction.followup.send(f"Movie Night details posted successfully. ID: {movie_night_id}")
        except Exception as e:
            logger.error(f"An error occurred while posting the Movie Night: {e}")
            await interaction.followup.send("An error occurred while posting the Movie Night.")
    
    async def update_movie_night_post(self, interaction, movie_night_id: int):
        await interaction.response.defer()
        
        movie_night = self.movie_night_manager.get_movie_night(movie_night_id)
        if not movie_night:
            await interaction.followup.send(f"No movie night found with ID: {movie_night_id}")
            return

        announcement_channel = interaction.guild.get_channel(self.announcement_channel_id)
        if not announcement_channel:
            await interaction.followup.send("Announcement channel is not configured correctly.")
            return

        if not movie_night.discord_post_id:
            await interaction.followup.send("This movie night has not been posted yet, so there is nothing to update.")
            return

        existing_post_ids = movie_night.discord_post_id.split(',')
        header_embed = create_header_embed(interaction, movie_night, self.ping_role_id)
        movie_embeds = [create_movie_embed(event, index, len(movie_night.events)) for index, event in enumerate(movie_night.events)]
        all_embeds = [header_embed] + movie_embeds

        embed_chunks = [all_embeds[i:i + 10] for i in range(0, len(all_embeds), 10)]
        new_post_ids = []

        for post_id in existing_post_ids:
            try:
                message = await announcement_channel.fetch_message(int(post_id))
                await message.delete()
            except discord.NotFound:
                pass

        for embed_chunk in embed_chunks:
            message = await announcement_channel.send(embeds=embed_chunk)
            new_post_ids.append(str(message.id))

        self.movie_night_manager.update_movie_night_post_ids(movie_night_id, ",".join(new_post_ids))

        await interaction.followup.send("Movie night details updated successfully.")

    async def view_movie_night(self, interaction, movie_night_id: int = None):
        try:
            await interaction.response.defer()
            
            # Case 1: No movie_night_id provided
            if movie_night_id is None:
                movie_night_id = self.movie_night_manager.get_most_recent_movie_night_id()
                if movie_night_id is None:
                    logger.info("No movie nights exist in the database")
                    await interaction.followup.send("No movie nights have been created yet. Use `/create_movie_night` to create one.")
                    return

            # Case 2: Specific movie_night_id provided but not found
            movie_night_details = self.movie_night_manager.get_movie_night_details(movie_night_id)
            
            # Handle case where get_movie_night_details returns an error message string
            if isinstance(movie_night_details, str):
                logger.warning(f"Attempted to view non-existent movie night with ID: {movie_night_id}")
                await interaction.followup.send(f"Movie Night #{movie_night_id} does not exist. Use `/create_movie_night` to create a new one.")
                return

            # Case 3: Movie night exists but has no events
            if not movie_night_details['events']:
                response_text = f"Movie Night #{movie_night_id}: {movie_night_details['title']}\n"
                response_text += f"Description: {movie_night_details['description']}\n"
                response_text += "No movies have been added to this movie night yet. Use `/add_movies` to add some movies!"
                await interaction.followup.send(response_text)
                logger.info(f"Viewed empty movie night ID {movie_night_id}")
                return

            # Case 4: Success case - Movie night exists with events
            response_text = f"Movie Night #{movie_night_id}: {movie_night_details['title']}\n"
            response_text += f"Description: {movie_night_details['description']}\n"
            for event in movie_night_details['events']:
                server_timezone_str = self.server_timezone.value
                start_time = utc_to_local_timestamp(event['start_time'], server_timezone_str)
                response_text += f"  - Event ID: {event['event_id']}\n - Name: {event['movie_name']}\n - Start Time: <t:{start_time}:F>\n\n"
            
            await interaction.followup.send(response_text)
            logger.info(f"Successfully viewed movie night ID {movie_night_id} with {len(movie_night_details['events'])} events")

        except Exception as e:
            error_msg = f"An unexpected error occurred while viewing the movie night: {str(e)}"
            logger.error(f"Error in view_movie_night: {error_msg}", exc_info=True)
            await interaction.followup.send("Sorry, something went wrong while trying to view the movie night. Please try again later.")
            raise e

    async def edit_movie_night(self, interaction, movie_night_id: int = None, title: str = None, description: str = None):
        try:
            if movie_night_id is None:
                movie_night_id = self.movie_night_manager.get_most_recent_movie_night_id()
                if movie_night_id is None:
                    await interaction.followup.send("No movie nights found.")
                    return

            if title or description is not None:
                movie_night_id = self.movie_night_manager.update_movie_night(movie_night_id, title, description)

            await interaction.response.send_message(f"Movie Night updated on ID: {movie_night_id}")
            logger.info(f"Edited movie night ID {movie_night_id}")
        except Exception as e:
            logger.error(f"Error in edit_movie_night: {e}")
            raise e

    async def delete_event(self, interaction, event_id: int):
        try:
            await interaction.response.defer()
            success = self.movie_night_manager.delete_movie_event(event_id)

            if success:
                await interaction.followup.send(f"Successfully deleted Movie Event with ID: {event_id}")
                logger.info(f"Deleted movie event ID {event_id}")
            else:
                await interaction.followup.send("Failed to delete movie event.")
                logger.warning(f"Failed to delete movie event ID {event_id}")
        except Exception as e:
            logger.error(f"Error in delete_event: {e}")
            raise e
    
    async def next_event(self, interaction, movie_night_id: int = None):
        try:
            await interaction.response.defer()
            if not movie_night_id:
                movie_night_id = self.movie_night_manager.get_most_recent_movie_night_id()

            if not movie_night_id:
                await interaction.followup.send("No active Movie Night found.")
                return

            # REFRESH the movie_night to get current state
            self.movie_event_manager.db_session.expire_all()  # ADD THIS LINE
            movie_night = self.movie_night_manager.get_movie_night(movie_night_id)
            
            if not movie_night:
                await interaction.followup.send(f"No Movie Night found with ID: {movie_night_id}")
                return

            # Check if there are any events left
            if not movie_night.events or len(movie_night.events) == 0:
                await interaction.followup.send("No movies left in this movie night.")
                logger.warning(f"[NEXT] No events remaining in movie night {movie_night_id}")
                return

            announcement_channel = interaction.guild.get_channel(self.announcement_channel_id)
            if not announcement_channel:
                await interaction.followup.send("Announcement channel is not configured.")
                logger.info("Announcement channel is not configured.")
                return

            total_events = len(movie_night.events)
            logger.info(f"[NEXT] Movie night {movie_night_id} - Status: {movie_night.status}, Index: {movie_night.current_movie_index}, Total: {total_events}")

            # Case 1: Movie night hasn't started yet (status = 0)
            if movie_night.status == 0:
                if total_events == 0:
                    await interaction.followup.send("No movies in this movie night yet.")
                    logger.warning(f"[NEXT] No movies in movie night {movie_night_id}")
                    return
                
                await self.movie_night_service.start_first_event(movie_night)
                current_movie_event = movie_night.events[0]
                movie_name = current_movie_event.movie.name if current_movie_event.movie else "Unknown Movie"
                message = f"Starting the first movie: {movie_name}"
                
                now_playing_embed = await post_now_playing(current_movie_event, self.ping_role_id)
                await announcement_channel.send(message, embed=now_playing_embed)
                await interaction.followup.send(f"Next event started: {message}")
                logger.info(f"[NEXT] Started first movie: {movie_name}")
                return

            # Case 2: Movie night is in progress (status = 1)
            if movie_night.status == 1:
                # Check if we're on the last movie
                if movie_night.current_movie_index >= total_events - 1:
                    logger.info(f"[NEXT] On last movie (index {movie_night.current_movie_index} of {total_events}), ending night")
                    await self.movie_night_service.end_last_event(movie_night)
                    await announcement_channel.send("🎬 Movie Night has ended. Thanks for watching!")
                    await interaction.followup.send("Movie Night has ended.")
                    return
                
                # Not on last movie - transition to next
                logger.info(f"[NEXT] Transitioning from index {movie_night.current_movie_index} to {movie_night.current_movie_index + 1}")
                await self.movie_night_service.transition_to_next_event(movie_night)
                
                # Refresh movie_night object after transition
                self.movie_event_manager.db_session.expire_all()
                movie_night = self.movie_night_manager.get_movie_night(movie_night_id)
                
                current_movie_event = movie_night.events[movie_night.current_movie_index]
                movie_name = current_movie_event.movie.name if current_movie_event.movie else "Unknown Movie"
                message = f"Starting the next movie: {movie_name}"
                
                now_playing_embed = await post_now_playing(current_movie_event, self.ping_role_id)
                await announcement_channel.send(message, embed=now_playing_embed)
                await interaction.followup.send(f"Next event started: {message}")
                logger.info(f"[NEXT] Started next movie: {movie_name} (index {movie_night.current_movie_index})")
                return

            # Case 3: Movie night already finished (status = 2)
            if movie_night.status == 2:
                await interaction.followup.send("This movie night has already ended.")
                logger.info(f"[NEXT] Movie night {movie_night_id} already ended")
                return

        except Exception as e:
            logger.error(f"[NEXT] Error in next_event: {e}", exc_info=True)
            await interaction.followup.send("An error occurred while processing the request.")


    async def cancel_movie_night(self, interaction, movie_night_id: int):
        movie_night = self.movie_night_manager.get_movie_night(movie_night_id)
        
        if not movie_night:
            await interaction.response.send_message("Movie Night not found.", ephemeral=True)
            return
        
        for event in movie_night.events:
            if event.discord_event_id:
                await self.discord_events.delete_event(guild_id=interaction.guild.id, event_id=event.discord_event_id)
            self.movie_event_manager.remove_movie_event(event.id)
        
        self.movie_night_manager.delete_movie_night(movie_night_id)
        
        await interaction.response.send_message(f"Movie Night {movie_night_id} and its events have been canceled and deleted.", ephemeral=True)   
                 
    async def view_all_movie_nights(self, interaction):
        try:
            await interaction.response.defer()
            
            # Get all movie nights from the database
            movie_nights = self.movie_night_manager.list_all_movie_nights()
            
            if not movie_nights:
                logger.info("No movie nights exist in the database")
                await interaction.followup.send("No movie nights have been created yet. Use `/create_movie_night` to create one.")
                return
            
            # Create a formatted list of movie nights
            response_text = "**All Movie Nights:**\n\n"
            
            # Define status labels
            status_labels = {
                0: "Not Started",
                1: "In Progress",
                2: "Finished"
            }
            
            # Sort movie nights by ID (newest first)
            movie_nights.sort(key=lambda x: x.id, reverse=True)
            
            for movie_night in movie_nights:
                status = status_labels.get(movie_night.status, "Unknown")
                movie_count = len(movie_night.events) if movie_night.events else 0
                
                response_text += f"**ID: {movie_night.id}** - {movie_night.title}\n"
                response_text += f"Status: {status} | Movies: {movie_count}\n"
                
                # Add a timestamp if available
                if movie_night.start_time:
                    server_timezone_str = self.server_timezone.value
                    start_time = utc_to_local_timestamp(movie_night.start_time, server_timezone_str)
                    response_text += f"Created: <t:{start_time}:F>\n"
                
                response_text += "\n"
            
            # If the response is too long, split it into chunks
            if len(response_text) > 2000:
                chunks = [response_text[i:i+1900] for i in range(0, len(response_text), 1900)]
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        await interaction.followup.send(chunk)
                    else:
                        await interaction.followup.send(f"(Continued {i+1}/{len(chunks)})\n{chunk}")
            else:
                await interaction.followup.send(response_text)
            
            logger.info(f"Successfully listed {len(movie_nights)} movie nights")
            
        except Exception as e:
            error_msg = f"An unexpected error occurred while listing movie nights: {str(e)}"
            logger.error(f"Error in view_all_movie_nights: {error_msg}", exc_info=True)
            await interaction.followup.send("Sorry, something went wrong while trying to list movie nights. Please try again later.")
            raise e

class ConfigCommands:
    def __init__(self, config_manager):
        self.config_manager = config_manager
    
    async def config(self, interaction, stream_channel: discord.VoiceChannel = None, announcement_channel: discord.TextChannel = None, ping_role: discord.Role = None,  timezone: TimeZones = None):
        try:
            guild_id = interaction.guild.id

            if timezone:
                timezone_value = timezone.value
                self.config_manager.set_setting(guild_id, 'timezone', timezone_value)
                await interaction.response.send_message(f"Timezone set to {timezone_value}")
                return

            if stream_channel:
                channel_id = stream_channel.id
                self.config_manager.set_setting(guild_id, 'stream_channel', channel_id)
                await interaction.response.send_message(f"Stream channel set to {stream_channel.name}")
                return

            if announcement_channel:
                channel_id = announcement_channel.id
                self.config_manager.set_setting(guild_id, 'announcement_channel', channel_id)
                await interaction.response.send_message(f"Announcement channel set to {announcement_channel.name}")
                return

            if ping_role:
                role_id = ping_role.id
                self.config_manager.set_setting(guild_id, 'ping_role', role_id)
                await interaction.response.send_message(f"Ping role set to {ping_role.name}")
                return
            
            # If we get here, no parameters were provided
            await interaction.response.send_message("""Please specify at least one of the following parameters:
            - stream_channel: The voice channel to use for streaming
            - announcement_channel: The text channel to post announcements in
            - ping_role: The role to ping when a movie night is posted
            - timezone: The timezone to use for movie nights
            """)
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {e}")
            logging.error(f"Error in config command: {e}")

class HelpCommands:
    def __init__(self):
        logger.info("HelpCommands initialized")

    async def help_command(self, interaction):
        try:
            pages = generate_help_pages()
            view = self.create_view(0, len(pages), pages)
            await interaction.response.send_message(embed=pages[0], view=view, ephemeral=True)
            logger.info("Help command executed")
        except Exception as e:
            logger.error(f"Error in help_command: {e}")
            raise e

    def create_view(self, current_page, total_pages, pages):
        view = discord.ui.View()

        previous_button = discord.ui.Button(label="Previous", style=discord.ButtonStyle.grey, disabled=current_page == 0)
        next_button = discord.ui.Button(label="Next", style=discord.ButtonStyle.grey, disabled=current_page == total_pages - 1)

        async def previous_callback(interaction):
            nonlocal current_page
            current_page -= 1
            new_embed = pages[current_page].set_footer(text=f"Page {current_page + 1} of {total_pages}")
            await interaction.response.edit_message(embed=new_embed, view=self.create_view(current_page, total_pages, pages))
            logger.info(f"Help page {current_page + 1} displayed")

        async def next_callback(interaction):
            nonlocal current_page
            current_page += 1
            new_embed = pages[current_page].set_footer(text=f"Page {current_page + 1} of {total_pages}")
            await interaction.response.edit_message(embed=new_embed, view=self.create_view(current_page, total_pages, pages))
            logger.info(f"Help page {current_page + 1} displayed")

        previous_button.callback = previous_callback
        next_button.callback = next_callback

        view.add_item(previous_button)
        view.add_item(next_button)

        return view
