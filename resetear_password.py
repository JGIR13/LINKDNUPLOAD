"""
Utilidad de rescate: resetea la contraseña de una cuenta directamente en la
base de datos local, para cuando se te olvida y no tienes otra cuenta de
administrador con la que entrar a gestionarlo desde la propia app.

Uso (con el entorno virtual activado, desde la carpeta de la app):
    python resetear_password.py tu@email.com

Te pedirá la contraseña nueva dos veces y la guarda con el mismo hash
(PBKDF2-HMAC-SHA256 + sal) que usa la app, así que sirve para iniciar sesión
de inmediato. No necesitas tocar la base de datos a mano ni conocer la
contraseña anterior.
"""
import getpass
import sys

import config
import db


def main():
    if len(sys.argv) != 2:
        print("Uso: python resetear_password.py tu@email.com")
        sys.exit(1)

    email = sys.argv[1].strip().lower()

    db.init_db()
    cuenta = db.obtener_cuenta_por_email(email)
    if not cuenta:
        print(f"No existe ninguna cuenta con el email '{email}' en esta instalación.")
        print("Cuentas existentes:")
        for c in db.listar_cuentas():
            print(f"  - {c['email']} ({c['rol']})")
        sys.exit(1)

    print(f"Cuenta encontrada: {cuenta['email']} ({cuenta['rol']}).")
    nueva = getpass.getpass("Contraseña nueva: ")
    repetir = getpass.getpass("Repite la contraseña nueva: ")
    if not nueva or nueva != repetir:
        print("Las dos contraseñas no coinciden (o está vacía). Nada se ha cambiado.")
        sys.exit(1)

    hash_hex, salt_hex = config.hash_password(nueva)
    db.cambiar_password_cuenta(cuenta["id"], hash_hex, salt_hex, debe_cambiar_password=False)
    print("Listo. Ya puedes iniciar sesión con la contraseña nueva.")


if __name__ == "__main__":
    main()
