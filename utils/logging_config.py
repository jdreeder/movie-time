import os
import logging
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
import json
from datetime import datetime

load_dotenv()

log_level = os.getenv('LOG_LEVEL', 'INFO').upper()

class StructuredFormatter(logging.Formatter):
    """Custom formatter that provides structured logging with additional context."""
    
    def format(self, record):
        # Add timestamp in ISO format
        record.iso_timestamp = datetime.utcnow().isoformat()
        
        # Add structured data if available
        if hasattr(record, 'structured_data'):
            record.structured_data_str = json.dumps(record.structured_data, default=str)
        else:
            record.structured_data_str = "{}"
        
        # Add component context
        if not hasattr(record, 'component'):
            record.component = record.name.split('.')[-1] if '.' in record.name else record.name
        
        return super().format(record)

def setup_logging():
    log_directory = os.path.join('storage', 'logs')
    
    # Create different log files for different purposes
    bot_log = os.path.join(log_directory, 'bot.log')
    discord_log = os.path.join(log_directory, 'discord.log')
    error_log = os.path.join(log_directory, 'errors.log')
    debug_log = os.path.join(log_directory, 'debug.log')

    if not os.path.exists(log_directory):
        os.makedirs(log_directory)

    # Create formatters
    detailed_formatter = StructuredFormatter(
        '%(iso_timestamp)s - %(component)s - %(levelname)s - %(message)s - %(structured_data_str)s'
    )
    
    simple_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    error_formatter = StructuredFormatter(
        '%(iso_timestamp)s - %(component)s - %(levelname)s - %(message)s - %(pathname)s:%(lineno)d - %(structured_data_str)s'
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.getLevelName(log_level))
    
    # Clear existing handlers
    root_logger.handlers.clear()

    # Main bot log handler (INFO and above)
    bot_handler = RotatingFileHandler(bot_log, maxBytes=10*1024*1024, backupCount=10)
    bot_handler.setLevel(logging.INFO)
    bot_handler.setFormatter(simple_formatter)
    root_logger.addHandler(bot_handler)

    # Discord-specific log handler
    discord_handler = RotatingFileHandler(discord_log, maxBytes=5*1024*1024, backupCount=5)
    discord_handler.setLevel(logging.DEBUG)
    discord_handler.setFormatter(detailed_formatter)
    
    # Create Discord logger
    discord_logger = logging.getLogger('discord')
    discord_logger.addHandler(discord_handler)
    discord_logger.setLevel(logging.DEBUG)
    discord_logger.propagate = False

    # Error log handler (ERROR and above)
    error_handler = RotatingFileHandler(error_log, maxBytes=5*1024*1024, backupCount=10)
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(error_formatter)
    root_logger.addHandler(error_handler)

    # Debug log handler (DEBUG level only)
    if log_level == 'DEBUG':
        debug_handler = RotatingFileHandler(debug_log, maxBytes=10*1024*1024, backupCount=5)
        debug_handler.setLevel(logging.DEBUG)
        debug_handler.setFormatter(detailed_formatter)
        root_logger.addHandler(debug_handler)

    # Console handler for development
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(simple_formatter)
    root_logger.addHandler(console_handler)

    # Set specific loggers
    logging.getLogger('bot_core.commands').setLevel(logging.INFO)
    logging.getLogger('services.movie_night_service').setLevel(logging.INFO)
    logging.getLogger('bot_core.discord_events').setLevel(logging.INFO)
    
    # Reduce noise from some libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('aiohttp').setLevel(logging.WARNING)

def log_with_context(logger, level, message, **context):
    """Helper function to log with structured context data."""
    extra = {'structured_data': context}
    logger.log(level, message, extra=extra)
