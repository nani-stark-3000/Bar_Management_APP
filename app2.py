from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, make_response, flash, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, desc, extract
from werkzeug.utils import secure_filename
import os
from datetime import datetime, date, timedelta
import uuid 
import pandas as pd
from PIL import Image
import csv
from io import StringIO

app = Flask(__name__)
app.secret_key = 'New Pavan Restaurant And Bar'

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
    barcode = db.Column(db.String(50), unique=True, nullable=False)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    brand_name = db.Column(db.String(80), nullable=False)
    brand_code = db.Column(db.String(80), nullable=False)
    barcode = db.Column(db.String(100), unique=True, nullable=False)
    brand_type = db.Column(db.String(80), nullable=False)
    brand_size = db.Column(db.String(80), nullable=False)
    image_path = db.Column(db.String(120), nullable=True)  # Image field
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    added_by = db.Column(db.String(80), nullable=False)
    selling_price = db.Column(db.Float, nullable=False, default=0.0)  # Added selling price field

class Stock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    invoice_rate = db.Column(db.Float, nullable=False)  # IR
    mrp = db.Column(db.Float, nullable=False)           # MRP
    added_by = db.Column(db.String(80), nullable=False)
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    product = db.relationship('Product', backref=db.backref('stocks', lazy=True))

class StockHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    invoice_rate = db.Column(db.Float, nullable=False)  # Newly added
    mrp = db.Column(db.Float, nullable=False)           # Newly added
    added_by = db.Column(db.String(80), nullable=False)
    date_added = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    product = db.relationship('Product', backref=db.backref('stock_history', lazy=True))


class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    date_sold = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    invoice_rate = db.Column(db.Float, nullable=False)  # Store invoice rate
    mrp = db.Column(db.Float, nullable=False)           # Store MRP
    selling_price = db.Column(db.Float, nullable=False)  # Store selling price
    profit = db.Column(db.Float, nullable=False)        # Store profit for the sale
    product = db.relationship('Product', backref=db.backref('sales', lazy=True))


class DailyReport(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    report_date = db.Column(db.Date, unique=True, nullable=False)
    report_data = db.Column(db.JSON, nullable=False)  # JSON column for report data
    total_sales_by_type = db.Column(db.JSON, nullable=False)  # JSON for sales by brand type
    total_profit_by_type = db.Column(db.JSON, nullable=False)  # ✅ NEW COLUMN for profit by brand type
    grand_total_sale = db.Column(db.Float, nullable=False)  # Grand total sales
    grand_total_profit = db.Column(db.Float, nullable=False)  # ✅ NEW COLUMN for grand total profit


# Dynamically fetch model classes
MODEL_CLASSES = {
    "User": User,
    "Product": Product,
    "Stock": Stock,
    "StockHistory": StockHistory,
    "Sale": Sale,
    "DailyReport": DailyReport,
}

# Default Admin Creation
with app.app_context():
    db.create_all()
    if not User.query.filter_by(username='admin').first():
        admin_user = User(username='admin', password='admin123', role='Admin', barcode='123456789101')
        db.session.add(admin_user)
        db.session.commit()

# Helper: Calculate total profit
def calculate_profit(selling_price, invoice_rate, quantity):
    return (selling_price - invoice_rate) * quantity


# Routes
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # Check if the request is a barcode-only login attempt
        if request.is_json:
            data = request.get_json()
            barcode = data.get("barcode")
            if barcode:
                user = User.query.filter_by(barcode=barcode).first()
                if user:
                    session['user_id'] = user.id
                    session['role'] = user.role
                    session['username'] = user.username
                    # Redirect to appropriate dashboard
                    redirect_url = url_for(f"{user.role.lower()}_dashboard")
                    return jsonify({"redirect_url": redirect_url})
                return jsonify({"error": "Invalid barcode"}), 401

        # Standard username/password login
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and user.password == password:
            session['user_id'] = user.id
            session['role'] = user.role
            session['username'] = user.username
            return redirect(url_for(f"{user.role.lower()}_dashboard"))
        return "Invalid credentials", 401

    return render_template('login.html')



def redirect_dashboard(role):
    if role == 'Admin':
        return redirect(url_for('admin_dashboard'))
    elif role == 'Supervisor':
        return redirect(url_for('supervisor_dashboard'))
    elif role == 'Salesman':
        return redirect(url_for('salesman_dashboard'))


def get_filtered_sales(filter_type, date_selected):
    today = date.today()
    date_selected = date_selected or today.strftime('%Y-%m-%d')
    records = []
    
    if filter_type == 'daily':
        date_obj = datetime.strptime(date_selected, '%Y-%m-%d').date()
        records = db.session.query(
            Sale.date_sold,
            func.sum(Sale.total_price),
            func.sum(Sale.profit)
        ).filter(func.date(Sale.date_sold) == date_obj).group_by(Sale.date_sold).all()

    elif filter_type == 'monthly':
        year, month = map(int, date_selected.split('-'))
        records = db.session.query(
            extract('day', Sale.date_sold),
            func.sum(Sale.total_price),
            func.sum(Sale.profit)
        ).filter(
            extract('year', Sale.date_sold) == year,
            extract('month', Sale.date_sold) == month
        ).group_by(extract('day', Sale.date_sold)).all()
    
    elif filter_type == 'yearly':
        year = int(date_selected)
        records = db.session.query(
            extract('month', Sale.date_sold),
            func.sum(Sale.total_price),
            func.sum(Sale.profit)
        ).filter(extract('year', Sale.date_sold) == year).group_by(extract('month', Sale.date_sold)).all()
    
    else:
        start_date = today - timedelta(days=7)
        records = db.session.query(
            Sale.date_sold,
            func.sum(Sale.total_price),
            func.sum(Sale.profit)
        ).filter(Sale.date_sold >= start_date).group_by(Sale.date_sold).all()
    
    return records

@app.route('/admin/dashboard/charts', methods=['GET'])
def get_chart_data():
    filter_type = request.args.get('filter', 'daily')
    date_selected = request.args.get('date', '')
    records = get_filtered_sales(filter_type, date_selected)
    
    return jsonify({
        "labels": [str(record[0]) for record in records],
        "datasets": [
            {"label": "Sales", "data": [float(record[1]) for record in records]},
            {"label": "Profit", "data": [float(record[2]) for record in records]}
        ]
    })

@app.route('/dashboard/brand-sales', methods=['GET'])
def brand_sales():
    sales_data = (
        db.session.query(Product.brand_type, func.sum(Sale.total_price).label("total_sales"))
        .join(Sale, Product.id == Sale.product_id)
        .group_by(Product.brand_type)
        .all()
    )
    
    total_sales = sum(item.total_sales for item in sales_data) or 1
    sales_percentages = [(item.total_sales / total_sales) * 100 for item in sales_data]
    
    return jsonify({
        "labels": [item.brand_type for item in sales_data],
        "datasets": [{"label": "Sales %", "data": sales_percentages}]
    })

@app.route('/dashboard/product-sales', methods=['GET'])
def product_sales():
    sort = request.args.get("sort", "sales")
    date_filter = request.args.get("date", None)
    
    query = db.session.query(
        Product.brand_name,
        Product.brand_size,
        Product.selling_price,
        func.avg(Sale.quantity).label("avg_sold")
    ).join(Sale, Product.id == Sale.product_id)
    
    if date_filter:
        query = query.filter(func.date(Sale.date_sold) == date_filter)
    
    query = query.group_by(Product.id)
    query = query.order_by(desc("avg_sold" if sort == "sales" else Product.selling_price))
    
    sales_data = query.all()
    
    return jsonify({
        "labels": [f"{p.brand_name} {p.brand_size}ml - ₹{p.selling_price}" for p in sales_data],
        "datasets": [{"label": "Avg Sold", "data": [p.avg_sold for p in sales_data]}]
    })


@app.route('/admin/add-user', methods=['POST'])
def add_user():
    if 'role' in session and session['role'] == 'Admin':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']

        # Check if the username already exists
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            return "Error: Username already exists!", 400

        # Generate a unique barcode
        barcode = str(uuid.uuid4())[:12]  # Truncate UUID for shorter barcodes

        # Create a new user
        new_user = User(username=username, password=password, role=role, barcode=barcode)
        db.session.add(new_user)
        db.session.commit()

        return redirect(url_for('user_management'))
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
        return redirect(url_for('sale_management'))
    return redirect(url_for('login'))

from PIL import Image

@app.route('/admin/add-product', methods=['GET', 'POST'])
def add_product():
    if 'role' in session and session['role'] in ['Admin', 'Supervisor']:
        if request.method == 'POST':
            try:
                data = request.form
                brand_name = data['brand_name'].strip().replace(" ", "_")
                brand_code = data['brand_code']
                barcode = data['barcode']
                brand_type = data['brand_type'].strip().replace(" ", "_")
                brand_size = data['brand_size'].strip()
                selling_price = float(data['selling_price'])
                added_by = session.get('user_id')

                # Handle image upload
                image_file = request.files.get('image')
                image_path = None

                if image_file and image_file.filename.split('.')[-1].lower() in app.config['ALLOWED_EXTENSIONS']:
                    filename = f"{brand_name}_{brand_type}_{brand_size}.png"
                    image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    save_compressed_image(image_file, image_path)
                else:
                    image_path = "static/uploads/Default.png"

                # Create product
                new_product = Product(
                    brand_name=brand_name,
                    brand_code=brand_code,
                    barcode=barcode,
                    brand_type=brand_type,
                    brand_size=brand_size,
                    selling_price=selling_price,
                    added_by=added_by,
                    image_path=image_path
                )

                db.session.add(new_product)
                db.session.commit()
                flash("Product added successfully!", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"Error adding product: {str(e)}", "danger")
            return redirect(request.referrer)

        return render_template('add_product.html')
    flash("Unauthorized access!", "danger")
    return redirect(url_for('login'))


def save_compressed_image(image_file, path, resolution=(300, 300)):
    """
    Compress and save an image to a specified resolution and path.
    """
    with Image.open(image_file) as img:
        img = img.convert("RGB")  # Ensure RGB mode
        img.thumbnail(resolution)  # Resize image
        img.save(path, format='PNG', optimize=True)

@app.route('/admin/import-products', methods=['GET', 'POST'])
def import_products():
    if 'role' not in session or session['role'] not in ['Admin', 'Supervisor']:
        return jsonify({'message': 'Unauthorized'}), 403

    if request.method == 'POST':
        file = request.files.get('file')
        if not file or file.filename.split('.')[-1].lower() not in ['xlsx', 'csv']:
            return jsonify({'error': 'Invalid file type. Only .xlsx or .csv files are allowed.'}), 400

        try:
            data = pd.read_excel(file) if file.filename.endswith('.xlsx') else pd.read_csv(file)

            for _, row in data.iterrows():
                if not Product.query.filter_by(barcode=row['barcode']).first():
                    product = Product(
                        brand_name=row['brand_name'],
                        brand_code=row['brand_code'],
                        barcode=row['barcode'],
                        brand_type=row['brand_type'],
                        brand_size=row['brand_size'],
                        selling_price=row.get('selling_price', 0.0),
                        image_path=f"static/uploads/{row['image_path']}",
                        added_by=session.get('user_id')
                    )
                    db.session.add(product)

            db.session.commit()
            flash("Products imported successfully!", "success")
        except Exception as e:
            db.session.rollback()
            flash(f"Failed to import products: {str(e)}", "danger")
        return redirect(url_for('view_products'))

    return render_template('import_products.html')


@app.route('/admin/export-products', methods=['GET'])
def export_products():
    export_dir = os.path.join('static', 'files')
    os.makedirs(export_dir, exist_ok=True)

    file_path = os.path.join(export_dir, 'products_export.xlsx')

    products = Product.query.all()

    if not products:
        columns = ['brand_name', 'brand_code', 'barcode', 'brand_type', 'brand_size', 'selling_price', 'image_path']
        pd.DataFrame(columns=columns).to_excel(file_path, index=False, engine='xlsxwriter')
    else:
        data = [vars(p) for p in products]
        df = pd.DataFrame(data).drop('_sa_instance_state', axis=1)
        df.to_excel(file_path, index=False, engine='xlsxwriter')

    return send_file(file_path, as_attachment=True)


@app.route('/admin/upload-images', methods=['GET', 'POST'])
def upload_images():
    if 'role' not in session or session['role'] not in ['Admin', 'Supervisor']:
        return jsonify({'message': 'Unauthorized'}), 403

    if request.method == 'POST':
        files = request.files.getlist('images')
        success_count, error_count = 0, 0

        for image_file in files:
            if image_file.filename.split('.')[-1].lower() not in app.config['ALLOWED_EXTENSIONS']:
                error_count += 1
                continue

            try:
                # Extract product details from the filename
                filename = secure_filename(image_file.filename)
                brand_name, brand_type, brand_size = filename.rsplit('.', 1)[0].split('_')

                # Find product
                product = Product.query.filter_by(
                    brand_name=brand_name.replace("_", " "),
                    brand_type=brand_type.replace("_", " "),
                    brand_size=brand_size
                ).first()

                if not product:
                    error_count += 1
                    continue

                # Save compressed image
                image_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{filename}")
                save_compressed_image(image_file, image_path)
                product.image_path = image_path  # Update product image path
                db.session.commit()
                success_count += 1
            except Exception as e:
                error_count += 1
                continue

        return jsonify({
            'message': f'{success_count} images uploaded successfully, {error_count} errors occurred.'
        }), 200

    return render_template('upload_images.html')

@app.route('/admin/add-stock', methods=['GET', 'POST'])
def add_stock():
    if 'role' in session and session['role'] in ['Admin', 'Supervisor']:
        if request.method == 'POST':
            try:
                data = request.form
                product_id = int(data['product_id'])
                quantity = int(data['quantity'])
                invoice_rate = float(data['invoice_rate'])
                mrp = float(data['mrp'])
                added_by = session['username']
                USE_FIXED_DATE = False  # Set to False for dynamic date logic
                if USE_FIXED_DATE:
                    date_added = datetime.strptime("2025-01-25", "%Y-%m-%d")
                else:
                    date_added = datetime.strptime(data['date_added'], '%Y-%m-%d') if 'date_added' in data else datetime.now()


                # Check for existing stock with matching MRP and Invoice Rate
                existing_stock = Stock.query.filter_by(
                    product_id=product_id,
                    invoice_rate=invoice_rate,
                    mrp=mrp
                ).first()

                if existing_stock:
                    # Update existing stock
                    existing_stock.quantity += quantity
                    existing_stock.date_added = date_added  # Update to the new date
                else:
                    # Add new stock record with a new price set
                    new_stock = Stock(
                        product_id=product_id,
                        quantity=quantity,
                        invoice_rate=invoice_rate,
                        mrp=mrp,
                        added_by=added_by,
                        date_added=date_added
                    )
                    db.session.add(new_stock)

                # Add record to StockHistory
                stock_history_entry = StockHistory(
                    product_id=product_id,
                    quantity=quantity,
                    invoice_rate=invoice_rate,
                    mrp=mrp,
                    added_by=added_by,
                    date_added=date_added
                )
                db.session.add(stock_history_entry)

                db.session.commit()
                flash("Stock added successfully!", "success")
            except Exception as e:
                db.session.rollback()
                flash(f"Error adding stock: {str(e)}", "danger")
            return redirect(url_for('add_stock'))

        # Load product details and most recent stock prices for selection
        products = db.session.query(
            Product.id,
            Product.brand_name,
            Product.brand_code,
            Product.barcode,
            Product.brand_type,
            Product.brand_size,
            Product.image_path,
            Product.selling_price,  # Include selling price
            db.func.max(Stock.invoice_rate).label('recent_invoice_rate'),
            db.func.max(Stock.mrp).label('recent_mrp')
        ).join(Stock, Stock.product_id == Product.id, isouter=True).group_by(Product.id).all()

        product_dicts = [
            {
                "id": product.id,
                "brand_name": product.brand_name,
                "brand_code": product.brand_code,
                "barcode": product.barcode,
                "brand_type": product.brand_type,
                "brand_size": product.brand_size,
                "image_path": product.image_path,
                "selling_price": product.selling_price,  # Add to the frontend
                "invoice_rate": product.recent_invoice_rate or "Undefined",
                "mrp": product.recent_mrp or "Undefined",
            }
            for product in products
        ]

        return render_template('add_stock.html', products=product_dicts, today=datetime.now().strftime('%Y-%m-%d'))
    return jsonify({'message': 'Unauthorized'}), 403

@app.route('/admin/view-products', methods=['GET'])
def view_products():
    products = Product.query.all()
    brand_types = {product.brand_type for product in products}
    brand_sizes = {product.brand_size for product in products}
    selling_prices = [product.selling_price for product in products]

    serialized_products = [
        {
            "id": product.id,
            "brand_name": product.brand_name,
            "brand_type": product.brand_type,
            "brand_size": product.brand_size,
            "brand_code": product.brand_code,
            "barcode": product.barcode,
            "image_path": product.image_path or '',
            "selling_price": product.selling_price  # Include selling price
        }
        for product in products
    ]

    return render_template(
        'view_products.html',
        products=serialized_products,
        filters={
            'types': sorted(brand_types),
            'sizes': sorted(brand_sizes),
            'selling_price_range': (min(selling_prices), max(selling_prices))  # Min and max selling price
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
            Product.brand_type,
            Product.brand_size,
            Product.image_path,
            Product.selling_price,
            db.func.sum(Stock.quantity).label('total_stock')
        ).join(Stock, Stock.product_id == Product.id).group_by(Product.id).all()

        # Fetch stock details grouped by product and pricing
        stock_sets = db.session.query(
            Stock.product_id,
            Stock.invoice_rate,
            Stock.mrp,
            db.func.sum(Stock.quantity).label('quantity'),
            Stock.date_added
        ).group_by(Stock.product_id, Stock.invoice_rate, Stock.mrp, Stock.date_added).all()

        # Organize stock sets by product
        stock_sets_by_product = {}
        for stock in stock_sets:
            if stock.product_id not in stock_sets_by_product:
                stock_sets_by_product[stock.product_id] = []
            stock_sets_by_product[stock.product_id].append({
                "invoice_rate": stock.invoice_rate,
                "mrp": stock.mrp,
                "quantity": stock.quantity,
                "date_added": stock.date_added.strftime('%d-%m-%Y %H:%M:%S')
            })

        # Prepare product data for the frontend
        product_dicts = []
        for product in products:
            product_data = dict(product._mapping)
            product_data["stock_sets"] = stock_sets_by_product.get(product.id, [])
            product_dicts.append(product_data)

        # Generate filters dynamically
        filters = {
            "types": [type_[0] for type_ in db.session.query(Product.brand_type).distinct().all()],
            "sizes": [size[0] for size in db.session.query(Product.brand_size).distinct().all()],
            "price_range": (
                min(p.selling_price for p in products),
                max(p.selling_price for p in products),
            )
        }

        return render_template('view_stock.html', products=product_dicts, filters=filters)
    return jsonify({'message': 'Unauthorized'}), 403

@app.route('/admin/export-stock', methods=['GET'])
def export_stock():
    if 'role' in session and session['role'] in ['Admin', 'Supervisor']:
        # Fetch stock data in database order
        stock_data = db.session.query(
            Product.brand_code,
            Product.brand_name,
            Product.brand_size,
            Product.selling_price,
            Stock.invoice_rate,
            Stock.mrp,
            db.func.sum(Stock.quantity).label('quantity')
        ).join(Stock, Stock.product_id == Product.id).group_by(
            Product.id, Stock.invoice_rate, Stock.mrp
        ).all()

        # Prepare the CSV
        csv_file = StringIO()
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(['Brand Code', 'Product Name', 'Size', 'Selling Price', 'Invoice Rate', 'MRP', 'Quantity'])

        for row in stock_data:
            csv_writer.writerow([
                row.brand_code,
                row.brand_name,
                f"{row.brand_size}ml",
                f"{row.selling_price:.2f}",
                f"{row.invoice_rate:.2f}",
                f"{row.mrp:.2f}",
                row.quantity, 
            ])

        # Return the CSV file
        csv_file.seek(0)
        return Response(
            csv_file.getvalue(),
            mimetype='text/csv',
            headers={"Content-Disposition": "attachment; filename=stock_data.csv"},
        )
    return jsonify({'message': 'Unauthorized'}), 403

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
            StockHistory.invoice_rate,
            StockHistory.mrp,
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
            'invoice_rate': h.invoice_rate,
            'mrp': h.mrp,
            'date_added': h.date_added.strftime('%d-%m-%Y %I:%M %p'),  # Date in DD-MM-YYYY, Time in 12-hour format
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

        # Find the specific stock record with matching invoice rate and MRP
        stock_entry = Stock.query.filter_by(
            product_id=product_id,
            invoice_rate=history_entry.invoice_rate,
            mrp=history_entry.mrp
        ).first()

        if stock_entry:
            stock_entry.quantity -= history_entry.quantity
            if stock_entry.quantity <= 0:
                db.session.delete(stock_entry)  # Remove stock entry if quantity is zero or less
        else:
            return jsonify({'error': 'Matching stock entry not found'}), 404

        # Delete the history entry
        db.session.delete(history_entry)
        db.session.commit()

        return jsonify({'message': 'Stock addition revoked successfully'})
    return jsonify({'error': 'Unauthorized'}), 403

@app.route('/admin/edit-stock', methods=['POST'])
def edit_stock():
    if 'role' in session and session['role'] in ['Admin', 'Supervisor']:
        data = request.get_json()
        history_id = data.get('history_id')
        new_quantity = int(data.get('new_quantity'))

        # Fetch stock history entry
        history_entry = StockHistory.query.get(history_id)
        if not history_entry:
            return jsonify({'error': 'Stock history entry not found'}), 404

        product_id = history_entry.product_id

        # Fetch corresponding stock entry
        stock_entry = Stock.query.filter_by(
            product_id=product_id,
            invoice_rate=history_entry.invoice_rate,
            mrp=history_entry.mrp
        ).first()

        if not stock_entry:
            return jsonify({'error': 'Matching stock entry not found'}), 404

        # Adjust stock quantity based on difference
        quantity_difference = new_quantity - history_entry.quantity
        stock_entry.quantity += quantity_difference

        # Update stock history entry
        history_entry.quantity = new_quantity

        db.session.commit()
        return jsonify({'message': 'Stock entry updated successfully.'})

    return jsonify({'error': 'Unauthorized'}), 403


@app.template_filter('to12hr')
def to12hr(value):
    """
    Convert a 24-hour time string to 12-hour format with AM/PM.
    """
    try:
        from datetime import datetime
        return datetime.strptime(value, "%H:%M:%S").strftime("%I:%M %p")
    except ValueError:
        return value
    
@app.template_filter('datetimeformat')
def datetimeformat(value):
    """
    Custom filter to format datetime in 'DD-MMM-YYYY HH:MM AM/PM' format.
    """
    if isinstance(value, datetime):
        return value.strftime('%d-%b-%Y %I:%M %p')
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
            product.brand_type = data['brand_type']
            product.brand_size = data['brand_size']
            product.selling_price = data['selling_price']

            # Handle image upload (optional for editing)
            image_file = request.files.get('image')
            if image_file:
                if image_file and image_file.filename.split('.')[-1].lower() in app.config['ALLOWED_EXTENSIONS']:
                    filename = f"{data['brand_name']}_{data['brand_type']}_{data['brand_size']}.png"
                    image_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    save_compressed_image(image_file, image_path)
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
            "image_path": product.image_path,
        }
        for product in products
    ]

    # Handle different possible sale list formats
    sale_list = session.get('sale_list', [])
    
    # Normalize sale list to consistent format
    normalized_sale_list = []
    
    if isinstance(sale_list, dict):
        # Convert dictionary to list of values
        sale_list = list(sale_list.values())
    
    # Ensure each item is a dictionary and has required keys
    for item in sale_list:
        if isinstance(item, dict):
            # Existing dictionary item
            try:
                normalized_item = {
                    "product_id": item.get("product_id") or item.get("id"),
                    "brand_name": item.get("brand_name", "Unknown"),
                    "brand_type": item.get("brand_type", ""),
                    "brand_size": item.get("brand_size", ""),
                    "selling_price": float(item.get("selling_price", 0)),
                    "quantity": int(item.get("quantity", 1))
                }
                normalized_sale_list.append(normalized_item)
            except (TypeError, ValueError):
                continue
        elif isinstance(item, list):
            # Handle potential list format
            try:
                normalized_item = {
                    "product_id": item[0] if len(item) > 0 else None,
                    "brand_name": item[1] if len(item) > 1 else "Unknown",
                    "selling_price": float(item[2]) if len(item) > 2 else 0,
                    "quantity": int(item[3]) if len(item) > 3 else 1
                }
                normalized_sale_list.append(normalized_item)
            except (TypeError, ValueError, IndexError):
                continue

    # Update session with normalized list
    session['sale_list'] = normalized_sale_list

    # Calculate grand total safely
    grand_total = sum(
        item.get("selling_price", 0) * item.get("quantity", 0)
        for item in normalized_sale_list
    )

    today = datetime.now()  # Get the current date

    return render_template(
        "sale_management.html",
        products=serialized_products,
        sale_list=normalized_sale_list,
        grand_total=grand_total,
        today=today
    )

@app.route('/sales/add-product', methods=['POST'])
def add_product_to_sale():
    data = request.get_json()
    product_id = data.get("product_id")
    quantity_to_add = int(data.get("quantity", 1))

    if quantity_to_add <= 0:
        return jsonify({"error": "Invalid quantity specified."}), 400

    if "sale_list" not in session:
        session["sale_list"] = []

    sale_list = session["sale_list"]

    # Fetch available stock
    stock_entries = Stock.query.filter_by(product_id=product_id).order_by(Stock.date_added).all()
    available_quantity = sum(stock.quantity for stock in stock_entries)

    if available_quantity < quantity_to_add:
        return jsonify({"error": "Not enough stock available."}), 400

    # Check if the product is already in the list
    for item in sale_list:
        if item.get("product_id") == product_id:
            item["quantity"] += quantity_to_add
            session["sale_list"] = sale_list
            return jsonify({"message": f"Added {quantity_to_add} more items.", "sale_list": sale_list})

    # If not in list, add new product
    product = Product.query.get(product_id)
    new_item = {
        "product_id": product_id,
        "brand_name": product.brand_name,
        "brand_type": product.brand_type,
        "brand_size": product.brand_size,
        "selling_price": product.selling_price,
        "quantity": quantity_to_add,
    }
    sale_list.append(new_item)
    session["sale_list"] = sale_list
    return jsonify({"message": f"Added {quantity_to_add} items to sale.", "sale_list": sale_list})


