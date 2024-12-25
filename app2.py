from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, make_response,flash
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
import os
import io
from datetime import datetime, timedelta, date, time
import json
import pandas as pd
from xhtml2pdf import pisa
import openpyxl

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Database Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///bar_management.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Image Upload Configuration
app.config['UPLOAD_FOLDER'] = 'static/uploads/'
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}

db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    brand_name = db.Column(db.String(80), nullable=False)
    brand_code = db.Column(db.String(80), nullable=False)
    barcode = db.Column(db.String(100), unique=True, nullable=False)
    invoice_rate = db.Column(db.Float, nullable=False)
    mrp = db.Column(db.Float, nullable=False)
    selling_price = db.Column(db.Float, nullable=False)
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    added_by = db.Column(db.String(80), nullable=False)
    brand_type = db.Column(db.String(80), nullable=False)
    brand_size = db.Column(db.String(80), nullable=False)
    image_path = db.Column(db.String(120), nullable=True)  # Image field

class Stock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    added_by = db.Column(db.String(80), nullable=False)
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    product = db.relationship('Product', backref=db.backref('stocks', lazy=True))

class StockHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    added_by = db.Column(db.String(80), nullable=False)
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    product = db.relationship('Product', backref=db.backref('stock_history', lazy=True))


class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)  # Link to Product
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # Link to User who made the sale
    quantity = db.Column(db.Integer, nullable=False)  # Quantity sold
    total_price = db.Column(db.Float, nullable=False)  # Total price of the sale
    date_sold = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)  # Date of sale
    product = db.relationship('Product', backref=db.backref('sales', lazy=True))
    user = db.relationship('User', backref=db.backref('sales', lazy=True))

# Default Admin Creation
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        hashed_password = generate_password_hash('admin123', method='pbkdf2:sha256')
        admin_user = User(username='admin', password=hashed_password, role='Admin')
        db.session.add(admin_user)
        db.session.commit()

def generate_daily_report_data():
    today = datetime.now().date()

    report_data = {}
    grand_total_sales_by_type = {}
    grand_total_sale = 0  # Grand total across all brand types

    products = Product.query.all()

    for product in products:
        if product.brand_type not in report_data:
            report_data[product.brand_type] = {}
            grand_total_sales_by_type[product.brand_type] = 0  # Initialize total sales for this type

        if product.brand_name not in report_data[product.brand_type]:
            report_data[product.brand_type][product.brand_name] = {
                "sizes": {},
                "total": {"ob": 0, "cb": 0, "sale": 0, "amount": 0, "new_stock": 0},
            }

        # Fetch current stock
        current_stock = (
            db.session.query(func.sum(Stock.quantity))
            .filter(Stock.product_id == product.id)
            .scalar()
            or 0
        )

        # Fetch today's sales
        today_sales = (
            db.session.query(func.sum(Sale.quantity))
            .filter(
                Sale.product_id == product.id,
                Sale.date_sold >= datetime.combine(today, time(2, 0))  # Assuming sales day starts at 2:00 AM
            )
            .scalar()
            or 0
        )

        # Fetch today's stock additions from StockHistory
        today_stock_added = (
            db.session.query(func.sum(StockHistory.quantity))
            .filter(
                StockHistory.product_id == product.id,
                StockHistory.date_added >= datetime.combine(today, time(2, 0))
            )
            .scalar()
            or 0
        )

        # Calculate OB (Opening Balance) and CB (Closing Balance)
        ob = current_stock + today_sales - today_stock_added
        cb = current_stock

        # Calculate sale and amount
        sale = today_sales
        amount = sale * product.selling_price

        # Update brand data
        report_data[product.brand_type][product.brand_name]["sizes"][product.brand_size] = {
            "ob": ob,
            "cb": cb,
            "sale": sale,
            "amount": amount,
            "new_stock": today_stock_added,
        }

        # Update totals
        totals = report_data[product.brand_type][product.brand_name]["total"]
        totals["ob"] += ob
        totals["cb"] += cb
        totals["sale"] += sale
        totals["amount"] += amount
        totals["new_stock"] += today_stock_added

        # Update grand total sales for this type and overall
        grand_total_sales_by_type[product.brand_type] += amount
        grand_total_sale += amount

    # Sort sizes in descending order for each brand
    for brand_type, brands in report_data.items():
        for brand_name, brand_data in brands.items():
            brand_data["sizes"] = dict(
                sorted(brand_data["sizes"].items(), key=lambda x: int(x[0]), reverse=True)
            )

    return report_data, grand_total_sales_by_type, grand_total_sale

