# coding=utf-8
#!/usr/bin/env python3

from asyncio.base_subprocess import WriteSubprocessPipeProto
import socket
import selectors                          # https://docs.python.org/3/library/selectors.html
import select
import types                              # Para definir el tipo de datos data
import argparse                           # Leer parametros de ejecución
import os                                 # Obtener ruta y extension
from datetime import datetime, timedelta  # Fechas de los mensajes HTTP
import time                               # Timeout conexión
import sys                                # sys.exit
import re                                 # Analizador sintáctico
import logging                            # Para imprimir logs


BUFSIZE = 8192                            # Tamaño máximo del buffer que se puede utilizar
TIMEOUT_CONNECTION = 20                   # Timeout para la conexión persistente
MAX_ACCESOS = 10

# Extensiones admitidas (extension, name in HTTP)
filetypes = {"gif": "image/gif", "jpg": "image/jpg", "jpeg": "image/jpeg", "png": "image/png", "htm": "text/htm",
             "html": "text/html", "css": "text/css", "js": "text/js"}

errortypes = {"400": "400 Bad Request", "403": "403 Forbidden",
              "404": "404 Not Found", "405": "405 Method Not Allowed", "505": "505 HTTP Version Not Supported"}

# Configuración de logging
logging.basicConfig(level=logging.INFO,
                    format='[%(asctime)s.%(msecs)03d] [%(levelname)-7s] %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger()

# Expresiones regulares
pattern_cookie = r'\bCookie: (.*; )*cookie_counter=(\d{1,2})(;.+)*$'
er_cookie = re.compile(pattern_cookie)
pattern_request = r'\b(GET|POST|HEAD|PUT|DELETE) (/.*) HTTP/(\d\.\d)$'
er_request = re.compile(pattern_request)


# La función send_error devuelve un mensaje de respuesta con un fichero html que muestra el error especificado
def send_error(cs, webroot, error):
    try:
        url = webroot + "/errors/error" + error + ".html"           # Forma la ruta del objeto error solicitado
        size = os.stat(url).st_size                                 # Obtiene el tamaño del " " "
        extention = "html"                                          # Especifica la extensión del " " "
        f = open(url, "rb", BUFSIZE)                                # Abre en modo binario el " " "
        text = f.read(size)                                         # Lee el contenido
        f.close()                                                   # Cierra el objeto
        resp = "HTTP/1.1 " + errortypes[error] + "\r\n" + \
            "Date: " + datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT') + "\r\n" + \
            "Server: web.shiroiwebmail27.org\r\n" + \
            "Content-Length: " + str(size) + "\r\n" + \
            "Connection: keep-Alive\r\n" + \
            "Keep-Alive: timeout= " + str(TIMEOUT_CONNECTION+1) + "\r\n" + \
            "Content-Type: " + filetypes[extention] + "; charset=utf-8\r\n" + \
            "\r\n"
        cs.send(resp.encode() + text)                               # Envía la respuesta formada por las cabeceras y el objeto error solicitado
        return False                                                # Devuelve False
    except socket.error as e:
        return True                                                 # Devuelve True si ha habido un error relacionado con el socket


# La función process_cookies asigna una cookie si el cliente no tiene, y en caso de tener se le incrementa el valor en 1
def process_cookies(headers):
    for header in headers:                                      # Para cada cabecera:
        result = er_cookie.fullmatch(header)                        # Analiza la cabecera
        if result:                                                  # Si es la cabecera cookie:
            cookie_counter = int(result.group(2))
            return cookie_counter+1                                     # Devuelve el valor de la cookie+1
    return 1                                                    # Devuelve 1


# La función process_web_request procesa los mensajes recibidos por parte de un cliente
def process_web_request(cs, webroot):
    rlist = [cs]                                                # Sockets de lectura
    xlist = [cs]                                                # " de excepciones
    wlist = []                                                  # " de escritura
    error = False
    while not error:                                            # Bucle para esperar hasta que lleguen datos en la red a través del socket cs con select()
        rsublist = []
        wsublist = []
        xsublist = []
        rsublist, wsublist, xsublist = select.select(
            rlist, wlist, xlist, TIMEOUT_CONNECTION)
        if rsublist == [cs]:                                        # Si hay caracteres disponibles para leer:
            try:                                                        
                data = cs.recv(BUFSIZE).decode()                        # Recibe la solicitud y la decodifica
            except UnicodeDecodeError as e:
                break                                                   # En caso de que la solicitud llegue vacía, corta la conexión
            headers = data.split("\r\n")                            
            result = er_request.fullmatch(headers[0])                   # Analiza la línea de solicitud
            if not result:                                              # Si la línea de solicitud no tiene el formato correcto:
                logger.info("Error 400 Bad Request")
                error = send_error(cs, webroot, "400")                      # Envía una respuesta con un objeto html que muestra el error 400
                continue                                                    # Termina de procesar la solicitud y vuelve a esperar a la próxima solicitud
            if not result.group(3) == "1.1":                            # Si la versión no es 1.1:
                logger.info("Error 505 Version Not Supported")
                error = send_error(cs, webroot, "505")                      # Envía una respuesta con un objeto html que muestra el error 505
                continue                                                    # Termina de procesar la solicitud y vuelve a esperar a la próxima solicitud
            if not result.group(1) == "GET":                            # Si el método no es GET:
                logger.info("Error 405 Method Not Allowed")
                error = send_error(cs, webroot, "405")                      # Envía una respuesta con un objeto html que muestra el error 405
                continue                                                    # Termina de procesar la solicitud y vuelve a esperar a la próxima solicitud
            url = result.group(2)                                       # Analiza la ruta
            url, c, param = url.partition('?')
            if url == '/':                                              # Si la ruta es la raíz:
                url = "/index.html"                                         # Selecciona la ruta del index.html
            url = webroot + url
            if not os.path.isfile(url):                                 # Si la ruta no existe:
                logger.info("Error 404 Not Found")
                error = send_error(cs, webroot, "404")                      # Envía una respuesta con un objeto html que muestra el error 404
                continue                                                    # Termina de procesar la solicitud y vuelve a esperar a la próxima solicitud
            cookie_counter = process_cookies(headers)                   # Procesamos las cookies del cliente
            if cookie_counter >= MAX_ACCESOS:                           # Si la cookie es mayor o igual que MAX_ACCESOS:
                logger.info("Error 403 Forbidden")
                error = send_error(cs, webroot, "403")                      # Envía una respuesta con un objeto html que muestra el error 403
                continue                                                    # Termina de procesar la solicitud y vuelve a esperar a la próxima solicitud
            size = os.stat(url).st_size                                 # Obtiene el tamaño del objeto solicitado
            extention = os.path.basename(url).split('.')[1]             # Obtiene la extensión del " "
            resp = "HTTP/1.1 200 OK\r\n" + \
                "Date: " + datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT') + "\r\n" + \
                "Server: web.shiroiwebmail27.org\r\n" + \
                "Content-Length: " + str(size) + "\r\n" + \
                "Connection: keep-alive\r\n" + \
                "Keep-Alive: timeout=" + str(TIMEOUT_CONNECTION+1) + "\r\n" + \
                "Content-Type: " + filetypes[extention] + "; charset=utf-8\r\n" + \
                "Set-Cookie: cookie_counter=" + str(cookie_counter) + "; Max-Age=" + str(120) + "\r\n" + \
                "\r\n"
            f = open(url, "rb", BUFSIZE)                                # Abre en modo binario el " "
            text = f.read(size)                                         # Lee el contenido
            f.close()                                                   # Cierra el objeto solicitado
            try:
                cs.send(resp.encode() + text)                           # Envía la respuesta formada por las cabeceras y el objeto solicitado
            except socket.error as e:
                break                                                   # En caso de que haya algún error relacionado con el socket, corta la conexión
                
        elif wsublist == [] and xsublist == []:                      # En caso de timeout:
            cs.close()                                                   # Cierra el socket
            break                                                        # Para el bucle


def main():
    """ Función principal del servidor
    """
    try:
        parser = argparse.ArgumentParser()                           # Argument parser para obtener la ip y puerto de los parámetros de ejecución del programa. IP por defecto 0.0.0.0
        parser.add_argument(
            "-p", "--port", help="Puerto del servidor", type=int, required=True)
        parser.add_argument(
            "-ip", "--host", help="Dirección IP del servidor o localhost", required=True)
        parser.add_argument(
            "-wb", "--webroot", help="Directorio base desde donde se sirven los ficheros (p.ej. /home/user/mi_web)")
        parser.add_argument('--verbose', '-v', action='store_true',
                            help='Incluir mensajes de depuración en la salida')
        args = parser.parse_args()
        # ------------------------------------------------------------------------------------------------------------------------- #
        if args.verbose:
            logger.setLevel(logging.DEBUG)

        logger.info('Enabling server in address {} and port {}.'.format(
            args.host, args.port))

        logger.info("Serving files from {}".format(args.webroot))
        # ------------------------------------------------------------------------------------------------------------------------- #
        cs = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)    # Crea un socket TCP (SOCK_STREAM)
        cs.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)     # Permite reusar la misma dirección previamente vinculada a otro proceso
        cs.bind((args.host, args.port))                              # Vincula el socket a una IP y puerto elegidos
        cs.listen()                                                  # Escucha conexiones entrantes
        while True:                                                  # Bucle para mantener el servidor activo indefinidamente
            conn, addr = cs.accept()                                      # Acepta la conexión entrante del cliente
            logger.info("Client {} connected".format(addr))
            pid = os.fork()                                               # Crea un proceso hijo
            if pid == 0:                                                  # El proceso hijo:
                cs.close()                                                    # Cierra el socket del proceso padre
                process_web_request(conn, args.webroot)                       # Procesa la solicitud del cliente
                logger.info(
                    "Timeout - Closing connection with {}".format(addr))
                break                                                         # Termina su ejecución
            else:                                                         # El proceso padre:
                conn.close()                                                  # Cierra el socket del proceso hijo
    except KeyboardInterrupt:
        True                                                          # En caso de Ctrl+C o Ctrl+Z, termina la ejecución del servidor


if __name__ == "__main__":
    main()