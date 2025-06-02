# app.py

import json
import requests
from flask import Flask, jsonify, request, abort, Response
from peewee import OperationalError

from models import DATABASE, Product, Order

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
    DATABASE.create_tables([Product, Order])

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

@app.route('/order', methods=['POST'])
def create_order():
    """
    POST /order
    JSON attendu :
    {
      "product": {
          "id": <int>,
          "quantity": <int>
      }
    }

    1. Vérifie que "product" existe dans le JSON.
       - Si absent ou mal formé => 422 + {"errors": {"product": { "code": "missing-fields", ... }}}

    2. Vérifie que quantity >= 1.
       - Sinon => même erreur "missing-fields".

    3. Récupère le produit en base via Product.get_or_none(id=...).
       - Si aucune entrée ou if in_stock == False => 422 + {"errors": {"product": { "code": "out-of-inventory", ... }}}

    4. Si OK, crée une Order(product=…, quantity=…) et renvoie :
       HTTP 302 Found
       Location: /order/<order_id>
    """
    data = request.get_json()

    # --- 1. Vérifier la présence de "product" et de ses sous-champs ---
    if not data or "product" not in data:
        return _error_missing_fields(
            "La création d'une commande nécessite un produit"
        )

    prod_obj = data["product"]
    if not isinstance(prod_obj, dict) or "id" not in prod_obj or "quantity" not in prod_obj:
        return _error_missing_fields(
            "La création d'une commande nécessite un produit"
        )

    # --- 2. Vérifier quantity >= 1 ---
    try:
        product_id = int(prod_obj["id"])
        quantity = int(prod_obj["quantity"])
    except (ValueError, TypeError):
        # Si id ou quantity ne sont pas convertibles en int
        return _error_missing_fields(
            "La création d'une commande nécessite un produit"
        )

    if quantity < 1:
        return _error_missing_fields(
            "La quantité doit être supérieure ou égale à 1"
        )

    # --- 3. Vérifier que le produit existe et est en stock ---
    product = Product.get_or_none(Product.id == product_id)
    if product is None or not product.in_stock:
        # Cas où produit non trouvé OU hors inventaire
        return _error_out_of_inventory(
            "Le produit demandé n'est pas en inventaire"
        )

    # --- 4. Créer la commande et renvoyer un 302 avec Location ---
    new_order = Order.create(product=product, quantity=quantity)
    location_url = f"/order/{new_order.id}"
    return '', 302, {'Location': location_url}


@app.route('/order/<int:order_id>', methods=['GET'])
def get_order(order_id):
    """
    GET /order/<order_id>
    (Optionnel : utile pour suivre la redirection)
    Renvoie le détail de la commande si elle existe. Sinon, 404.
    Exemple de JSON renvoyé :
    {
      "order": {
         "id": 5,
         "product": {
            "id": 2,
            "name": "Sweet fresh stawberry"
         },
         "quantity": 3
      }
    }
    """
    order = Order.get_or_none(Order.id == order_id)
    if order is None:
        abort(404)

    return jsonify({
        "order": {
            "id": order.id,
            "product": {
                "id": order.product.id,
                "name": order.product.name
            },
            "quantity": order.quantity
        }
    }), 200


# ——— Fonctions utilitaires pour générer les erreurs 422 ———

def _error_missing_fields(message: str):
    """
    Retourne un 422 Unprocessable Entity pour le cas 'missing-fields'.
    """
    payload = {
        "errors": {
            "product": {
                "code": "missing-fields",
                "name": message
            }
        }
    }
    return jsonify(payload), 422


def _error_out_of_inventory(message: str):
    """
    Retourne un 422 Unprocessable Entity pour le cas 'out-of-inventory'.
    """
    payload = {
        "errors": {
            "product": {
                "code": "out-of-inventory",
                "name": message
            }
        }
    }
    return jsonify(payload), 422


if __name__ == '__main__':
    # Avant de démarrer Flask, on initialise la base / on charge les produits distants
    init_database()
    # Démarrage de l’app Flask (débug activé si FLASK_DEBUG=True)
    app.run(debug=True)
