import os

class Config:
    # Live Aiven Database Connection
    MYSQL_HOST = 'mysql-printsmart-printsmart.j.aivencloud.com'
    MYSQL_USER = 'avnadmin'
    # This line pulls the password from the server's hidden settings
    MYSQL_PASSWORD = os.environ.get('DB_PASSWORD') 
    MYSQL_DB = 'defaultdb'
    MYSQL_PORT = 27072

    SECRET_KEY = 'printsmart_secret_key_123'