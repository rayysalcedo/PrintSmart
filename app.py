from flask import Flask, render_template, request, session, redirect, url_for
import mysql.connector
from config import Config
import os
from werkzeug.utils import secure_filename

# 1. SETUP UPLOAD FOLDER
UPLOAD_FOLDER = 'static/uploads'
# Allow Image + Design Files (PSD, AI)
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'docx', 'psd', 'ai'}

app = Flask(__name__)
app.config.from_object(Config)
# Allow 5GB Uploads
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024 * 1024
app.secret_key = 'super_secret_key_for_session' 

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

# --- CONTEXT PROCESSOR (Global Cart Count) ---
@app.context_processor
def inject_cart_count():
    if 'user_id' in session:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
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
        
        cursor.execute("SELECT * FROM categories ORDER BY category_id")
        categories = cursor.fetchall()

        query_products = """
            SELECT p.*, c.slug as category_slug 
            FROM products p 
            JOIN categories c ON p.category_id = c.category_id
            ORDER BY p.product_id
        """
        cursor.execute(query_products)
        products = cursor.fetchall()

        cursor.execute("SELECT * FROM product_features")
        all_features = cursor.fetchall()

        cursor.close()
        conn.close()

        features_map = {}
        for f in all_features:
            pid = f['product_id']
            if pid not in features_map: features_map[pid] = []
            features_map[pid].append(f['feature_text'])

        return render_template('services.html', categories=categories, products=products, features_map=features_map)

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

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    user_id = session.get('user_id', 1)

    try:
        product_id = int(request.form.get('product_id'))
        qty = int(request.form.get('quantity', 1))
        
        # 1. FILE UPLOAD LOGIC
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

        # 2. GET DYNAMIC VALUES
        unit_price = float(request.form.get('dynamic_unit_price', 0))
        variant_name = request.form.get('dynamic_variant_name', '')
        has_layout = request.form.get('has_layout') == 'on'

        details_list = []
        item_total = 0
        layout_fee = 0

        # --- PRODUCT SPECIFIC LOGIC ---
        
        if product_id == 1: # TARPAULIN
            h = float(request.form.get('height_ft', 0))
            w = float(request.form.get('width_ft', 0))
            details_list.append(f"Material: {variant_name}")
            details_list.append(f"Size: {h}x{w} ft")
            layout_fee = 150 if has_layout else 0
            item_total = ((h * w * unit_price) * qty) + layout_fee
            
        elif product_id == 2: # SINTRA BOARD
            details_list.append(f"Variant: {variant_name}")
            
            add_stand = 150 if request.form.get('sintra_stand') else 0
            if add_stand: details_list.append("Add-on: Box Type/Stand (+150)")
            
            layout_fee = 150 if has_layout else 0
            item_total = ((unit_price + add_stand) * qty) + layout_fee

        elif product_id == 3: # STICKERS
            mode = request.form.get('size_mode')
            if mode == 'sheet':
                details_list.append(f"Sheet: {variant_name}")
            else:
                details_list.append(f"Custom: {variant_name}")
            pre_cut = 50 if request.form.get('pre_cut') else 0
            if pre_cut: details_list.append("Pre-cut Service")
            layout_fee = 300 if has_layout else 0
            item_total = ((unit_price + pre_cut) * qty) + layout_fee

        elif product_id == 4: # DOCUMENTS
            details_list.append(f"Type: {variant_name}")
            layout_fee = 150 if has_layout else 0
            item_total = (unit_price * qty) + layout_fee

        elif product_id == 5: # PHOTOS
            details_list.append(f"Size: {variant_name}")
            layout_fee = 150 if has_layout else 0
            item_total = (unit_price * qty) + layout_fee

        elif product_id == 6: # ID PACKAGES (NEW!)
            details_list.append(f"Package: {variant_name}")
            
            enhance = 50 if request.form.get('extra_enhance') else 0
            softcopy = 20 if request.form.get('extra_softcopy') else 0
            
            if enhance: details_list.append("Enhance/Edit (+50)")
            if softcopy: details_list.append("Softcopy (+20)")
            
            layout_fee = 150 if has_layout else 0
            item_total = ((unit_price + enhance + softcopy) * qty) + layout_fee
        elif product_id == 6: # ID PACKAGES
            details_list.append(f"Package: {variant_name}")
            enhance = 50 if request.form.get('extra_enhance') else 0
            softcopy = 20 if request.form.get('extra_softcopy') else 0
            if enhance: details_list.append("Enhance (+50)")
            if softcopy: details_list.append("Softcopy (+20)")
            layout_fee = 150 if has_layout else 0
            item_total = ((unit_price + enhance + softcopy) * qty) + layout_fee

        elif product_id == 7: # SHIRTS (NEW!)
            service_type = request.form.get('shirt_service_type')
            
            if service_type == 'Supply':
                details_list.append(f"Supply: {variant_name}")
            else:
                details_list.append(f"Print Only: {variant_name}")
            
            layout_fee = 150 if has_layout else 0
            item_total = (unit_price * qty) + layout_fee
        # --- DEFAULT ---
        else:
            item_total = 0

        # 3. SAVE TO DB
        item_details = " | ".join(details_list)
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO cart (user_id, product_id, quantity, total_price, item_details, file_path)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, product_id, qty, item_total, item_details, file_path_str))
        conn.commit()
        conn.close()

        if request.form.get('action') == 'buy_now':
            return redirect('/checkout')
        else:
            return redirect(request.referrer)

    except Exception as e:
        print(f"CART ERROR: {e}")
        return f"Error: {e}"
