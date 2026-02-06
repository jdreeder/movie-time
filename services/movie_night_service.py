from services.movie_scraper import MovieScraper
from bot_core.discord_events import DiscordEvents
from datetime import datetime, timedelta
from pytz import utc
from utils.image_util import download_image, convert_image_format
from bot_core.helpers import round_to_next_quarter_hour_timestamp
from utils.logging_config import log_with_context
from utils.discord_error_handler import ErrorMessages  # ADD THIS
import base64
import time
import logging


logger = logging.getLogger(__name__)


class MovieNightService:
    def __init__(self, movie_night_manager, movie_manager, movie_scraper: MovieScraper, movie_event_manager, token, guild_id, stream_channel, server_timezone=None):
        self.guild_id = guild_id
        self.movie_night_manager = movie_night_manager
        self.movie_event_manager = movie_event_manager
        self.movie_manager = movie_manager
        self.movie_scraper = movie_scraper
        self.api_key = movie_scraper.api_key
        self.stream_channel = stream_channel
        self.discord_events = DiscordEvents(token)
        self.server_timezone = server_timezone or TimeZones.UTC
        log_with_context(
            logger, 
            logging.INFO, 
            "MovieNightService initialized", 
            guild_id=guild_id,
            stream_channel=stream_channel,
            server_timezone=str(server_timezone)
        )

    async def add_movie_to_movie_night(self, movie_night_id, movie_url):
        """
        Add a movie to a movie night.
        
        Returns:
            tuple: (movie_event_id, discord_event_id) on success
            dict: {'error': error_type, 'message': details} on failure
        """
        log_with_context(
            logger, 
            logging.DEBUG, 
            "Adding movie to movie night", 
            movie_night_id=movie_night_id,
            movie_url=movie_url
        )
        
        try:
            self.movie_event_manager.db_session.begin_nested()
            
            # Step 1: Scrape movie details
            try:
                movie_details = self.movie_scraper.get_movie_details_from_url(movie_url)
            except Exception as scrape_error:
                log_with_context(
                    logger, 
                    logging.ERROR, 
                    "Movie scraping failed", 
                    movie_url=movie_url,
                    error=str(scrape_error)
                )
                self.movie_event_manager.db_session.rollback()
                return {
                    'error': 'SCRAPING_FAILED',
                    'message': f"Failed to load movie from Letterboxd",
                    'technical': str(scrape_error),
                    'url': movie_url
                }
            
            if not movie_details:
                self.movie_event_manager.db_session.rollback()
                log_with_context(
                    logger, 
                    logging.WARNING, 
                    "No movie details returned from scraper", 
                    movie_url=movie_url
                )
                return {
                    'error': 'SCRAPING_FAILED',
                    'message': "No movie information found at the provided URL",
                    'url': movie_url
                }

            # Step 2: Save or find movie
            existing_movie = self.movie_manager.find_movie_by_name_and_year(
                movie_details['name'], 
                movie_details['year']
            )
            
            if existing_movie:
                movie_id = existing_movie.id
                log_with_context(
                    logger, 
                    logging.DEBUG, 
                    "Using existing movie", 
                    movie_id=movie_id,
                    movie_name=movie_details['name']
                )
            else:
                movie_id = self.movie_manager.save_movie(movie_details)
                log_with_context(
                    logger, 
                    logging.DEBUG, 
                    "Saved new movie", 
                    movie_id=movie_id,
                    movie_name=movie_details['name']
                )

            # Step 3: Validate movie night exists
            movie_night = self.movie_night_manager.find_movie_night_by_id(movie_night_id)
            if not movie_night:
                log_with_context(
                    logger, 
                    logging.ERROR, 
                    "Movie night not found", 
                    movie_night_id=movie_night_id
                )
                self.movie_event_manager.db_session.rollback()
                return {
                    'error': 'MOVIE_NIGHT_NOT_FOUND',
                    'message': f"Movie night #{movie_night_id} doesn't exist",
                    'movie_night_id': movie_night_id
                }

            # EDGE CASE FIX 2: Check if night ended, resume it
            was_ended = False
            if movie_night.status == 2:
                log_with_context(
                    logger,
                    logging.INFO,
                    "Reopening ended movie night for new movie",
                    movie_night_id=movie_night_id,
                    old_index=movie_night.current_movie_index,
                    total_events=len(movie_night.events)
                )
                movie_night.status = 1  # Set back to "in progress"
                was_ended = True

                # Commit the status change
                self.movie_event_manager.db_session.commit()

            # Calculate start time with buffer
            last_movie_event = self.movie_event_manager.find_last_movie_event_by_movie_night_id(movie_night_id)
            if last_movie_event and last_movie_event.movie:
                runtime_seconds = last_movie_event.movie.runtime * 60
                last_movie_end_time = last_movie_event.start_time + runtime_seconds
            else:
                last_movie_end_time = movie_night.start_time

            # EDGE CASE FIX 1: Ensure minimum 5-minute buffer
            current_time_unix = int(time.time())
            minimum_future_time = current_time_unix + (5 * 60)  # 5 min buffer
            
            new_start_time_unix = max(minimum_future_time, last_movie_end_time)
            rounded_time_unix = round_to_next_quarter_hour_timestamp(new_start_time_unix)

            # Final validation - must be at least 2 minutes in future for Discord
            if rounded_time_unix - current_time_unix < 120:
                rounded_time_unix = current_time_unix + (5 * 60)
                rounded_time_unix = round_to_next_quarter_hour_timestamp(rounded_time_unix)
                log_with_context(
                    logger,
                    logging.WARNING,
                    "Adjusted event time to meet Discord minimum",
                    adjusted_time=rounded_time_unix
                )
        
            new_start_time_iso = datetime.utcfromtimestamp(rounded_time_unix).isoformat()

            # Step 5: Create movie event in database
            new_movie_event_id = self.movie_event_manager.create_movie_event(
                movie_night_id, 
                movie_id, 
                rounded_time_unix
            )

            movie_event = self.movie_event_manager.find_movie_event_by_id(new_movie_event_id)
            if not movie_event:
                log_with_context(
                    logger, 
                    logging.ERROR, 
                    "Failed to create movie event in database", 
                    movie_event_id=new_movie_event_id
                )
                self.movie_event_manager.db_session.rollback()
                return {
                    'error': 'DATABASE_ERROR',
                    'message': "Failed to save movie event to database"
                }

            movie = self.movie_manager.find_movie_by_id(movie_event.movie_id)
            if not movie:
                log_with_context(
                    logger, 
                    logging.ERROR, 
                    "Failed to find movie by ID after creation", 
                    movie_id=movie_event.movie_id
                )
                self.movie_event_manager.db_session.rollback()
                return {
                    'error': 'DATABASE_ERROR',
                    'message': "Failed to retrieve saved movie"
                }

            # Step 6: Prepare movie image
            backdrop_url = movie_details.get('backdrop_url', None)
            image_data = None
            
            if backdrop_url:
                try:
                    image_bytes = await download_image(backdrop_url)
                    if image_bytes:
                        converted_image_bytes = convert_image_format(image_bytes, format="JPEG")
                        base64_image = base64.b64encode(converted_image_bytes).decode()
                        image_data = f"data:image/jpeg;base64,{base64_image}"
                        log_with_context(
                            logger, 
                            logging.DEBUG, 
                            "Image prepared successfully", 
                            image_size_bytes=len(converted_image_bytes)
                        )
                except Exception as img_error:
                    log_with_context(
                        logger, 
                        logging.WARNING, 
                        "Failed to process movie image", 
                        backdrop_url=backdrop_url,
                        error=str(img_error)
                    )
                    # Continue without image - not a critical failure
            
            # Step 7: Validate voice channel
            channel_check = await self.discord_events.check_channel(self.guild_id, self.stream_channel)
            log_with_context(
                logger, 
                logging.INFO, 
                "Channel validation completed", 
                channel_id=self.stream_channel,
                channel_valid=channel_check.get('valid', False),
                channel_type=channel_check.get('type'),
                channel_name=channel_check.get('name')
            )
            
            if not channel_check.get('valid', False):
                log_with_context(
                    logger, 
                    logging.ERROR, 
                    "Invalid voice channel for Discord event", 
                    channel_id=self.stream_channel,
                    channel_message=channel_check.get('message'),
                    channel_type=channel_check.get('type')
                )
                self.movie_event_manager.db_session.rollback()
                return {
                    'error': 'CHANNEL_INVALID',
                    'message': f"Voice channel is invalid: {channel_check.get('message', 'Unknown error')}",
                    'channel_id': self.stream_channel,
                    'channel_type': channel_check.get('type')
                }
            
            # Step 8: Create Discord event
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
            except Exception as discord_error:
                log_with_context(
                    logger, 
                    logging.ERROR, 
                    "Exception while creating Discord event", 
                    error=str(discord_error),
                    movie_name=movie.name
                )
                self.movie_event_manager.db_session.rollback()
                return {
                    'error': 'DISCORD_EVENT_FAILED',
                    'message': "Failed to create Discord event",
                    'technical': str(discord_error),
                    'movie_name': movie.name
                }
            
            if discord_event and 'id' in discord_event:
                movie_event.discord_event_id = discord_event['id']
                self.movie_event_manager.db_session.commit()
                log_with_context(
                    logger, 
                    logging.INFO, 
                    "Movie added successfully", 
                    discord_event_id=discord_event['id'],
                    movie_event_id=new_movie_event_id,
                    movie_name=movie.name,
                    start_time=new_start_time_iso
                )
                return (new_movie_event_id, discord_event['id'])
            else:
                error_msg = discord_event.get('message', 'Unknown error') if isinstance(discord_event, dict) else 'Unknown error'
                code = discord_event.get('code', 'No code') if isinstance(discord_event, dict) else 'No code'
                log_with_context(
                    logger, 
                    logging.ERROR, 
                    "Discord event creation returned error", 
                    error_message=error_msg,
                    error_code=code,
                    movie_name=movie.name,
                    movie_event_id=new_movie_event_id
                )
                self.movie_event_manager.db_session.rollback()
                return {
                    'error': 'DISCORD_EVENT_FAILED',
                    'message': f"Discord API error: {error_msg}",
                    'technical': f"Code: {code}",
                    'movie_name': movie.name
                }
                
        except Exception as e:
            log_with_context(
                logger, 
                logging.ERROR, 
                "Unexpected exception in add_movie_to_movie_night", 
                error=str(e),
                error_type=type(e).__name__,
                movie_url=movie_url,
                movie_night_id=movie_night_id
            )
            self.movie_event_manager.db_session.rollback()
            return {
                'error': 'UNEXPECTED_ERROR',
                'message': "An unexpected error occurred",
                'technical': f"{type(e).__name__}: {str(e)}"
            }
    
    # Rest of your methods remain unchanged...
    
    async def start_first_event(self, movie_night):
        if movie_night.events:
            first_event = movie_night.events[0]
            await self.discord_events.start_event(self.guild_id, first_event.discord_event_id)
            movie_night.status = 1  # Update status to Started
            movie_night.current_movie_index = 0
            self.movie_event_manager.db_session.commit()
            log_with_context(
                logger, 
                logging.INFO, 
                "Started first movie event", 
                movie_night_id=movie_night.id,
                discord_event_id=first_event.discord_event_id
            )

    async def end_last_event(self, movie_night):
        if movie_night.events:
            last_event = movie_night.events[-1]
            await self.discord_events.end_event(self.guild_id, last_event.discord_event_id)
            
            movie_night.status = 2  # Update status to Finished
            # DON'T increment index - keep it on the last movie
            
            self.movie_event_manager.db_session.commit()

            log_with_context(
                logger, 
                logging.INFO, 
                "Movie night ended successfully", 
                movie_night_id=movie_night.id,
                discord_event_id=last_event.discord_event_id,
                total_events=len(movie_night.events),
                final_index=movie_night.current_movie_index  # Should stay at last valid index
            )

    async def transition_to_next_event(self, movie_night):
        # Refresh to get current state
        self.movie_event_manager.db_session.expire_all()
        self.movie_event_manager.db_session.refresh(movie_night)
        
        log_with_context(
            logger, 
            logging.INFO, 
            "Transitioning to next event", 
            movie_night_id=movie_night.id,
            current_index=movie_night.current_movie_index,
            total_events=len(movie_night.events)
        )
        
        # Double-check events still exist
        if not movie_night.events or len(movie_night.events) == 0:
            log_with_context(
                logger, 
                logging.WARNING, 
                "No events found after refresh", 
                movie_night_id=movie_night.id
            )
            movie_night.status = 2  # End the night
            self.movie_event_manager.db_session.commit()
            return
        
        # Validate we're not already at the end
        if movie_night.current_movie_index >= len(movie_night.events) - 1:
            log_with_context(
                logger, 
                logging.WARNING, 
                "Already at last event, cannot transition", 
                movie_night_id=movie_night.id,
                current_index=movie_night.current_movie_index
            )
            return
        
        # End current event
        current_event = movie_night.events[movie_night.current_movie_index]
        await self.discord_events.end_event(self.guild_id, current_event.discord_event_id)
        log_with_context(
            logger, 
            logging.INFO, 
            "Ended current event", 
            movie_night_id=movie_night.id,
            event_id=current_event.discord_event_id,
            movie_name=current_event.movie.name
        )

        # Increment to next event BEFORE starting it
        movie_night.current_movie_index += 1
        self.movie_event_manager.db_session.commit()
        
        log_with_context(
            logger, 
            logging.INFO, 
            "Incremented index", 
            movie_night_id=movie_night.id,
            new_index=movie_night.current_movie_index
        )

        # Start next event
        next_event = movie_night.events[movie_night.current_movie_index]
        await self.discord_events.start_event(self.guild_id, next_event.discord_event_id)
            
        log_with_context(
            logger, 
            logging.INFO, 
            "Started next event", 
            movie_night_id=movie_night.id,
            new_index=movie_night.current_movie_index,
            event_id=next_event.discord_event_id,
            movie_name=next_event.movie.name
        )
