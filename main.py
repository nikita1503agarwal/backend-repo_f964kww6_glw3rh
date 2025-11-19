import os
from datetime import datetime, date
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bson import ObjectId

from database import db
from schemas import Product as ProductSchema, User as UserSchema, Address as AddressSchema, Order as OrderSchema


class PyObjectId(ObjectId):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)


def usd_to_syp_rate() -> int:
    try:
        return int(os.getenv("USD_TO_SYP", "15000"))
    except Exception:
        return 15000


def product_doc_with_id(doc):
    if not doc:
        return None
    doc["id"] = str(doc.pop("_id"))
    return doc


def order_doc_with_id(doc):
    if not doc:
        return None
    doc["id"] = str(doc.pop("_id"))
    # Convert any ObjectIds nested
    if "items" in doc:
        for it in doc["items"]:
            if isinstance(it.get("product_id"), ObjectId):
                it["product_id"] = str(it["product_id"])
    return doc


app = FastAPI(title="Handmade by Rama API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {"name": "Handmade by Rama", "status": "ok"}


@app.get("/test")
def test_database():
    resp = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "collections": [],
        "rate": usd_to_syp_rate(),
    }
    try:
        collections = db.list_collection_names()
        resp["database"] = "✅ Connected"
        resp["collections"] = collections
    except Exception as e:
        resp["database"] = f"❌ {str(e)[:120]}"
    return resp


# -----------------------------
# Products
# -----------------------------

class ProductIn(BaseModel):
    name: str
    description: Optional[str] = None
    category: str
    price_usd: Optional[float] = None
    price_syp: Optional[int] = None
    images: List[str] = []
    featured: bool = False
    new_arrival: bool = False
    in_stock: bool = True


@app.get("/api/products")
def list_products(
    category: Optional[str] = None,
    search: Optional[str] = None,
    featured: Optional[bool] = None,
    new_arrival: Optional[bool] = None,
    sort: Optional[str] = Query(None, description="name_asc|name_desc|price_asc|price_desc|new")
):
    q = {}
    if category:
        q["category"] = category
    if featured is not None:
        q["featured"] = featured
    if new_arrival is not None:
        q["new_arrival"] = new_arrival

    cursor = db["product"].find(q)

    if search:
        cursor = db["product"].find({**q, "name": {"$regex": search, "$options": "i"}})

    sort_map = {
        "name_asc": ("name", 1),
        "name_desc": ("name", -1),
        "price_asc": ("price_syp", 1),
        "price_desc": ("price_syp", -1),
        "new": ("created_at", -1),
    }
    if sort and sort in sort_map:
        field, direction = sort_map[sort]
        cursor = cursor.sort(field, direction)

    products = [product_doc_with_id(p) for p in cursor]
    return {"items": products, "count": len(products)}


@app.get("/api/products/{product_id}")
def get_product(product_id: str):
    doc = db["product"].find_one({"_id": ObjectId(product_id)})
    if not doc:
        raise HTTPException(404, "Product not found")
    return product_doc_with_id(doc)


@app.post("/api/seed")
def seed_products(force: bool = False):
    count = db["product"].count_documents({})
    if count > 0 and not force:
        return {"status": "exists", "count": count}

    rate = usd_to_syp_rate()

    def priced(category: str, usd: Optional[float]):
        if usd is None:
            return {"price_usd": 0.0, "price_syp": 0}
        return {"price_usd": usd, "price_syp": int(usd * rate)}

    seed = [
        # Necklaces ($2.5)
        {
            "name": "Handmade Necklace 1",
            "description": "Elegant minimalist handmade necklace.",
            "category": "necklaces",
            **priced("necklaces", 2.5),
            "images": [],
            "featured": True,
            "new_arrival": True,
        },
        {
            "name": "Handmade Necklace 2",
            "description": "Delicate everyday necklace.",
            "category": "necklaces",
            **priced("necklaces", 2.5),
            "images": [],
        },
        # Bracelets ($1.5)
        {
            "name": "Handmade Bracelet 1",
            "description": "Simple bracelet for daily wear.",
            "category": "bracelets",
            **priced("bracelets", 1.5),
            "images": [],
            "new_arrival": True,
        },
        # Earrings ($1.5)
        {
            "name": "Handmade Earrings 1",
            "description": "Lightweight handmade earrings.",
            "category": "earrings",
            **priced("earrings", 1.5),
            "images": [],
            "featured": True,
        },
        # Rings (admin defined individually → set 0 as placeholder)
        {
            "name": "Handmade Ring 1",
            "description": "Adjustable handmade ring.",
            "category": "rings",
            **priced("rings", None),
            "images": [],
            "in_stock": True,
        },
    ]

    # Validate with ProductSchema and insert
    docs = []
    for p in seed:
        schema = ProductSchema(**p)
        doc = schema.model_dump()
        doc["created_at"] = datetime.utcnow()
        doc["updated_at"] = datetime.utcnow()
        docs.append(doc)

    db["product"].delete_many({})
    db["product"].insert_many(docs)

    return {"status": "seeded", "count": len(docs)}


# -----------------------------
# Users & Addresses
# -----------------------------