@app.route('/remove_from_cart/<int:cart_id>')
def remove_from_cart(cart_id):
    # FIX: Use the same logic as 'add_to_cart' (Default to User 1 if not logged in)
    user_id = session.get('user_id', 1)
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Delete the specific item for this user
        cursor.execute("DELETE FROM cart WHERE cart_id = %s AND user_id = %s", (cart_id, user_id))
        conn.commit()
        conn.close()
        
        # Optional: Print to terminal to confirm it ran
        print(f"--- DEBUG: Deleted Cart ID {cart_id} for User {user_id} ---")
        
    except Exception as e:
        print(f"Error removing item: {e}")
        
    return redirect('/checkout')
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
        
        subtotal = 0.0
        for item in cart_items:
            subtotal += float(item['total_price'])
            if item['file_path']:
                item['file_list'] = item['file_path'].split(',')
            else:
                item['file_list'] = []

        processing_fee = 50.00
        grand_total = subtotal + processing_fee
        conn.close()
        
        return render_template('checkout.html', cart_items=cart_items, subtotal=subtotal, processing_fee=processing_fee, grand_total=grand_total)
    except Exception as e:
        return f"Checkout Error: {e}"

@app.route('/place_order', methods=['POST'])
def place_order():
    user_id = session.get('user_id', 1)
    payment_method = request.form.get('payment_method')
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT * FROM cart WHERE user_id = %s", (user_id,))
        cart_items = cursor.fetchall()
        if not cart_items: return "Cart is empty!"

        total_amount = float(request.form.get('grand_total'))
        cursor.execute("INSERT INTO orders (user_id, total_amount, payment_status, payment_method, order_status, created_at) VALUES (%s, %s, 'Paid', %s, 'Pending', NOW())", (user_id, total_amount, payment_method))
        conn.commit()
        new_order_id = cursor.lastrowid
        
        for item in cart_items:
            cursor.execute("INSERT INTO order_items (order_id, product_id, quantity, price_at_order, item_details, file_path) VALUES (%s, %s, %s, %s, %s, %s)", (new_order_id, item['product_id'], item['quantity'], item['total_price'], item['item_details'], item['file_path']))
            
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        conn.commit()
        conn.close()
        return "SUCCESS! Order placed."
    except Exception as e:
        return f"Order Error: {e}"

# --- AUTH ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # FIX 1: Get 'email' from the form (matches login.html)
        email = request.form.get('email')
        password = request.form.get('password')
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            
            # FIX 2: Query the 'email' column instead of 'username'
            cursor.execute("SELECT * FROM users WHERE email = %s AND password_hash = %s", (email, password))
            user = cursor.fetchone()
            
            conn.close()
            
            if user:
                session['user_id'] = user['user_id']
                session['role'] = user['role']
                # Store full name for the welcome message
                session['username'] = user['full_name'] 
                
                # Check Role and Redirect
                if user['role'] == 'admin':
                    return redirect('/admin')
                else:
                    return redirect('/')
            else:
                return "Invalid Email or Password"
                
        except Exception as e: 
            return f"Login Error: {e}"
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/register')
def register():
    return render_template('register.html')

@app.route('/about')
def about():
    return render_template('about.html')

# --- ADMIN ROUTES ---
@app.route('/admin')
def admin_dashboard():
    if 'role' not in session or session['role'] != 'admin':
        return "ACCESS DENIED"
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT COUNT(*) as count FROM orders")
        total_orders = cursor.fetchone()['count']
        cursor.execute("SELECT SUM(total_amount) as revenue FROM orders")
        res = cursor.fetchone()
        total_revenue = res['revenue'] if res['revenue'] else 0
        
        cursor.execute("SELECT * FROM products")
        products = cursor.fetchall()
        cursor.execute("SELECT * FROM product_variants")
        variants = cursor.fetchall()
        conn.close()

        variants_map = {}
        for v in variants:
            pid = v['product_id']
            if pid not in variants_map: variants_map[pid] = []
            variants_map[pid].append(v)

        return render_template('admin.html', total_orders=total_orders, total_revenue=total_revenue, products=products, variants_map=variants_map)
    except Exception as e: return f"DB Error: {e}"

# --- ADMIN ACTIONS ---

@app.route('/admin/update_variant', methods=['POST'])
def update_variant():
    # 1. Security Check
    if 'role' not in session or session['role'] != 'admin':
        return redirect('/login')

    try:
        # 2. Get Data from the Admin Form
        variant_id = request.form.get('variant_id')
        price = request.form.get('price')
        stock = request.form.get('stock')

        # 3. Update the Database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE product_variants 
            SET price = %s, stock_quantity = %s 
            WHERE variant_id = %s
        """, (price, stock, variant_id))
        
        conn.commit()
        conn.close()
        
        # 4. CRITICAL FIX: Return a redirect so Flask doesn't crash
        return redirect('/admin')

    except Exception as e:
        return f"Update Error: {e}"
# Change port to 5001 to avoid the 'Address in use' error
app.run(debug=True, port=5001)