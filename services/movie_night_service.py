from services.movie_scraper import MovieScraper
from bot_core.discord_events import DiscordEvents
from datetime import datetime, timedelta
from pytz import utc
from utils.image_util import download_image, convert_image_format
from bot_core.helpers import round_to_next_quarter_hour_timestamp, utc_to_local_timestamp, local_to_utc_timestamp
import base64
import time
import logging

logger = logging.getLogger(__name__)

class MovieNightService:
    def __init__(self, movie_night_manager, movie_manager, movie_scraper: MovieScraper, movie_event_manager, token, guild_id, stream_channel, server_timezone):
        self.guild_id = guild_id
        self.movie_night_manager = movie_night_manager
        self.movie_event_manager = movie_event_manager
        self.movie_manager = movie_manager
        self.movie_scraper = movie_scraper
        self.api_key = movie_scraper.api_key
        self.stream_channel = stream_channel
        self.server_timezone = server_timezone
        self.discord_events = DiscordEvents(token)
        logger.info("MovieNightService initialized")

    async def add_movie_to_movie_night(self, movie_night_id, movie_url):
        logger.debug(f"Attempting to add movie from URL: {movie_url} to movie night ID: {movie_night_id}")
        try:
            self.movie_event_manager.db_session.begin_nested()
            movie_details = self.movie_scraper.get_movie_details_from_url(movie_url)
            logger.debug(f"Received movie details: {movie_details}")

            if not movie_details:
                self.movie_event_manager.db_session.rollback()
                logger.debug("No movie details found, rolling back transaction")
                return None

            existing_movie = self.movie_manager.find_movie_by_name_and_year(movie_details['name'], movie_details['year'])
            if existing_movie:
                movie_id = existing_movie.id
                logger.debug(f"Found existing movie ID: {movie_id}")
            else:
                movie_id = self.movie_manager.save_movie(movie_details)
                logger.debug(f"Saved new movie, ID: {movie_id}")

            movie_night = self.movie_night_manager.find_movie_night_by_id(movie_night_id)
            if not movie_night:
                logger.warning("Movie Night not found")
                return "Movie Night not found"

            if movie_night.current_movie_index >= len(movie_night.events):
                movie_night.current_movie_index = len(movie_night.events) - 1
                self.movie_event_manager.db_session.commit()
                logger.info("Movie night index reset after adding a new movie")

            last_movie_event = self.movie_event_manager.find_last_movie_event_by_movie_night_id(movie_night_id)
            current_time = int(time.time())
            
            if last_movie_event and last_movie_event.movie:
                runtime_seconds = last_movie_event.movie.runtime * 60
                last_movie_end_time = last_movie_event.start_time + runtime_seconds
                logger.debug(f"Last movie event end time: {last_movie_end_time}")
                logger.info(f"Last movie event end time: {last_movie_end_time}")
                
                # If the last movie's end time is in the past, use current time
                if last_movie_end_time < current_time:
                    logger.info("Last movie's end time is in the past, using current time as base")
                    last_movie_end_time = current_time
            else:
                logger.debug("No last movie event, using current time")
                last_movie_end_time = current_time

            logger.info(f"current time: {current_time}")
            # Add 10 minute buffer to ensure event is in the future
            min_start_time = current_time + (5 * 60)  # 5 minutes in seconds
            new_start_time_unix = max(min_start_time, last_movie_end_time)

            try:
                rounded_time_unix = round_to_next_quarter_hour_timestamp(new_start_time_unix)
                new_start_time_iso = datetime.utcfromtimestamp(rounded_time_unix).isoformat()
                logger.debug(f"Calculated new start time: {new_start_time_iso}")
                logger.info(f"Calculated new start time: {new_start_time_iso}")

                # Validate the calculated time is actually in the future
                if rounded_time_unix <= current_time:
                    error_msg = f"Calculated time {new_start_time_iso} is not in the future"
                    logger.error(error_msg)
                    self.movie_event_manager.db_session.rollback()
                    return f"Failed to add movie: {error_msg}"

                new_movie_event_id = self.movie_event_manager.create_movie_event(movie_night_id, movie_id, rounded_time_unix)
                if not new_movie_event_id:
                    logger.error("Failed to create movie event in database")
                    self.movie_event_manager.db_session.rollback()
                    return "Failed to create movie event in database"
                
                logger.debug(f"Created new movie event ID: {new_movie_event_id}")
                logger.info(f"Created new movie event ID: {new_movie_event_id}")

                movie_event = self.movie_event_manager.find_movie_event_by_id(new_movie_event_id)
                if not movie_event:
                    logger.error(f"Could not find newly created movie event with ID: {new_movie_event_id}")
                    self.movie_event_manager.db_session.rollback()
                    return "Failed to retrieve created movie event"

                movie = self.movie_manager.find_movie_by_id(movie_event.movie_id)
                if not movie:
                    logger.error(f"Could not find movie with ID: {movie_event.movie_id}")
                    self.movie_event_manager.db_session.rollback()
                    return "Failed to retrieve movie details"

                # Prepare Discord event data
                backdrop_url = movie_details.get('backdrop_url', None)
                image_data = None
                if backdrop_url:
                    try:
                        image_bytes = await download_image(backdrop_url)
                        if image_bytes:
                            converted_image_bytes = convert_image_format(image_bytes, format="JPEG")
                            base64_image = base64.b64encode(converted_image_bytes).decode()
                            image_data = f"data:image/jpeg;base64,{base64_image}"
                    except Exception as e:
                        logger.warning(f"Failed to process image for Discord event: {e}")
                        # Continue without image rather than failing

                event_title = f"{movie.name} ({movie.year})" if movie.year else movie.name
                
                try:
                    discord_event = await self.discord_events.create_event(
                        self.guild_id,
                        self.stream_channel,
                        event_title,
                        movie.overview,
                        new_start_time_iso,
                        image_data=image_data,
                        movie_url=movie_url  
                    )
                except Exception as e:
                    logger.error(f"Failed to create Discord event: {str(e)}")
                    self.movie_event_manager.db_session.rollback()
                    return f"Failed to create Discord event: {str(e)}"

                if not discord_event:
                    logger.error("Discord event creation returned None")
                    self.movie_event_manager.db_session.rollback()
                    return "Failed to create Discord event: No response from Discord API"

                if 'code' in discord_event:
                    error_msg = f"Discord API error {discord_event.get('code')}: {discord_event.get('message', 'Unknown error')}"
                    if 'errors' in discord_event:
                        error_details = discord_event['errors']
                        if 'scheduled_start_time' in error_details:
                            time_errors = error_details['scheduled_start_time'].get('_errors', [])
                            for err in time_errors:
                                if err.get('code') == 'GUILD_SCHEDULED_EVENT_SCHEDULE_PAST':
                                    error_msg = "Cannot schedule event in the past. Please try again."
                                    break
                    logger.error(f"Failed to create Discord event: {error_msg}")
                    self.movie_event_manager.db_session.rollback()
                    return f"Failed to add movie: {error_msg}"

                if 'id' not in discord_event:
                    logger.error(f"Discord event response missing ID: {discord_event}")
                    self.movie_event_manager.db_session.rollback()
                    return "Failed to create Discord event: Missing event ID"

                movie_event.discord_event_id = discord_event['id']
                self.movie_event_manager.db_session.commit()
                logger.info(f"Successfully created Discord event: {discord_event['id']}")
                return (new_movie_event_id, discord_event['id'])

            except Exception as e:
                logger.error(f"Unexpected error while creating movie event: {str(e)}")
                self.movie_event_manager.db_session.rollback()
                return f"Failed to add movie: {str(e)}"
        except Exception as e:
            logger.error(f"An error occurred: {e}")
            self.movie_event_manager.db_session.rollback()
            return None
    
    async def start_first_event(self, movie_night):
        if movie_night.events:
            first_event = movie_night.events[0]
            await self.discord_events.start_event(self.guild_id, first_event.discord_event_id)
            movie_night.status = 1  # Update status to Started
            movie_night.current_movie_index = 0
            self.movie_event_manager.db_session.commit()

    async def end_last_event(self, movie_night):
        if movie_night.events:
            last_event = movie_night.events[-1]
            await self.discord_events.end_event(self.guild_id, last_event.discord_event_id)
            movie_night.status = 2  # Update status to Finished
            movie_night.current_movie_index = len(movie_night.events) # Move past the last event
            self.movie_event_manager.db_session.commit()

            logger.info("Movie night has ended successfully - end_last_event")

    async def transition_to_next_event(self, movie_night):
        if movie_night.current_movie_index >= len(movie_night.events) - 1:

            # Re-fetch movie night events to see if new movies were added
            updated_movie_night = self.movie_night_manager.get_movie_night(movie_night.id)
            if len(updated_movie_night.events) > len(movie_night.events):
                movie_night.events = updated_movie_night.events  # Refresh the event list
                movie_night.current_movie_index = len(movie_night.events) - 1  # Move to the latest added movie
                self.movie_event_manager.db_session.commit()

                # Start the new movie
                next_event = movie_night.events[movie_night.current_movie_index]
                logger.info(f"Starting newly added movie: {next_event}")
                await self.discord_events.start_event(self.guild_id, next_event.discord_event_id)
                return

            # No new movies, end the movie night properly
            logger.info("No new movies found. Ending movie night.")
            await self.end_last_event(movie_night)
            return

        if movie_night.current_movie_index < len(movie_night.events) - 1:
            # End current event
            current_event = movie_night.events[movie_night.current_movie_index]
            await self.discord_events.end_event(self.guild_id, current_event.discord_event_id)

            # Move to the next movie and start it
            movie_night.current_movie_index += 1
            next_event = movie_night.events[movie_night.current_movie_index]
            logger.info(f"Starting next movie: {next_event}")
            await self.discord_events.start_event(self.guild_id, next_event.discord_event_id)
            self.movie_event_manager.db_session.commit()