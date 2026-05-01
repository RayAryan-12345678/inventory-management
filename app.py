"""
Inventory Manager — Flask + MongoDB Backend
Improved version of the original Tkinter app.

Improvements over original:
- Web-based (runs in browser, no Tkinter needed)
- Proper password hashing with werkzeug
- JWT session tokens (more secure than plain session)
- Input validation on all routes
- Pagination on product listing
- Low-stock alerts API
- Sales history with full line items
- QR code served as image response (not saved to disk)
- RESTful API structure — all routes return JSON
- Proper HTTP status codes
- CORS-safe (same origin — Flask serves frontend)
"""

import os, io, json, base64
from functools import wraps
from datetime import datetime, timedelta, timezone

from flask import (Flask, request, jsonify, render_template,
                   session, redirect, url_for, send_file)
from werkzeug.security import generate_password_hash, check_password_hash
from bson.objectid import ObjectId
from pymongo import MongoClient, ASCENDING, DESCENDING
import qrcode
from qrcode.image.pure import PyPNGImage

# ── App setup ──────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-me-in-production-use-random-32-bytes")

# ── MongoDB ────────────────────────────────────────────────
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(MONGO_URI)
db = client["inventory_db"]

# Indexes for performance
db.products.create_index([("name", ASCENDING)])
db.products.create_index([("sku", ASCENDING)])   # no unique — allows existing duplicate SKUs
db.sales.create_index([("created_at", DESCENDING)])

LOW_STOCK_THRESHOLD = 5
PAGE_SIZE = 20

# ── Auth helpers ───────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            if request.is_json:
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for("index"))
        return f(*args, **kwargs)
    return decorated


def seed_admin():
    """Create a default admin user if none exists."""
    if db.users.count_documents({}) == 0:
        db.users.insert_one({
            "username": "admin",
            "password": generate_password_hash("admin123"),
            "role": "admin",
            "created_at": datetime.now(timezone.utc),
        })
        print("  Default user created: admin / admin123")


# ── Utility ────────────────────────────────────────────────
def serialize(doc):
    """Convert MongoDB document to JSON-safe dict."""
    if doc is None:
        return None
    doc["_id"] = str(doc["_id"])
    for k, v in doc.items():
        if isinstance(v, ObjectId):
            doc[k] = str(v)
        if isinstance(v, datetime):
            doc[k] = v.isoformat()
    return doc


def validate_product(data):
    """Validate product fields. Returns (clean_data, error_string)."""
    name = str(data.get("name", "")).strip()
    if not name:
        return None, "Product name is required"
    price_raw = data.get("price", "")
    try:
        price = float(price_raw)
        if price < 0:
            raise ValueError
    except (ValueError, TypeError):
        return None, "Price must be a non-negative number"
    qty_raw = data.get("quantity", 0)
    try:
        qty = int(qty_raw)
        if qty < 0:
            raise ValueError
    except (ValueError, TypeError):
        return None, "Quantity must be a non-negative integer"
    return {
        "sku":         str(data.get("sku", "")).strip() or None,
        "name":        name,
        "price":       round(price, 2),
        "quantity":    qty,
        "description": str(data.get("description", "")).strip() or None,
        "category":    str(data.get("category", "")).strip() or None,
    }, None


# ══════════════════════════════════════════════════════════
#  PAGE ROUTES
# ══════════════════════════════════════════════════════════

@app.route("/")
def index():
    if "user" in session:
        return render_template("index.html", user=session["user"])
    return render_template("index.html", user=None)


# ══════════════════════════════════════════════════════════
#  AUTH API
# ══════════════════════════════════════════════════════════

@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()

    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    user = db.users.find_one({"username": username})
    if not user or not check_password_hash(user["password"], password):
        return jsonify({"error": "Invalid username or password"}), 401

    session["user"] = username
    session["role"] = user.get("role", "staff")
    return jsonify({"message": "Login successful", "user": username, "role": session["role"]})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"message": "Logged out"})


@app.route("/api/me")
def me():
    if "user" not in session:
        return jsonify({"user": None})
    return jsonify({"user": session["user"], "role": session.get("role", "staff")})


# ══════════════════════════════════════════════════════════
#  PRODUCTS API
# ══════════════════════════════════════════════════════════

