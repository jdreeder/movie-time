import aiohttp
import logging
from utils.logging_config import log_with_context

logger = logging.getLogger(__name__)

class DiscordEvents:
    def __init__(self, discord_token):
        self.base_api_url = 'https://discord.com/api/v8'
        self.auth_headers = {
            'Authorization': f'Bot {discord_token}',
            'Content-Type': 'application/json'
        }
        log_with_context(
            logger, 
            logging.INFO, 
            "DiscordEvents initialized", 
            api_url=self.base_api_url
        )

    async def create_event(self, guild_id, channel_id, name, description, start_time, movie_url, image_data=None, ):
        # Convert IDs to strings to ensure proper format for Discord API
        guild_id_str = str(guild_id)
        channel_id_str = str(channel_id)
        
        event_data = {
            'name': name,
            'description': description + "\n\n" + movie_url,
            'scheduled_start_time': start_time,
            'entity_type': 2,
            'channel_id': channel_id_str,  # Ensure it's a string
            'privacy_level': 2,
        }
        
        log_with_context(
            logger, 
            logging.DEBUG, 
            "Creating Discord event", 
            guild_id=guild_id_str,
            channel_id=channel_id_str,
            event_name=name,
            start_time=start_time,
            has_image=image_data is not None
        )
        
        if image_data:
            event_data['image'] = "[image data]"  # Don't log actual image data, just indicate it's present
            # Still include the actual image data in the API request
            api_event_data = event_data.copy()
            api_event_data['image'] = image_data
        else:
            api_event_data = event_data

        url = f'https://discord.com/api/v8/guilds/{guild_id_str}/scheduled-events'
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=self.auth_headers, json=api_event_data) as response:
                    result = await response.json()
                    
                    if response.status == 201:  # Success
                        log_with_context(
                            logger, 
                            logging.INFO, 
                            "Discord event created successfully", 
                            guild_id=guild_id_str,
                            event_id=result.get('id'),
                            event_name=name
                        )
                    else:
                        log_with_context(
                            logger, 
                            logging.ERROR, 
                            "Discord API error creating event", 
                            status_code=response.status,
                            error_message=result.get('message'),
                            error_code=result.get('code'),
                            guild_id=guild_id_str,
                            event_name=name,
                            request_data={
                                'name': event_data['name'],
                                'description_length': len(event_data['description']),
                                'start_time': event_data['scheduled_start_time'],
                                'channel_id': event_data['channel_id']
                            }
                        )
                    
                    return result
        except Exception as e:
            log_with_context(
                logger, 
                logging.ERROR, 
                "Exception creating Discord event", 
                error=str(e),
                guild_id=guild_id_str,
                event_name=name
            )
            return {'error': str(e)}

    async def delete_event(self, guild_id, event_id):
        url = f'{self.base_api_url}/guilds/{guild_id}/scheduled-events/{event_id}'
        log_with_context(
            logger, 
            logging.DEBUG, 
            "Deleting Discord event", 
            guild_id=guild_id,
            event_id=event_id
        )
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=self.auth_headers) as response:
                    success = response.status == 204
                    log_with_context(
                        logger, 
                        logging.INFO if success else logging.ERROR, 
                        "Discord event deletion result", 
                        success=success,
                        status_code=response.status,
                        guild_id=guild_id,
                        event_id=event_id
                    )
                    return success
        except Exception as e:
            log_with_context(
                logger, 
                logging.ERROR, 
                "Exception deleting Discord event", 
                error=str(e),
                guild_id=guild_id,
                event_id=event_id
            )
            return False

    async def modify_event(self, guild_id, event_id, updated_data):
        url = f'{self.base_api_url}/guilds/{guild_id}/scheduled-events/{event_id}'
        log_with_context(
            logger, 
            logging.DEBUG, 
            "Modifying Discord event", 
            guild_id=guild_id,
            event_id=event_id,
            update_data=updated_data
        )
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.patch(url, headers=self.auth_headers, json=updated_data) as response:
                    result = await response.json()
                    
                    if response.status == 200:
                        log_with_context(
                            logger, 
                            logging.INFO, 
                            "Discord event modified successfully", 
                            guild_id=guild_id,
                            event_id=event_id
                        )
                    else:
                        log_with_context(
                            logger, 
                            logging.ERROR, 
                            "Discord API error modifying event", 
                            status_code=response.status,
                            error_message=result.get('message'),
                            error_code=result.get('code'),
                            guild_id=guild_id,
                            event_id=event_id
                        )
                    
                    return result
        except Exception as e:
            log_with_context(
                logger, 
                logging.ERROR, 
                "Exception modifying Discord event", 
                error=str(e),
                guild_id=guild_id,
                event_id=event_id
            )
            return {'error': str(e)}

    async def list_events(self, guild_id):
        url = f'{self.base_api_url}/guilds/{guild_id}/scheduled-events'
        log_with_context(
            logger, 
            logging.DEBUG, 
            "Listing Discord events", 
            guild_id=guild_id
        )
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.auth_headers) as response:
                    result = await response.json()
                    
                    if response.status == 200:
                        log_with_context(
                            logger, 
                            logging.DEBUG, 
                            "Discord events listed successfully", 
                            guild_id=guild_id,
                            event_count=len(result) if isinstance(result, list) else 0
                        )
                    else:
                        log_with_context(
                            logger, 
                            logging.ERROR, 
                            "Discord API error listing events", 
                            status_code=response.status,
                            error_message=result.get('message'),
                            error_code=result.get('code'),
                            guild_id=guild_id
                        )
                    
                    return result
        except Exception as e:
            log_with_context(
                logger, 
                logging.ERROR, 
                "Exception listing Discord events", 
                error=str(e),
                guild_id=guild_id
            )
            return {'error': str(e)}

    async def start_event(self, guild_id, event_id):
        log_with_context(
            logger, 
            logging.INFO, 
            "Starting Discord event", 
            guild_id=guild_id,
            event_id=event_id
        )
        return await self.modify_event(guild_id, event_id, {'status': 2})

    async def end_event(self, guild_id, event_id):
        log_with_context(
            logger, 
            logging.INFO, 
            "Ending Discord event", 
            guild_id=guild_id,
            event_id=event_id
        )
        return await self.modify_event(guild_id, event_id, {'status': 3})
    
    async def check_channel(self, guild_id, channel_id):
        """Check if a channel exists and is a valid voice channel."""
        guild_id_str = str(guild_id)
        channel_id_str = str(channel_id)
        
        log_with_context(
            logger, 
            logging.DEBUG, 
            "Checking channel validity", 
            guild_id=guild_id_str,
            channel_id=channel_id_str
        )
        
        # First check the guild
        guild_url = f'{self.base_api_url}/guilds/{guild_id_str}'
        
        try:
            async with aiohttp.ClientSession() as session:
                # Check if the channel exists
                channel_url = f'{self.base_api_url}/channels/{channel_id_str}'
                async with session.get(channel_url, headers=self.auth_headers) as response:
                    if response.status != 200:
                        log_with_context(
                            logger, 
                            logging.ERROR, 
                            "Channel check failed", 
                            guild_id=guild_id_str,
                            channel_id=channel_id_str,
                            status_code=response.status
                        )
                        return {
                            'exists': False,
                            'valid': False,
                            'message': f'Channel {channel_id_str} does not exist or bot lacks permissions',
                            'status': response.status
                        }
                    
                    channel_data = await response.json()
                    # Discord channel types:
                    # 0: GUILD_TEXT
                    # 2: GUILD_VOICE
                    # 4: GUILD_CATEGORY
                    # 13: GUILD_STAGE_VOICE
                    is_voice = channel_data.get('type') in [2, 13]  # 2 for voice, 13 for stage
                    
                    result = {
                        'exists': True,
                        'valid': is_voice,
                        'type': channel_data.get('type'),
                        'name': channel_data.get('name'),
                        'message': 'Channel is valid voice channel' if is_voice else 'Channel exists but is not a voice channel'
                    }
                    
                    log_with_context(
                        logger, 
                        logging.DEBUG, 
                        "Channel check completed", 
                        guild_id=guild_id_str,
                        channel_id=channel_id_str,
                        channel_name=result['name'],
                        channel_type=result['type'],
                        is_voice=is_voice
                    )
                    
                    return result
        except Exception as e:
            log_with_context(
                logger, 
                logging.ERROR, 
                "Exception checking channel", 
                error=str(e),
                guild_id=guild_id_str,
                channel_id=channel_id_str
            )
            return {
                'exists': False,
                'valid': False,
                'message': f'Error checking channel: {str(e)}',
                'error': str(e)
            }
    