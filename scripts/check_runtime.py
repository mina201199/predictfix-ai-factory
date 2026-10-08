"""Import and database preflight without touching application databases."""
import json
import platform
import sys
import tempfile
from pathlib import Path


def main():
    if sys.version_info[:2] != (3, 12):
        raise SystemExit('This project is validated with Python 3.12; create a 3.12 environment first.')
    try:
        import fastapi
        import numpy
        import pydantic
        import sklearn
        import sqlalchemy
        from PIL import Image
        from sqlalchemy import create_engine, text
        from sqlalchemy.util._has_cython import HAS_CYEXTENSION
        runtime=Path(__file__).resolve().parents[1]/'.runtime'
        runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='preflight-',dir=runtime) as folder:
            engine=create_engine('sqlite:///'+str(Path(folder)/'check.db'))
            with engine.begin() as db:
                db.execute(text('CREATE TABLE checks (value INTEGER NOT NULL)'))
                db.execute(text('INSERT INTO checks VALUES (1)'))
                assert db.scalar(text('SELECT value FROM checks'))==1
            engine.dispose()
        print(json.dumps({'python':platform.python_version(),'sqlalchemy':sqlalchemy.__version__,
                          'sqlalchemy_native_extensions':HAS_CYEXTENSION,'sqlite_read_write':True,
                          'imports':'FastAPI, Pydantic, NumPy, scikit-learn, Pillow'},ensure_ascii=False))
    except Exception as exc:
        # Import errors contain only diagnostic text; don't dump environment values.
        print(f'Runtime preflight failed: {type(exc).__name__}: {exc}',file=sys.stderr)
        raise SystemExit(1)


if __name__=='__main__':main()
