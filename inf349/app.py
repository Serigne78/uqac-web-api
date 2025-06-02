# app.py

import json
import requests
from flask import (
    Flask, jsonify, request, make_response, url_for
)
from peewee import OperationalError, IntegrityError

from models import DATABASE, Product, Order

app = Flask(__name__)

# URL du service distant pour charger les produits au démarrage
REMOTE_URL = "http://dimensweb.uqac.ca/~jgnault/shops/products/products.json"

# Taux de taxe par défaut (utilisé à la création de l’ordre, province inconnue)
TAX_DEFAULT = 0.15  # 15% (QC par défaut)

# Dictionnaire des taux selon la province
TAX_BY_PROVINCE = {
    "QC": 0.15,
    "ON": 0.13,
    "AB": 0.05,
    "BC": 0.12,
    "NS": 0.14
}


def init_database():
    """
    Initialise la base (SQLite). Crée les tables Product et Order. 
    Si Product est vide, on charge depuis REMOTE_URL.
    """
    DATABASE.connect()
    # On crée Product ET Order
    DATABASE.create_tables([Product, Order])

    # Charger les produits distants si la table est vide
    try:
        count = Product.select().count()
    except OperationalError:
        count = 0

    if count == 0:
        print("[init_database] Table products vide, récupération à distance…")
        response = requests.get(REMOTE_URL)
        response.raise_for_status()
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
        print(f"[init_database] {count} produit(s) déjà présent(s).")


