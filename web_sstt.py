# coding=utf-8
#!/usr/bin/env python3

from asyncio.base_subprocess import WriteSubprocessPipeProto
import socket
import selectors  # https://docs.python.org/3/library/selectors.html
import select
import types        # Para definir el tipo de datos data
import argparse     # Leer parametros de ejecución
import os           # Obtener ruta y extension
from datetime import datetime, timedelta  # Fechas de los mensajes HTTP
import time         # Timeout conexión
import sys          # sys.exit
import re           # Analizador sintáctico
import logging      # Para imprimir logs


BUFSIZE = 8192  # Tamaño máximo del buffer que se puede utilizar
TIMEOUT_CONNECTION = 20  # Timeout para la conexión persistente
MAX_ACCESOS = 10

# Extensiones admitidas (extension, name in HTTP)
filetypes = {"gif": "image/gif", "jpg": "image/jpg", "jpeg": "image/jpeg", "png": "image/png", "htm": "text/htm",
             "html": "text/html", "css": "text/css", "js": "text/js"}

errortypes = {"403": "403 Forbidden",
              "404": "404 Not Found", "405": "405 Method Not Allowed"}

# Configuración de logging
logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s.%(msecs)03d] [%(levelname)-7s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger()

# Expresiones regulares
pattern_cookie = r'\b(Cookie: .*)(\d{1,2})$'
er_cookie = re.compile(pattern_cookie)
pattern_request = r'\b(GET|POST|HEAD|PUT|DELETE) (/.*) HTTP/1\.1$'
er_request = re.compile(pattern_request)
pattern_host = r'\bHost: .+:\d{1,}'
er_host = re.compile(pattern_host)


def enviar_mensaje(cs, data):
    """ Esta función envía datos (data) a través del socket cs
        Devuelve el número de bytes enviados.
    """
    return cs.send(data)


def recibir_mensaje(cs):
    """ Esta función recibe datos a través del socket cs
        Leemos la información que nos llega. recv() devuelve un string con los datos.
    """
    return cs.recv(BUFSIZE).decode()


def cerrar_conexion(cs):
    """ Esta función cierra una conexión activa.
    """
    cs.close()


def enviar_error(cs, webroot, error):
    url = webroot + "/errors/error" + error + ".html"
    size = os.stat(url).st_size
    extention = "html"
    f = open(url, "rb", BUFSIZE)
    text = f.read(size)
    f.close()
    resp = "HTTP/1.1" + errortypes[error] + "\r\n" + \
        "Date: " + datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT') + "\r\n" + \
        "Server: web.shiroiwebmail27.org\r\n" + \
        "Content-Length: " + str(size) + "\r\n" + \
        "Connection: keep-Alive\r\n" + \
        "Keep-Alive: timeout= " + str(TIMEOUT_CONNECTION+1) + "\r\n" + \
        "Content-Type: " + filetypes[extention] + "; charset=utf-8\r\n" + \
        "\r\n"
    enviar_mensaje(cs, resp.encode() + text)


def process_cookies(headers):
    """ Esta función procesa la cookie cookie_counter
        1. Se analizan las cabeceras en headers para buscar la cabecera Cookie
        2. Una vez encontrada una cabecera Cookie se comprueba si el valor es cookie_counter
        3. Si no se encuentra cookie_counter , se devuelve 1
        4. Si se encuentra y tiene el valor MAX_ACCESOS se devuelve MAX_ACCESOS
        5. Si se encuentra y tiene un valor 1 <= x < MAX_ACCESOS se incrementa en 1 y se devuelve el valor
    """
    for header in headers:
        result = er_cookie.fullmatch(header)
        if result:
            cookie_counter = int(result.group(2))
            return cookie_counter+1
    return 1


def process_web_request(cs, webroot):
    """ 
    Procesamiento principal de los mensajes recibidos.
    Típicamente se seguirá un procedimiento similar al siguiente (aunque el alumno puede modificarlo si lo desea)

    * Bucle para esperar hasta que lleguen datos en la red a través del socket cs con select()
    """
    rlist = [cs]
    xlist = [cs]
    wlist = []
    while True:
        rsublist = []
        wsublist = []
        xsublist = []
        rsublist, wsublist, xsublist = select.select(
            rlist, wlist, xlist, TIMEOUT_CONNECTION)
        """
        * Se comprueba si hay que cerrar la conexión por exceder TIMEOUT_CONNECTION segundos
        sin recibir ningún mensaje o hay datos. Se utiliza select.select
        * Si no es por timeout y hay datos en el socket cs.
            * Leer los datos con recv.
            * Analizar la línea de solicitud y comprobar que está bien formateada según HTTP 1.1
                * Devuelve una lista con los atributos de las cabeceras.
                * Comprobar si la versión de HTTP es 1.1
                * Comprobar si es un método GET. Si no devolver un error Error 405 "Method Not Allowed".
                * Leer URL y eliminar parámetros si los hubiera
                * Comprobar si el recurso solicitado es /, En ese caso el recurso es index.html
                * Construir la ruta absoluta del recurso (webroot + recurso solicitado)
                * Comprobar que el recurso (fichero) existe, si no devolver Error 404 "Not found"
                * Analizar las cabeceras. Imprimir cada cabecera y su valor. Si la cabecera es Cookie comprobar
                el valor de cookie_counter para ver si ha llegado a MAX_ACCESOS.
                Si se ha llegado a MAX_ACCESOS devolver un Error "403 Forbidden"
                * Obtener el tamaño del recurso en bytes.
                * Extraer extensión para obtener el tipo de archivo. Necesario para la cabecera Content-Type
                * Preparar respuesta con código 200. Construir una respuesta que incluya: la línea de respuesta y
                las cabeceras Date, Server, Connection, Set-Cookie (para la cookie cookie_counter),
                Content-Length y Content-Type.
                * Leer y enviar el contenido del fichero a retornar en el cuerpo de la respuesta.
                * Se abre el fichero en modo lectura y modo binario
                    * Se lee el fichero en bloques de BUFSIZE bytes (8KB)
                    * Cuando ya no hay más información para leer, se corta el bucle

        * Si es por timeout, se cierra el socket tras el período de persistencia.
            * NOTA: Si hay algún error, enviar una respuesta de error con una pequeña página HTML que informe del error.
        """
        if rsublist == [cs]:
            data = recibir_mensaje(cs)
            headers = data.split("\r\n")
            result = er_request.fullmatch(headers[0])
            host = False
            for header in headers:
                result2 = er_host.fullmatch(header)
                if result2:
                    host = True
            if result and host:
                if not result.group(1) == "GET":
                    logger.info("Error 405 Method Not Allowed")
                    return enviar_error(cs, webroot, "405")
                url = result.group(2)
                url, c, param = url.partition('?')
                if url == '/':
                    url = "/index.html"
                url = webroot + url
                if not os.path.isfile(url):
                    logger.info("Error 404 Not Found")
                    return enviar_error(cs, webroot, "404")
                cookie_counter = process_cookies(headers)
                if cookie_counter == MAX_ACCESOS:
                    logger.info("Error 403 Forbidden")
                    return enviar_error(cs, webroot, "403")
                size = os.stat(url).st_size
                extention = os.path.basename(url).split('.')[1]
                resp = "HTTP/1.1 200 OK\r\n" + \
                    "Date: " + datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT') + "\r\n" + \
                    "Server: web.shiroiwebmail27.org\r\n" + \
                    "Content-Length: " + str(size) + "\r\n" + \
                    "Connection: keep-Alive\r\n" + \
                    "Keep-Alive: timeout= " + str(TIMEOUT_CONNECTION+1) + "\r\n" + \
                    "Content-Type: " + filetypes[extention] + "; charset=utf-8\r\n" + \
                    "Set-Cookie: cookie_counter=" + str(cookie_counter) + "; Max-Age=" + str(120) + "\r\n" + \
                    "\r\n"
                f = open(url, "rb", BUFSIZE)
                text = f.read(size)
                f.close()
                resp = resp.encode() + text
                enviar_mensaje(cs, resp)


def main():
    """ Función principal del servidor
    """
    try:
        # Argument parser para obtener la ip y puerto de los parámetros de ejecución del programa. IP por defecto 0.0.0.0
        parser = argparse.ArgumentParser()
        parser.add_argument(
            "-p", "--port", help="Puerto del servidor", type=int, required=True)
        parser.add_argument(
            "-ip", "--host", help="Dirección IP del servidor o localhost", required=True)
        parser.add_argument(
            "-wb", "--webroot", help="Directorio base desde donde se sirven los ficheros (p.ej. /home/user/mi_web)")
        parser.add_argument('--verbose', '-v', action='store_true',
                            help='Incluir mensajes de depuración en la salida')
        args = parser.parse_args()

        if args.verbose:
            logger.setLevel(logging.DEBUG)

        logger.info('Enabling server in address {} and port {}.'.format(
            args.host, args.port))

        logger.info("Serving files from {}".format(args.webroot))

        """ Funcionalidad a realizar
        * Crea un socket TCP (SOCK_STREAM)
        """
        cs = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        """
        * Permite reusar la misma dirección previamente vinculada a otro proceso. Debe ir antes de sock.bind
        """
        cs.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        """
        * Vinculamos el socket a una IP y puerto elegidos
        """
        cs.bind((args.host, args.port))
        """
        * Escucha conexiones entrantes
        """
        cs.listen()
        """
        * Bucle infinito para mantener el servidor activo indefinidamente
        """
        while True:
            """
            - Aceptamos la conexión
            """
            conn, addr = cs.accept()
            """
            - Creamos un proceso hijo
            """
            pid = os.fork()
            """
            - Si es el proceso hijo se cierra el socket del padre y procesar la petición con process_web_request()
            - Si es el proceso padre cerrar el socket que gestiona el hijo.
            """
            if pid == 0:
                cerrar_conexion(cs)
                process_web_request(conn, args.webroot)
                break
            else:
                cerrar_conexion(conn)
    except KeyboardInterrupt:
        True


if __name__ == "__main__":
    main()
