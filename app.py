from flask import Flask, render_template
import mysql.connector
from config import Config

app = Flask(__name__)
app.config.from_object(Config)

# --- FUNCTION TO TEST DATABASE CONNECTION ---
def test_db_connection():
    try:
        conn = mysql.connector.connect(
            host=app.config['MYSQL_HOST'],
            user=app.config['MYSQL_USER'],
            password=app.config['MYSQL_PASSWORD'],
            database=app.config['MYSQL_DB']
        )
        print("\n------------------------------------------------")
        print("✅ SUCCESS: Database connected successfully!")
        print("------------------------------------------------\n")
        conn.close()
    except mysql.connector.Error as err:
        print("\n------------------------------------------------")
        print(f"❌ ERROR: Could not connect to database. \nError: {err}")
        print("------------------------------------------------\n")

# Run the test immediately when the app starts
test_db_connection()

# --- ROUTES ---
@app.route('/services')
def services():
    return render_template('services.html')

@app.route('/order')
def order():
    return "This will be the Order Page"
@app.route('/')
def home():
    return render_template('home.html')
@app.route('/about')
# --- Add these to your existing routes in app.py ---

@app.route('/about')
def about():
    return "About Us Page Coming Soon"

@app.route('/login')
def login():
    return render_template('login.html') 
    # ^ If you don't have login.html yet, change this to: return "Login Page"

@app.route('/register')
def register():
    return "Register Page"
if __name__ == '__main__':
    app.run(debug=True)