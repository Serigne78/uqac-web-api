# models.py

from peewee import Model, SqliteDatabase, IntegerField, CharField, BooleanField, FloatField

# Base de données SQLite (fichier local inf349.db)
DATABASE = SqliteDatabase('inf349.db')


class BaseModel(Model):
    class Meta:
        database = DATABASE


class Product(BaseModel):
    """
    Correspond à un produit tel que renvoyé par le service distant.
    On réutilise exactement les champs fournis :
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