@app.get("/api/user/{phone}/addresses")
def get_addresses(phone: str):
    user = db["user"].find_one({"phone": phone})
    if not user:
        return {"addresses": []}
    return {"addresses": user.get("addresses", [])}


class AddressIn(AddressSchema):
    pass


@app.post("/api/user/{phone}/addresses")
def add_address(phone: str, body: AddressIn):
    user = db["user"].find_one({"phone": phone})
    addr = body.model_dump()
    if not user:
        user_doc = UserSchema(phone=phone, name=body.full_name, addresses=[body]).model_dump()
        user_doc["created_at"] = datetime.utcnow()
        user_doc["updated_at"] = datetime.utcnow()
        db["user"].insert_one(user_doc)
        return {"ok": True}
    # append if not duplicate (match by phone+street)
    addresses = user.get("addresses", [])
    exists = any((a.get("phone") == addr.get("phone") and a.get("street") == addr.get("street")) for a in addresses)
    if not exists:
        addresses.append(addr)
        db["user"].update_one({"_id": user["_id"]}, {"$set": {"addresses": addresses, "updated_at": datetime.utcnow()}})
    return {"ok": True}


# -----------------------------
# Orders
# -----------------------------

class OrderItemIn(BaseModel):
    product_id: str
    quantity: int = Field(..., ge=1)


class OrderCreateIn(BaseModel):
    full_name: str
    phone: str
    city: str
    street: str
    notes: Optional[str] = None
    address_id: Optional[str] = None
    items: List[OrderItemIn]


@app.post("/api/orders")
def create_order(body: OrderCreateIn):
    # Load products and compute totals
    items_out = []
    for it in body.items:
        prod = db["product"].find_one({"_id": ObjectId(it.product_id)})
        if not prod:
            raise HTTPException(400, f"Invalid product: {it.product_id}")
        price_syp = int(prod.get("price_syp", 0))
        price_usd = float(prod.get("price_usd", 0))
        items_out.append({
            "product_id": prod["_id"],
            "name": prod["name"],
            "category": prod["category"],
            "quantity": it.quantity,
            "price_syp": price_syp,
            "price_usd": price_usd,
            "image": (prod.get("images") or [None])[0]
        })

    addr = AddressSchema(full_name=body.full_name, phone=body.phone, city=body.city, street=body.street, notes=body.notes)

    order_schema = OrderSchema(
        user_phone=addr.phone,
        user_name=addr.full_name,
        items=items_out,
        address=addr,
        city=addr.city,
        notes=addr.notes,
        status="Pending COD",
    )

    order_doc = order_schema.model_dump()
    now = datetime.utcnow()
    order_doc["created_at"] = now
    order_doc["updated_at"] = now

    result = db["order"].insert_one(order_doc)

    # Upsert user & save address
    user = db["user"].find_one({"phone": addr.phone})
    if not user:
        user_doc = UserSchema(phone=addr.phone, name=addr.full_name, addresses=[addr]).model_dump()
        user_doc["created_at"] = now
        user_doc["updated_at"] = now
        db["user"].insert_one(user_doc)
    else:
        addresses = user.get("addresses", [])
        exists = any((a.get("phone") == addr.phone and a.get("street") == addr.street) for a in addresses)
        if not exists:
            addresses.append(addr.model_dump())
            db["user"].update_one({"_id": user["_id"]}, {"$set": {"addresses": addresses, "updated_at": now}})

    return {"id": str(result.inserted_id), "status": "Pending COD"}


@app.get("/api/orders")
def get_orders(phone: str):
    cursor = db["order"].find({"user_phone": phone}).sort("created_at", -1)
    orders = [order_doc_with_id(o) for o in cursor]
    return {"items": orders}


class StatusUpdateIn(BaseModel):
    status: str
    admin_note: Optional[str] = None
    expected_delivery_date: Optional[date] = None


@app.patch("/api/orders/{order_id}/status")
def update_order_status(order_id: str, body: StatusUpdateIn):
    allowed = {"Pending", "Confirmed", "On Delivery", "Delivered", "Canceled", "Pending COD"}
    if body.status not in allowed:
        raise HTTPException(400, "Invalid status")

    upd = {
        "status": body.status,
        "updated_at": datetime.utcnow(),
    }
    if body.admin_note is not None:
        upd["admin_note"] = body.admin_note
    if body.expected_delivery_date is not None:
        upd["expected_delivery_date"] = body.expected_delivery_date

    res = db["order"].update_one({"_id": ObjectId(order_id)}, {"$set": upd})
    if res.matched_count == 0:
        raise HTTPException(404, "Order not found")

    doc = db["order"].find_one({"_id": ObjectId(order_id)})
    return order_doc_with_id(doc)


@app.get("/api/orders/notifications")
def order_notifications(phone: str):
    """For customer homepage banner: if any order is On Delivery, return message and expected date."""
    doc = db["order"].find_one({"user_phone": phone, "status": "On Delivery"}, sort=[("updated_at", -1)])
    if not doc:
        return {"on_delivery": False}
    return {
        "on_delivery": True,
        "order_id": str(doc["_id"]),
        "expected_delivery_date": doc.get("expected_delivery_date"),
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
