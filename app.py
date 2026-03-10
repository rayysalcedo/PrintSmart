import os
import secrets
from dotenv import load_dotenv
import re

# 1. LOAD THE SECRETS BEFORE ANYTHING ELSE!
load_dotenv()

from flask import Flask, render_template, request, session, redirect, url_for, flash
import mysql.connector 
from config import Config
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth

# --- CLOUDINARY INTEGRATION ---
import cloudinary
import cloudinary.uploader

cloudinary.config( 
    cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'), 
    api_key = os.environ.get('CLOUDINARY_API_KEY'), 
    api_secret = os.environ.get('CLOUDINARY_API_SECRET') 
)

# CREATE THE APP
app = Flask(__name__)

# Proxy fix for Render HTTPS compatibility
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

app.config.from_object(Config)
app.secret_key = 'super_secret_key_for_session'
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Retained upload folder config as a fallback mechanism
UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'docx', 'psd', 'ai'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024 

def get_db_connection():
    return mysql.connector.connect(
        host=app.config['MYSQL_HOST'],
        user=app.config['MYSQL_USER'],
        password=app.config['MYSQL_PASSWORD'],
        database=app.config['MYSQL_DB'],
        port=app.config.get('MYSQL_PORT', 27072),
        connection_timeout=5  
    )

# --- SOCIAL AUTH SETUP ---
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id='370896002580-hqntv6uk4teq3isr8iappbkbfkh0rl85.apps.googleusercontent.com',
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    access_token_url='https://accounts.google.com/o/oauth2/token',
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    api_base_url='https://www.googleapis.com/oauth2/v1/',
    userinfo_endpoint='https://openidconnect.googleapis.com/v1/userinfo',
    client_kwargs={'scope': 'email profile'},
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration'
)

facebook = oauth.register(
    name='facebook',
    client_id='1869215153960592',
    client_secret=os.environ.get('FB_CLIENT_SECRET'),
    access_token_url='https://graph.facebook.com/oauth/access_token',
    authorize_url='https://www.facebook.com/dialog/oauth',
    api_base_url='https://graph.facebook.com/',
    client_kwargs={'scope': 'email public_profile'},
)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def social_auth_logic(email, name, provider):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
    user = cursor.fetchone()
    
    if user:
        session['loggedin'] = True
        session['user_id'] = user[0]
        session['name'] = user[2] 
        session['role'] = user[6] if len(user) > 6 else 'customer'
        flash(f"Logged in with {provider.title()}!", "success")
    else:
        assigned_role = 'admin' if email == 'system.printsmart@gmail.com' else 'customer'
        random_pw = secrets.token_hex(16)
        hashed_password = generate_password_hash(random_pw)
        
        cursor.execute("INSERT INTO users (full_name, email, password_hash, role) VALUES (%s, %s, %s, %s)", 
                       (name, email, hashed_password, assigned_role))
        conn.commit()
        
        session['loggedin'] = True
        session['user_id'] = cursor.lastrowid
        session['name'] = name
        session['role'] = assigned_role
        flash(f"Account created via {provider.title()}!", "success")

    cursor.close()
    conn.close()
    return redirect('/admin') if session['role'] == 'admin' else redirect(url_for('home'))

@app.context_processor
def inject_cart_count():
    if 'user_id' in session:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(quantity) FROM cart WHERE user_id = %s", (session['user_id'],))
            result = cursor.fetchone()
            count = int(result[0]) if result and result[0] else 0
            cursor.close()
            conn.close()
            return {'cart_count': count}
        except:
            return {'cart_count': 0}
    return {'cart_count': 0}

# --- ROUTES ---

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/login/google')
def google_login():
    redirect_uri = url_for('google_authorize', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/authorize/google')
def google_authorize():
    try:
        token = google.authorize_access_token()
        user_info = google.get('https://www.googleapis.com/oauth2/v3/userinfo').json()
        return social_auth_logic(user_info['email'], user_info['name'], 'google')
    except Exception as e:
        flash("Google Login Failed.", "error")
        return redirect(url_for('login'))

@app.route('/login/facebook')
def facebook_login():
    redirect_uri = url_for('facebook_authorize', _external=True)
    return facebook.authorize_redirect(redirect_uri)

@app.route('/authorize/facebook')
def facebook_authorize():
    try:
        token = facebook.authorize_access_token()
        user_info = facebook.get('me?fields=id,name,email').json()
        return social_auth_logic(user_info.get('email'), user_info.get('name'), 'facebook')
    except Exception as e:
        flash("Facebook Login Failed.", "error")
        return redirect(url_for('login'))

@app.route('/services')
def services():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True) 
        cursor.execute("SELECT * FROM categories ORDER BY category_id")
        categories = cursor.fetchall()
        cursor.execute("""
            SELECT p.*, c.slug as category_slug 
            FROM products p 
            JOIN categories c ON p.category_id = c.category_id
            ORDER BY p.product_id
        """)
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

