# app.py

import json
import requests
from flask import Flask, jsonify
from peewee import OperationalError

from models import DATABASE, Product

app = Flask(__name__)

# URL du service distant à interroger lors du démarrage
REMOTE_URL = "http://dimensweb.uqac.ca/~jgnault/shops/products/products.json"


def init_database():
    """
    Initialise la base locale (SQLite). Si la table n'existe pas, on la crée.
    Puis, si elle est vide, on va récupérer les produits distants une seule fois,
    et les insérer dans la table 'products'.
    """
    # Crée le fichier SQLite (si nécessaire) et la table
    DATABASE.connect()
    DATABASE.create_tables([Product])

    # Vérifier si des produits existent déjà en base
    try:
        count = Product.select().count()
    except OperationalError:
        count = 0

    # Si pas de produit en local, on interroge le service distant
    if count == 0:
        print("[init_database] Base vide, récupération des produits distants...")
        response = requests.get(REMOTE_URL)
        response.raise_for_status()  # Erreur si code ≠ 200

        payload = response.json()
        products = payload.get("products", [])

        with DATABASE.atomic():
            for item in products:
                Product.create(
                    id=item["id"],
                    name=item["name"],
                    description=item["description"],
                    price=item["price"],
                    weight=item["weight"],
                    in_stock=item["in_stock"],
                    image=item["image"],
                )
        print(f"[init_database] Inséré {len(products)} produits en local.")
    else:
        print(f"[init_database] {count} produit(s) déjà présent(s) en local.")


@app.route('/', methods=['GET'])
def get_all_products():
    """
    GET /
    Renvoie la liste complète des produits (stockés localement) au format JSON :
    {
       "products": [ {...}, {...}, ... ]
    }
    """
    # On récupère tous les produits en base, même ceux hors stock
    query = Product.select()
    all_products = []
    for p in query:
        all_products.append({
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "price": p.price,
            "weight": p.weight,
            "in_stock": p.in_stock,
            "image": p.image
        })

    return jsonify({"products": all_products}), 200


if __name__ == '__main__':
    # Avant de démarrer Flask, on initialise la base / on charge les produits distants
    init_database()
    # Démarrage de l’app Flask (débug activé si FLASK_DEBUG=True)
    app.run(debug=True)