# Routes
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            # Store necessary user details in session
            session['user_id'] = user.id
            session['role'] = user.role
            session['username'] = user.username
            
            # Redirect based on role
            if user.role == 'Admin':
                return redirect(url_for('admin_dashboard'))
            elif user.role == 'Supervisor':
                return redirect(url_for('supervisor_dashboard'))
            elif user.role == 'Salesman':
                return redirect(url_for('salesman_dashboard'))
        else:
            return "Invalid credentials", 401

    return render_template('login.html')


@app.route('/admin/add-user', methods=['POST'])
def add_user():
    if 'role' in session and session['role'] == 'Admin':  # Ensure only Admin can add users
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']

        # Check if the username already exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return "Error: Username already exists!", 400

        # Hash the password
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')

        # Create a new user
        new_user = User(username=username, password=hashed_password, role=role)
        db.session.add(new_user)
        db.session.commit()

        return redirect(url_for('user_management'))  # Redirect back to user management
    return jsonify({'message': 'Unauthorized'}), 403

@app.route('/admin/delete-user/<int:id>', methods=['POST'])
def delete_user(id):
    if 'role' in session and session['role'] == 'Admin':
        user = User.query.get(id)
        db.session.delete(user)
        db.session.commit()
        return redirect(url_for('user_management'))
    return jsonify({'message': 'Unauthorized'}), 403

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.context_processor
def inject_user_details():
    return {
        'current_user': {
            'id': session.get('user_id'),
            'role': session.get('role'),
            'username': session.get('username')
        }
    }

# Admin Dashboard
@app.route('/admin/dashboard')
def admin_dashboard():
    if 'role' in session and session['role'] == 'Admin':
        return render_template('admin_dashboard.html',session=session)
    return redirect(url_for('login'))

@app.route('/admin/user-management')
def user_management():
    if 'role' in session and session['role'] == 'Admin':
        users = User.query.all()
        return render_template('partials/user_management.html', users=users)
    return jsonify({'message': 'Unauthorized'}), 403

# Supervisor Dashboard
@app.route('/supervisor/dashboard')
def supervisor_dashboard():
    if 'role' in session and session['role'] == 'Supervisor':
        return render_template('supervisor_dashboard.html',session=session)
    return redirect(url_for('login'))

# Salesman Dashboard
@app.route('/salesman/dashboard')
def salesman_dashboard():
    if 'role' in session and session['role'] == 'Salesman':
        return render_template('salesman_dashboard.html',session=session)
    return redirect(url_for('login'))

@app.route('/admin/add-product', methods=['GET', 'POST'])
def add_product():
    if 'role' in session and session['role'] in ['Admin', 'Supervisor']:
        if request.method == 'POST':
            data = request.form
            brand_name = data['brand_name']
            brand_code = data['brand_code']
            barcode = data['barcode']
            invoice_rate = float(data['invoice_rate'])
            mrp = float(data['mrp'])
            selling_price = float(data['selling_price'])
            brand_type = data['brand_type']
            brand_size = data['brand_size']
            added_by = session.get('user_id')

            # Handle image upload
            image_file = request.files.get('image')
            image_path = None

            if image_file:
                if image_file.filename.split('.')[-1].lower() in app.config['ALLOWED_EXTENSIONS']:
                    filename = secure_filename(image_file.filename)
                    image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    image_file.save(image_path)

            new_product = Product(
                brand_name=brand_name,
                brand_code=brand_code,
                barcode=barcode,
                invoice_rate=invoice_rate,
                mrp=mrp,
                selling_price=selling_price,
                brand_type=brand_type,
                brand_size=brand_size,
                added_by=added_by,
                image_path=image_path
            ) 

            db.session.add(new_product)
            db.session.commit()
            return redirect(url_for('admin_dashboard'))
        return render_template('add_product.html')
    return jsonify({'message': 'Unauthorized'}), 403

