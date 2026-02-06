import os
import json
import logging

logger = logging.getLogger(__name__)

class ConfigManager:
    def __init__(self):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.directory = os.path.join(base_dir, 'storage', 'settings')
        os.makedirs(self.directory, exist_ok=True)

    def get_settings_path(self, guild_id):
        return os.path.join(self.directory, f'{guild_id}_settings.json')

    def save_settings(self, guild_id, settings_dict):
        filepath = self.get_settings_path(guild_id)
        
        try:
            with open(filepath, 'r') as file:
                settings = json.load(file)
        except FileNotFoundError:
            settings = {}

        settings.update(settings_dict)

        try:
            with open(filepath, 'w') as file:
                json.dump(settings, file)
        except Exception as e:
            logger.error(f"An error occurred while saving {filepath}: {str(e)}")

    def set_setting(self, guild_id, key, value):
        filepath = self.get_settings_path(guild_id)
        settings = {}
        
        try:
            with open(filepath, 'r') as f:
                settings = json.load(f)
        except FileNotFoundError:
            logger.info(f"Settings file not found for guild ID: {guild_id}, creating new file")
        except json.JSONDecodeError:
            logger.warning(f"Error decoding JSON in settings file for guild ID: {guild_id}, creating new file")
        
        settings[key] = value
        self.save_settings(guild_id, settings)

    def get_setting(self, guild_id, setting_name):
        filepath = self.get_settings_path(guild_id)
        try:
            with open(filepath, 'r') as file:
                settings = json.load(file)
                return settings.get(setting_name, None)
        except FileNotFoundError:
            logger.info(f"Settings file not found for guild ID: {guild_id}")
            return None
        except json.JSONDecodeError:
            logger.warning(f"Error decoding JSON in settings file for guild ID: {guild_id}")
            return None

    def get_all_settings(self, guild_id):
        filepath = self.get_settings_path(guild_id)
        try:
            with open(filepath, 'r') as file:
                settings = json.load(file)
                return settings  # Return all settings
        except FileNotFoundError:
            logger.info(f"Settings file not found for guild ID: {guild_id}")
            return None
        except json.JSONDecodeError:
            logger.warning(f"Error decoding JSON in settings file for guild ID: {guild_id}")
            return None