@app.route('/sales/update-quantity', methods=['POST'])
def update_quantity():
    data = request.get_json()
    product_id = data.get("product_id")
    quantity_change = int(data.get("quantity_change"))

    sale_list = session.get("sale_list", [])

    for item in sale_list:
        if item.get("product_id") == product_id:
            # Fetch available stock
            stock_entries = Stock.query.filter_by(product_id=product_id).order_by(Stock.date_added).all()
            available_quantity = sum(stock.quantity for stock in stock_entries)

            # Calculate new quantity
            new_quantity = item["quantity"] + quantity_change

            if new_quantity > available_quantity:
                return jsonify({"error": "Not enough stock available."}), 400

            # Remove item if quantity reaches zero
            if new_quantity <= 0:
                sale_list.remove(item)
            else:
                item["quantity"] = new_quantity

            session["sale_list"] = sale_list
            return jsonify({"message": "Quantity updated successfully.", "sale_list": sale_list})

    return jsonify({"error": "Product not found in sale list."}), 404


@app.route('/sales/confirm-sale', methods=['POST'])
def confirm_sale():
    if "sale_list" not in session or not session["sale_list"]:
        return jsonify({"error": "No sale list to confirm."}), 400

    sale_list = session["sale_list"]
    user_id = session.get("username")

    data = request.get_json()
    sale_date = data.get("sale_date")

    from datetime import datetime
    sale_date = datetime.strptime(sale_date, "%Y-%m-%d") if sale_date else datetime.now()

    for item in sale_list:
        product_id = item["product_id"]
        quantity_to_deduct = item["quantity"]

        stock_entries = Stock.query.filter_by(product_id=product_id).order_by(Stock.date_added).all()
        remaining_quantity = quantity_to_deduct

        for stock_entry in stock_entries:
            if remaining_quantity <= 0:
                break

            deduct_quantity = min(remaining_quantity, stock_entry.quantity)
            if deduct_quantity > 0:
                sale = Sale(
                    product_id=product_id,
                    user_id=user_id,
                    quantity=deduct_quantity,
                    total_price=deduct_quantity * item["selling_price"],
                    date_sold=sale_date,
                    invoice_rate=stock_entry.invoice_rate,
                    mrp=stock_entry.mrp,
                    selling_price=item["selling_price"],
                    profit=(item["selling_price"] - stock_entry.invoice_rate) * deduct_quantity,
                )
                db.session.add(sale)
                stock_entry.quantity -= deduct_quantity
                remaining_quantity -= deduct_quantity

        if remaining_quantity > 0:
            return jsonify({"error": "Stock mismatch detected. Sale cannot be processed."}), 400

    db.session.commit()
    session.pop("sale_list", None)
    return jsonify({"message": "Sale confirmed successfully."})