@app.route('/admin/import-products', methods=['GET', 'POST'])
def import_products():
    if 'role' not in session or session['role'] not in ['Admin', 'Supervisor']:
        return jsonify({'message': 'Unauthorized'}), 403

    if request.method == 'POST':
        file = request.files.get('file')
        if not file or file.filename.split('.')[-1].lower() not in ['xlsx', 'csv']:
            return jsonify({'error': 'Invalid file type. Only .xlsx or .csv files are allowed.'}), 400

        try:
            # Read the uploaded file into a DataFrame
            data = pd.read_excel(file) if file.filename.endswith('.xlsx') else pd.read_csv(file)

            # Iterate through the rows to create Product objects
            for _, row in data.iterrows():
                if not Product.query.filter_by(barcode=row['barcode']).first():
                    product = Product(
                        brand_name=row['brand_name'],
                        brand_code=row['brand_code'],
                        barcode=row['barcode'],
                        invoice_rate=row['invoice_rate'],
                        mrp=row['mrp'],
                        selling_price=row['selling_price'],
                        brand_type=row['brand_type'],
                        brand_size=row['brand_size'],
                        added_by=session.get('user_id')
                    )
                    db.session.add(product)

            db.session.commit()
            return jsonify({'message': 'Products imported successfully!'})
        except Exception as e:
            return jsonify({'error': f'Failed to import products: {str(e)}'}), 500

    return render_template('import_products.html')

@app.route('/admin/export-products', methods=['GET'])
def export_products():
    # Ensure the static/files directory exists
    export_dir = os.path.join('static', 'files')
    os.makedirs(export_dir, exist_ok=True)  # Create the directory if it doesn't exist

    file_path = os.path.join(export_dir, 'products_export.xlsx')  # Path for the Excel file

    # Fetch products from the database
    products = Product.query.all()

    if not products:
        # If no products exist, create a template file
        columns = [
            'brand_name', 'brand_code', 'barcode', 'invoice_rate',
            'mrp', 'selling_price', 'brand_type', 'brand_size', 'image_path'
        ]
        pd.DataFrame(columns=columns).to_excel(file_path, index=False, engine='xlsxwriter')
    else:
        # Prepare data for export
        data = [{
            'brand_name': p.brand_name, 
            'brand_code': p.brand_code,
            'barcode': p.barcode, 
            'invoice_rate': p.invoice_rate,
            'mrp': p.mrp, 
            'selling_price': p.selling_price,
            'brand_type': p.brand_type, 
            'brand_size': p.brand_size,
            'image_path': p.image_path or ''
        } for p in products]
        # Convert to DataFrame and save to Excel
        df = pd.DataFrame(data)
        df.to_excel(file_path, index=False, engine='xlsxwriter')

    # Send the file to the user as a downloadable attachment
    return send_file(file_path, as_attachment=True)
 