# --- SMART CART LOGIC ---
@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    user_id = session.get('user_id', 1)
    try:
        product_id = int(request.form.get('product_id'))
        qty = int(request.form.get('quantity', 1))
        
        file_paths = []
        if 'design_file' in request.files:
            files = request.files.getlist('design_file')
            for file in files:
                if file and file.filename != '':
                    upload_result = cloudinary.uploader.upload(file, folder="customer_designs")
                    file_paths.append(upload_result['secure_url'])
        
        file_path_str = ",".join(file_paths) if file_paths else None

        unit_price = float(request.form.get('dynamic_unit_price', 0))
        variant_name = request.form.get('dynamic_variant_name', '')
        
        has_layout = request.form.get('has_layout') == 'on'
        design_instructions = request.form.get('instructions', '').strip()
        special_instructions = request.form.get('order_note', '').strip()

        details_list = []
        layout_fee = 0
        item_total = 0

        # Build physical specs
        if product_id == 1: 
            h = float(request.form.get('height_ft', 0))
            w = float(request.form.get('width_ft', 0))
            details_list.append(f"Material: {variant_name}")
            details_list.append(f"Size: {h}x{w} ft")
            item_total = ((h * w * unit_price) * qty)
        elif product_id == 2: 
            details_list.append(f"Variant: {variant_name}")
            add_stand = 150 if request.form.get('sintra_stand') else 0
            if add_stand: details_list.append("Add-on: Box Type/Stand (+150)")
            item_total = ((unit_price + add_stand) * qty)
        elif product_id == 3: 
            mode = request.form.get('size_mode')
            details_list.append(f"{'Sheet' if mode == 'sheet' else 'Custom'}: {variant_name}")
            pre_cut = 50 if request.form.get('pre_cut') else 0
            if pre_cut: details_list.append("Pre-cut Service")
            layout_fee = 300 if has_layout else 0
            item_total = ((unit_price + pre_cut) * qty)
        elif product_id == 4: 
            details_list.append(f"Type: {variant_name}")
            item_total = (unit_price * qty)
        elif product_id == 5: 
            details_list.append(f"Size: {variant_name}")
            item_total = (unit_price * qty)
        elif product_id == 6: 
            details_list.append(f"Package: {variant_name}")
            enhance = 50 if request.form.get('extra_enhance') else 0
            softcopy = 20 if request.form.get('extra_softcopy') else 0
            if enhance: details_list.append("Enhance (+50)")
            if softcopy: details_list.append("Softcopy (+20)")
            item_total = ((unit_price + enhance + softcopy) * qty)
        elif product_id == 7: 
            service_type = request.form.get('shirt_service_type')
            if service_type == 'Supply':
                color = request.form.get('shirt_color')
                details_list.append(f"Supply: {variant_name} | Color: {color}")
            else:
                details_list.append(f"Print Only: {variant_name}")
            item_total = (unit_price * qty)

        if has_layout and product_id != 3:
            layout_fee = 150
            
        item_total += layout_fee

        base_specs = " | ".join(details_list)
        final_details = base_specs
        if design_instructions: final_details += f" || DESIGN: {design_instructions}"
        if special_instructions: final_details += f" || NOTE: {special_instructions}"
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO cart (user_id, product_id, quantity, total_price, item_details, file_path)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, product_id, qty, item_total, final_details, file_path_str))
        conn.commit()
        cursor.close()
        conn.close()

        flash('Successfully added to your Printagram cart!', 'success')
        if request.form.get('action') == 'buy_now':
            return redirect('/checkout')
        else:
            return redirect(request.referrer or url_for('services'))
            
    except Exception as e:
        flash(f"Error: {e}", 'error')
        return redirect(request.referrer or url_for('services'))