# Other routes remain the same as in the original code
@app.route('/sales/remove-product', methods=['POST'])
def remove_product_from_sale():
    data = request.get_json()
    sale_item_key = data.get("sale_item_key")

    if not sale_item_key:
        return jsonify({"error": "Sale item key is required."}), 400

    sale_list = session.get("sale_list", {})

    if sale_item_key in sale_list:
        sale_list[sale_item_key]["quantity"] -= 1
        if sale_list[sale_item_key]["quantity"] <= 0:
            del sale_list[sale_item_key]

        session["sale_list"] = sale_list
        return jsonify({"message": "Product removed successfully.", "sale_list": sale_list})

    return jsonify({"error": "Product not found in sale list."}), 404

@app.route('/sales/reject-sale', methods=['POST'])
def reject_sale():
    if "sale_list" in session:
        session.pop("sale_list", None)

    message = "Sale list cleared successfully."
    return jsonify({"message": message})

@app.route('/sales/view-sales', methods=['GET'])
def view_sales():
    if session.get('role') not in ['Admin', 'Supervisor', 'Salesman']:
        return jsonify({'error': 'Unauthorized'}), 403

    # Fetch all sales records with related data
    sales = Sale.query.join(Product, Sale.product_id == Product.id)\
        .join(User, Sale.user_id == User.username)\
        .order_by(Sale.date_sold.desc()).all()

    # Serialize sales data
    serialized_sales = [
        {
            "id": sale.id,
            "brand_name": sale.product.brand_name,
            "brand_type": sale.product.brand_type,
            "brand_size": sale.product.brand_size,
            "quantity": sale.quantity,
            "selling_price": sale.selling_price,
            "total_price": sale.total_price,
            "date_sold": sale.date_sold.strftime('%Y-%m-%d'),
            "time_sold": sale.date_sold.strftime('%I:%M %p'),
            "added_by": sale.user_id,  # Username of the user who added the sale
        }
        for sale in sales
    ]

    # Calculate grand totals
    grand_total_sales = sum(sale["total_price"] for sale in serialized_sales)

    return render_template(
        'view_sales.html',
        sales=serialized_sales,
        grand_total_sales=grand_total_sales,
    )