@app.route('/admin/add-stock', methods=['GET', 'POST'])
def add_stock():
    if 'role' in session and session['role'] in ['Admin', 'Supervisor']:
        if request.method == 'POST':
            data = request.form
            product_id = int(data['product_id'])
            quantity = int(data['quantity'])
            added_by = session['username']
            date_added = datetime.utcnow()

            # Update or insert stock
            existing_stock = Stock.query.filter_by(product_id=product_id).first()
            if existing_stock:
                # Update existing stock
                existing_stock.quantity += quantity
            else:
                # Add new stock record
                stock_entry = Stock(product_id=product_id, quantity=quantity, added_by=added_by, date_added=date_added)
                db.session.add(stock_entry)

            # Add record to stock history
            stock_history_entry = StockHistory(
                product_id=product_id,
                quantity=quantity,
                added_by=added_by,
                date_added=date_added
            )
            db.session.add(stock_history_entry)

            db.session.commit()
            return redirect(url_for('admin_dashboard'))

        barcode = request.args.get('barcode', '')
        brand_code = request.args.get('brand_code', '')

        if barcode:
            products = Product.query.filter(Product.barcode == barcode).all()
        elif brand_code:
            products = Product.query.filter(Product.brand_code == brand_code).all()
        else:
            products = Product.query.all()

        # Convert products to JSON-serializable dictionaries
        product_dicts = [
            {
                "id": product.id,
                "brand_name": product.brand_name,
                "brand_code": product.brand_code,
                "barcode": product.barcode,
                "mrp": product.mrp,
                "selling_price": product.selling_price,
                "brand_type": product.brand_type,
                "brand_size": product.brand_size,
                "image_path": product.image_path,
            }
            for product in products
        ]

        return render_template('add_stock.html', products=product_dicts, barcode=barcode, brand_code=brand_code)
    return jsonify({'message': 'Unauthorized'}), 403

@app.route('/admin/view-products', methods=['GET'])
def view_products():
    products = Product.query.all()
    brand_types = {product.brand_type for product in products}
    brand_sizes = {product.brand_size for product in products}

    serialized_products = [
        {
            "id": product.id,
            "brand_name": product.brand_name,
            "brand_type": product.brand_type,
            "brand_size": product.brand_size,
            "brand_code": product.brand_code,
            "barcode": product.barcode,
            "invoice_rate": product.invoice_rate,
            "mrp": product.mrp,
            "selling_price": product.selling_price,
            "image_path": product.image_path or ''
        }
        for product in products
    ]

    return render_template(
        'view_products.html',
        products=serialized_products,
        filters={
            'types': sorted(brand_types),
            'sizes': sorted(brand_sizes)
        }
    )

@app.route('/admin/view-stock', methods=['GET'])
def view_stock():
    if 'role' in session and session['role'] in ['Admin', 'Supervisor']:
        # Fetch all products with their total stock
        products = db.session.query(
            Product.id,
            Product.brand_name,
            Product.brand_code,
            Product.barcode,
            Product.invoice_rate,
            Product.mrp,
            Product.selling_price,
            Product.brand_type,
            Product.brand_size,
            Product.image_path,
            db.func.sum(Stock.quantity).label('total_stock')
        ).join(Stock, Stock.product_id == Product.id).group_by(Product.id).all()

        # Generate filters dynamically
        filters = {
            "types": [type_[0] for type_ in db.session.query(Product.brand_type).distinct().all()],
            "sizes": [size[0] for size in db.session.query(Product.brand_size).distinct().all()],
        }

        # Convert products for JSON serialization
        product_dicts = [dict(product._mapping) for product in products]

        return render_template('view_stock.html', products=product_dicts, filters=filters)
    return jsonify({'message': 'Unauthorized'}), 403

from datetime import datetime

@app.route('/admin/stock-history', methods=['GET'])
def stock_history():
    if 'role' in session and session['role'] in ['Admin', 'Supervisor']:
        stock_history = db.session.query(
            StockHistory.id,
            StockHistory.product_id,
            Product.brand_name,
            Product.brand_code,
            Product.barcode,
            Product.brand_type,
            Product.brand_size,
            StockHistory.quantity,
            StockHistory.date_added,
            StockHistory.added_by
        ).join(Product, StockHistory.product_id == Product.id).order_by(StockHistory.date_added.desc()).all()

        history_list = [{
            'id': h.id,
            'product_id': h.product_id,
            'brand_name': h.brand_name,
            'brand_code': h.brand_code,
            'barcode': h.barcode,
            'brand_type': h.brand_type,
            'brand_size': h.brand_size,
            'quantity': h.quantity,
            'date_added': h.date_added.strftime('%Y-%m-%d %I:%M %p'),  # Convert to 12-hour format
            'added_by': h.added_by
        } for h in stock_history]

        return render_template('stock_history.html', stock_history=history_list)
    return jsonify({'message': 'Unauthorized'}), 403