@app.route('/update_cart_item', methods=['POST'])
def update_cart_item():
    user_id = session.get('user_id', 1)
    cart_id = request.form.get('cart_id')
    
    try:
        new_qty = int(request.form.get('quantity', 1))
        if new_qty < 1: new_qty = 1 

        base_specs = request.form.get('base_specs', '')
        design_note = request.form.get('design_note', '').strip()
        special_note = request.form.get('special_note', '').strip()

        final_details = base_specs
        if design_note: final_details += f" || DESIGN: {design_note}"
        if special_note: final_details += f" || NOTE: {special_note}"

        file_paths = []
        if 'design_file' in request.files:
            files = request.files.getlist('design_file')
            for f in files:
                if f and f.filename != '':
                    res = cloudinary.uploader.upload(f, folder="customer_designs")
                    file_paths.append(res['secure_url'])

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT quantity, total_price, file_path FROM cart WHERE cart_id = %s AND user_id = %s", (cart_id, user_id))
        item = cursor.fetchone()

        if item:
            unit_price = float(item['total_price']) / int(item['quantity'])
            new_total = unit_price * new_qty
            final_file_path = ",".join(file_paths) if file_paths else item['file_path']

            cursor.execute("""
                UPDATE cart 
                SET quantity = %s, total_price = %s, item_details = %s, file_path = %s
                WHERE cart_id = %s AND user_id = %s
            """, (new_qty, new_total, final_details, final_file_path, cart_id, user_id))
            conn.commit()
            flash("Item details updated successfully!", "success")
            
        conn.close()
    except Exception as e:
        flash(f"Error updating item: {e}", "error")

    return redirect('/checkout')

@app.route('/remove_from_cart/<int:cart_id>')
def remove_from_cart(cart_id):
    user_id = session.get('user_id', 1)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM cart WHERE cart_id = %s AND user_id = %s", (cart_id, user_id))
        conn.commit()
        conn.close()
        flash("Item removed from cart.", "success")
    except Exception as e:
        print(f"Error removing item: {e}")
    return redirect('/checkout')

# --- NEW: BULK REMOVE ROUTE ---
@app.route('/bulk_remove_from_cart', methods=['POST'])
def bulk_remove_from_cart():
    user_id = session.get('user_id', 1)
    cart_ids = request.form.getlist('cart_ids')
    
    if not cart_ids:
        flash("No items were selected for deletion.", "error")
        return redirect('/checkout')
        
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Dynamically build the SQL IN clause depending on how many items are selected
        format_strings = ','.join(['%s'] * len(cart_ids))
        query = f"DELETE FROM cart WHERE cart_id IN ({format_strings}) AND user_id = %s"
        
        # Tuple containing all selected cart IDs plus the user ID at the end
        params = tuple(cart_ids) + (user_id,)
        
        cursor.execute(query, params)
        conn.commit()
        conn.close()
        
        flash(f"Successfully deleted {len(cart_ids)} selected items.", "success")
    except Exception as e:
        print(f"Error bulk removing items: {e}")
        flash("Error removing selected items.", "error")
        
    return redirect('/checkout')

