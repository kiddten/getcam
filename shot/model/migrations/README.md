* `alembic init alembic # put dir name after init`
* fix `file_template` in alembic.ini
* sqlalchemy.url set via `env.py`
* specify correct `target_metadata`
* import full model module for correct usage of tables in metadata `from shot import model`
* generate migration `alembic revision --autogenerate -m "Init db"`
* upgrade to current head `alembic upgrade head`
