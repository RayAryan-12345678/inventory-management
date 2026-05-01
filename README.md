# 📦 Inventory Manager
### Flask + MongoDB + Web Frontend

---

## Project Structure

```
inventory/
├── app.py              ← Flask backend + all API routes
├── requirements.txt    ← Python dependencies
├── README.md
└── templates/
    └── index.html      ← Full web frontend (served by Flask)
```

---

## How to Run (Windows — username: adars)

### Step 1 — Make sure MongoDB is running
Download from: https://www.mongodb.com/try/download/community
Start it or run: `net start MongoDB`

### Step 2 — Open Command Prompt
Win + R → cmd → Enter

### Step 3 — Go to project folder
```cmd
cd C:\Users\adars\Downloads\inventory
```

### Step 4 — Create virtual environment
```cmd
python -m venv venv
venv\Scripts\activate
```

### Step 5 — Install dependencies
```cmd
pip install -r requirements.txt
```

### Step 6 — Run the app
```cmd
python app.py
```

### Step 7 — Open browser
```
http://127.0.0.1:5000
```

**Default login: admin / admin123**

---

## API Endpoints

| Method | Route | Description |
|---|---|---|
| POST | /api/login | Login |
| POST | /api/logout | Logout |
| GET | /api/me | Current user info |
| GET | /api/products | List products (paginated, filterable) |
| POST | /api/products | Add product |
| GET | /api/products/:id | Get single product |
| PUT | /api/products/:id | Update product |
| DELETE | /api/products/:id | Delete product |
| GET | /api/products/:id/qr | Generate QR code PNG |
| POST | /api/sales | Create sale (checkout) |
| GET | /api/sales | Sales history |
| GET | /api/stats | Dashboard stats |
| POST | /api/users | Create user (admin only) |

## Improvements Over Original Tkinter App

| Feature | Original | New |
|---|---|---|
| Interface | Desktop (Tkinter) | Web browser |
| Password storage | Plain text | Hashed (werkzeug) |
| Input validation | Minimal | Full validation on all routes |
| Search | Name + SKU | Name + SKU + Description |
| Pagination | None | 20 per page |
| Low stock alerts | None | Badge + filter |
| QR Code | Saved to disk | Streamed as HTTP response |
| Sales | Basic | Full line items + history |
| Dashboard | None | Stats + charts |
| Cart | Simple listbox | Interactive with qty controls |
| HTTP codes | N/A | Proper 200/201/400/401/404/409 |
