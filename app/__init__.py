from flask import Flask
from dotenv import load_dotenv
from .config import Config

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)  

    from . import routes
    app.register_blueprint(routes.main)

    return app
