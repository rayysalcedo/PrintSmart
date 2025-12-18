import os

class Config:
    # Database connection for XAMPP (user is 'root', password is blank)
    MYSQL_HOST = 'localhost'
    MYSQL_USER = 'root'
    MYSQL_PASSWORD = ''
    MYSQL_DB = 'printsmart_db'
    
    # Secret key for sessions (keeps users logged in)
    SECRET_KEY = 'printsmart_secret_key_123'
    
    # Where to save uploaded files
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads')