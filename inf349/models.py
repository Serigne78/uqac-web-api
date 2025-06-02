# models.py

from peewee import (
    Model, SqliteDatabase, IntegerField, CharField,
    BooleanField, FloatField, ForeignKeyField, TextField
)

# Base de données SQLite (fichier local inf349.db)
DATABASE = SqliteDatabase('inf349.db')


class BaseModel(Model):
    class Meta:
        database = DATABASE


class Product(BaseModel):
    """
    Correspond à un produit tel que renvoyé par le service distant.
      - id         : identifiant unique (IntegerField, PRIMARY KEY)
      - name       : nom du produit (CharField)
      - description: description du produit (CharField)
      - price      : prix (FloatField)
      - weight     : poids en grammes (IntegerField)
      - in_stock   : booléen indiquant si en stock (BooleanField)
      - image      : nom de l’image (CharField)
    """
    id = IntegerField(primary_key=True)
    name = CharField()
    description = CharField()
    price = FloatField()
    weight = IntegerField()
    in_stock = BooleanField()
    image = CharField()

    class Meta:
        table_name = 'products'


class Order(BaseModel):
    """
    Représente une commande (un seul produit par commande pour cette remise).
      - id                  : auto-incrément
      - product             : clé étrangère vers Product
      - quantity            : quantité (>= 1)
      - total_price         : HT = product.price * quantity
      - total_price_tax     : TTC = total_price * (1 + taux_taxe_par_défaut)
      - shipping_price      : calculé au départ selon poids total
      - email               : adresse client, null tant que non renseignée
      - shipping_country    : null jusqu’à PUT
      - shipping_address    : null jusqu’à PUT
      - shipping_postal_code: null jusqu’à PUT
      - shipping_city       : null jusqu’à PUT
      - shipping_province   : null jusqu’à PUT
      - paid                : booléen false tant que pas payé
      - credit_card         : JSON stocké en texte (vide "{}" par défaut)
      - transaction         : JSON stocké en texte (vide "{}" par défaut)
    """
    product = ForeignKeyField(Product, backref='orders', on_delete='CASCADE')
    quantity = IntegerField()
    total_price = FloatField()
    total_price_tax = FloatField()

    shipping_price = FloatField()
    email = CharField(null=True)

    # Champs shipping_information (tous obligatoires dans le PUT)
    shipping_country = CharField(null=True)
    shipping_address = CharField(null=True)
    shipping_postal_code = CharField(null=True)
    shipping_city = CharField(null=True)
    shipping_province = CharField(null=True)

    paid = BooleanField(default=False)

    # On stocke credit_card et transaction sous forme de JSON en texte
    credit_card = TextField(default="{}")
    transaction = TextField(default="{}")

    class Meta:
        table_name = 'orders'
