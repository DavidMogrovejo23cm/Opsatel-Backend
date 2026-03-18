from sqlalchemy import create_engine, text



SQLALCHEMY_DATABASE_URL = "mysql+pymysql://root:@localhost/opsatel"

engine = create_engine(SQLALCHEMY_DATABASE_URL)



def cleanup():

    print("Iniciando proceso de limpieza y renombrado...")

    try:

        with engine.connect() as connection:

                                                                                 

            result = connection.execute(text("SELECT * FROM `hoja_de_c__lculo_sin_t__tulo` LIMIT 1"))

            first_row = result.fetchone()

            

            if not first_row:

                print("La tabla está vacía.")

                return



                                                                    

            raw_headers = list(first_row)

            

                                                                   

            rename_cmds = []

            seen_headers = {}

            cleaned_headers = []



            for i, header in enumerate(raw_headers):

                col_name = f"COL {i+1}"

                                                               

                clean_header = header.strip()

                

                                                            

                if clean_header in seen_headers:

                    seen_headers[clean_header] += 1

                    nuevo_nombre = f"{clean_header}_{seen_headers[clean_header]}"

                else:

                    seen_headers[clean_header] = 1

                    nuevo_nombre = clean_header

                

                cleaned_headers.append(nuevo_nombre)

                rename_cmds.append(f"CHANGE `{col_name}` `{nuevo_nombre}` VARCHAR(255)")



                                                       

            full_rename_sql = f"ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` {', '.join(rename_cmds)};"

            print("Renombrando columnas...")

            connection.execute(text(full_rename_sql))

            

                                                              

                                                                                                 

            print("Eliminando la fila de encabezados...")

            delete_sql = text(f"DELETE FROM `hoja_de_c__lculo_sin_t__tulo` WHERE `{cleaned_headers[0]}` = :header_val")

            connection.execute(delete_sql, {"header_val": raw_headers[0]})



                                                                    

            print("Estableciendo NUMERO como Primary Key Autoincremental...")

                                                                                        

            connection.execute(text("UPDATE `hoja_de_c__lculo_sin_t__tulo` SET `NUMERO` = CAST(`NUMERO` AS UNSIGNED)"))

            pk_sql = "ALTER TABLE `hoja_de_c__lculo_sin_t__tulo` MODIFY COLUMN `NUMERO` INT AUTO_INCREMENT PRIMARY KEY;"

            connection.execute(text(pk_sql))

            

            connection.commit()

            print("¡Limpieza completada exitosamente!")



    except Exception as e:

        print(f"Error durante la limpieza: {e}")



if __name__ == "__main__":

    cleanup()

