from flask import Flask, render_template, request, session, redirect, url_for, flash
import mysql.connector
from config import Config
import os
from werkzeug.utils import secure_filename

# 1. SETUP UPLOAD FOLDER
UPLOAD_FOLDER = 'static/uploads'
# Added 'psd' and 'ai' to the list
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'docx', 'psd', 'ai'}

app = Flask(__name__)
app.config.from_object(Config)
# ALLOW UP TO 5GB UPLOADS (Note: Large files take time to upload!)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024 * 1024
app.secret_key = 'super_secret_key_for_session' # Required for login sessions

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- HELPER: GET DB CONNECTION ---
def get_db_connection():
    return mysql.connector.connect(
        host=app.config['MYSQL_HOST'],
        user=app.config['MYSQL_USER'],
        password=app.config['MYSQL_PASSWORD'],
        database=app.config['MYSQL_DB']
    )

# --- CONTEXT PROCESSOR: MAKES 'cart_count' AVAILABLE ON EVERY PAGE ---
# --- CONTEXT PROCESSOR: MAKES 'cart_count' AVAILABLE ON EVERY PAGE ---
@app.context_processor
def inject_cart_count():
    if 'user_id' in session:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            # Count total items (sum of quantities)
            cursor.execute("SELECT SUM(quantity) FROM cart WHERE user_id = %s", (session['user_id'],))
            result = cursor.fetchone()
            count = int(result[0]) if result and result[0] else 0
            conn.close()
            return {'cart_count': count}
        except:
            return {'cart_count': 0}
    return {'cart_count': 0}
# --- ROUTES ---

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/services')
def services():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True) 

        # Fetch Categories
        cursor.execute("SELECT * FROM categories ORDER BY category_id")
        categories = cursor.fetchall()

        # Fetch Products
        query_products = """
            SELECT p.*, c.slug as category_slug 
            FROM products p 
            JOIN categories c ON p.category_id = c.category_id
            ORDER BY p.product_id
        """
        cursor.execute(query_products)
        products = cursor.fetchall()

        # Fetch Features
        cursor.execute("SELECT * FROM product_features")
        all_features = cursor.fetchall()

        cursor.close()
        conn.close()

        # Organize Features
        features_map = {}
        for f in all_features:
            pid = f['product_id']
            if pid not in features_map:
                features_map[pid] = []
            features_map[pid].append(f['feature_text'])

        return render_template('services.html', 
                               categories=categories, 
                               products=products, 
                               features_map=features_map)

    except Exception as e:
        return f"Error fetching data: {e}"

@app.route('/order/<int:product_id>')
def order(product_id=None):
    product = None
    variants = [] 

    if product_id:
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("SELECT * FROM products WHERE product_id = %s", (product_id,))
            product = cursor.fetchone()

            cursor.execute("SELECT * FROM product_variants WHERE product_id = %s", (product_id,))
            variants = cursor.fetchall()
            
            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error fetching product: {e}")
            
    return render_template('order.html', product=product, variants=variants)

# --- SHOPPING CART & CHECKOUT ROUTES ---

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    user_id = session.get('user_id', 1)

    try:
        # ... (Your existing file upload and details logic remains here) ...
        # ... (Copy the file upload logic from your previous code) ...
        
        # --- (SIMPLIFIED FOR CLARITY - KEEP YOUR EXISTING LOGIC UP TO HERE) ---
        # 1. GET FORM DATA
        product_id = request.form.get('product_id')
        qty = int(request.form.get('quantity', 1))
        
        # 2. FILE UPLOAD LOGIC (Keep your existing code)
        file_paths = []
        if 'design_file' in request.files:
            files = request.files.getlist('design_file')
            for file in files:
                if file and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    save_name = f"cart_{user_id}_{filename}"
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], save_name))
                    file_paths.append(f"uploads/{save_name}")
        file_path_str = ",".join(file_paths) if file_paths else None

        # 3. DETAILS & PRICE LOGIC (Keep your existing code)
        details_list = []
        for key, value in request.form.items():
            if key not in ['product_id', 'quantity', 'design_file', 'action'] and value:
                details_list.append(f"{key.replace('_', ' ').title()}: {value}")
        item_details = " | ".join(details_list)

        rate = float(request.form.get('material_variant_id', 0))
        h = float(request.form.get('height_ft', 0))
        w = float(request.form.get('width_ft', 0))
        has_layout = 150 if request.form.get('has_layout') else 0
        item_total = ((h * w * rate) * qty) + has_layout if (h and w) else 0

        # 4. INSERT TO DB
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO cart (user_id, product_id, quantity, total_price, item_details, file_path)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, product_id, qty, item_total, item_details, file_path_str))
        conn.commit()
        conn.close()

        # 5. REDIRECT LOGIC (New!)
        action = request.form.get('action')
        if action == 'buy_now':
            return redirect('/checkout')
        else:
            # Stay on the same page (Referrer)
            return redirect(request.referrer)

    except Exception as e:
        return f"Error: {e}"

