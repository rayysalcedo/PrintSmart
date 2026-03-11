import os
import secrets
import re
import random
import requests
from datetime import datetime, timedelta
from itsdangerous import URLSafeTimedSerializer
from flask import Flask, render_template, request, session, redirect, url_for, flash, make_response, jsonify
from dotenv import load_dotenv
import mysql.connector 
from config import Config
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from authlib.integrations.flask_client import OAuth
import cloudinary
import cloudinary.uploader
import base64

# 1. LOAD THE SECRETS
load_dotenv()

# --- CLOUDINARY INTEGRATION ---
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

# Security and Sessions
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_key_for_session')
s = URLSafeTimedSerializer(app.secret_key)
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

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

# --- BREVO EMAIL API HELPER ---
def send_system_email(to_email, subject, body_text):
    api_key = os.environ.get('BREVO_API_KEY')
    if not api_key:
        print("ERROR: BREVO_API_KEY is missing from environment variables!")
        return False
    sender_email = "system.printsmart@gmail.com" 
    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"name": "PrintSmart Security", "email": sender_email},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": body_text
    }
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json"
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code not in [200, 201, 202]:
            print(f"BREVO API ERROR {response.status_code}: {response.text}")
        return response.status_code in [200, 201, 202]
    except Exception as e:
        print(f"REQUEST CRASHED: {e}")
        return False

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
        cursor.execute("INSERT INTO users (full_name, email, password_hash, role, is_active) VALUES (%s, %s, %s, %s, TRUE)", 
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

        cursor.execute("SELECT product_id, MIN(price) as min_price FROM product_variants GROUP BY product_id")
        min_prices_db = cursor.fetchall()
        min_price_map = {row['product_id']: row['min_price'] for row in min_prices_db}

        cursor.close()
        conn.close()

        features_map = {}
        for f in all_features:
            pid = f['product_id']
            if pid not in features_map: features_map[pid] = []
            features_map[pid].append(f['feature_text'])

        for p in products:
            p['starting_price'] = min_price_map.get(p['product_id'], 0.00)

        return render_template('services.html', categories=categories, products=products, features_map=features_map)
    except Exception as e:
        return f"Error fetching data: {e}"

@app.route('/order/<int:product_id>')
def order(product_id=None):
    product = None
    variants = [] 
    gallery = []
    reviews = []
    avg_rating = 0
    total_reviews = 0
    can_review = False

    if product_id:
        try:
            conn = get_db_connection()
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM products WHERE product_id = %s", (product_id,))
            product = cursor.fetchone()
            
            cursor.execute("SELECT * FROM product_variants WHERE product_id = %s", (product_id,))
            variants = cursor.fetchall()

            cursor.execute("SELECT image_url FROM product_images WHERE product_id = %s", (product_id,))
            gallery_rows = cursor.fetchall()
            gallery = [row['image_url'] for row in gallery_rows]

            cursor.execute("""
                SELECT r.*, u.full_name 
                FROM product_reviews r
                JOIN users u ON r.user_id = u.user_id
                WHERE r.product_id = %s
                ORDER BY r.created_at DESC
            """, (product_id,))
            reviews = cursor.fetchall()
            
            total_reviews = len(reviews)
            if total_reviews > 0:
                avg_rating = round(sum(r['rating'] for r in reviews) / total_reviews, 1)
            else:
                avg_rating = 0.0 

            if session.get('loggedin'):
                user_id = session['user_id']
                cursor.execute("""
                    SELECT COUNT(*) as count 
                    FROM orders o
                    JOIN order_items oi ON o.order_id = oi.order_id
                    WHERE o.user_id = %s AND oi.product_id = %s AND o.order_status = 'Completed'
                """, (user_id, product_id))
                has_completed_order = cursor.fetchone()['count'] > 0
                
                cursor.execute("SELECT COUNT(*) as count FROM product_reviews WHERE user_id = %s AND product_id = %s", (user_id, product_id))
                already_reviewed = cursor.fetchone()['count'] > 0

                if has_completed_order and not already_reviewed:
                    can_review = True

            cursor.close()
            conn.close()
        except Exception as e:
            print(f"Error fetching product data: {e}")
            
    return render_template('order.html', product=product, variants=variants, gallery=gallery, 
                           reviews=reviews, avg_rating=avg_rating, total_reviews=total_reviews, can_review=can_review)

# --- SUBMIT REVIEW SECURE ROUTE (UPDATED) ---
@app.route('/submit_review', methods=['POST'])
def submit_review():
    if not session.get('loggedin'):
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    product_id = request.form.get('product_id')
    rating = request.form.get('rating')
    comment = request.form.get('comment')
    source_order_id = request.form.get('source_order_id') # NEW: Knows where the request came from
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT COUNT(*) as count FROM orders o
            JOIN order_items oi ON o.order_id = oi.order_id
            WHERE o.user_id = %s AND oi.product_id = %s AND o.order_status = 'Completed'
        """, (user_id, product_id))
        
        if cursor.fetchone()['count'] > 0:
            cursor.execute("INSERT INTO product_reviews (product_id, user_id, rating, comment) VALUES (%s, %s, %s, %s)", 
                           (product_id, user_id, rating, comment))
            conn.commit()
            flash("Thank you! Your review has been posted.", "success")
        else:
            flash("Action denied. You must receive your order before reviewing.", "error")
            
        conn.close()
    except Exception as e:
        print(f"Review Error: {e}")
        
    # Smart Redirect: Send them back to wherever they submitted the review from!
    if source_order_id:
        return redirect(url_for('my_order_details', order_id=source_order_id))
    return redirect(url_for('order', product_id=product_id))

# --- SMART CART LOGIC (FIXED) ---
@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    if not session.get('loggedin'):
        flash("Please sign in or create an account to start adding items to your cart!", "error")
        return redirect(url_for('login'))
        
    user_id = session.get('user_id')
    
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
        format_strings = ','.join(['%s'] * len(cart_ids))
        query = f"DELETE FROM cart WHERE cart_id IN ({format_strings}) AND user_id = %s"
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
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM cart WHERE user_id = %s", (user_id,))
        cart_items = cursor.fetchall()
        
        if not cart_items: 
            conn.close()
            return "Cart is empty!"

        total_amount = float(request.form.get('grand_total'))
        
        # 1. Create the order in the DB as 'Pending'
        cursor.execute("INSERT INTO orders (user_id, total_amount, payment_status, payment_method, order_status, created_at) VALUES (%s, %s, 'Pending', 'PayMongo', 'Pending', NOW())", (user_id, total_amount))
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

        # 2. GENERATE PAYMONGO CHECKOUT LINK
        paymongo_key = os.environ.get('PAYMONGO_SECRET_KEY')
        
        # Failsafe: If no API key is set, bypass to success (so your app doesn't break if env vars are missing)
        if not paymongo_key:
            return redirect(url_for('payment_success', order_id=new_order_id))

        # PayMongo expects amounts in cents (e.g., Php 100.00 = 10000 cents)
        amount_in_cents = int(total_amount * 100)

        url = "https://api.paymongo.com/v1/checkout_sessions"
        payload = {
            "data": {
                "attributes": {
                    "billing": {"name": session.get('name', 'Printagram Customer')},
                    "send_email_receipt": False,
                    "show_description": True,
                    "show_line_items": True,
                    "line_items": [{
                        "currency": "PHP",
                        "amount": amount_in_cents,
                        "name": f"Printagram Order #{new_order_id}",
                        "quantity": 1
                    }],
                    "payment_method_types": ["card", "gcash", "paymaya"],
                    "success_url": url_for('payment_success', order_id=new_order_id, _external=True),
                    "cancel_url": url_for('checkout', _external=True),
                    "description": "Professional Printing Services"
                }
            }
        }
        
        # PayMongo uses Basic Auth. We encode the secret key to Base64.
        auth_str = f"{paymongo_key}:"
        b64_auth = base64.b64encode(auth_str.encode()).decode()
        
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "authorization": f"Basic {b64_auth}"
        }

        response = requests.post(url, json=payload, headers=headers)
        api_data = response.json()

        if response.status_code == 200:
            # 3. Redirect the user to the official PayMongo Hosted Checkout Page!
            checkout_url = api_data['data']['attributes']['checkout_url']
            return redirect(checkout_url)
        else:
            flash(f"Payment API Error. Please try again.", "error")
            print(f"PAYMONGO ERROR: {api_data}")
            return redirect('/checkout')

    except Exception as e:
        return f"Order Error: {e}"
    
# --- NEW: PAYMENT SUCCESS CALLBACK ROUTE ---
@app.route('/payment_success/<int:order_id>')
def payment_success(order_id):
    if not session.get('loggedin'):
        return redirect(url_for('login'))
        
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Update the order status to Paid!
        cursor.execute("UPDATE orders SET payment_status = 'Paid' WHERE order_id = %s AND user_id = %s", (order_id, session['user_id']))
        conn.commit()
        conn.close()
        
        return render_template('order_success.html', order_id=order_id)
    except Exception as e:
        return f"Error finalizing payment: {e}"
    
# --- AUTHENTICATION & OTP ---

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        phone = request.form.get('phone', '').strip()
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')

        if not name or not re.match(r'^[A-Za-z\s]{2,}$', name):
            flash("Invalid name. Please use only letters.", "error")
            return redirect(url_for('register'))
        if not phone or not re.match(r'^\+?[0-9]{10,15}$', phone):
            flash("Invalid phone number.", "error")
            return redirect(url_for('register'))
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
            flash("This email address is already linked to an existing account. Please sign in instead.", "error")
            return redirect(url_for('login'))

        hashed_password = generate_password_hash(password)
        try:
            otp = str(random.randint(100000, 999999))
            expiry = datetime.now() + timedelta(minutes=10)
            cursor.execute("""
                INSERT INTO users (full_name, email, phone_number, password_hash, role, is_active, otp_code, otp_expiry) 
                VALUES (%s, %s, %s, %s, 'customer', FALSE, %s, %s)
            """, (name, email, phone, hashed_password, otp, expiry))
            conn.commit()
            conn.close()

            msg_body = f"Hello {name},\n\nWelcome to Printagram!\n\nYour 6-digit verification code is: {otp}\n\nThis code will expire in 10 minutes."
            success = send_system_email(email, 'Your PrintSmart Verification Code', msg_body)
            if not success:
                print(f"YOUR OTP IS: {otp}")
            
            session['verify_email'] = email
            return redirect(url_for('verify_otp'))
        except Exception as e:
            conn.close()
            flash(f"An error occurred: {e}", "error")
            return redirect(url_for('register'))
    return render_template('register.html')

@app.route('/verify_otp', methods=['GET', 'POST'])
def verify_otp():
    email = session.get('verify_email')
    if not email:
        return redirect(url_for('login'))

    if request.method == 'POST':
        user_otp = request.form.get('otp')
        remember_device = request.form.get('remember_device')
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()

        if user:
            if user['otp_code'] == user_otp:
                if datetime.now() <= user['otp_expiry']:
                    cursor.execute("UPDATE users SET is_active = TRUE, otp_code = NULL, otp_expiry = NULL WHERE email = %s", (email,))
                    conn.commit()
                    
                    session['loggedin'] = True
                    session['user_id'] = user['user_id']
                    session['name'] = user['full_name']
                    session['role'] = user['role']
                    session.pop('verify_email', None)
                    
                    redirect_target = '/admin' if user['role'] == 'admin' else url_for('home')
                    resp = make_response(redirect(redirect_target))
                    
                    if remember_device == 'on':
                        device_token = s.dumps(email, salt='trusted-device-salt')
                        resp.set_cookie('trusted_device', device_token, max_age=30*24*60*60)
                        flash("Verified! We will remember this device for 30 days.", "success")
                    else:
                        flash("Verified and logged in securely!", "success")
                        
                    conn.close()
                    return resp
                else:
                    flash("This OTP has expired. Please log in again to get a new one.", "error")
            else:
                flash("Invalid OTP code. Please try again.", "error")
        conn.close()
    return render_template('verify_otp.html', email=email)

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
            trusted_cookie = request.cookies.get('trusted_device')
            is_trusted = False
            
            if trusted_cookie:
                try:
                    cookie_email = s.loads(trusted_cookie, salt='trusted-device-salt', max_age=30*24*60*60)
                    if cookie_email == user['email']:
                        is_trusted = True
                except Exception:
                    pass 

            if not is_trusted or not user.get('is_active'):
                otp = str(random.randint(100000, 999999))
                expiry = datetime.now() + timedelta(minutes=10)
                
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute("UPDATE users SET otp_code = %s, otp_expiry = %s WHERE email = %s", (otp, expiry, email))
                conn.commit()
                conn.close()

                msg_body = f"Hello {user['full_name']},\n\nYour login security code is: {otp}\n\nThis code will expire in 10 minutes."
                success = send_system_email(email, 'Your PrintSmart Security Code', msg_body)
                if not success:
                    print(f"NEW OTP: {otp}")

                session['verify_email'] = email
                return redirect(url_for('verify_otp'))

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
    resp = make_response(redirect(url_for('login')))
    resp.set_cookie('trusted_device', '', expires=0) 
    flash("You have been logged out securely.", "success")
    return resp

@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        conn.close()

        if user:
            token = s.dumps(email, salt='password-reset-salt')
            reset_url = url_for('reset_password', token=token, _external=True)
            msg_body = f"Hello {user['full_name']},\n\nClick the link below to securely reset your Printagram password:\n{reset_url}\n\nIf you did not request this, please ignore this email. This link will expire in 1 hour."
            success = send_system_email(email, 'Password Reset Request - PrintSmart', msg_body)
            
            if success:
                flash("A password reset link has been sent to your email.", "success")
            else:
                flash(f"System Email is disabled. Testing Link Generated: {reset_url}", "success")
                print(f"YOUR RESET LINK: {reset_url}")
        else:
            flash("If that email exists in our system, a reset link has been sent.", "success")
        return redirect(url_for('login'))
    return render_template('forgot_password.html')

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    try:
        email = s.loads(token, salt='password-reset-salt', max_age=3600)
    except Exception:
        flash("The reset link is invalid or has expired.", "error")
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return redirect(url_for('reset_password', token=token))
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT password_hash FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()

        if user and check_password_hash(user['password_hash'], password):
            conn.close()
            flash("Your new password cannot be the same as your current password.", "error")
            return redirect(url_for('reset_password', token=token))
        
        hashed_password = generate_password_hash(password)
        cursor.execute("UPDATE users SET password_hash = %s WHERE email = %s", (hashed_password, email))
        conn.commit()
        conn.close()
        
        flash("Your password has been successfully updated! You can now log in.", "success")
        return redirect(url_for('login'))
    return render_template('reset_password.html', token=token)

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
    files = request.files.getlist('product_images') 
    if files:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            for i, file in enumerate(files):
                if file and file.filename != '':
                    upload_result = cloudinary.uploader.upload(file)
                    image_url = upload_result['secure_url']
                    if i == 0:
                        cursor.execute("UPDATE products SET image_path = %s WHERE product_id = %s", (image_url, product_id))
                    cursor.execute("INSERT INTO product_images (product_id, image_url) VALUES (%s, %s)", (product_id, image_url))
            conn.commit()
            flash("Gallery images updated successfully!", "success")
        except Exception as e:
            flash(f"Upload Error: {e}", "error")
        finally:
            conn.close()
    return redirect('/admin')

@app.route('/admin/update_variant', methods=['POST'])
def update_variant():
    if 'role' not in session or session['role'] != 'admin': return redirect('/login')
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
        SELECT oi.*, p.name as product_name, p.image_path 
        FROM order_items oi
        JOIN products p ON oi.product_id = p.product_id
        WHERE oi.order_id = %s
    """, (order_id,))
    order_items = cursor.fetchall()
    
    # --- NEW LOGIC: Check if items are eligible for review ---
    if order['order_status'] == 'Completed':
        for item in order_items:
            cursor.execute("SELECT COUNT(*) as count FROM product_reviews WHERE user_id = %s AND product_id = %s", (session['user_id'], item['product_id']))
            already_reviewed = cursor.fetchone()['count'] > 0
            # They can review if they haven't already!
            item['can_review'] = not already_reviewed
    else:
        for item in order_items:
            item['can_review'] = False

    conn.close()
    return render_template('order_details.html', order=order, items=order_items)

