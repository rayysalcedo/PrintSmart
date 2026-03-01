import os
from dotenv import dotenv_values

secrets = dotenv_values(".env")

class Config:
    MYSQL_HOST = secrets.get('MYSQL_HOST') or os.environ.get('MYSQL_HOST')
    MYSQL_USER = secrets.get('MYSQL_USER') or os.environ.get('MYSQL_USER')
    MYSQL_PASSWORD = secrets.get('DB_PASSWORD') or os.environ.get('DB_PASSWORD')
    MYSQL_DB = secrets.get('MYSQL_DB') or os.environ.get('MYSQL_DB')
    
    raw_port = secrets.get('MYSQL_PORT') or os.environ.get('MYSQL_PORT', 27072)
    MYSQL_PORT = int(raw_port)