@app.route('/checkout')
def checkout():
    user_id = session.get('user_id', 1)
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT c.*, p.name as product_name, p.image_path 
            FROM cart c
            JOIN products p ON c.product_id = p.product_id
            WHERE c.user_id = %s
        """
        cursor.execute(query, (user_id,))
        cart_items = cursor.fetchall()
        
        subtotal = 0.0
        for item in cart_items:
            subtotal += float(item['total_price'])
            item['file_list'] = item['file_path'].split(',') if item['file_path'] else []
            
            parts = item['item_details'].split(' || ')
            item['specs'] = parts[0]
            item['design_note'] = ''
            item['special_note'] = ''
            
            for p in parts[1:]:
                if p.startswith('DESIGN: '):
                    item['design_note'] = p.replace('DESIGN: ', '', 1)
                elif p.startswith('NOTE: '):
                    item['special_note'] = p.replace('NOTE: ', '', 1)

        processing_fee = 50.00 if cart_items else 0.00
        grand_total = subtotal + processing_fee
        conn.close()
        return render_template('checkout.html', cart_items=cart_items, subtotal=subtotal, processing_fee=processing_fee, grand_total=grand_total)
    except Exception as e:
        return f"Checkout Error: {e}"

@app.route('/place_order', methods=['POST'])
def place_order():
    if not session.get('loggedin'):
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    payment_method = request.form.get('payment_method')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM cart WHERE user_id = %s", (user_id,))
        cart_items = cursor.fetchall()
        
        if not cart_items: 
            conn.close()
            return "Cart is empty!"

        total_amount = float(request.form.get('grand_total'))
        
        cursor.execute("INSERT INTO orders (user_id, total_amount, payment_status, payment_method, order_status, created_at) VALUES (%s, %s, 'Paid', %s, 'Pending', NOW())", (user_id, total_amount, payment_method))
        conn.commit() 
        new_order_id = cursor.lastrowid

        for item in cart_items:
            safe_file_path = item['file_path'] if item['file_path'] else ""
            cursor.execute("""
                INSERT INTO order_items (order_id, product_id, quantity, price_at_time, item_details, file_path) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (new_order_id, item['product_id'], item['quantity'], item['total_price'], item['item_details'], safe_file_path))
            
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        conn.commit()
        conn.close()
        return render_template('order_success.html', order_id=new_order_id)
    except Exception as e:
        return f"Order Error: {e}"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user['password_hash'], password):
            session['loggedin'] = True
            session['user_id'] = user['user_id']
            session['name'] = user['full_name']
            session['role'] = user.get('role', 'customer')

            flash("Logged in successfully!", "success")
            return redirect('/admin') if session['role'] == 'admin' else redirect(url_for('home'))
        else:
            flash("Incorrect email or password.", "error")
            return redirect(url_for('login'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        # 1. Full Name Validation (Letters and spaces only, min 2 chars)
        if not name or not re.match(r'^[A-Za-z\s]{2,}$', name):
            flash("Invalid name. Please use only letters (minimum 2 characters).", "error")
            return redirect(url_for('register'))

        # 2. Phone Validation (10 to 15 digits, allows optional + for international)
        if not phone or not re.match(r'^\+?[0-9]{10,15}$', phone):
            flash("Invalid phone number. Please enter 10 to 15 digits without spaces or letters.", "error")
            return redirect(url_for('register'))

        # 3. Email Structure Validation
        if not email or not re.match(r'^[\w\.-]+@[\w\.-]+\.\w{2,}$', email):
            flash("Invalid email format.", "error")
            return redirect(url_for('register'))

        if password != confirm_password:
            flash("Passwords do not match!", "error")
            return redirect(url_for('register'))

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            conn.close()
            # QA FIX: Redirect to login with specific instruction message
            flash("This email address is already linked to an existing account. Please sign in instead.", "error")
            return redirect(url_for('login'))

        hashed_password = generate_password_hash(password)
        try:
            cursor.execute("INSERT INTO users (full_name, email, phone_number, password_hash, role) VALUES (%s, %s, %s, %s, 'customer')", 
                           (name, email, phone, hashed_password))
            conn.commit()
            conn.close()
            flash("Account created successfully! You can now login.", "success")
            return redirect(url_for('login'))
        except Exception as e:
            conn.close()
            flash(f"An error occurred: {e}", "error")
            return redirect(url_for('register'))
            
    return render_template('register.html')

# --- Add this placeholder route for the Forgot Password button ---
@app.route('/forgot_password')
def forgot_password():
    flash("Password reset instructions have been sent to your email. (Feature in development)", "success")
    return redirect(url_for('login'))

# --- ADMIN AND PROFILE MANAGEMENT ---
@app.route('/admin')
def admin_dashboard():
    if 'role' not in session or session['role'] != 'admin':
        return "ACCESS DENIED"
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT COUNT(*) as count FROM orders")
        res_orders = cursor.fetchone()
        total_orders = res_orders['count'] if res_orders else 0
        
        cursor.execute("SELECT SUM(total_amount) as revenue FROM orders")
        res_rev = cursor.fetchone()
        total_revenue = res_rev['revenue'] if res_rev and res_rev['revenue'] else 0
        
        cursor.execute("SELECT * FROM products")
        products = cursor.fetchall() or [] 
        
        cursor.execute("SELECT * FROM product_variants")
        list_of_variants = cursor.fetchall() or []

        cursor.execute("""
            SELECT o.*, u.full_name FROM orders o
            JOIN users u ON o.user_id = u.user_id
            ORDER BY o.created_at DESC
        """)
        orders = cursor.fetchall() or []

        for order in orders:
            cursor.execute("""
                SELECT oi.*, p.name as product_name FROM order_items oi
                JOIN products p ON oi.product_id = p.product_id
                WHERE oi.order_id = %s
            """, (order['order_id'],))
            order['safe_items'] = cursor.fetchall() or []

        cursor.execute("SELECT * FROM users WHERE role = 'customer' ORDER BY user_id DESC")
        customers = cursor.fetchall() or []
        conn.close() 

        variants_map = {}
        for v in list_of_variants: 
            pid = v['product_id']
            if pid not in variants_map: variants_map[pid] = []
            variants_map[pid].append(v)

        return render_template('admin.html', total_orders=total_orders, total_revenue=total_revenue, 
                               products=products, variants_map=variants_map, orders=orders, customers=customers)
    except Exception as e:
        return f"DB Error: {e}"

@app.route('/admin/update_order_status', methods=['POST'])
def update_order_status():
    if 'role' not in session or session['role'] != 'admin': return redirect('/login')
    order_id = request.form.get('order_id')
    new_status = request.form.get('status')
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET order_status = %s WHERE order_id = %s", (new_status, order_id))
        conn.commit()
        conn.close()
        flash(f"Order #{order_id} updated to {new_status}", "success")
    except Exception as e:
        flash(f"Error updating status: {e}", "error")
    return redirect('/admin')

@app.route('/admin/upload_product_image', methods=['POST'])
def upload_product_image():
    if 'role' not in session or session['role'] != 'admin':
        return redirect('/login')

    product_id = request.form.get('product_id')
    file = request.files.get('product_image')

    if file:
        try:
            upload_result = cloudinary.uploader.upload(file)
            image_url = upload_result['secure_url']

            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE products SET image_path = %s WHERE product_id = %s", 
                           (image_url, product_id))
            conn.commit()
            conn.close()
            flash("Cloud image updated successfully!", "success")
        except Exception as e:
            flash(f"Cloudinary Error: {e}", "error")

    return redirect('/admin')

@app.route('/admin/update_variant', methods=['POST'])
def update_variant():
    if 'role' not in session or session['role'] != 'admin':
        return redirect('/login')

    variant_id = request.form.get('variant_id')
    new_price = request.form.get('price')
    new_stock = request.form.get('stock')

    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE product_variants SET price = %s, stock_quantity = %s WHERE variant_id = %s", 
                       (new_price, new_stock, variant_id))
        conn.commit()
        conn.close()
        flash("Price and Stock updated!", "success")
    except Exception as e:
        flash(f"Database Error: {e}", "error")

    return redirect('/admin')