@app.route('/sales/revoke', methods=['POST'])
def revoke_sale():
    if session.get('role') != 'Admin':
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    sale_id = data.get('sale_id')
    new_quantity = int(data.get('new_quantity'))

    # Fetch the sale record
    sale = Sale.query.get(sale_id)
    if not sale:
        return jsonify({'error': 'Sale record not found'}), 404

    stock_entries = Stock.query.filter_by(
        product_id=sale.product_id,
        invoice_rate=sale.invoice_rate,
        mrp=sale.mrp
    ).order_by(Stock.date_added).all()

    quantity_difference = new_quantity - sale.quantity

    if quantity_difference > 0:  # Increase sale quantity
        remaining_quantity = quantity_difference
        for stock in stock_entries:
            if remaining_quantity <= 0:
                break
            if stock.quantity >= remaining_quantity:
                stock.quantity -= remaining_quantity
                remaining_quantity = 0
            else:
                remaining_quantity -= stock.quantity
                stock.quantity = 0

        if remaining_quantity > 0:
            db.session.rollback()
            return jsonify({'error': 'Not enough stock available to increase sale quantity.'}), 400

    elif quantity_difference < 0:  # Decrease sale quantity
        remaining_quantity = abs(quantity_difference)
        for stock in stock_entries:
            if remaining_quantity <= 0:
                break
            stock.quantity += min(stock.quantity, remaining_quantity)
            remaining_quantity = 0

    # Update sale record
    sale.quantity = new_quantity
    sale.total_price = new_quantity * sale.selling_price
    sale.profit = sale.total_price - (new_quantity * sale.invoice_rate)

    db.session.commit()

    return jsonify({'message': 'Sale quantity updated successfully.'})

