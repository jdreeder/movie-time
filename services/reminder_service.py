import logging
import asyncio
import discord
from datetime import datetime, timedelta
import time

class ReminderService:
    def __init__(self, bot, db_manager, config_manager):
        self.bot = bot
        self.db_manager = db_manager
        self.config_manager = config_manager
        self.reminder_tasks = {}
        self.is_running = False
        
    async def start_reminder_service(self):
        """Start the reminder service to check for upcoming events"""
        self.is_running = True
        while self.is_running:
            try:
                await self.check_upcoming_events()
                # Check every minute
                await asyncio.sleep(60)
            except Exception as e:
                logging.error(f"Error in reminder service: {e}")
                await asyncio.sleep(60)  # Continue checking even if there's an error
    
    async def check_upcoming_events(self):
        """Check for upcoming events and schedule reminders"""
        current_time = int(time.time())
        # Get all active movie nights
        movie_nights = self.db_manager.get_active_movie_nights()
        
        for movie_night in movie_nights:
            guild_id = movie_night.guild_id
            reminder_minutes = self.config_manager.get_setting(guild_id, 'reminder_minutes')
            
            if not reminder_minutes:
                continue  # Skip if no reminder setting
                
            # Get upcoming events for this movie night
            events = self.db_manager.get_movie_events(movie_night.id)
            
            for event in events:
                event_id = event.id
                start_time = event.start_time
                
                # If this event already has a scheduled reminder, skip it
                if event_id in self.reminder_tasks:
                    continue
                    
                # Calculate when to send the reminder
                reminder_time = start_time - (reminder_minutes * 60)
                
                # If reminder time is in the future, schedule it
                if reminder_time > current_time:
                    seconds_until_reminder = reminder_time - current_time
                    self.schedule_reminder(event, guild_id, seconds_until_reminder)
    
    def schedule_reminder(self, event, guild_id, seconds_until_reminder):
        """Schedule a reminder for a specific event"""
        event_id = event.id
        
        # Create and store the task
        task = asyncio.create_task(self.send_reminder(event, guild_id, seconds_until_reminder))
        self.reminder_tasks[event_id] = task
        
        # Set up callback to remove the task when done
        task.add_done_callback(lambda t: self.reminder_tasks.pop(event_id, None))
    
    async def send_reminder(self, event, guild_id, seconds_until_reminder):
        """Send a reminder after the specified delay"""
        try:
            # Wait until it's time to send the reminder
            await asyncio.sleep(seconds_until_reminder)
            
            # Get the announcement channel
            announcement_channel_id = self.config_manager.get_setting(guild_id, 'announcement_channel')
            if not announcement_channel_id:
                return
                
            channel = self.bot.get_channel(announcement_channel_id)
            if not channel:
                logging.error(f"Could not find announcement channel {announcement_channel_id}")
                return
                
            # Get ping role if configured
            ping_role_id = self.config_manager.get_setting(guild_id, 'ping_role')
            ping_text = f"<@&{ping_role_id}> " if ping_role_id else ""
            
            # Get movie details
            movie = self.db_manager.get_movie(event.movie_id)
            if not movie:
                logging.error(f"Could not find movie for event {event.id}")
                return
                
            # Create reminder embed
            embed = discord.Embed(
                title=f"Movie Starting Soon: {movie.name}",
                description=f"{ping_text}The movie will begin <t:{event.start_time}:R>!",
                color=0x00ff00
            )
            
            if movie.image_url:
                embed.set_thumbnail(url=movie.image_url)
                
            embed.add_field(name="Runtime", value=f"{movie.runtime} minutes", inline=True)
            
            # Send the reminder
            await channel.send(embed=embed)
            
        except Exception as e:
            logging.error(f"Error sending reminder for event {event.id}: {e}")
    
    def stop_reminder_service(self):
        """Stop the reminder service"""
        self.is_running = False
        
        # Cancel all scheduled reminders
        for task in self.reminder_tasks.values():
            task.cancel()
        self.reminder_tasks.clear() 