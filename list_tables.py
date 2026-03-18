from sqlalchemy import create_engine, text



SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:@localhost/opsatel"

engine = create_engine(SQLALCHEMY_DATABASE_URL)



def list_tables():

    try:

        with engine.connect() as connection:

            result = connection.execute(text("SHOW TABLES"))

            for row in result:

                print(row)

    except Exception as e:

        print(f"Error: {e}")



if __name__ == "__main__":

    list_tables()