# ==========================================
# --- LIVE CHAT API ROUTES ---
# ==========================================

@app.route('/api/get_messages')
def get_messages():
    if not session.get('loggedin'):
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401
    
    user_id = session['user_id']
    role = session.get('role', 'customer')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        if role == 'admin':
            other_user_id = request.args.get('user_id')
            if not other_user_id:
                return jsonify([])
                
            # THE FIX: Admin fetches ALL messages belonging to this specific customer's thread
            cursor.execute("""
                SELECT * FROM chat_messages 
                WHERE sender_id = %s OR receiver_id = %s
                ORDER BY created_at ASC
            """, (other_user_id, other_user_id))
        else:
            # THE FIX: Customer fetches ALL messages in their own thread
            cursor.execute("""
                SELECT * FROM chat_messages 
                WHERE sender_id = %s OR receiver_id = %s
                ORDER BY created_at ASC
            """, (user_id, user_id))
            
        messages = cursor.fetchall()
        conn.close()
        
        for msg in messages:
            msg['created_at'] = msg['created_at'].strftime('%b %d, %I:%M %p')
            # Identifies if the message bubble should be orange (mine) or grey (theirs)
            msg['is_mine'] = (msg['sender_id'] == user_id)
            
        return jsonify(messages)
    except Exception as e:
        print(f"Chat Fetch Error: {e}")
        return jsonify([])

@app.route('/api/send_message', methods=['POST'])
def send_message():
    if not session.get('loggedin'):
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401
        
    sender_id = session['user_id']
    role = session.get('role', 'customer')
    
    message_text = request.form.get('message_text', '').strip()
    attachment = request.files.get('attachment')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        if role == 'admin':
            receiver_id = request.form.get('receiver_id')
        else:
            # Ensures the customer always points to the primary admin account
            cursor.execute("SELECT user_id FROM users WHERE role = 'admin' ORDER BY user_id ASC LIMIT 1")
            admin_user = cursor.fetchone()
            receiver_id = admin_user['user_id'] if admin_user else 1
            
        if not message_text and not attachment:
            return jsonify({'status': 'error', 'message': 'Empty message'})
            
        attachment_url = None
        if attachment and attachment.filename != '':
            upload_result = cloudinary.uploader.upload(attachment, folder="chat_attachments")
            attachment_url = upload_result['secure_url']
            
        cursor.execute("""
            INSERT INTO chat_messages (sender_id, receiver_id, message_text, attachment_url)
            VALUES (%s, %s, %s, %s)
        """, (sender_id, receiver_id, message_text, attachment_url))
        conn.commit()
        conn.close()
        
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"Chat Send Error: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)