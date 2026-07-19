"""Safe SQLite schema migration for MediFlow.

Adds missing tables and columns only. It never drops tables or deletes data.
Run from the project folder: py migrate_db.py
"""
import sqlite3

from models import Base, DATABASE_URL, engine


def get_database_path() -> str:
    prefix = "sqlite:///./"
    if not DATABASE_URL.startswith(prefix):
        raise ValueError("This migration script expects a relative SQLite DATABASE_URL.")
    return DATABASE_URL[len(prefix):]


def get_existing_columns(cursor, table_name: str) -> set:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def get_existing_tables(cursor) -> set:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cursor.fetchall()}


def migrate() -> None:
    # Creates new models.py tables such as chat_messages and symptom_logs.
    # create_all never modifies/drops a table that already exists.
    Base.metadata.create_all(bind=engine)

    conn = sqlite3.connect(get_database_path())
    try:
        cursor = conn.cursor()
        existing_tables = get_existing_tables(cursor)
        print(f"Existing tables: {sorted(existing_tables)}")

        # SQLite needs ALTER TABLE for a new column on an existing table.
        column_additions = {
            "medication_reminders": [
                ("medicine_name", "VARCHAR"),
            ],
            "patients": [
                ("address", "VARCHAR"),
                ("latitude", "FLOAT"),
                ("longitude", "FLOAT"),
                ("location_updated_at", "DATETIME"),
            ],
        }

        for table_name, columns in column_additions.items():
            if table_name not in existing_tables:
                continue

            current_columns = get_existing_columns(cursor, table_name)
            for column_name, column_type in columns:
                if column_name in current_columns:
                    print(f"Column {table_name}.{column_name} already exists — skipping.")
                    continue

                print(f"Adding column {table_name}.{column_name} ({column_type})...")
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                )

        conn.commit()
        print("Migration complete. No existing data was deleted.")
    finally:
        conn.close()


if __name__ == "__main__":
    migrate()
