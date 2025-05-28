# app/models/product.py
from peewee import Model, IntegerField, CharField, BooleanField, FloatField
from .base import BaseModel

class Product(BaseModel):
    id          = IntegerField(primary_key=True)
    name        = CharField()
    type        = CharField()
    description = CharField()
    image       = CharField(null=True)
    height      = FloatField()
    weight      = FloatField()
    price       = FloatField()
    in_stock    = BooleanField()

"""
# Exemple #
"id": 10,
"name": "Lemon and salt",
"type": "fruit",
"description": "Rosemary, lemon and salt on the table",
"image": "9.jpg",
"height": 450,
"weight": 299,
"price": 15.79,
"in_stock": true
"""