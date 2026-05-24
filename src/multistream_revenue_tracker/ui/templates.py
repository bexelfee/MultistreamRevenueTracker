from fastapi.templating import Jinja2Templates

from ..app_paths import ui_templates_directory
from .external_links import UI_EXTERNAL_LINK_TEMPLATE_VARS

templates = Jinja2Templates(directory=ui_templates_directory())
templates.env.globals.update(UI_EXTERNAL_LINK_TEMPLATE_VARS)