@app.route('/sales/delete/<int:sale_id>', methods=['DELETE'])
def delete_sale(sale_id):
    if session.get('role') != 'Admin':
        return jsonify({'error': 'Unauthorized'}), 403

    # Fetch the sale record
    sale = Sale.query.get(sale_id)
    if not sale:
        return jsonify({'error': 'Sale record not found'}), 404

    # Restore stock
    stock_entries = Stock.query.filter_by(
        product_id=sale.product_id,
        invoice_rate=sale.invoice_rate,
        mrp=sale.mrp
    ).order_by(Stock.date_added).all()

    remaining_quantity = sale.quantity
    for stock in stock_entries:
        stock.quantity += min(stock.quantity, remaining_quantity)
        remaining_quantity = 0
        if remaining_quantity <= 0:
            break

    # Delete the sale record
    db.session.delete(sale)
    db.session.commit()

    return jsonify({'message': 'Sale record deleted successfully.'})


@app.route('/daily-report', methods=['GET'])
def daily_report():
    requested_date = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    requested_date = datetime.strptime(requested_date, '%Y-%m-%d').date()

    # Get the first stock entry date
    first_stock_date = db.session.query(func.min(Stock.date_added)).scalar()
    if not first_stock_date:
        return "No stock data found.", 404

    first_stock_date = first_stock_date.date()  # Convert to date format
    today = datetime.now().date()

    # Check if report exists for the requested date
    daily_report = DailyReport.query.filter_by(report_date=requested_date).first()

    if daily_report and requested_date != datetime.now().date():
        # Use stored report for past dates
        report_data = daily_report.report_data
        total_sales_by_type = daily_report.total_sales_by_type
        total_profit_by_type = daily_report.total_profit_by_type  # ✅ Fetch stored profit data
        grand_total_sale = daily_report.grand_total_sale
        grand_total_profit = daily_report.grand_total_profit  # ✅ Fetch stored grand profit
    else:
        if requested_date < today and requested_date >= first_stock_date:
            ensure_daily_reports()

        # Generate report for today or if no stored report is found
        report_data, total_sales_by_type, total_profit_by_type, grand_total_sale, grand_total_profit = generate_report_data(requested_date)

        # Store report if it's today's date
        if requested_date == datetime.now().date():
            if daily_report:
                # Update existing entry
                daily_report.report_data = report_data
                daily_report.total_sales_by_type = total_sales_by_type
                daily_report.total_profit_by_type = total_profit_by_type  # ✅ Store profit data
                daily_report.grand_total_sale = grand_total_sale
                daily_report.grand_total_profit = grand_total_profit  # ✅ Store grand total profit
            else:
                # Create a new entry
                new_report = DailyReport(
                    report_date=requested_date,
                    report_data=report_data,
                    total_sales_by_type=total_sales_by_type,
                    total_profit_by_type=total_profit_by_type,  # ✅ Store profit data
                    grand_total_sale=grand_total_sale,
                    grand_total_profit=grand_total_profit  # ✅ Store grand total profit
                )
                db.session.add(new_report)
            db.session.commit()

    return render_template(
        'daily_report.html',
        today=requested_date,
        report_data=report_data,
        total_sales_by_type=total_sales_by_type,
        total_profit_by_type=total_profit_by_type,  # ✅ Pass profit data to template
        grand_total_sale=grand_total_sale,
        grand_total_profit=grand_total_profit  # ✅ Pass grand total profit
    )


def generate_report_data(requested_date):
    report_data = {}
    total_sales_by_type = {}
    total_profit_by_type = {}  # Store brand type-wise profit
    grand_total_sale = 0
    grand_total_profit = 0  # Store total profit across all products

    products = Product.query.all()
    for product in products:
        if product.brand_type not in report_data:
            report_data[product.brand_type] = {}

        if product.brand_name not in report_data[product.brand_type]:
            report_data[product.brand_type][product.brand_name] = {
                "sizes": {},
                "total": {"ob": 0, "cb": 0, "sale": 0, "amount": 0, "new_stock": 0, "profit": 0},
            }

        # Fetch current stock for this product
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
                func.date(Sale.date_sold) == requested_date
            )
            .scalar()
            or 0
        )

        # Fetch today's stock additions
        today_stock_added = (
            db.session.query(func.sum(StockHistory.quantity))
            .filter(
                StockHistory.product_id == product.id,
                func.date(StockHistory.date_added) == requested_date
            )
            .scalar()
            or 0
        )

        # Fetch today's profit
        today_profit = (
            db.session.query(func.sum(Sale.profit))
            .filter(
                Sale.product_id == product.id,
                func.date(Sale.date_sold) == requested_date
            )
            .scalar()
            or 0
        )

        # Calculate OB and CB
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
            "profit": today_profit,  # Include profit per product size
        }

        # Update totals
        totals = report_data[product.brand_type][product.brand_name]["total"]
        totals["ob"] += ob
        totals["cb"] += cb
        totals["sale"] += sale
        totals["amount"] += amount
        totals["new_stock"] += today_stock_added
        totals["profit"] += today_profit  # Include profit in total

        # Update brand type-wise profit
        total_sales_by_type[product.brand_type] = total_sales_by_type.get(product.brand_type, 0) + amount
        total_profit_by_type[product.brand_type] = total_profit_by_type.get(product.brand_type, 0) + today_profit

        # Update grand totals
        grand_total_sale += amount
        grand_total_profit += today_profit

    return report_data, total_sales_by_type, total_profit_by_type, grand_total_sale, grand_total_profit

