# Routes Package
# Register all Flask blueprints

from .auth_routes import auth_bp
from .page_routes import page_bp
from .payment_routes import payment_bp
from .document_routes import document_bp
from .document_routes import bp as main_bp


def register_blueprints(app):
    """Register all blueprints with the Flask app."""
    app.register_blueprint(auth_bp)
    app.register_blueprint(page_bp)
    app.register_blueprint(payment_bp)
    app.register_blueprint(document_bp)
    app.register_blueprint(main_bp)


__all__ = [
    'auth_bp',
    'page_bp', 
    'payment_bp',
    'document_bp',
    'register_blueprints'
]
