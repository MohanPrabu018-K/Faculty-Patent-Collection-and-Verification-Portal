import sys
sys.path.insert(0, r'E:\Faculty profile portal\backend')

from alembic.config import Config
from alembic import command

cfg = Config('alembic.ini')
cfg.set_main_option('sqlalchemy.url', 'postgresql+asyncpg://faculty_user:change-me@localhost:5432/faculty_portal')

command.revision(cfg, autogenerate=True, msg='initial_schema')
print('Migration created successfully!')