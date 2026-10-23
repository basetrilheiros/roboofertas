"""Production entry point: TLS is terminated by the configured hosting proxy."""
import logging
from web.app import create_app
logging.getLogger('werkzeug').disabled = True
app = create_app()