@app.route('/admin/revoke-stock', methods=['POST'])
def revoke_stock():
    if 'role' in session and session['role'] in ['Admin', 'Supervisor']:
        data = request.get_json()
        product_id = data.get('product_id')
        history_id = data.get('history_id')

        # Fetch the stock history entry
        history_entry = StockHistory.query.get(history_id)
        if not history_entry:
            return jsonify({'error': 'Stock history entry not found'}), 404

        # Update the stock quantity
        stock_entry = Stock.query.filter_by(product_id=product_id).first()
        if stock_entry:
            stock_entry.quantity -= history_entry.quantity
            if stock_entry.quantity < 0:
                stock_entry.quantity = 0  # Ensure stock is not negative

        # Delete the history entry
        db.session.delete(history_entry)
        db.session.commit()

        return jsonify({'message': 'Stock addition revoked successfully'})
    return jsonify({'error': 'Unauthorized'}), 403

@app.template_filter('to12hr')
def to12hr(value):
    try:
        from datetime import datetime
        return datetime.strptime(value, "%H:%M:%S").strftime("%I:%M %p")
    except ValueError:
        return value

@app.route('/admin/edit-product/<int:id>', methods=['GET', 'POST'])
def edit_product(id):
    if 'role' in session and session['role'] in ['Admin', 'Supervisor']:
        product = Product.query.get(id)
        if request.method == 'POST':
            data = request.form
            product.brand_name = data['brand_name']
            product.brand_code = data['brand_code']
            product.barcode = data['barcode']
            product.invoice_rate = float(data['invoice_rate'])
            product.mrp = float(data['mrp'])
            product.selling_price = float(data['selling_price'])
            product.brand_type = data['brand_type']
            product.brand_size = data['brand_size']

            # Handle image upload (optional for editing)
            image_file = request.files.get('image')
            if image_file:
                if image_file.filename.split('.')[-1].lower() in app.config['ALLOWED_EXTENSIONS']:
                    filename = secure_filename(image_file.filename)
                    image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    image_file.save(image_path)
                    product.image_path = image_path

            db.session.commit()
            return redirect(url_for('view_products'))
        return render_template('edit_product.html', product=product)
    return jsonify({'message': 'Unauthorized'}), 403

@app.route('/admin/delete-product/<int:id>', methods=['POST'])
def delete_product(id):
    if 'role' in session and session['role'] in ['Admin', 'Supervisor']:
        product = Product.query.get(id)
        if product:
            # Check if the product exists in any sales record
            existing_sales = Sale.query.filter_by(product_id=id).first()
            if existing_sales:
                flash(f"Product '{product.brand_name}' cannot be deleted because it exists in sales records.", "danger")
                return redirect(url_for('view_products'))

            # Safe to delete the product
            db.session.delete(product)
            db.session.commit()
            flash(f"Product '{product.brand_name}' deleted successfully!", "success")
            return redirect(url_for('view_products'))

        flash("Product not found.", "warning")
        return redirect(url_for('view_products'))

    flash("Unauthorized access.", "danger")
    return redirect(url_for('view_products'))

@app.route('/sales/manage', methods=['GET'])
def sale_management():
    # Fetch all products
    products = Product.query.all()

    serialized_products = [
        {
            "id": product.id,
            "brand_name": product.brand_name,
            "brand_type": product.brand_type,
            "brand_size": product.brand_size,
            "brand_code": product.brand_code,
            "barcode": product.barcode,
            "selling_price": product.selling_price,
            "quantity": sum(stock.quantity for stock in product.stocks),
            "image_path": product.image_path if product.image_path.startswith('static/') else f'static/uploads/{product.image_path}',
        }
        for product in products
    ]

    # Get the existing sale list from the session
    sale_list = session.get('sale_list', {})
    grand_total = 0  # Initialize grand total

    for product_id, details in sale_list.items():
        # Build the item name and handle missing fields
        details['brand_type'] = details.get('brand_type', 'Unknown Type')
        details['brand_size'] = details.get('brand_size', 'Unknown Size')
        details['item_name'] = f"{details['brand_name']} {details['brand_type']} {details['brand_size']}"
        details['total_price'] = details['quantity'] * details['selling_price']  # Calculate total price
        grand_total += details['total_price']  # Accumulate grand total

    return render_template(
        'sale_management.html',
        products=serialized_products,
        sale_list=sale_list,
        grand_total=grand_total
    )


