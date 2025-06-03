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
# URL du service distant de paiement
REMOTE_PAY_URL = "https://dimensweb.uqac.ca/~jgnault/shops/pay/"

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
def update_or_pay_order(order_id):
    """
    PUT /order/<order_id>

    Deux cas selon la forme du JSON reçu :

    1) Mise à jour des infos client :
       On reçoit un JSON de la forme :
       {
         "order": {
           "email": "...",
           "shipping_information": {
             "country": "...",
             "address": "...",
             "postal_code": "...",
             "city": "...",
             "province": "..."
           }
         }
       }
       -> On met à jour email + shipping_*.
       -> Si un champ manque, 422 missing-fields.
       -> Si order.paid == True, 422 already-paid.

    2) Paiement par carte :
       On reçoit un JSON de la forme :
       {
         "credit_card": {
           "name": "...",
           "number": "...",
           "expiration_year": 2024,
           "cvv": "...",
           "expiration_month": 9
         }
       }
       -> Si email ou shipping_* de la commande sont manquants en DB, 422 missing-fields.
       -> Si order.paid == True, 422 already-paid.
       -> Sinon, on envoie au service de paiement distant :
          {
            "credit_card": { … },
            "amount_charged": total_price_tax + shipping_price
          }
         • Si distant renvoie 422, on renvoie 422 + corps tel quel.
         • Si 200, on met à jour order.credit_card, order.transaction, order.paid=True, order.save()
           puis on renvoie 200 + JSON complet de la commande.
         • Sinon, 502 service-error.

    Tout autre cas (ni "order", ni "credit_card") -> 422 missing-fields.
    """
    order = Order.get_or_none(Order.id == order_id)
    if order is None:
        return jsonify({"error": "Order not found"}), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error_missing_fields_order("Corps JSON invalide ou manquant")

    # Cas 1 : mise à jour des infos client
    if "order" in data:
        payload = data["order"]
        has_email = "email" in payload
        has_ship_info = "shipping_information" in payload

        # Nécessite à la fois email + shipping_information
        if not (has_email and has_ship_info):
            return _error_missing_fields_order(
                "Les informations client sont incomplètes ou manquantes"
            )
        if order.paid:
            return _error_order_already_paid("La commande a déjà été payée.")

        ship_info = payload["shipping_information"]
        if not isinstance(ship_info, dict):
            return _error_missing_fields_order("Le format de shipping_information est invalide")
        for field in ("country", "address", "postal_code", "city", "province"):
            if field not in ship_info:
                return _error_missing_fields_order(
                    "Les informations client sont incomplètes ou manquantes"
                )

        # Mettre à jour en base
        order.email = payload["email"]
        order.shipping_country = ship_info["country"]
        order.shipping_address = ship_info["address"]
        order.shipping_postal_code = ship_info["postal_code"]
        order.shipping_city = ship_info["city"]
        order.shipping_province = ship_info["province"]
        order.save()

        return jsonify({
            "order": {
                "id": order.id,
                "total_price": order.total_price,
                "total_price_tax": order.total_price_tax,
                "email": order.email,
                "shipping_information": {
                    "country": order.shipping_country,
                    "address": order.shipping_address,
                    "postal_code": order.shipping_postal_code,
                    "city": order.shipping_city,
                    "province": order.shipping_province
                },
                "paid": order.paid,
                "credit_card": json.loads(order.credit_card),
                "transaction": json.loads(order.transaction),
                "product": {
                    "id": order.product.id,
                    "name": order.product.name
                },
                "quantity": order.quantity,
                "shipping_price": order.shipping_price
            }
        }), 200

    # Cas 2 : paiement par carte (payload = { "credit_card": { ... } })
    if "credit_card" in data:
        cc_obj = data["credit_card"]
        if not isinstance(cc_obj, dict):
            return _error_missing_fields_order("Corps credit_card invalide")

        # Vérifier que les infos client existent déjà en base
        required = (
            order.email,
            order.shipping_country,
            order.shipping_address,
            order.shipping_postal_code,
            order.shipping_city,
            order.shipping_province
        )
        if any(val is None for val in required):
            return _error_missing_fields_order(
                "Les informations du client sont nécessaires avant d'appliquer une carte de crédit"
            )
        if order.paid:
            return _error_order_already_paid("La commande a déjà été payée.")

        montant = int(round(order.total_price_tax + order.shipping_price))
        pay_payload = {
            "credit_card": cc_obj,
            "amount_charged": montant
        }

        try:
            pay_response = requests.post(
                REMOTE_PAY_URL,
                json=pay_payload,
                headers={"Content-Type": "application/json"}
            )
        except requests.RequestException:
            return jsonify({
                "errors": {
                    "payment": {
                        "code": "service-unavailable",
                        "name": "Impossible de contacter le service de paiement"
                    }
                }
            }), 502

        if pay_response.status_code == 422:
            return pay_response.json(), 422

        if pay_response.status_code == 200:
            resp_json = pay_response.json()
            received_cc = resp_json.get("credit_card", {})
            received_tx = resp_json.get("transaction", {})

            order.credit_card = json.dumps(received_cc)
            order.transaction = json.dumps(received_tx)
            order.paid = True
            order.save()

            return jsonify({
                "order": {
                    "id": order.id,
                    "total_price": order.total_price,
                    "total_price_tax": order.total_price_tax,
                    "email": order.email,
                    "shipping_information": {
                        "country": order.shipping_country,
                        "address": order.shipping_address,
                        "postal_code": order.shipping_postal_code,
                        "city": order.shipping_city,
                        "province": order.shipping_province
                    },
                    "paid": order.paid,
                    "credit_card": received_cc,
                    "transaction": received_tx,
                    "product": {
                        "id": order.product.id,
                        "name": order.product.name
                    },
                    "quantity": order.quantity,
                    "shipping_price": order.shipping_price
                }
            }), 200

        return jsonify({
            "errors": {
                "payment": {
                    "code": "service-error",
                    "name": "Erreur inattendue du service de paiement"
                }
            }
        }), 502

    # Ni "order" ni "credit_card" → 422 missing-fields
    return _error_missing_fields_order(
        "Aucune information valide fournie pour la mise à jour ou le paiement"
    )

# ——— Fonctions utilitaires pour générer les erreurs 422 ———

def _error_missing_fields_order(message: str):
    """
    Retourne un 422 Unprocessable Entity pour le cas 'missing-fields' (Order).
    """
    payload = {
        "errors": {
            "order": {
                "code": "missing-fields",
                "name": message
            }
        }
    }
    return jsonify(payload), 422

def _error_order_already_paid(message: str):
    """
    Retourne un 422 Unprocessable Entity pour le cas 'already-paid'.
    """
    payload = {
        "errors": {
            "order": {
                "code": "already-paid",
                "name": message
            }
        }
    }
    return jsonify(payload), 422

if __name__ == '__main__':
    init_database()
    app.run(debug=True)
