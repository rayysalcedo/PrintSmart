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
from threading import Timer

# 1. LOAD THE SECRETS
load_dotenv()

# QA FIX: ALLOW HTTP FOR LOCAL OAUTH TESTING
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

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
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'docx', 'psd', 'ai', 'zip', 'rar'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024 

def get_db_connection():
    db_password = os.environ.get('MYSQL_PASSWORD') or os.environ.get('DB_PASSWORD') or app.config.get('MYSQL_PASSWORD')
    
    return mysql.connector.connect(
        host=os.environ.get('MYSQL_HOST') or app.config.get('MYSQL_HOST'),
        user=os.environ.get('MYSQL_USER') or app.config.get('MYSQL_USER'),
        password=db_password,
        database=os.environ.get('MYSQL_DB') or app.config.get('MYSQL_DB'),
        port=int(os.environ.get('MYSQL_PORT') or app.config.get('MYSQL_PORT', 27072)),
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

# --- SOCIAL AUTH LOGIC ---
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
        # QA FIX: Added the new email to the official Super Admin list
        super_admins = ['system.printsmart@gmail.com', 'printagrambataan2019@gmail.com']
        assigned_role = 'super_admin' if email in super_admins else 'customer'
        
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
    return redirect('/admin') if session['role'] in ['admin', 'super_admin'] else redirect(url_for('home'))

# --- HTML ENHANCED EMAIL API HELPER ---
def send_system_email(to_email, subject, body_text, html_body=None):
    api_key = os.environ.get('BREVO_API_KEY')
    if not api_key:
        print("ERROR: BREVO_API_KEY is missing from environment variables!")
        return False
    sender_email = "system.printsmart@gmail.com" 
    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"name": "Printagram", "email": sender_email}, 
        "to": [{"email": to_email}],
        "subject": subject
    }
    
    if html_body:
        payload["htmlContent"] = html_body
        
    payload["textContent"] = body_text
        
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

# --- HTML FORMATTED BACKGROUND PAYMENT REMINDER ---
def delayed_payment_reminder(order_id, contact_name, email, total_amount, pay_url):
    try:
        print(f"Checking payment status for Order #{order_id}...")
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT payment_status FROM orders WHERE order_id = %s", (order_id,))
        order = cursor.fetchone()
        
        if order and order['payment_status'] == 'Pending':
            cursor.execute("""
                SELECT oi.*, p.name as product_name 
                FROM order_items oi 
                JOIN products p ON oi.product_id = p.product_id 
                WHERE oi.order_id = %s
            """, (order_id,))
            items = cursor.fetchall()
            
            subject = f"Action Required: Complete your Printagram Order #{order_id}"
            fallback_text = f"Hello {contact_name},\n\nWe noticed you haven't completed the payment for your order #{order_id}. Don't worry, your items are safely saved!\n\nPay here: {pay_url}"
            
            html_items = ""
            for item in items:
                clean_details = item['item_details'].replace(' || ', ' | ')
                html_items += f"<li style='margin-bottom: 10px;'><strong>{item['quantity']}x {item['product_name']}</strong> (₱{float(item['price_at_time']):,.2f})<br><span style='color:#666; font-size:12px;'>{clean_details}</span></li>"

            html_body = f"""
            <div style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 12px; overflow: hidden; background-color: #ffffff;">
                <div style="background: #dc3545; color: white; padding: 25px 20px; text-align: center;">
                    <h2 style="margin: 0; font-size: 24px; font-weight: 700;">Action Required</h2>
                    <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">Complete your Order #{order_id}</p>
                </div>
                <div style="padding: 30px 25px; color: #333;">
                    <p style="font-size: 16px; margin-top: 0;">Hello <strong>{contact_name}</strong>,</p>
                    <p style="font-size: 15px; line-height: 1.5;">We noticed you haven't completed the payment for your recent order. Don't worry, your items are safely saved!</p>
                    
                    <div style="background: #f9f9f9; padding: 20px; border-radius: 8px; margin: 25px 0; border: 1px solid #eee;">
                        <h3 style="margin: 0 0 15px 0; color: #333; font-size: 16px; border-bottom: 1px solid #ddd; padding-bottom: 10px;">Order Summary</h3>
                        <ul style="padding-left: 20px; margin: 0; font-size: 14px;">
                            {html_items}
                        </ul>
                        <div style="margin-top: 15px; padding-top: 15px; border-top: 1px dashed #ddd; font-size: 18px; font-weight: bold; color: #DC5500; text-align: right;">
                            Total Due: ₱{total_amount:,.2f}
                        </div>
                    </div>
                    
                    <div style="text-align: center; margin: 35px 0;">
                        <a href="{pay_url}" style="background: #28a745; color: white; text-decoration: none; padding: 14px 30px; border-radius: 8px; font-size: 16px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(0,0,0,0.1);">
                            💳 Pay Now
                        </a>
                    </div>
                    
                    <p style="font-size: 13px; color: #888; text-align: center; margin: 0; line-height: 1.5;">
                        If you accidentally closed the payment window, you can always use the link above to return and complete your purchase.
                    </p>
                </div>
            </div>
            """
            
            send_system_email(email, subject, fallback_text, html_body)
            print(f"Reminder HTML email successfully sent for Order #{order_id}")
            
        conn.close()
    except Exception as e:
        print(f"Background HTML Email Error: {e}")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS
    
@app.context_processor
def inject_cart_count():
    if 'user_id' in session:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM cart WHERE user_id = %s", (session['user_id'],))
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
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT product_id, MIN(price) as min_price FROM product_variants GROUP BY product_id")
        min_prices = {row['product_id']: row['min_price'] for row in cursor.fetchall()}
        conn.close()
        return render_template('home.html', prices=min_prices)
    except Exception as e:
        print(f"DB Error: {e}")
        return render_template('home.html', prices={})

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/privacy')
def privacy(): 
    return render_template('privacy.html')

@app.route('/terms')
def terms(): 
    return render_template('terms.html')

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
        print(f"GOOGLE CRASH: {str(e)}")
        flash(f"CRASH REPORT: {str(e)}", "error")
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
        print(f"FACEBOOK CRASH: {str(e)}")
        flash(f"CRASH REPORT: {str(e)}", "error")
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

            cursor.execute("SELECT image_url FROM product_images WHERE product_id = %s ORDER BY image_id ASC", (product_id,))
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