def ensure_daily_reports():
    """
    Ensure daily reports exist for all past dates starting from the first stock entry.
    """
    # Get the first stock entry date
    first_stock_date = db.session.query(func.min(Stock.date_added)).scalar()
    if not first_stock_date:
        print("No stock data found. Skipping report generation.")
        return
    
    first_stock_date = first_stock_date.date()  # Convert to date format
    today = datetime.now().date()

    # Iterate through each date from first stock date to today
    current_date = first_stock_date
    while current_date <= today:
        # Check if a daily report exists for this date
        existing_report = DailyReport.query.filter_by(report_date=current_date).first()

        if not existing_report:
            print(f"Generating missing report for {current_date}...")
            report_data, total_sales_by_type, total_profit_by_type, grand_total_sale, grand_total_profit = generate_report_data(current_date)

            # Save the generated report to the database
            new_report = DailyReport(
                report_date=current_date,
                report_data=report_data,
                total_sales_by_type=total_sales_by_type,
                total_profit_by_type=total_profit_by_type,
                grand_total_sale=grand_total_sale,
                grand_total_profit=grand_total_profit
            )
            db.session.add(new_report)
            db.session.commit()
        else:
            print(f"Report already exists for {current_date}. Skipping.")

        current_date += timedelta(days=1)  # Move to next date


@app.route('/admin/data-management', methods=['GET', 'POST'])
def data_management():
    """
    View and manage data for various models.
    """
    if request.method == 'POST':
        data_type = request.form.get('data_type')
        if not data_type or data_type not in MODEL_CLASSES:
            flash("Invalid data type selected.", "danger")
            return redirect(url_for('data_management'))

        model_class = MODEL_CLASSES[data_type]
        records = model_class.query.all()
        columns = [col.name for col in model_class.__table__.columns]

        # Convert records into dictionaries
        data = [
            {col: getattr(record, col) for col in columns} for record in records
        ]

        return render_template(
            'data_management.html',
            data_type=data_type,
            data=data,
            columns=columns,
        )

    return render_template('data_management.html')


@app.route('/admin/edit-record/<string:data_type>/<int:record_id>', methods=['GET', 'POST'])
def edit_record(data_type, record_id):
    """
    Fetch or update a specific record based on the data type.
    """
    if data_type not in MODEL_CLASSES:
        return jsonify({"success": False, "error": "Invalid data type."}), 400

    model_class = MODEL_CLASSES[data_type]
    record = model_class.query.get(record_id)

    if request.method == 'GET':
        if not record:
            return jsonify({"success": False, "error": "Record not found."}), 404

        record_data = {
            col.name: getattr(record, col.name)
            for col in model_class.__table__.columns
        }
        return jsonify({"success": True, "record": record_data})

    if request.method == 'POST':
        data = request.get_json()
        if not record:
            return jsonify({"success": False, "error": "Record not found."}), 404

        try:
            for key, value in data.items():
                setattr(record, key, value)
            db.session.commit()
            return jsonify({"success": True})
        except Exception as e:
            db.session.rollback()
            return jsonify({"success": False, "error": str(e)}), 500


@app.route('/admin/delete-record/<string:data_type>/<int:record_id>', methods=['POST'])
def delete_record(data_type, record_id):
    """
    Delete a record from the database.
    """
    if data_type not in MODEL_CLASSES:
        return jsonify({"success": False, "error": "Invalid data type."}), 400

    model_class = MODEL_CLASSES[data_type]
    record = model_class.query.get(record_id)

    if not record:
        return jsonify({"success": False, "error": "Record not found."}), 404

    try:
        db.session.delete(record)
        db.session.commit()
        flash(f"{data_type} record deleted successfully!", "success")
        return redirect(url_for('data_management'))
    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting record: {e}", "danger")
        return redirect(url_for('data_management'))


@app.route('/admin/export/<string:data_type>', methods=['GET'])
def export_data(data_type):
    """
    Export data to a CSV file.
    """
    if data_type not in MODEL_CLASSES:
        flash("Invalid data type for export.", "danger")
        return redirect(url_for('data_management'))

    model_class = MODEL_CLASSES[data_type]
    records = model_class.query.all()
    columns = [col.name for col in model_class.__table__.columns]

    csv_file = StringIO()
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(columns)

    for record in records:
        csv_writer.writerow([getattr(record, col) for col in columns])

    csv_file.seek(0)

    return Response(
        csv_file,
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename={data_type}.csv"},
    )


from datetime import datetime

@app.route('/admin/import/<string:data_type>', methods=['POST'])
def import_data(data_type):
    """
    Import data from a CSV file and handle date fields properly.
    """
    if data_type not in MODEL_CLASSES:
        return jsonify({"success": False, "error": "Invalid data type."}), 400

    model_class = MODEL_CLASSES[data_type]
    file = request.files.get("file")

    if not file:
        return jsonify({"success": False, "error": "No file uploaded."}), 400

    try:
        csv_file = StringIO(file.stream.read().decode("utf-8"))
        csv_reader = csv.DictReader(csv_file)

        for row in csv_reader:
            # Prepare the record data
            record_data = {}
            for key, value in row.items():
                if not value:
                    record_data[key] = None  # Handle empty values as None
                    continue

                # Check if the column is a date or datetime field
                column_type = getattr(model_class, key).type
                if isinstance(column_type, db.DateTime):
                    record_data[key] = datetime.strptime(value, "%d-%m-%Y")  # Adjust format as per your CSV
                elif isinstance(column_type, db.Date):
                    record_data[key] = datetime.strptime(value, "%d-%m-%Y").date()
                else:
                    record_data[key] = value  # Non-date fields remain unchanged

            # Create a new record
            record = model_class(**record_data)
            db.session.add(record)

        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/admin/delete-all/<string:data_type>', methods=['POST'])
def delete_all_data(data_type):
    """
    Delete all records from the selected data type.
    """
    if data_type not in MODEL_CLASSES:
        return jsonify({"success": False, "error": "Invalid data type."}), 400

    model_class = MODEL_CLASSES[data_type]

    try:
        num_deleted = db.session.query(model_class).delete()
        db.session.commit()
        return jsonify({"success": True, "message": f"Deleted {num_deleted} records."})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