@app.route('/checkout')
def checkout():
    user_id = session.get('user_id', 1)
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        query = """
            SELECT c.*, p.name as product_name 
            FROM cart c
            JOIN products p ON c.product_id = p.product_id
            WHERE c.user_id = %s
        """
        cursor.execute(query, (user_id,))
        cart_items = cursor.fetchall()
        
        # --- FIX: CONVERT DECIMAL TO FLOAT ---
        subtotal = 0.0
        for item in cart_items:
            # Convert the MySQL Decimal to Python Float before adding
            subtotal += float(item['total_price'])
            
            # Helper: Split file paths back into a list for the template
            if item['file_path']:
                item['file_list'] = item['file_path'].split(',')
            else:
                item['file_list'] = []

        processing_fee = 50.00
        grand_total = subtotal + processing_fee
        
        conn.close()
        
        return render_template('checkout.html', 
                               cart_items=cart_items, 
                               subtotal=subtotal, 
                               processing_fee=processing_fee, 
                               grand_total=grand_total)
                               
    except Exception as e:
        return f"Checkout Error: {e}"

@app.route('/place_order', methods=['POST'])
def place_order():
    user_id = session.get('user_id', 1)
    payment_method = request.form.get('payment_method') # GCash or Card
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # 1. Get Cart Items
        cursor.execute("SELECT * FROM cart WHERE user_id = %s", (user_id,))
        cart_items = cursor.fetchall()
        
        if not cart_items:
            return "Cart is empty!"

        # 2. Create ONE Master Order
        total_amount = float(request.form.get('grand_total'))
        
        cursor.execute("""
            INSERT INTO orders (user_id, total_amount, payment_status, payment_method, order_status, created_at)
            VALUES (%s, %s, 'Paid', %s, 'Pending', NOW())
        """, (user_id, total_amount, payment_method))
        conn.commit()
        new_order_id = cursor.lastrowid
        
        # 3. Move Cart Items -> Order Items
        for item in cart_items:
            cursor.execute("""
                INSERT INTO order_items (order_id, product_id, quantity, price_at_order, item_details, file_path)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (new_order_id, item['product_id'], item['quantity'], item['total_price'], item['item_details'], item['file_path']))
            
        # 4. Clear Cart
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        conn.commit()
        
        conn.close()
        
        return "SUCCESS! Order placed and sent to Admin."

    except Exception as e:
        return f"Order Error: {e}"

# --- AUTHENTICATION ROUTES (FIXED) ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        try: # <--- This starts the block
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("SELECT * FROM users WHERE email = %s AND password_hash = %s", (email, password))
            user = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            if user:
                session['user_id'] = user['user_id']
                session['role'] = user['role']
                session['username'] = user['full_name']
                
                if user['role'] == 'admin':
                    return redirect(url_for('admin_dashboard'))
                else:
                    return redirect('/') 
            else:
                flash("Invalid Email or Password", "danger")
                return redirect(url_for('login'))

        except Exception as e: # <--- THIS IS LIKELY WHAT IS MISSING OR MISALIGNED
            flash(f"Database Error: {e}", "danger")
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    # Using 'success' instead of 'danger' or 'info'
    flash("You have been successfully logged out.", "success") 
    return redirect(url_for('login'))

@app.route('/register')
def register():
    return render_template('register.html')

@app.route('/about')
def about():
    return render_template('about.html')

# --- ADMIN DASHBOARD ROUTES ---

@app.route('/admin')
def admin_dashboard():
    # 1. SECURITY CHECK
    if 'role' not in session or session['role'] != 'admin':
        return "ACCESS DENIED: Admins only. Please <a href='/login'>Login</a>."

    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        # --- A. FETCH STATS (For the top cards) ---
        cursor.execute("SELECT COUNT(*) as count FROM orders")
        total_orders = cursor.fetchone()['count']

        cursor.execute("SELECT SUM(total_amount) as revenue FROM orders")
        result_revenue = cursor.fetchone()
        total_revenue = result_revenue['revenue'] if result_revenue['revenue'] else 0

        # --- B. FETCH PRODUCTS (For the Inventory Tab) ---
        cursor.execute("SELECT * FROM products ORDER BY product_id")
        products = cursor.fetchall()

        cursor.execute("SELECT * FROM product_variants ORDER BY product_id, variant_id")
        variants = cursor.fetchall()

        cursor.close()
        conn.close()

        # Group variants
        variants_map = {}
        for v in variants:
            pid = v['product_id']
            if pid not in variants_map: variants_map[pid] = []
            variants_map[pid].append(v)

        return render_template('admin.html', 
                               total_orders=total_orders,
                               total_revenue=total_revenue,
                               products=products, 
                               variants_map=variants_map)

    except Exception as e:
        return f"Database Error: {e}"

@app.route('/admin/update_variant', methods=['POST'])
def update_variant():
    if 'role' not in session or session['role'] != 'admin':
        return redirect('/login')

    try:
        variant_id = request.form.get('variant_id')
        price = request.form.get('price')
        stock = request.form.get('stock')

        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE product_variants 
            SET price = %s, stock_quantity = %s 
            WHERE variant_id = %s
        """, (price, stock, variant_id))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return redirect('/admin')
    except Exception as e:
        return f"Update Error: {e}"

@app.route('/admin/upload_product_image', methods=['POST'])
def upload_product_image():
    if 'role' not in session or session['role'] != 'admin':
        return redirect('/login')

    try:
        product_id = request.form.get('product_id')
        file = request.files['product_image']
        
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            ext = filename.rsplit('.', 1)[1].lower()
            new_filename = f"product_{product_id}.{ext}"
            
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], new_filename))
            db_path = f"uploads/{new_filename}" 
            
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE products SET image_path = %s WHERE product_id = %s", (db_path, product_id))
            conn.commit()
            conn.close()

        return redirect('/admin')
        
    except Exception as e:
        return f"Upload Error: {e}"

if __name__ == '__main__':
    app.run(debug=True)