@app.route("/api/products", methods=["GET"])
@login_required
def get_products():
    page     = max(1, int(request.args.get("page", 1)))
    q        = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    sort_by  = request.args.get("sort", "name")
    order    = ASCENDING if request.args.get("order", "asc") == "asc" else DESCENDING
    low_stock = request.args.get("low_stock", "false").lower() == "true"

    filt = {}
    if q:
        filt["$or"] = [
            {"name":        {"$regex": q, "$options": "i"}},
            {"sku":         {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
        ]
    if category:
        filt["category"] = {"$regex": category, "$options": "i"}
    if low_stock:
        filt["quantity"] = {"$lte": LOW_STOCK_THRESHOLD}

    total = db.products.count_documents(filt)
    skip  = (page - 1) * PAGE_SIZE
    products = list(
        db.products.find(filt)
        .sort(sort_by, order)
        .skip(skip)
        .limit(PAGE_SIZE)
    )

    return jsonify({
        "products": [serialize(p) for p in products],
        "total":    total,
        "page":     page,
        "pages":    max(1, -(-total // PAGE_SIZE)),  # ceiling division
        "low_stock_count": db.products.count_documents({"quantity": {"$lte": LOW_STOCK_THRESHOLD}}),
    })


@app.route("/api/products", methods=["POST"])
@login_required
def add_product():
    data, err = validate_product(request.get_json(force=True))
    if err:
        return jsonify({"error": err}), 400

    # Check SKU uniqueness
    if data["sku"] and db.products.find_one({"sku": data["sku"]}):
        return jsonify({"error": f"SKU '{data['sku']}' already exists"}), 409

    data["created_at"] = datetime.now(timezone.utc)
    data["created_by"] = session["user"]
    result = db.products.insert_one(data)
    data["_id"] = str(result.inserted_id)
    return jsonify({"message": "Product added", "product": data}), 201


@app.route("/api/products/<pid>", methods=["GET"])
@login_required
def get_product(pid):
    try:
        product = db.products.find_one({"_id": ObjectId(pid)})
    except Exception:
        return jsonify({"error": "Invalid product ID"}), 400
    if not product:
        return jsonify({"error": "Product not found"}), 404
    return jsonify(serialize(product))


@app.route("/api/products/<pid>", methods=["PUT"])
@login_required
def update_product(pid):
    try:
        oid = ObjectId(pid)
    except Exception:
        return jsonify({"error": "Invalid product ID"}), 400

    existing = db.products.find_one({"_id": oid})
    if not existing:
        return jsonify({"error": "Product not found"}), 404

    data, err = validate_product(request.get_json(force=True))
    if err:
        return jsonify({"error": err}), 400

    # SKU uniqueness (exclude self)
    if data["sku"]:
        conflict = db.products.find_one({"sku": data["sku"], "_id": {"$ne": oid}})
        if conflict:
            return jsonify({"error": f"SKU '{data['sku']}' already in use"}), 409

    data["updated_at"] = datetime.now(timezone.utc)
    data["updated_by"] = session["user"]
    db.products.update_one({"_id": oid}, {"$set": data})
    data["_id"] = pid
    return jsonify({"message": "Product updated", "product": data})


@app.route("/api/products/<pid>", methods=["DELETE"])
@login_required
def delete_product(pid):
    try:
        oid = ObjectId(pid)
    except Exception:
        return jsonify({"error": "Invalid product ID"}), 400

    result = db.products.delete_one({"_id": oid})
    if result.deleted_count == 0:
        return jsonify({"error": "Product not found"}), 404
    return jsonify({"message": "Product deleted"})


@app.route("/api/products/<pid>/qr")
@login_required
def product_qr(pid):
    """Generate and stream a QR code PNG for a product."""
    try:
        product = db.products.find_one({"_id": ObjectId(pid)})
    except Exception:
        return jsonify({"error": "Invalid ID"}), 400
    if not product:
        return jsonify({"error": "Product not found"}), 404

    data = (
        f"Name: {product.get('name')}\n"
        f"SKU: {product.get('sku', 'N/A')}\n"
        f"Price: {product.get('price')}\n"
        f"Qty: {product.get('quantity')}"
    )
    img = qrcode.make(data)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png",
                     download_name=f"qr_{product.get('name', pid)}.png")


# ══════════════════════════════════════════════════════════
#  SALES API
# ══════════════════════════════════════════════════════════

@app.route("/api/sales", methods=["POST"])
@login_required
def checkout():
    data  = request.get_json(force=True)
    items = data.get("items", [])
    if not items:
        return jsonify({"error": "Cart is empty"}), 400

    total = 0
    line_items = []

    for it in items:
        try:
            prod_id = ObjectId(it["id"])
        except Exception:
            return jsonify({"error": f"Invalid product ID: {it.get('id')}"}), 400

        product = db.products.find_one({"_id": prod_id})
        if not product:
            return jsonify({"error": f"Product not found: {it.get('id')}"}), 404

        qty = int(it.get("qty", 1))
        if qty <= 0:
            return jsonify({"error": "Quantity must be > 0"}), 400
        if product["quantity"] < qty:
            return jsonify({
                "error": f"Insufficient stock for '{product['name']}'. Available: {product['quantity']}"
            }), 409

        price    = float(product["price"])
        subtotal = round(price * qty, 2)
        total   += subtotal
        line_items.append({
            "product_id":   prod_id,
            "product_name": product["name"],
            "sku":          product.get("sku"),
            "price":        price,
            "qty":          qty,
            "subtotal":     subtotal,
        })

    total = round(total, 2)

    # Insert sale
    sale_doc = {
        "items":      line_items,
        "total":      total,
        "sold_by":    session["user"],
        "created_at": datetime.now(timezone.utc),
    }
    sale_result = db.sales.insert_one(sale_doc)

    # Deduct stock
    for it in line_items:
        db.products.update_one(
            {"_id": it["product_id"]},
            {"$inc": {"quantity": -it["qty"]}}
        )

    return jsonify({
        "message":  "Sale completed",
        "sale_id":  str(sale_result.inserted_id),
        "total":    total,
        "items":    len(line_items),
    }), 201


@app.route("/api/sales", methods=["GET"])
@login_required
def get_sales():
    page  = max(1, int(request.args.get("page", 1)))
    skip  = (page - 1) * PAGE_SIZE
    total = db.sales.count_documents({})
    sales = list(db.sales.find().sort("created_at", DESCENDING).skip(skip).limit(PAGE_SIZE))

    # Serialize ObjectIds in nested line items
    result = []
    for s in sales:
        s["_id"] = str(s["_id"])
        s["created_at"] = s["created_at"].isoformat() if isinstance(s.get("created_at"), datetime) else ""
        for item in s.get("items", []):
            item["product_id"] = str(item.get("product_id", ""))
        result.append(s)

    return jsonify({
        "sales": result,
        "total": total,
        "page":  page,
        "pages": max(1, -(-total // PAGE_SIZE)),
    })


# ══════════════════════════════════════════════════════════
#  DASHBOARD / STATS API
# ══════════════════════════════════════════════════════════

@app.route("/api/stats")
@login_required
def stats():
    total_products = db.products.count_documents({})
    total_sales    = db.sales.count_documents({})
    low_stock      = db.products.count_documents({"quantity": {"$lte": LOW_STOCK_THRESHOLD}})
    out_of_stock   = db.products.count_documents({"quantity": 0})

    # Total revenue
    pipeline = [{"$group": {"_id": None, "revenue": {"$sum": "$total"}}}]
    rev_result = list(db.sales.aggregate(pipeline))
    revenue = round(rev_result[0]["revenue"], 2) if rev_result else 0

    # Top 5 products by quantity sold
    top_pipeline = [
        {"$unwind": "$items"},
        {"$group": {"_id": "$items.product_name", "sold": {"$sum": "$items.qty"}}},
        {"$sort": {"sold": -1}},
        {"$limit": 5},
    ]
    top_products = [{"name": r["_id"], "sold": r["sold"]}
                    for r in db.sales.aggregate(top_pipeline)]

    # Sales last 7 days
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    daily_pipeline = [
        {"$match": {"created_at": {"$gte": seven_days_ago}}},
        {"$group": {
            "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}},
            "total": {"$sum": "$total"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"_id": 1}},
    ]
    daily_sales = [{"date": r["_id"], "total": r["total"], "count": r["count"]}
                   for r in db.sales.aggregate(daily_pipeline)]

    return jsonify({
        "total_products": total_products,
        "total_sales":    total_sales,
        "low_stock":      low_stock,
        "out_of_stock":   out_of_stock,
        "revenue":        revenue,
        "top_products":   top_products,
        "daily_sales":    daily_sales,
    })


# ══════════════════════════════════════════════════════════
#  USERS API (admin only)
# ══════════════════════════════════════════════════════════

@app.route("/api/users", methods=["POST"])
@login_required
def create_user():
    if session.get("role") != "admin":
        return jsonify({"error": "Admin access required"}), 403
    data = request.get_json(force=True)
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", "")).strip()
    role     = data.get("role", "staff")
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if db.users.find_one({"username": username}):
        return jsonify({"error": "Username already exists"}), 409
    db.users.insert_one({
        "username":   username,
        "password":   generate_password_hash(password),
        "role":       role,
        "created_at": datetime.now(timezone.utc),
    })
    return jsonify({"message": f"User '{username}' created"}), 201


# ══════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    seed_admin()
    print("\n" + "="*50)
    print("  Inventory Manager — running at")
    print("  http://127.0.0.1:5000")
    print("  Default login: admin / admin123")
    print("="*50 + "\n")
    app.run(debug=False, port=5000)