@app.route('/submit_review', methods=['POST'])
def submit_review():
    if not session.get('loggedin'):
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    product_id = request.form.get('product_id')
    rating = request.form.get('rating')
    comment = request.form.get('comment')
    source_order_id = request.form.get('source_order_id')
    
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
        
    if source_order_id:
        return redirect(url_for('my_order_details', order_id=source_order_id))
    return redirect(url_for('order', product_id=product_id))

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
                    upload_result = cloudinary.uploader.upload(file, folder="customer_designs", use_filename=True, unique_filename=True)
                    file_paths.append(upload_result['secure_url'])
        
        file_path_str = ",".join(file_paths) if file_paths else None

        item_total = float(request.form.get('calculated_total', 0))
        base_specs = request.form.get('item_specs', '')
        design_instructions = request.form.get('instructions', '').strip()
        special_instructions = request.form.get('order_note', '').strip()

        final_details = base_specs
        if design_instructions: 
            final_details += f" || DESIGN: {design_instructions}"
        if special_instructions: 
            final_details += f" || NOTE: {special_instructions}"
        
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO cart (user_id, product_id, quantity, total_price, item_details, file_path)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (user_id, product_id, qty, item_total, final_details, file_path_str))
        conn.commit()
        
        new_cart_id = cursor.lastrowid
        cursor.close()
        conn.close()

        if request.form.get('action') == 'buy_now': 
            return redirect(url_for('checkout', buy_now=new_cart_id))
        else: 
            flash('Successfully added to your Printagram cart!', 'success')
            return redirect(url_for('cart'))
            
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
                    res = cloudinary.uploader.upload(f, folder="customer_designs", use_filename=True, unique_filename=True)
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
    return redirect('/cart')

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
    return redirect('/cart')

@app.route('/bulk_remove_from_cart', methods=['POST'])
def bulk_remove_from_cart():
    user_id = session.get('user_id', 1)
    cart_ids = request.form.getlist('cart_ids')
    if not cart_ids:
        flash("No items were selected for deletion.", "error")
        return redirect('/cart')
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
    return redirect('/cart')

@app.route('/cart')
def cart():
    if not session.get('loggedin'):
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT c.*, p.name as product_name, 
                   COALESCE((SELECT image_url FROM product_images WHERE product_id = p.product_id ORDER BY image_id ASC LIMIT 1), p.image_path) as image_path 
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
        
        return render_template('cart.html', cart_items=cart_items, subtotal=subtotal, processing_fee=processing_fee, grand_total=grand_total)
    except Exception as e:
        return f"Cart Error: {e}"

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if not session.get('loggedin'):
        flash("Please log in to checkout.", "error")
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    buy_now_id = request.args.get('buy_now')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        selected_ids = []
        if request.method == 'POST':
            selected_ids = request.form.getlist('selected_cart_ids')
            
        if buy_now_id:
            query = """
                SELECT c.*, p.name as product_name, 
                       COALESCE((SELECT image_url FROM product_images WHERE product_id = p.product_id ORDER BY image_id ASC LIMIT 1), p.image_path) as image_path 
                FROM cart c
                JOIN products p ON c.product_id = p.product_id
                WHERE c.user_id = %s AND c.cart_id = %s
            """
            cursor.execute(query, (user_id, buy_now_id))
        elif selected_ids:
            format_strings = ','.join(['%s'] * len(selected_ids))
            query = f"""
                SELECT c.*, p.name as product_name, 
                       COALESCE((SELECT image_url FROM product_images WHERE product_id = p.product_id ORDER BY image_id ASC LIMIT 1), p.image_path) as image_path 
                FROM cart c
                JOIN products p ON c.product_id = p.product_id
                WHERE c.user_id = %s AND c.cart_id IN ({format_strings})
            """
            cursor.execute(query, tuple([user_id] + selected_ids))
        else:
            conn.close()
            flash("No items selected for checkout.", "error")
            return redirect('/cart')
            
        checkout_items = cursor.fetchall()
        
        if not checkout_items:
            conn.close()
            flash("No valid items found for checkout.", "error")
            return redirect('/cart')

        subtotal = 0.0
        for item in checkout_items:
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
        
        processing_fee = 50.00 if checkout_items else 0.00
        grand_total = subtotal + processing_fee
        
        cursor.execute("SELECT full_name, email, phone_number FROM users WHERE user_id = %s", (user_id,))
        user_info = cursor.fetchone()
        
        conn.close()
        
        return render_template('checkout.html', checkout_items=checkout_items, subtotal=subtotal, processing_fee=processing_fee, grand_total=grand_total, user_info=user_info)
        
    except Exception as e:
        return f"Checkout Error: {e}"

