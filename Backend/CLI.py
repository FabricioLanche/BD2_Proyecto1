from Backend.DBMS.SQLengine import DBMSEngine

def main():
    print("=========================================")
    print("       MOTOR DE BASE DE DATOS U-SQL      ")
    print("=========================================")
    print("Escribe 'exit' o 'quit' para salir.\n")
    
    engine = DBMSEngine()
    
    while True:
        try:
            consulta = input("U-SQL> ")
            if consulta.strip().lower() in ['exit', 'quit']:
                print("Cerrando motor U-SQL. ¡Hasta pronto!")
                break
            
            if not consulta.strip():
                continue
                
            engine.execute_query(consulta)
            
        except KeyboardInterrupt:
            print("\nCerrando motor U-SQL de emergencia...")
            break
        except Exception as e:
            print(f"Error crítico en la consola: {e}")

if __name__ == "__main__":
    main()