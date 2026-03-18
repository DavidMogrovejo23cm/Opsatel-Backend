from database import engine

try:

    with engine.connect() as connection:

        print("Successfully connected to the database!")

except Exception as e:

    print(f"Error connecting to the database: {e}")

