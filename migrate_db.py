"""Safe SQLite database migration.

This adds missing tables/columns only. Existing patients and data are not deleted.
Run: py migrate_db.py
"""

import sqlite3
from models import Base, DATABASE_URL, engine

DB_PATH = DATABASE_URL.replace("sqlite:///./", "")


def get_existing_columns(cursor, table_name: str) -> set:
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def get_existing_tables(cursor) -> set:
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    return {row[0] for row in cursor.fetchall()}


def migrate():
    # Creates every table that exists in models.py but is missing in SQLite.
    # It never drops existing tables or deletes records.
    Base.metadata.create_all(bind=engine)

    conn = sqlite3.connect(DB_PATH)

    try:
        cursor = conn.cursor()

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

        existing_tables = get_existing_tables(cursor)
        print(f"Existing tables: {sorted(existing_tables)}")

        for table_name, columns in column_additions.items():
            if table_name not in existing_tables:
                continue

            current_columns = get_existing_columns(cursor, table_name)

            for column_name, column_type in columns:
                if column_name in current_columns:
                    print(
                        f"Column {table_name}.{column_name} already exists — skipping."
                    )
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