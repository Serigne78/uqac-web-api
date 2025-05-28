from flask import Blueprint, render_template_string

bp = Blueprint('main', __name__)

@bp.route('/')
def hello():
    return render_template_string('<h1>Hello, World!</h1>')