@app.route('/sales/add-product', methods=['POST'])
def add_product_to_sale():
    data = request.get_json() or {}
    product_id = data.get('product_id')
    barcode = data.get('barcode')

    if 'sale_list' not in session:
        session['sale_list'] = {}

    sale_list = session['sale_list']

    # Find product by ID or barcode
    product = None
    if product_id:
        product = db.session.get(Product, product_id)
    elif barcode:
        matching_products = Product.query.filter_by(barcode=barcode).all()
        if len(matching_products) == 1:
            product = matching_products[0]
        elif len(matching_products) > 1:
            return jsonify({'error': 'Multiple products match this barcode. Please refine the input.'}), 400

    if not product:
        return jsonify({'error': 'Product not found'}), 404

    total_stock = sum(stock.quantity for stock in product.stocks)
    str_product_id = str(product.id)
    if str_product_id in sale_list:
        existing_quantity = sale_list[str_product_id]['quantity']
        if existing_quantity + 1 > total_stock:
            return jsonify({'error': f'Not enough stock for {product.brand_name}'}), 400
        sale_list[str_product_id]['quantity'] += 1
    else:
        if total_stock < 1:
            return jsonify({'error': f'No stock available for {product.brand_name}'}), 400
        sale_list[str_product_id] = {
            'brand_name': product.brand_name,
            'brand_type': product.brand_type,
            'brand_size': product.brand_size,
            'brand_code': product.brand_code,
            'barcode': product.barcode,
            'selling_price': product.selling_price,
            'quantity': 1,
            'item_name': f"{product.brand_name} {product.brand_type} {product.brand_size}",
            # Ensure correct image path
            'image_path': product.image_path if product.image_path.startswith('static/') else f'static/uploads/{product.image_path}',
        }

    session['sale_list'] = sale_list

    return jsonify({'message': 'Product added successfully', 'sale_list': sale_list})

@app.route('/sales/remove-product', methods=['POST'])
def remove_product_from_sale():
    data = request.get_json()  # Get the JSON payload
    product_id = data.get('product_id')  # Extract product_id

    if not product_id:
        return jsonify({'error': 'Product ID is required'}), 400

    # Load the sale list from the session
    sale_list = session.get('sale_list', {})

    product_id = str(product_id)  # Ensure product_id is a string
    if product_id in sale_list:
        if sale_list[product_id]['quantity'] > 1:
            sale_list[product_id]['quantity'] -= 1  # Decrease quantity by 1
        else:
            del sale_list[product_id]  # Remove product if quantity reaches zero

        session['sale_list'] = sale_list  # Update the session
        return jsonify({'message': 'Product updated successfully', 'sale_list': sale_list})
    else:
        return jsonify({'error': 'Product not found in sale list'}), 404

from datetime import datetime

@app.route('/sales/confirm-sale', methods=['POST'])
def confirm_sale():
    if 'sale_list' not in session:
        return jsonify({'error': 'No sale list to confirm'}), 400

    sale_list = session['sale_list']
    user_id = session.get('user_id')

    for product_id, details in sale_list.items():
        product_id = int(product_id)
        quantity = details['quantity']
        selling_price = details['selling_price']

        # Deduct from stock
        stock_entry = Stock.query.filter_by(product_id=product_id).first()
        if stock_entry and stock_entry.quantity >= quantity:
            stock_entry.quantity -= quantity
        else:
            return jsonify({'error': f'Not enough stock for {details["brand_name"]}'}), 400

        # Add sale record with the current local time
        total_price = quantity * selling_price
        sale = Sale(
            product_id=product_id,
            user_id=user_id,
            quantity=quantity,
            total_price=total_price,
            date_sold=datetime.now()  # Record the correct time
        )
        db.session.add(sale)

    db.session.commit()

    # Clear the sale list
    session.pop('sale_list', None)

    return jsonify({'message': 'Sale confirmed successfully'})

