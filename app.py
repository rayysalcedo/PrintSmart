from flask import Flask, render_template, request, redirect, url_for
import os

app = Flask(__name__)
app.secret_key = 'printsmart_secret_key'

# --- ROUTE: HOME PAGE ---
@app.route('/')
def home():
    return render_template('home.html')

# --- ROUTE: ABOUT US ---
@app.route('/about')
def about():
    return render_template('about.html')

# --- ROUTE: SERVICES ---
@app.route('/services')
def services():
    return render_template('services.html')

# --- ROUTE: LOGIN ---
@app.route('/login')
def login():
    return render_template('login.html')

# --- ROUTE: REGISTER ---
@app.route('/register')
def register():
    return render_template('register.html')

if __name__ == '__main__':
    app.run(debug=True)