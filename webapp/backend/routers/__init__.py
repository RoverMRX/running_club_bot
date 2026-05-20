import sys, os
# Добавляем backend/ в путь чтобы роутеры видели database, config, auth, schemas
_backend = os.path.dirname(os.path.dirname(__file__))
if _backend not in sys.path:
    sys.path.insert(0, _backend)