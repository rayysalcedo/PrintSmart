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
# --- UPDATE THIS ROUTE IN app.py ---
@app.route('/services')
def services():
    try:
        # 1. Connect to Database
        conn = mysql.connector.connect(
            host=app.config['MYSQL_HOST'],
            user=app.config['MYSQL_USER'],
            password=app.config['MYSQL_PASSWORD'],
            database=app.config['MYSQL_DB']
        )
        cursor = conn.cursor(dictionary=True) # dictionary=True is CRITICAL

        # 2. Fetch Categories (for the Tabs)
        cursor.execute("SELECT * FROM categories ORDER BY category_id")
        categories = cursor.fetchall()

        # 3. Fetch Products (Joined with Category Slug so we know where to put them)
        # We grab the 'slug' from the categories table to match your HTML IDs
        query_products = """
            SELECT p.*, c.slug as category_slug 
            FROM products p 
            JOIN categories c ON p.category_id = c.category_id
            ORDER BY p.product_id
        """
        cursor.execute(query_products)
        products = cursor.fetchall()

        # 4. Fetch All Features (The Bullet Points)
        cursor.execute("SELECT * FROM product_features")
        all_features = cursor.fetchall()

        cursor.close()
        conn.close()

        # 5. Organize Features for the Template
        # We create a dictionary where Key = Product_ID, Value = List of Features
        # Example: {1: ['Material options', 'Custom sizes'], 2: [...]}
        features_map = {}
        for f in all_features:
            pid = f['product_id']
            if pid not in features_map:
                features_map[pid] = []
            features_map[pid].append(f['feature_text'])

        # 6. Send everything to the HTML
        return render_template('services.html', 
                               categories=categories, 
                               products=products, 
                               features_map=features_map)

    except Exception as e:
        return f"Error fetching data: {e}"

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