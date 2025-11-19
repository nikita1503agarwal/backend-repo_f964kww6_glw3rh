"""
Database Schemas for Handmade by Rama

Each Pydantic model corresponds to a MongoDB collection.
Collection name is the lowercase of the class name.

- User -> "user"
- Product -> "product"
- Order -> "order"
- Address -> embedded in User but may also be stored separately if needed
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Literal
from datetime import date

# -----------------------
# Core domain models
# -----------------------

CategoryLiteral = Literal["necklaces", "bracelets", "earrings", "rings"]


class Address(BaseModel):
    id: Optional[str] = Field(None, description="Address identifier")
    full_name: str = Field(..., description="Recipient full name")
    phone: str = Field(..., description="Phone in +963 format")
    city: str = Field(..., description="City inside Syria")
    street: str = Field(..., description="Street / Building / Apartment")
    notes: Optional[str] = Field(None, description="Optional delivery notes")

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        # Accept +963XXXXXXXXX or 09XXXXXXXX with normalization to +963
        v = v.strip()
        if v.startswith("+963") and len(v) in (12, 13):
            return v
        if v.startswith("09") and len(v) == 10:
            # Normalize 09XXXXXXXX -> +9639XXXXXXXX
            return "+963" + v[1:]
        raise ValueError("Phone must be in Syrian format starting with +963 or 09")


class User(BaseModel):
    phone: str = Field(..., description="Primary phone identifier in +963 format")
    name: str = Field(..., description="Customer name")
    addresses: List[Address] = Field(default_factory=list)
    is_active: bool = Field(default=True)


class Product(BaseModel):
    name: str
    description: Optional[str] = None
    category: CategoryLiteral
    price_syp: int = Field(..., ge=0, description="Price in SYP")
    price_usd: float = Field(..., ge=0, description="Approx price in USD")
    images: List[str] = Field(default_factory=list)
    featured: bool = Field(default=False)
    new_arrival: bool = Field(default=False)
    in_stock: bool = Field(default=True)


class OrderItem(BaseModel):
    product_id: str
    name: str
    category: CategoryLiteral
    quantity: int = Field(..., ge=1)
    price_syp: int
    price_usd: float
    image: Optional[str] = None


OrderStatus = Literal["Pending COD", "Pending", "Confirmed", "On Delivery", "Delivered", "Canceled"]


class Order(BaseModel):
    user_phone: str
    user_name: str
    items: List[OrderItem]
    address: Address
    city: str
    notes: Optional[str] = None
    status: OrderStatus = Field(default="Pending COD")
    admin_note: Optional[str] = None
    expected_delivery_date: Optional[date] = None

# Note: The database helper and API will take care of timestamps and ObjectId serialization.