@app.route('/', methods=['GET'])
def get_all_products():
    """
    GET /
    Renvoie la liste complète des produits (tous, même hors stock).
    {
      "products": [ {…}, {…}, … ]
    }
    """
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
    Body attendu :
    {
      "product": {
        "id": <int>,
        "quantity": <int>
      }
    }

    Réponses :
      - 302 Found + Location: /order/<order_id> si OK
      - 422 Unprocessable Entity + JSON d’erreur si champs manquants / produits hors stock / quantité <1
    """
    if not request.is_json:
        return make_response(jsonify({
            "errors": {
                "product": {
                    "code": "missing-fields",
                    "name": "La création d'une commande nécessite un produit"
                }
            }
        }), 422)

    data = request.get_json()

    # 1) Vérifier existence de "product" et que c'est un objet
    if "product" not in data or not isinstance(data["product"], dict):
        return make_response(jsonify({
            "errors": {
                "product": {
                    "code": "missing-fields",
                    "name": "La création d'une commande nécessite un produit"
                }
            }
        }), 422)

    prod_obj = data["product"]

    # 2) Vérifier que "id" et "quantity" sont présents
    if "id" not in prod_obj or "quantity" not in prod_obj:
        return make_response(jsonify({
            "errors": {
                "product": {
                    "code": "missing-fields",
                    "name": "La création d'une commande nécessite un produit"
                }
            }
        }), 422)

    # 3) Valider id et quantity
    try:
        product_id = int(prod_obj["id"])
        quantity = int(prod_obj["quantity"])
    except (ValueError, TypeError):
        return make_response(jsonify({
            "errors": {
                "product": {
                    "code": "missing-fields",
                    "name": "L’id et la quantité doivent être des entiers valides"
                }
            }
        }), 422)

    if quantity < 1:
        return make_response(jsonify({
            "errors": {
                "product": {
                    "code": "missing-fields",
                    "name": "La quantité doit être supérieure ou égale à 1"
                }
            }
        }), 422)

    # 4) Vérifier existence du produit et stock
    try:
        product = Product.get(Product.id == product_id)
    except Product.DoesNotExist:
        return make_response(jsonify({
            "errors": {
                "product": {
                    "code": "out-of-inventory",
                    "name": "Le produit demandé n'est pas en inventaire"
                }
            }
        }), 422)

    if not product.in_stock:
        return make_response(jsonify({
            "errors": {
                "product": {
                    "code": "out-of-inventory",
                    "name": "Le produit demandé n'est pas en inventaire"
                }
            }
        }), 422)

    # 5) Calculer total_price = prix * quantité
    total_ht = product.price * quantity

    # === CALCUL DU shipping_price selon poids total ===
    poids_total = product.weight * quantity  # en grammes
    if poids_total <= 500:
        shipping_price = 5.0
    elif poids_total < 2000:
        shipping_price = 10.0
    else:
        shipping_price = 25.0

    # 6) Calculer total_price_tax par défaut au taux QC (15%)  
    # (on ne connaît pas encore la province du client, donc on applique le taux QC par défaut)
    total_ttc = round(total_ht * (1 + TAX_DEFAULT), 2)

    # 7) Créer la commande avec tous les champs initiaux
    try:
        new_order = Order.create(
            product=product,
            quantity=quantity,
            total_price=round(total_ht, 2),
            total_price_tax=total_ttc,
            shipping_price=shipping_price,
            email=None,
            shipping_country=None,
            shipping_address=None,
            shipping_postal_code=None,
            shipping_city=None,
            shipping_province=None,
            paid=False,
            credit_card="{}",       # JSON vide
            transaction="{}"        # JSON vide
        )
    except IntegrityError:
        return make_response(jsonify({
            "errors": {
                "product": {
                    "code": "creation-failed",
                    "name": "Impossible de créer la commande"
                }
            }
        }), 500)

    # 8) Retourner 302 Found + Location: /order/<new_order.id>
    location_url = url_for('get_order', order_id=new_order.id)
    response = make_response('', 302)
    response.headers['Location'] = location_url
    return response


@app.route('/order/<int:order_id>', methods=['GET'])
def get_order(order_id):
    """
    GET /order/<order_id>
    Retourne l’objet complet de la commande :
    {
      "order": {
        "id": <int>,
        "total_price": <float>,
        "total_price_tax": <float>,
        "email": <string|null>,
        "credit_card": { … },
        "shipping_information": { … },
        "paid": <bool>,
        "transaction": { … },
        "product": {
            "id": <int>,
            "quantity": <int>
        },
        "shipping_price": <float>
      }
    }
    """
    try:
        order = Order.get(Order.id == order_id)
    except Order.DoesNotExist:
        return make_response(jsonify({
            "errors": {
                "order": {
                    "code": "not-found",
                    "name": f"La commande d'ID {order_id} n'existe pas"
                }
            }
        }), 404)

    # Préparer shipping_information (soit vide, soit rempli)
    if order.shipping_country is None:
        shipping_info = {}
    else:
        shipping_info = {
            "country": order.shipping_country,
            "address": order.shipping_address,
            "postal_code": order.shipping_postal_code,
            "city": order.shipping_city,
            "province": order.shipping_province
        }

    # Préparer credit_card et transaction (champ JSON stocké en texte)
    try:
        cc_json = json.loads(order.credit_card)
    except Exception:
        cc_json = {}
    try:
        tx_json = json.loads(order.transaction)
    except Exception:
        tx_json = {}

    # Construire la réponse
    order_data = {
        "id": order.id,
        "total_price": order.total_price,
        "total_price_tax": order.total_price_tax,
        "email": order.email,
        "credit_card": cc_json,
        "shipping_information": shipping_info,
        "paid": order.paid,
        "transaction": tx_json,
        "product": {
            "id": order.product.id,
            "quantity": order.quantity
        },
        "shipping_price": order.shipping_price
    }
    return jsonify({"order": order_data}), 200


@app.route('/order/<int:order_id>', methods=['PUT'])
def update_order(order_id):
    """
    PUT /order/<order_id>
    Body attendu (JSON) :
    {
      "order": {
         "email": <string>,
         "shipping_information": {
            "country"    : <string>,
            "address"    : <string>,
            "postal_code": <string>,
            "city"       : <string>,
            "province"   : <string>  # QC, ON, AB, BC ou NS
         }
      }
    }

    Exigences :
     1. Si la commande n'existe pas → 404
     2. Les champs "email" ET "shipping_information" (avec ses 5 sous-champs) sont tous obligatoires.
     3. Tout autre champ (total_price, total_price_tax, product, shipping_price, id, paid, credit_card, transaction) ne peut pas être modifié ici.
     4. Calculer le nouveau total_price_tax en fonction de la province fournie.
     5. Retourner 200 OK + JSON avec l’ordre mis à jour.
    """
    # 1) Vérifier que l'ordre existe
    try:
        order = Order.get(Order.id == order_id)
    except Order.DoesNotExist:
        return make_response(jsonify({
            "errors": {
                "order": {
                    "code": "not-found",
                    "name": f"La commande d'ID {order_id} n'existe pas"
                }
            }
        }), 404)

    # 2) Vérifier que c'est du JSON
    if not request.is_json:
        return make_response(jsonify({
            "errors": {
                "order": {
                    "code": "missing-fields",
                    "name": "Le format doit être application/json"
                }
            }
        }), 422)

    payload = request.get_json()

    # 3) Vérifier présence de "order"
    if "order" not in payload or not isinstance(payload["order"], dict):
        return make_response(jsonify({
            "errors": {
                "order": {
                    "code": "missing-fields",
                    "name": "Les champs 'email' et 'shipping_information' sont obligatoires"
                }
            }
        }), 422)

    order_obj = payload["order"]

    # 4) Vérifier que "email" et "shipping_information" sont présents
    if "email" not in order_obj or "shipping_information" not in order_obj:
        return make_response(jsonify({
            "errors": {
                "order": {
                    "code": "missing-fields",
                    "name": "Les champs 'email' et 'shipping_information' sont obligatoires"
                }
            }
        }), 422)

    # 5) Valider email
    email = order_obj["email"]
    if not isinstance(email, str) or email.strip() == "":
        return make_response(jsonify({
            "errors": {
                "order": {
                    "code": "missing-fields",
                    "name": "Le champ 'email' doit être une chaîne non vide"
                }
            }
        }), 422)

    # 6) Valider shipping_information (doit être un dict avec 5 sous-champs)
    ship_info = order_obj["shipping_information"]
    expected_fields = ["country", "address", "postal_code", "city", "province"]
    if (not isinstance(ship_info, dict)) or any(f not in ship_info for f in expected_fields):
        return make_response(jsonify({
            "errors": {
                "order": {
                    "code": "missing-fields",
                    "name": "shipping_information doit contenir country, address, postal_code, city et province"
                }
            }
        }), 422)

    # 7) Extraire et valider chacun des sous-champs
    country = ship_info["country"]
    address = ship_info["address"]
    postal_code = ship_info["postal_code"]
    city = ship_info["city"]
    province = ship_info["province"]

    # Tous doivent être des chaînes non vides
    for field_name, val in [
        ("country", country),
        ("address", address),
        ("postal_code", postal_code),
        ("city", city),
        ("province", province)
    ]:
        if not isinstance(val, str) or val.strip() == "":
            return make_response(jsonify({
                "errors": {
                    "order": {
                        "code": "missing-fields",
                        "name": f"Le champ '{field_name}' dans shipping_information est obligatoire"
                    }
                }
            }), 422)

    # 8) Vérifier que province est dans notre liste de taux
    if province not in TAX_BY_PROVINCE:
        return make_response(jsonify({
            "errors": {
                "order": {
                    "code": "invalid-field",
                    "name": f"Province '{province}' non supportée pour calcul de taxes"
                }
            }
        }), 422)

    # 9) Mettre à jour email + shipping_* dans l'objet Order
    order.email = email
    order.shipping_country = country
    order.shipping_address = address
    order.shipping_postal_code = postal_code
    order.shipping_city = city
    order.shipping_province = province

    # 10) Recalculer total_price_tax selon le taux de la province
    taux = TAX_BY_PROVINCE[province]
    new_total_ttc = round(order.total_price * (1 + taux), 2)
    order.total_price_tax = new_total_ttc

    # Remarque : shipping_price ne change pas ici (basé sur le poids qui n’évolue pas).
    # Les autres champs (product, quantity, total_price, paid, credit_card, transaction, id) 
    # ne sont pas modifiables via ce PUT.

    # 11) Sauvegarder l'objet order
    order.save()

    # 12) Construire la réponse JSON complète comme demandé
    shipping_info_resp = {
        "country": order.shipping_country,
        "address": order.shipping_address,
        "postal_code": order.shipping_postal_code,
        "city": order.shipping_city,
        "province": order.shipping_province
    }

    try:
        cc_json = json.loads(order.credit_card)
    except:
        cc_json = {}
    try:
        tx_json = json.loads(order.transaction)
    except:
        tx_json = {}

    response_order = {
        "id": order.id,
        "total_price": order.total_price,
        "total_price_tax": order.total_price_tax,
        "email": order.email,
        "credit_card": cc_json,
        "shipping_information": shipping_info_resp,
        "paid": order.paid,
        "transaction": tx_json,
        "product": {
            "id": order.product.id,
            "quantity": order.quantity
        },
        "shipping_price": order.shipping_price
    }

    return jsonify({"order": response_order}), 200


if __name__ == '__main__':
    init_database()
    app.run(debug=True)