@app.route('/profile', methods=['GET', 'POST'])
def profile():
    if not session.get('loggedin'): return redirect(url_for('login'))
    user_id = session['user_id']
    if request.method == 'POST':
        action = request.form.get('action')
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            if action == 'update_info':
                cursor.execute("UPDATE users SET full_name = %s, email = %s, phone_number = %s WHERE user_id = %s", 
                               (request.form.get('name'), request.form.get('email'), request.form.get('phone'), user_id))
                session['name'] = request.form.get('name')
                flash("Profile details updated!", "success")
            elif action == 'change_password':
                cursor.execute("SELECT password_hash FROM users WHERE user_id = %s", (user_id,))
                user_data = cursor.fetchone()
                if user_data and check_password_hash(user_data[0], request.form.get('current_password')):
                    cursor.execute("UPDATE users SET password_hash = %s WHERE user_id = %s", 
                                   (generate_password_hash(request.form.get('new_password')), user_id))
                    flash("Password changed successfully!", "success")
                else:
                    flash("Incorrect current password.", "error")
            conn.commit()
        except Exception as e:
            flash(f"Error: {e}", "error")
        finally:
            conn.close()
        return redirect(url_for('profile'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    user = cursor.fetchone()
    cursor.execute("SELECT * FROM orders WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
    my_orders = cursor.fetchall()
    for order in my_orders:
        cursor.execute("""
            SELECT oi.*, p.name as product_name FROM order_items oi
            JOIN products p ON oi.product_id = p.product_id
            WHERE oi.order_id = %s
        """, (order['order_id'],))
        order['safe_items'] = cursor.fetchall()
    conn.close()
    return render_template('profile.html', user=user, orders=my_orders)

@app.route('/my_orders')
def my_orders():
    if not session.get('loggedin'): return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM orders WHERE user_id = %s ORDER BY created_at DESC", (session['user_id'],))
    orders = cursor.fetchall()
    conn.close()
    return render_template('my_orders.html', orders=orders)

@app.route('/my_order_details/<int:order_id>')
def my_order_details(order_id):
    if not session.get('loggedin'): return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM orders WHERE order_id = %s AND user_id = %s", (order_id, session['user_id']))
    order = cursor.fetchone()
    if not order:
        conn.close()
        return "Order not found."
    cursor.execute("""
        SELECT oi.*, p.name as product_name, p.image_path FROM order_items oi
        JOIN products p ON oi.product_id = p.product_id
        WHERE oi.order_id = %s
    """, (order_id,))
    order_items = cursor.fetchall()
    conn.close()
    return render_template('order_details.html', order=order, items=order_items)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)