@app.route('/sales/reject-sale', methods=['POST'])
def reject_sale():
    session.pop('sale_list', None)
    return jsonify({'message': 'Sale list cleared successfully'})

@app.route('/admin/view-sales', methods=['GET'])
def view_sales():
    if session.get('role') != 'Admin':
        return jsonify({'error': 'Unauthorized'}), 403

    # Fetch all sales
    sales = Sale.query.join(Product, Sale.product_id == Product.id).join(User, Sale.user_id == User.id).all()

    serialized_sales = [
        {
            "id": sale.id,
            "brand_name": sale.product.brand_name,
            "brand_type": sale.product.brand_type,
            "brand_size": sale.product.brand_size,
            "brand_code": sale.product.brand_code,
            "quantity": sale.quantity,
            "seller": sale.user.username,
            "date_sold": sale.date_sold.strftime('%Y-%m-%d %H:%M:%S'),
            "product_id": sale.product_id,
        }
        for sale in sales
    ]
    return render_template('view_sales.html', sales=serialized_sales)


@app.route('/admin/revoke-sale', methods=['POST'])
def revoke_sale():
    if session.get('role') != 'Admin':
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    sale_id = data.get('sale_id')

    # Fetch sale record
    sale = Sale.query.get(sale_id)
    if not sale:
        return jsonify({'error': 'Sale record not found'}), 404

    # Add quantity back to stock
    stock_entry = Stock.query.filter_by(product_id=sale.product_id).first()
    if stock_entry:
        stock_entry.quantity += sale.quantity
    else:
        # Create a new stock entry if none exists
        stock_entry = Stock(product_id=sale.product_id, quantity=sale.quantity)
        db.session.add(stock_entry)

    # Remove or update the sale record
    db.session.delete(sale)  # Remove the sale record
    db.session.commit()

    return jsonify({'message': 'Sale revoked and stock updated successfully'})

@app.route('/daily-report', methods=['GET'])
def daily_report():
    today = datetime.now().date()
    report_data, grand_total_sales_by_type, grand_total_sale = generate_daily_report_data()
    return render_template('daily_report2.html', 
                           report_data=report_data,
                           grand_total_sales_by_type = grand_total_sales_by_type,
                           grand_total_sale = grand_total_sale, 
                           today=today)


@app.route('/export/pdf', methods=['GET'])
def export_to_pdf():
    today = datetime.now().date()
    report_data, grand_total_sales_by_type, grand_total_sale = generate_daily_report_data()

    # Render the updated report HTML
    rendered_html = render_template(
        'daily_report2.html',
        report_data=report_data,
        grand_total_sales_by_type=grand_total_sales_by_type,
        grand_total_sale=grand_total_sale,
        today=today
    )

    # Convert the rendered HTML to PDF
    pdf_output = io.BytesIO()
    pisa_status = pisa.CreatePDF(io.BytesIO(rendered_html.encode('utf-8')), dest=pdf_output)

    if pisa_status.err:
        return "Error: Unable to generate PDF", 500

    response = make_response(pdf_output.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename="daily_report_{today}.pdf"'
    return response

@app.route('/export/excel', methods=['GET'])
def export_to_excel():
    today = datetime.now().date()
    report_data, grand_total_sales_by_type, grand_total_sale = generate_daily_report_data()

    rows = []
    for brand_type, total_sale in grand_total_sales_by_type.items():
        rows.append({"Brand Type": brand_type, "Total Sale (₹)": total_sale})

    rows.append({"Brand Type": "Grand Total", "Total Sale (₹)": grand_total_sale})

    df = pd.DataFrame(rows)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name=f"Daily Report {today}")

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    response.headers['Content-Disposition'] = f'attachment; filename="daily_report_{today}.xlsx"'
    return response

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')