# --- QA FIX: REMOVED IMMEDIATE EMAIL SENDING ---
@app.route('/place_order', methods=['POST'])
def place_order():
    if not session.get('loggedin'):
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    selected_cart_ids = request.form.getlist('checkout_cart_ids')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        if not selected_cart_ids:
            cursor.execute("""
                SELECT c.*, p.name as product_name 
                FROM cart c 
                JOIN products p ON c.product_id = p.product_id 
                WHERE c.user_id = %s
            """, (user_id,))
        else:
            format_strings = ','.join(['%s'] * len(selected_cart_ids))
            query = f"""
                SELECT c.*, p.name as product_name 
                FROM cart c 
                JOIN products p ON c.product_id = p.product_id 
                WHERE c.user_id = %s AND c.cart_id IN ({format_strings})
            """
            cursor.execute(query, tuple([user_id] + selected_cart_ids))
            
        cart_items = cursor.fetchall()
        
        if not cart_items: 
            conn.close()
            flash("No valid items selected for checkout.", "error")
            return redirect('/cart')

        total_amount = float(request.form.get('grand_total'))
        delivery_method = request.form.get('delivery_method', 'Pickup') 
        contact_name = request.form.get('contact_name', '').strip()
        contact_email = request.form.get('contact_email', '').strip()
        contact_phone = request.form.get('contact_phone', '').strip()
        deadline = request.form.get('target_deadline', '').strip()
        
        try:
            deadline_dt = datetime.strptime(deadline, '%Y-%m-%d')
            deadline_str = deadline_dt.strftime('%B %d, %Y')
        except:
            deadline_str = deadline

        full_details = f"Contact: {contact_name}\nEmail: {contact_email}\nPhone: {contact_phone}\nTarget Deadline: {deadline_str}"
        
        if delivery_method == 'Delivery':
            street = request.form.get('addr_street', '').strip()
            brgy = request.form.get('addr_brgy', '').strip()
            city = request.form.get('addr_city', '').strip()
            province = request.form.get('addr_province', '').strip()
            zip_code = request.form.get('addr_zip', '').strip()
            landmark = request.form.get('addr_landmark', '').strip()
            
            formatted_addr = f"{street}, Brgy. {brgy}\n{city}, {province} {zip_code}"
            if landmark:
                formatted_addr += f"\nLandmark: {landmark}"
                
            full_details += f"\n\nDelivery Address:\n{formatted_addr}"
        
        cursor.execute("""
            INSERT INTO orders (user_id, total_amount, payment_status, payment_method, delivery_method, shipping_address, order_status, created_at) 
            VALUES (%s, %s, 'Pending', 'PayMongo', %s, %s, 'Pending', NOW())
        """, (user_id, total_amount, delivery_method, full_details))
        conn.commit() 
        new_order_id = cursor.lastrowid

        for item in cart_items:
            safe_file_path = item['file_path'] if item['file_path'] else ""
            cursor.execute("""
                INSERT INTO order_items (order_id, product_id, quantity, price_at_time, item_details, file_path) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (new_order_id, item['product_id'], item['quantity'], item['total_price'], item['item_details'], safe_file_path))
            
        if selected_cart_ids:
            format_strings = ','.join(['%s'] * len(selected_cart_ids))
            cursor.execute(f"DELETE FROM cart WHERE user_id = %s AND cart_id IN ({format_strings})", tuple([user_id] + selected_cart_ids))
        else:
            cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
            
        cursor.execute("SELECT email FROM users WHERE user_id = %s", (user_id,))
        user_account = cursor.fetchone()
        
        if user_account and user_account['email']:
            pay_url = url_for('pay_now', order_id=new_order_id, _external=True)
            
           # Start Background Timer (60 seconds = 1 minute)
            Timer(60.0, delayed_payment_reminder, args=(
                new_order_id, contact_name, user_account['email'], total_amount, pay_url
            )).start()
            print(f"Background timer started for Order #{new_order_id}. Will check payment status in 1 minute.")
            
        conn.commit()
        conn.close()

        paymongo_key = os.environ.get('PAYMONGO_SECRET_KEY')
        
        if not paymongo_key:
            return redirect(url_for('payment_success', order_id=new_order_id))

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
                    "payment_method_types": ["card", "gcash", "paymaya", "qrph"],
                    "success_url": url_for('payment_success', order_id=new_order_id, _external=True),
                    "cancel_url": url_for('cancel_payment', order_id=new_order_id, _external=True),
                    "description": "Professional Printing Services"
                }
            }
        }
        
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
            checkout_url = api_data['data']['attributes']['checkout_url']
            return redirect(checkout_url)
        else:
            flash(f"Payment API Error. Please try again.", "error")
            print(f"PAYMONGO ERROR: {api_data}")
            return redirect('/cart')

    except Exception as e:
        return f"Order Error: {e}"

@app.route('/cancel_payment/<int:order_id>')
def cancel_payment(order_id):
    if not session.get('loggedin'): return redirect(url_for('login'))
    flash("Payment incomplete. You can complete your payment at any time via the secure link sent to your email, or directly from your Orders dashboard.", "info")
    return redirect(url_for('my_order_details', order_id=order_id))

@app.route('/pay_now/<int:order_id>')
def pay_now(order_id):
    if not session.get('loggedin'): return redirect(url_for('login'))
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM orders WHERE order_id = %s AND user_id = %s AND payment_status = 'Pending'", (order_id, session['user_id']))
        order = cursor.fetchone()
        conn.close()
        
        if not order:
            flash("Order not found or already paid.", "error")
            return redirect('/my_orders')
            
        paymongo_key = os.environ.get('PAYMONGO_SECRET_KEY')
        url = "https://api.paymongo.com/v1/checkout_sessions"
        payload = {
            "data": {
                "attributes": {
                    "billing": {"name": session.get('name', 'Printagram Customer')},
                    "send_email_receipt": False,
                    "show_description": True,
                    "show_line_items": True,
                    "line_items": [{"currency": "PHP", "amount": int(float(order['total_amount']) * 100), "name": f"Printagram Order #{order_id}", "quantity": 1}],
                    "payment_method_types": ["card", "gcash", "paymaya", "qrph"],
                    "success_url": url_for('payment_success', order_id=order_id, _external=True),
                    "cancel_url": url_for('my_order_details', order_id=order_id, _external=True),
                    "description": "Professional Printing Services"
                }
            }
        }
        
        auth_str = f"{paymongo_key}:"
        b64_auth = base64.b64encode(auth_str.encode()).decode()
        headers = {"accept": "application/json", "content-type": "application/json", "authorization": f"Basic {b64_auth}"}
        response = requests.post(url, json=payload, headers=headers)

        if response.status_code == 200:
            return redirect(response.json()['data']['attributes']['checkout_url'])
        else:
            flash("Payment API Error. Please try again.", "error")
            return redirect(f'/my_order_details/{order_id}')
            
    except Exception as e: return f"Payment Error: {e}"

@app.route('/payment_success/<int:order_id>')
def payment_success(order_id):
    if not session.get('loggedin'):
        return redirect(url_for('login'))
        
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT payment_status FROM orders WHERE order_id = %s", (order_id,))
        current_status = cursor.fetchone()
        
        if current_status and current_status['payment_status'] != 'Paid':
            cursor.execute("UPDATE orders SET payment_status = 'Paid' WHERE order_id = %s AND user_id = %s", (order_id, session['user_id']))
            
            cursor.execute("""
                SELECT o.*, u.full_name, u.email 
                FROM orders o 
                JOIN users u ON o.user_id = u.user_id 
                WHERE o.order_id = %s
            """, (order_id,))
            order = cursor.fetchone()
            
            cursor.execute("""
                SELECT oi.*, p.name 
                FROM order_items oi 
                JOIN products p ON oi.product_id = p.product_id 
                WHERE oi.order_id = %s
            """, (order_id,))
            items = cursor.fetchall()
            
            conn.commit()
            
            if order and order['email']:
                subject = f"Printagram Order Confirmation - #{order_id}"
                fallback_text = f"Hello {order['full_name']},\n\nYour payment was successful! Your order #{order_id} has been received and our team will begin processing it shortly."
                
                html_items = ""
                for item in items:
                    clean_details = item['item_details'].replace(' || ', ' | ')
                    html_items += f"<li style='margin-bottom: 10px;'><strong>{item['quantity']}x {item['name']}</strong> (₱{float(item['price_at_time']):,.2f})<br><span style='color:#666; font-size:12px;'>{clean_details}</span></li>"

                html_body = f"""
                <div style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 12px; overflow: hidden; background-color: #ffffff;">
                    <div style="background: #28a745; color: white; padding: 25px 20px; text-align: center;">
                        <h2 style="margin: 0; font-size: 24px; font-weight: 700;">Payment Successful</h2>
                        <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">Order #{order_id} Confirmed</p>
                    </div>
                    <div style="padding: 30px 25px; color: #333;">
                        <p style="font-size: 16px; margin-top: 0;">Hello <strong>{order['full_name']}</strong>,</p>
                        <p style="font-size: 15px; line-height: 1.5;">Your payment has been successfully received and our team will begin processing your order shortly.</p>
                        
                        <div style="background: #f9f9f9; padding: 20px; border-radius: 8px; margin: 25px 0; border: 1px solid #eee;">
                            <h3 style="margin: 0 0 15px 0; color: #333; font-size: 16px; border-bottom: 1px solid #ddd; padding-bottom: 10px;">Order Summary</h3>
                            <ul style="padding-left: 20px; margin: 0; font-size: 14px;">
                                {html_items}
                            </ul>
                            <div style="margin-top: 15px; padding-top: 15px; border-top: 1px dashed #ddd; font-size: 16px; font-weight: bold; color: #333; display: flex; justify-content: space-between;">
                                <span>Delivery Method:</span>
                                <span>{order['delivery_method']}</span>
                            </div>
                            <div style="margin-top: 10px; font-size: 18px; font-weight: bold; color: #DC5500; display: flex; justify-content: space-between;">
                                <span>Total Paid:</span>
                                <span>₱{order['total_amount']:,.2f}</span>
                            </div>
                        </div>
                        
                        <div style="text-align: center; margin: 35px 0;">
                            <a href="{url_for('my_order_details', order_id=order_id, _external=True)}" style="background: #333; color: white; text-decoration: none; padding: 14px 30px; border-radius: 8px; font-size: 16px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(0,0,0,0.1);">
                                View Order Details
                            </a>
                        </div>
                        
                        <p style="font-size: 13px; color: #888; text-align: center; margin: 0; line-height: 1.5;">
                            We will notify you again once your order is ready for pickup or out for delivery.<br>Thank you for choosing Printagram!
                        </p>
                    </div>
                </div>
                """
                send_system_email(order['email'], subject, fallback_text, html_body)
        
        conn.close()
        return render_template('order_success.html', order_id=order_id)
        
    except Exception as e:
        return f"Error finalizing payment: {e}"

@app.route('/help')
def help_page():
    return render_template('help.html')

@app.route('/submit_ticket', methods=['POST'])
def submit_ticket():
    first_name = request.form.get('first_name')
    last_name = request.form.get('last_name')
    email = request.form.get('email')
    subject = request.form.get('subject')
    details = request.form.get('details')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT email FROM users WHERE role IN ('admin', 'super_admin')")
        admins = cursor.fetchall()
        conn.close()
        
        email_subject = f"New Support Ticket: {subject}"
        email_body = f"You have received a new support ticket from Printagram.\n\nFrom: {first_name} {last_name}\nEmail: {email}\nInquiry Type: {subject}\n\nDetails:\n{details}\n\nPlease reply directly to the customer's email address to assist them."
        
        for admin in admins:
            if admin['email']:
                send_system_email(admin['email'], email_subject, email_body)
                
        flash("Ticket submitted successfully! We will email you back within 24-48 hours.", "success")
    except Exception as e:
        print(f"Error submitting ticket: {e}")
        flash("An error occurred while submitting your ticket. Please try again.", "error")
        
    return redirect(url_for('help_page'))
    
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
            
        if not phone or not re.match(r'^(?:\+639|09|9)\d{9}$', phone):
            flash("Invalid phone number. Please use a valid 10 or 11-digit mobile number.", "error")
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

        cursor.execute("SELECT * FROM users WHERE phone_number = %s", (phone,))
        if cursor.fetchone():
            conn.close()
            flash("This phone number is already registered to another account.", "error")
            return redirect(url_for('register'))

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
                    
                    redirect_target = '/admin' if user['role'] in ['admin', 'super_admin'] else url_for('home')
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
            return redirect('/admin') if session['role'] in ['admin', 'super_admin'] else redirect(url_for('home'))
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

@app.route('/admin')
def admin_dashboard():
    if 'role' not in session or session['role'] not in ['admin', 'super_admin']:
        return "ACCESS DENIED"
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("SELECT COUNT(*) as count FROM orders WHERE order_status != 'Cancelled'")
        res_orders = cursor.fetchone()
        total_orders = res_orders['count'] if res_orders else 0
        
        cursor.execute("SELECT SUM(total_amount) as revenue FROM orders WHERE order_status != 'Cancelled'")
        res_rev = cursor.fetchone()
        total_revenue = res_rev['revenue'] if res_rev and res_rev['revenue'] else 0
        
        cursor.execute("SELECT * FROM products")
        products = cursor.fetchall() or []
        
        cursor.execute("SELECT * FROM product_variants")
        list_of_variants = cursor.fetchall() or []

        cursor.execute("SELECT * FROM product_images ORDER BY image_id ASC")
        gallery_images = cursor.fetchall() or []

        cursor.execute("""
            SELECT o.*, u.full_name FROM orders o
            JOIN users u ON o.user_id = u.user_id
            ORDER BY o.created_at DESC
        """)
        orders = cursor.fetchall() or []
        for order in orders:
            if order.get('created_at'):
                order['created_at'] += timedelta(hours=8)
                
            cursor.execute("""
                SELECT oi.*, p.name as product_name,
                       COALESCE((SELECT image_url FROM product_images WHERE product_id = p.product_id ORDER BY image_id ASC LIMIT 1), p.image_path) as image_path
                FROM order_items oi
                JOIN products p ON oi.product_id = p.product_id
                WHERE oi.order_id = %s
            """, (order['order_id'],))
            order['safe_items'] = cursor.fetchall() or []
            
        cursor.execute("""
            SELECT u.user_id, u.full_name, u.email, u.phone_number, u.created_at,
                   (SELECT message_text FROM chat_messages WHERE sender_id = u.user_id OR receiver_id = u.user_id ORDER BY created_at DESC LIMIT 1) as latest_message,
                   (SELECT created_at FROM chat_messages WHERE sender_id = u.user_id OR receiver_id = u.user_id ORDER BY created_at DESC LIMIT 1) as latest_time,
                   (SELECT COUNT(*) FROM chat_messages WHERE sender_id = u.user_id AND (is_read = FALSE OR is_read IS NULL)) as unread_count
            FROM users u
            WHERE u.role IN ('customer', 'guest')
            ORDER BY latest_time DESC, u.user_id DESC
        """)
        customers = cursor.fetchall() or []

        cursor.execute("SELECT * FROM users WHERE role IN ('admin', 'super_admin') ORDER BY user_id")
        staff_members = cursor.fetchall() or []

        cursor.execute("SELECT * FROM users WHERE user_id = %s", (session['user_id'],))
        current_admin = cursor.fetchone()

        conn.close() 
        
        variants_map = {}
        for v in list_of_variants: 
            pid = v['product_id']
            if pid not in variants_map: variants_map[pid] = []
            variants_map[pid].append(v)
            
        gallery_map = {}
        for img in gallery_images:
            pid = img['product_id']
            if pid not in gallery_map: gallery_map[pid] = []
            gallery_map[pid].append(img)
            
        return render_template('admin.html', total_orders=total_orders, total_revenue=total_revenue, 
                               products=products, variants_map=variants_map, gallery_map=gallery_map, orders=orders, customers=customers, staff_members=staff_members, current_admin=current_admin, role=session['role'])
    except Exception as e:
        return f"DB Error: {e}"

@app.route('/admin/update_profile', methods=['POST'])
def admin_update_profile():
    if 'role' not in session or session['role'] not in ['admin', 'super_admin']: return redirect('/login')
    action = request.form.get('action')
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if action == 'update_info':
            cursor.execute("UPDATE users SET full_name = %s, email = %s, phone_number = %s WHERE user_id = %s", 
                           (request.form.get('name'), request.form.get('email'), request.form.get('phone'), session['user_id']))
            session['name'] = request.form.get('name')
            flash("Profile updated successfully!", "success")
        elif action == 'change_password':
            cursor.execute("SELECT password_hash FROM users WHERE user_id = %s", (session['user_id'],))
            user_data = cursor.fetchone()
            if user_data and check_password_hash(user_data[0], request.form.get('current_password')):
                cursor.execute("UPDATE users SET password_hash = %s WHERE user_id = %s", 
                               (generate_password_hash(request.form.get('new_password')), session['user_id']))
                flash("Password changed successfully!", "success")
            else:
                flash("Incorrect current password.", "error")
        conn.commit()
        conn.close()
    except Exception as e: flash(f"Error: {e}", "error")
    return redirect('/admin')

@app.route('/admin/add_staff', methods=['POST'])
def add_staff():
    if session.get('role') != 'super_admin': return "Access Denied", 403
    name = request.form.get('name')
    email = request.form.get('email')
    password = request.form.get('password')
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            flash("A user with this email already exists.", "error")
        else:
            hashed_password = generate_password_hash(password)
            
            # QA FIX: Automatically grant super_admin privileges to this specific email
            assigned_role = 'super_admin' if email in ['system.printsmart@gmail.com', 'printagrambataan2019@gmail.com'] else 'admin'
            
            cursor.execute("INSERT INTO users (full_name, email, password_hash, role, is_active) VALUES (%s, %s, %s, %s, TRUE)", 
                           (name, email, hashed_password, assigned_role))
            conn.commit()
            
            # Formats the flash message nicely (e.g. "Super Admin" instead of "super_admin")
            role_display = assigned_role.replace('_', ' ').title()
            flash(f"Staff member {name} added successfully as {role_display}!", "success")
            
        conn.close()
    except Exception as e: flash(f"Database Error: {e}", "error")
    return redirect('/admin')

@app.route('/admin/delete_staff/<int:user_id>', methods=['POST'])
def delete_staff(user_id):
    if session.get('role') != 'super_admin': return "Access Denied", 403
    if user_id == session['user_id']:
        flash("You cannot delete your own account.", "error")
        return redirect('/admin')
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE user_id = %s AND role = 'admin'", (user_id,))
        conn.commit()
        conn.close()
        flash("Staff member removed successfully.", "success")
    except Exception as e: flash(f"Database Error: {e}", "error")
    return redirect('/admin')

@app.route('/admin/add_variant', methods=['POST'])
def add_variant():
    if 'role' not in session or session['role'] not in ['admin', 'super_admin']:
        return redirect('/login')
    product_id = request.form.get('product_id')
    variant_name = request.form.get('variant_name')
    price = request.form.get('price')
    stock = request.form.get('stock', 100)
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO product_variants (product_id, variant_name, price, stock_quantity) VALUES (%s, %s, %s, %s)", 
                       (product_id, variant_name, price, stock))
        conn.commit()
        conn.close()
        flash(f"Successfully added variant: {variant_name}", "success")
    except Exception as e:
        flash(f"Database Error: {e}", "error")
    return redirect('/admin')

@app.route('/admin/delete_variant', methods=['POST'])
def delete_variant():
    if 'role' not in session or session['role'] not in ['admin', 'super_admin']:
        return redirect('/login')
    variant_id = request.form.get('variant_id')
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM product_variants WHERE variant_id = %s", (variant_id,))
        conn.commit()
        conn.close()
        flash("Pricing variant deleted successfully!", "success")
    except Exception as e:
        flash(f"Database Error: {e}", "error")
    return redirect('/admin')

@app.route('/admin/delete_gallery_image', methods=['POST'])
def delete_gallery_image():
    if 'role' not in session or session['role'] not in ['admin', 'super_admin']:
        return redirect('/login')
        
    image_id = request.form.get('image_id')
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM product_images WHERE image_id = %s", (image_id,))
        conn.commit()
        conn.close()
        flash("Image removed from gallery successfully!", "success")
    except Exception as e:
        flash(f"Error removing image: {e}", "error")
        
    return redirect('/admin')

# --- QA FIX: HTML FORMATTED STATUS UPDATE EMAIL WITH DYNAMIC BUTTONS ---
@app.route('/admin/update_order_status', methods=['POST'])
def update_order_status():
    if 'role' not in session or session['role'] not in ['admin', 'super_admin']: 
        return redirect('/login')
        
    order_id = request.form.get('order_id')
    new_status = request.form.get('status')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        if new_status == 'Out for Delivery':
            est_date = datetime.now() + timedelta(days=5)
            cursor.execute("UPDATE orders SET order_status = %s, estimated_delivery_date = %s WHERE order_id = %s", (new_status, est_date, order_id))
        else:
            cursor.execute("UPDATE orders SET order_status = %s, estimated_delivery_date = NULL WHERE order_id = %s", (new_status, order_id))
            
        cursor.execute("""
            SELECT o.order_id, o.payment_status, u.email, u.full_name 
            FROM orders o 
            JOIN users u ON o.user_id = u.user_id 
            WHERE o.order_id = %s
        """, (order_id,))
        order_info = cursor.fetchone()
        
        conn.commit()
        conn.close()

        if order_info and order_info['email']:
            subject = f"Printagram Order Update: #{order_id} is now {new_status}"
            
            status_message = "Your order has been received and is waiting for processing."
            if new_status == 'Processing':
                status_message = "Great news! Our team is currently preparing and printing your items. We'll notify you as soon as they are ready."
            elif new_status == 'Ready for Pickup':
                status_message = "Your order is printed, packed, and ready to be picked up at our store!"
            elif new_status == 'Out for Delivery':
                status_message = "Your order is on its way to your shipping address and will arrive soon."
            elif new_status == 'Completed':
                status_message = "Your order has been successfully completed. Thank you for choosing Printagram! We'd love it if you could leave a review for your items on our website."
            elif new_status == 'Cancelled':
                status_message = "Your order has been cancelled. If you have already paid, please allow 3-5 business days for the refund to process. Contact us if you have any questions."
            
            fallback_text = f"Hello {order_info['full_name']},\n\nYour Printagram order #{order_id} has been updated to: {new_status}.\n\n{status_message}\n\nBest regards,\nThe Printagram Team"
            
            # Define Button Logic
            action_url = url_for('my_order_details', order_id=order_id, _external=True)
            button_text = "View Order Details"
            button_color = "#333333"

            if order_info['payment_status'] == 'Pending' and new_status not in ['Cancelled', 'Completed']:
                button_text = "💳 Pay Now"
                button_color = "#28a745"
                action_url = url_for('pay_now', order_id=order_id, _external=True)
            elif new_status == 'Completed':
                button_text = "⭐ Write a Review"
                button_color = "#DC5500"
            elif new_status == 'Cancelled':
                button_text = "View Cancelled Order"
                button_color = "#dc3545"

            # Beautiful HTML Wrapper
            html_body = f"""
            <div style="font-family: 'Helvetica Neue', Arial, sans-serif; max-width: 600px; margin: 0 auto; border: 1px solid #e0e0e0; border-radius: 12px; overflow: hidden; background-color: #ffffff;">
                <div style="background: #DC5500; color: white; padding: 25px 20px; text-align: center;">
                    <h2 style="margin: 0; font-size: 24px; font-weight: 700;">Order Update</h2>
                    <p style="margin: 5px 0 0 0; font-size: 14px; opacity: 0.9;">Transaction #{order_id}</p>
                </div>
                <div style="padding: 30px 25px; color: #333;">
                    <p style="font-size: 16px; margin-top: 0;">Hello <strong>{order_info['full_name']}</strong>,</p>
                    <p style="font-size: 16px; line-height: 1.5;">Your Printagram order has been updated to: <strong style="color: #DC5500; font-size: 18px;">{new_status}</strong>.</p>
                    
                    <div style="background: #fff5eb; border-left: 4px solid #DC5500; padding: 15px 20px; margin: 25px 0; border-radius: 0 8px 8px 0;">
                        <p style="margin: 0; font-size: 15px; color: #555; line-height: 1.5;">{status_message}</p>
                    </div>
                    
                    <div style="text-align: center; margin: 35px 0;">
                        <a href="{action_url}" style="background: {button_color}; color: white; text-decoration: none; padding: 14px 30px; border-radius: 8px; font-size: 16px; font-weight: bold; display: inline-block; box-shadow: 0 4px 10px rgba(0,0,0,0.1);">
                            {button_text}
                        </a>
                    </div>
                    
                    <hr style="border: 0; border-top: 1px solid #eee; margin: 30px 0;">
                    <p style="font-size: 13px; color: #888; text-align: center; margin: 0; line-height: 1.5;">
                        Thank you for choosing Printagram!<br>
                        If you have any questions, simply reply to this email or submit a support ticket on our website.
                    </p>
                </div>
            </div>
            """
            
            send_system_email(order_info['email'], subject, fallback_text, html_body)
            
        flash(f"Order #{order_id} updated to {new_status} and customer notified!", "success")
        
    except Exception as e:
        flash(f"Error updating status: {e}", "error")
        print(f"Status Update Error: {e}")
        
    return redirect('/admin')


@app.route('/admin/upload_product_image', methods=['POST'])
def upload_product_image():
    if 'role' not in session or session['role'] not in ['admin', 'super_admin']:
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
    if 'role' not in session or session['role'] not in ['admin', 'super_admin']: return redirect('/login')
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
        if order.get('created_at'):
            order['created_at'] += timedelta(hours=8)
            
        cursor.execute("""
            SELECT oi.*, p.name as product_name,
                   COALESCE((SELECT image_url FROM product_images WHERE product_id = p.product_id ORDER BY image_id ASC LIMIT 1), p.image_path) as image_path
            FROM order_items oi
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
    
    for order in orders:
        if order.get('created_at'):
            order['created_at'] += timedelta(hours=8)
            
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
        
    if order.get('created_at'):
        order['created_at'] += timedelta(hours=8)
        
    cursor.execute("""
        SELECT oi.*, p.name as product_name, 
               COALESCE((SELECT image_url FROM product_images WHERE product_id = p.product_id ORDER BY image_id ASC LIMIT 1), p.image_path) as image_path 
        FROM order_items oi
        JOIN products p ON oi.product_id = p.product_id
        WHERE oi.order_id = %s
    """, (order_id,))
    order_items = cursor.fetchall()
    
    subtotal = sum(float(item['price_at_time']) for item in order_items)
    processing_fee = float(order['total_amount']) - subtotal
    
    if order['order_status'] == 'Completed':
        for item in order_items:
            cursor.execute("SELECT COUNT(*) as count FROM product_reviews WHERE user_id = %s AND product_id = %s", (session['user_id'], item['product_id']))
            already_reviewed = cursor.fetchone()['count'] > 0
            item['can_review'] = not already_reviewed
    else:
        for item in order_items:
            item['can_review'] = False

    conn.close()
    return render_template('order_details.html', order=order, items=order_items, subtotal=subtotal, processing_fee=processing_fee)

@app.route('/cancel_order', methods=['POST'])
def cancel_order():
    if not session.get('loggedin'): return redirect(url_for('login'))
    
    order_id = request.form.get('order_id')
    reasons = request.form.getlist('reason')
    other_reason = request.form.get('other_reason', '').strip()
    
    final_reasons = [r for r in reasons if r != 'Others']
    if 'Others' in reasons and other_reason:
        final_reasons.append(f"Others: {other_reason}")
    
    cancel_reason_str = " | ".join(final_reasons)
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM orders WHERE order_id = %s AND user_id = %s", (order_id, session['user_id']))
        order = cursor.fetchone()
        
        if order and order['order_status'] == 'Pending':
            cursor.execute("UPDATE orders SET order_status = 'Cancelled', cancellation_reason = %s WHERE order_id = %s", (cancel_reason_str, order_id))
            conn.commit()
            flash("Order cancelled successfully. A refund request has been sent to PayMongo (Processing takes 3-5 business days).", "success")
        else:
            flash("This order can no longer be cancelled.", "error")
            
        conn.close()
    except Exception as e:
        flash(f"Error cancelling order: {e}", "error")
        
    return redirect(url_for('my_order_details', order_id=order_id))

@app.route('/api/admin_notifications_data')
def admin_notifications_data():
    if session.get('role') not in ['admin', 'super_admin']: 
        return jsonify({})
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        cursor.execute("""
            SELECT o.order_id, u.full_name, o.order_status, CAST(DATE_ADD(o.created_at, INTERVAL 8 HOUR) AS CHAR) as created_at
            FROM orders o
            JOIN users u ON o.user_id = u.user_id
            WHERE o.order_status = 'Pending' 
            ORDER BY o.order_id DESC
        """)
        pending_orders = cursor.fetchall()
        
        cursor.execute("""
            SELECT o.order_id, u.full_name, o.order_status 
            FROM orders o
            JOIN users u ON o.user_id = u.user_id
            WHERE o.order_status = 'Cancelled' 
            ORDER BY o.order_id DESC LIMIT 5
        """)
        cancelled_orders = cursor.fetchall()
        
        cursor.execute("""
            SELECT c.message_id, c.message_text, u.full_name, c.sender_id, CAST(DATE_ADD(c.created_at, INTERVAL 8 HOUR) AS CHAR) as created_at
            FROM chat_messages c
            JOIN users u ON c.sender_id = u.user_id
            WHERE u.role IN ('customer', 'guest') AND (c.is_read = FALSE OR c.is_read IS NULL)
            ORDER BY c.message_id DESC
        """)
        unread_chats = cursor.fetchall()
        
        conn.close()
        return jsonify({
            'pending_orders': pending_orders,
            'cancelled_orders': cancelled_orders,
            'unread_chats': unread_chats
        })
    except Exception as e:
        print(f"Notification System Error: {e}")
        return jsonify({
            'pending_orders': [],
            'cancelled_orders': [],
            'unread_chats': []
        })
    
@app.route('/api/admin_sidebar')
def admin_sidebar():
    if session.get('role') not in ['admin', 'super_admin']:
        return jsonify([])
        
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT u.user_id, u.full_name,
                   (SELECT message_text FROM chat_messages WHERE sender_id = u.user_id OR receiver_id = u.user_id ORDER BY created_at DESC LIMIT 1) as latest_message,
                   (SELECT created_at FROM chat_messages WHERE sender_id = u.user_id OR receiver_id = u.user_id ORDER BY created_at DESC LIMIT 1) as latest_time,
                   (SELECT COUNT(*) FROM chat_messages WHERE sender_id = u.user_id AND (is_read = FALSE OR is_read IS NULL)) as unread_count
            FROM users u
            WHERE u.role IN ('customer', 'guest')
            ORDER BY latest_time DESC, u.user_id DESC
        """)
        customers = cursor.fetchall()
        conn.close()
        
        for c in customers:
            if c['latest_time']:
                local_time = c['latest_time'] + timedelta(hours=8)
                c['latest_time_str'] = local_time.strftime('%b %d, %I:%M %p')
            else:
                c['latest_time_str'] = ''
                
            c['latest_message'] = c['latest_message'] if c['latest_message'] else 'No messages yet'
            
        return jsonify(customers)
    except Exception as e:
        print(f"Sidebar Error: {e}")
        return jsonify([])

@app.route('/api/heartbeat', methods=['POST'])
def heartbeat():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    cursor.execute("SELECT COUNT(*) as admin_count FROM users WHERE role IN ('admin', 'super_admin') AND last_active >= NOW() - INTERVAL 5 MINUTE")
    admin_online = cursor.fetchone()['admin_count'] > 0
    
    user_id = session.get('user_id')
    if user_id:
        cursor.execute("UPDATE users SET last_active = NOW() WHERE user_id = %s", (user_id,))
    
    conn.commit()
    conn.close()
    return jsonify({'admin_online': admin_online})

@app.route('/api/get_messages')
def get_messages():
    role = session.get('role', 'customer')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        if role in ['admin', 'super_admin']:
            if not session.get('loggedin'): return jsonify([])
            other_user_id = request.args.get('user_id')
            if not other_user_id: return jsonify([])
            
            cursor.execute("UPDATE chat_messages SET is_read = TRUE WHERE sender_id = %s", (other_user_id,))
            conn.commit()
            
            cursor.execute("""
                SELECT * FROM chat_messages 
                WHERE sender_id = %s OR receiver_id = %s
                ORDER BY created_at ASC
            """, (other_user_id, other_user_id))
        else:
            user_id = session.get('user_id')
            if not user_id: return jsonify([])
            
            cursor.execute("""
                SELECT * FROM chat_messages 
                WHERE sender_id = %s OR receiver_id = %s
                ORDER BY created_at ASC
            """, (user_id, user_id))
            
        messages = cursor.fetchall()
        conn.close()
        
        for msg in messages:
            local_time = msg['created_at'] + timedelta(hours=8)
            msg['created_at'] = local_time.strftime('%b %d, %I:%M %p')
            msg['is_mine'] = (msg['sender_id'] == session.get('user_id'))
            
        return jsonify(messages)
    except Exception as e:
        return jsonify([])

@app.route('/api/send_message', methods=['POST'])
def send_message():
    role = session.get('role', 'guest')
    
    if role in ['admin', 'super_admin'] and not session.get('loggedin'):
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401
        
    if 'user_id' not in session:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            guest_name = f"GUEST-{random.randint(1000, 9999)}"
            guest_email = f"guest_{secrets.token_hex(4)}@printagram.local"
            
            cursor.execute("""
                INSERT INTO users (full_name, email, phone_number, password_hash, role, is_active)
                VALUES (%s, %s, %s, 'guest_no_login', 'customer', TRUE)
            """, (guest_name, guest_email, 'No Phone'))
            conn.commit()
            
            session['user_id'] = cursor.lastrowid
            session['role'] = 'guest'
            session['name'] = guest_name
            conn.close()
        except Exception as e:
            print(f"Guest Creation Error: {e}")
            return jsonify({'status': 'error', 'message': f'Guest creation failed: {str(e)}'})
        
    sender_id = session['user_id']
    message_text = request.form.get('message_text', '').strip()
    attachment = request.files.get('attachment')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        if role in ['admin', 'super_admin']:
            receiver_id = request.form.get('receiver_id')
        else:
            cursor.execute("SELECT user_id FROM users WHERE role IN ('admin', 'super_admin') ORDER BY user_id ASC LIMIT 1")
            admin_user = cursor.fetchone()
            receiver_id = admin_user['user_id'] if admin_user else 1
            
        if not message_text and not attachment:
            return jsonify({'status': 'error', 'message': 'Empty message'})
            
        attachment_url = None
        if attachment and attachment.filename != '':
            from werkzeug.utils import secure_filename
            
            safe_filename = secure_filename(attachment.filename)
            ext = safe_filename.rsplit('.', 1)[-1].lower() if '.' in safe_filename else ''
            
            if ext in ['zip', 'rar', '7z', 'docx', 'xlsx', 'txt']:
                upload_result = cloudinary.uploader.upload(
                    attachment, 
                    folder="chat_attachments", 
                    resource_type="raw", 
                    use_filename=True,
                    unique_filename=True
                )
            else:
                upload_result = cloudinary.uploader.upload(
                    attachment, 
                    folder="chat_attachments", 
                    resource_type="auto", 
                    use_filename=True,
                    unique_filename=True
                )
                
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
    
@app.route('/admin/delete_customer/<int:user_id>', methods=['POST'])
def admin_delete_customer(user_id):
    if 'role' not in session or session['role'] not in ['admin', 'super_admin']:
        return redirect(url_for('login'))
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM product_reviews WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM chat_messages WHERE sender_id = %s OR receiver_id = %s", (user_id, user_id))
        cursor.execute("""
            DELETE oi FROM order_items oi
            INNER JOIN orders o ON oi.order_id = o.order_id
            WHERE o.user_id = %s
        """, (user_id,))
        cursor.execute("DELETE FROM orders WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        
        conn.commit()
        conn.close()
        flash("Customer account and all related data have been permanently deleted.", "success")
    except Exception as e:
        flash(f"Error deleting account: {e}", "error")
        
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/reset_user_password', methods=['POST'])
def admin_reset_user_password():
    if 'role' not in session or session['role'] not in ['admin', 'super_admin']:
        return redirect(url_for('login'))
        
    user_id = request.form.get('user_id')
    new_password = request.form.get('new_password')
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        hashed_password = generate_password_hash(new_password)
        
        cursor.execute("UPDATE users SET password_hash = %s WHERE user_id = %s", (hashed_password, user_id))
        conn.commit()
        conn.close()
        
        flash(f"Password has been successfully reset for User #{user_id}.", "success")
    except Exception as e:
        flash(f"Error resetting password: {e}", "error")
        
    return redirect(url_for('admin_dashboard'))

@app.route('/delete_my_account', methods=['POST'])
def delete_my_account():
    if not session.get('loggedin'):
        return redirect(url_for('login'))
        
    user_id = session['user_id']
    
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM product_reviews WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM chat_messages WHERE sender_id = %s OR receiver_id = %s", (user_id, user_id))
        cursor.execute("""
            DELETE oi FROM order_items oi
            INNER JOIN orders o ON oi.order_id = o.order_id
            WHERE o.user_id = %s
        """, (user_id,))
        cursor.execute("DELETE FROM orders WHERE user_id = %s", (user_id,))
        cursor.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        
        conn.commit()
        conn.close()
        
        session.clear()
        flash("Your account has been deleted. We're sorry to see you go!", "success")
        return redirect(url_for('home'))
    except Exception as e:
        flash(f"Error: {e}", "error")
        return redirect(url_for('profile'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port)