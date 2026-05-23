import logging
import os
import sys
from datetime import datetime

class PrintLogger:
    def __init__(self, logger):
        self.logger = logger
        self.in_write = False

    def write(self, message):
        if message.startswith('\r'):
            sys.__stdout__.write(message)
            sys.__stdout__.flush()
        else:
            if message.strip() and not self.in_write:
                self.in_write = True
                # Log message only to file (without printing it to console)
                self.logger.info(message.strip())
                # Print the raw message directly to the terminal (without log format)
                sys.__stdout__.write(message + '\n')
                sys.__stdout__.flush()
                self.in_write = False

    def flush(self):
        pass


# Create a 'logs' directory in the parent directory of the current script
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
log_dir = os.path.join(parent_dir, 'logs')
os.makedirs(log_dir, exist_ok=True)

# Set up logging
current_date = datetime.now().strftime('%Y-%m-%d-%H-%M')
log_file_path = os.path.join(log_dir, f'fasttarget_{current_date}.log')

# Configure the root logger so that logging.error(), logging.info(), etc. work everywhere
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# File handler (logs everything to file)
file_handler = logging.FileHandler(log_file_path, mode='w')
file_handler.setLevel(logging.INFO)
# Customize the log format to include timestamp and message
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

# Console handler (only shows warnings and errors on console)
console_handler = logging.StreamHandler(sys.__stdout__)
console_handler.setLevel(logging.WARNING)
# User-friendly format for console (no timestamp, just level and message)
console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
logger.addHandler(console_handler)

# Redirect stdout and stderr to the logger
print_logger = PrintLogger(logger)
sys.stdout = print_logger
sys.stderr = print_logger