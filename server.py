import socket
import threading
import sqlite3
import json
import datetime
import base64
import os
import uuid
import hashlib

# Crear carpeta de servidor si no existe
if not os.path.exists("archivos_servidor"):
    os.makedirs("archivos_servidor")

HOST = '127.0.0.1'
PORT = 65432

# Diccionario para rastrear usuarios conectados: {usuario: socket_cliente}
clientes_conectados = {}
transferencias_activas = {} # <-- NUEVO: Para rastrear archivos en pedazos

def inicializar_bd():
    conn = sqlite3.connect('chat_app.db')
    cursor = conn.cursor()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS Usuarios (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT, usuario TEXT UNIQUE, password TEXT, perfil_id INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS Auditoria_Login (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, ip TEXT, usuario TEXT, accion TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS Mensajes_Directos (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, remitente TEXT, destinatario TEXT, mensaje TEXT, es_archivo BOOLEAN DEFAULT 0, archivo_path TEXT, reply_to TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS Grupos (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE, solo_gestores BOOLEAN DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS Grupo_Miembros (grupo_id INTEGER, usuario_id INTEGER, es_gestor BOOLEAN DEFAULT 0)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS Archivos (id INTEGER PRIMARY KEY AUTOINCREMENT,remitente TEXT,destino TEXT,nombre_original TEXT,nombre_servidor TEXT,fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    
    # --- NUEVA TABLA PARA HISTORIAL GRUPAL ---
    cursor.execute('''CREATE TABLE IF NOT EXISTS Mensajes_Grupos (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, grupo TEXT, remitente TEXT, mensaje TEXT)''')
    
    cursor.execute("SELECT * FROM Usuarios WHERE usuario='admin'")
    if not cursor.fetchone():
        salt = "ChatAppEmpresarial_Secreto!"
        admin_pass_hash = hashlib.sha256(("admin" + salt).encode('utf-8')).hexdigest()
        
        cursor.execute("INSERT INTO Usuarios (nombre, usuario, password, perfil_id) VALUES ('Administrador', 'admin', ?, 1)", (admin_pass_hash,))
        
    try:
        cursor.execute("ALTER TABLE Mensajes_Grupos ADD COLUMN reply_to TEXT")
    except:
        pass # Si ya existe, no hace nada
        
    try:
        cursor.execute("ALTER TABLE Mensajes_Directos ADD COLUMN reply_to TEXT")
    except:
        pass

    conn.commit()
    conn.close()

def registrar_auditoria(usuario, ip, accion):
    conn = sqlite3.connect('chat_app.db')
    cursor = conn.cursor()
    fecha = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO Auditoria_Login (fecha, ip, usuario, accion) VALUES (?, ?, ?, ?)", (fecha, ip, usuario, accion))
    conn.commit()
    conn.close()

def guardar_mensaje_directo(remitente, destinatario, mensaje):
    conn = sqlite3.connect('chat_app.db')
    cursor = conn.cursor()
    fecha = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO Mensajes_Directos (fecha, remitente, destinatario, mensaje) VALUES (?, ?, ?, ?)", (fecha, remitente, destinatario, mensaje))
    conn.commit()
    conn.close()

def notificar_cambio_estado(excluir_usuario=None):
    # En lugar de armar listas globales que pueden sobreescribir los grupos personales,
    # simplemente le damos la orden a todos los clientes de que vuelvan a pedir su panel.
    # Así, cada cliente ejecuta su propio OBTENER_PANEL y recibe exactamente lo suyo.
    paquete = json.dumps({"accion": "REFRESCAR_PANEL"}).encode('utf-8')
    
    for usr, conn in clientes_conectados.items():
        if usr != excluir_usuario:
            try: conn.send(paquete)
            except: pass

def forzar_recarga_cliente(usuario_objetivo, nuevo_perfil=None):
    """Fuerza al cliente a recargar su interfaz si le cambiaron los permisos"""
    if usuario_objetivo in clientes_conectados:
        msg = {"accion": "RECARGAR_INTERFAZ"}
        if nuevo_perfil is not None:
            msg["nuevo_perfil"] = nuevo_perfil
        try:
            clientes_conectados[usuario_objetivo].send(json.dumps(msg).encode('utf-8'))
        except: pass

def manejar_cliente(conn, addr):
    usuario_actual = None
    usuario_real = None
    buffer_texto = ""  # <-- NUEVO: Nuestra memoria temporal infalible
    decoder = json.JSONDecoder()
    
    try:
        while True:
            datos = conn.recv(1024 * 64).decode('utf-8') # 64KB es el tamaño óptimo de red
            if not datos:
                break
                
            buffer_texto += datos # Acumulamos lo que llegue de la red
            
            while buffer_texto:
                buffer_texto = buffer_texto.lstrip() # Quitamos espacios vacíos
                if not buffer_texto:
                    break
                    
                try:
                    # Intenta extraer un JSON completo y nos dice dónde termina (indice)
                    peticion, indice = decoder.raw_decode(buffer_texto)
                    buffer_texto = buffer_texto[indice:] # Recortamos el buffer reteniendo lo sobrante
                except json.JSONDecodeError:
                    # Si el JSON está incompleto, rompemos este mini-bucle y esperamos el siguiente recv()
                    break 
                    
                accion = peticion.get("accion")

                if accion == "LOGIN":
                    usuario = peticion.get("usuario")
                    password = peticion.get("password")
                    
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    cursor.execute("SELECT id, perfil_id FROM Usuarios WHERE usuario=? AND password=?", (usuario, password))
                    user_data = cursor.fetchone()
                    
                    if user_data:
                        perfil_id = user_data[1]
                        clientes_conectados[usuario] = conn
                        usuario_actual = usuario
                        
                        # 1. Le damos acceso al cliente
                        conn.send(json.dumps({"status": "OK", "perfil": perfil_id}).encode('utf-8'))
                        db_conn.close() # Cerramos la BD de validación
                        
                        # 2. Llamamos a la función maestra
                        notificar_cambio_estado()
                        
                        # 3. Registrar auditoría 
                        fecha = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        db_conn = sqlite3.connect('chat_app.db')
                        cursor = db_conn.cursor()
                        cursor.execute("INSERT INTO Auditoria_Login (fecha, ip, usuario, accion) VALUES (?, ?, ?, ?)", (fecha, addr[0], usuario, "LOGIN"))
                        db_conn.commit()
                        db_conn.close()
                    else:
                        conn.send(json.dumps({"status": "ERROR", "mensaje": "Credenciales incorrectas"}).encode('utf-8'))
                        db_conn.close()

                elif accion == "ENVIAR_MENSAJE":
                    destinatario = peticion.get("destinatario")
                    mensaje = peticion.get("mensaje")
                    reply_to = peticion.get("reply_to")
                    
                    # Capturamos la fecha y hora actual
                    fecha_actual = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    
                    if destinatario.startswith("#"):
                        nombre_grupo = destinatario[1:]

                        cursor.execute("SELECT es_gestor FROM Grupo_Miembros WHERE usuario_id=(SELECT id FROM Usuarios WHERE usuario=?) AND grupo_id=(SELECT id FROM Grupos WHERE nombre=?)", (usuario_actual, nombre_grupo))
                        es_gest_db = cursor.fetchone()
                        pref_gestor = "[Gestor]-" if es_gest_db and es_gest_db[0] == 1 else ""
                        
                        # --- FIX: Agregamos la columna 'fecha' a la inserción ---
                        cursor.execute("INSERT INTO Mensajes_Grupos (grupo, remitente, mensaje, fecha, reply_to) VALUES (?, ?, ?, ?, ?)", (nombre_grupo, usuario_actual, mensaje, fecha_actual, reply_to))
                        db_conn.commit()
                        
                        cursor.execute("SELECT Usuarios.usuario FROM Grupo_Miembros JOIN Usuarios ON Grupo_Miembros.usuario_id = Usuarios.id JOIN Grupos ON Grupos.id = Grupo_Miembros.grupo_id WHERE Grupos.nombre=?", (nombre_grupo,))
                        miembros = [row[0] for row in cursor.fetchall()]
                        
                        paquete_vivo = json.dumps({
                        "accion": "NUEVO_MENSAJE", 
                        "remitente": f"{pref_gestor}{usuario_actual} (#{nombre_grupo})", # ¡Cambio aquí!
                        "mensaje": mensaje,
                        "reply_to": reply_to
                        }).encode('utf-8')
                        
                        for miembro in miembros:
                            if miembro in clientes_conectados and miembro != usuario_actual:
                                try: clientes_conectados[miembro].send(paquete_vivo)
                                except: pass
                    else:
                        # --- FIX: Agregamos la columna 'fecha' a la inserción ---
                        cursor.execute("INSERT INTO Mensajes_Directos (remitente, destinatario, mensaje, fecha, reply_to) VALUES (?, ?, ?, ?, ?)", (usuario_actual, destinatario, mensaje, fecha_actual, reply_to))
                        db_conn.commit()
                        
                        paquete_vivo = json.dumps({
                            "accion": "NUEVO_MENSAJE", 
                            "remitente": usuario_actual, 
                            "mensaje": mensaje,
                            "reply_to": reply_to
                        }).encode('utf-8')
                        
                        if destinatario in clientes_conectados:
                            try: clientes_conectados[destinatario].send(paquete_vivo)
                            except: pass
                            
                    db_conn.close()

                # --- NUEVAS ACCIONES DE GESTIÓN DE GRUPOS ---
                elif accion == "CREAR_GRUPO":
                    nombre_grupo = peticion.get("nombre_grupo")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    try:
                        cursor.execute("INSERT INTO Grupos (nombre) VALUES (?)", (nombre_grupo,))
                        # El que lo crea es Gestor automáticamente (1)
                        cursor.execute("INSERT INTO Grupo_Miembros (grupo_id, usuario_id, es_gestor) VALUES ((SELECT id FROM Grupos WHERE nombre=?), (SELECT id FROM Usuarios WHERE usuario=?), 1)", (nombre_grupo, usuario_actual))
                        db_conn.commit()
                        registrar_auditoria(usuario_actual, addr[0], f"CREÓ GRUPO: #{nombre_grupo}") # <-- NUEVO
                        notificar_cambio_estado()
                        respuesta = {"accion": "INFO", "mensaje": f"Grupo #{nombre_grupo} creado exitosamente. Eres Gestor."}
                    except sqlite3.IntegrityError:
                        respuesta = {"accion": "ERROR", "mensaje": "El grupo ya existe."}
                    db_conn.close()
                    conn.send(json.dumps(respuesta).encode('utf-8'))

                elif accion == "AGREGAR_MIEMBRO":
                    nombre_grupo = peticion.get("nombre_grupo")
                    nuevo_usuario = peticion.get("nuevo_usuario") # Debe ser la CUENTA de usuario, no el nombre
                    hacer_gestor = peticion.get("hacer_gestor", 0)
                    
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    
                    # 1. Validar estrictamente si la cuenta de usuario EXISTE
                    cursor.execute("SELECT id FROM Usuarios WHERE usuario=?", (nuevo_usuario,))
                    user_obj = cursor.fetchone()
                    
                    if not user_obj:
                        respuesta = {"accion": "ERROR", "mensaje": f"La cuenta de usuario '{nuevo_usuario}' no existe."}
                        conn.send(json.dumps(respuesta).encode('utf-8'))
                        db_conn.close()
                        continue
                        
                    id_nuevo_usuario = user_obj[0]
                    
                    # 2. Validar si soy gestor del grupo
                    cursor.execute("SELECT es_gestor, grupo_id FROM Grupo_Miembros JOIN Grupos ON Grupos.id = Grupo_Miembros.grupo_id WHERE Grupos.nombre=? AND usuario_id=(SELECT id FROM Usuarios WHERE usuario=?)", (nombre_grupo, usuario_actual))
                    auth = cursor.fetchone()
                    
                    if auth and auth[0] == 1:
                        # 3. Validar que el usuario no esté ya en el grupo
                        cursor.execute("SELECT 1 FROM Grupo_Miembros WHERE grupo_id=? AND usuario_id=?", (auth[1], id_nuevo_usuario))
                        if cursor.fetchone():
                            respuesta = {"accion": "ERROR", "mensaje": "Este usuario ya pertenece al grupo."}
                        else:
                            # 4. Insertar de forma segura
                            cursor.execute("INSERT INTO Grupo_Miembros (grupo_id, usuario_id, es_gestor) VALUES (?, ?, ?)", (auth[1], id_nuevo_usuario, hacer_gestor))
                            db_conn.commit()
                            respuesta = {"accion": "INFO", "mensaje": f"Usuario '{nuevo_usuario}' añadido al grupo #{nombre_grupo}."}
                            
                            # Avisamos a los DEMÁS clientes para que refresquen (evita colisión de sockets en mi propio cliente)
                            notificar_cambio_estado(excluir_usuario=usuario_actual)
                    else:
                        respuesta = {"accion": "ERROR", "mensaje": "No eres gestor de este grupo o el grupo no existe."}
                        
                    db_conn.close()
                    conn.send(json.dumps(respuesta).encode('utf-8'))
                    
                elif accion == "BLOQUEAR_GRUPO":
                    nombre_grupo = peticion.get("nombre_grupo")
                    bloquear = peticion.get("bloquear") # 1 o 0
                    
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    cursor.execute("SELECT es_gestor, grupo_id FROM Grupo_Miembros JOIN Grupos ON Grupos.id = Grupo_Miembros.grupo_id WHERE Grupos.nombre=? AND usuario_id=(SELECT id FROM Usuarios WHERE usuario=?)", (nombre_grupo, usuario_actual))
                    auth = cursor.fetchone()
                    
                    if auth and auth[0] == 1:
                        cursor.execute("UPDATE Grupos SET solo_gestores=? WHERE id=?", (bloquear, auth[1]))
                        db_conn.commit()
                        estado = "bloqueado (Solo Gestores)" if bloquear else "desbloqueado (Todos escriben)"
                        respuesta = {"accion": "INFO", "mensaje": f"Grupo #{nombre_grupo} ha sido {estado}."}
                    else:
                        respuesta = {"accion": "ERROR", "mensaje": "No tienes permiso de gestor para hacer esto."}
                    db_conn.close()
                    conn.send(json.dumps(respuesta).encode('utf-8'))

                elif accion == "CREAR_USUARIO":
                    # Módulo ABM Cuentas (Alta)
                    nuevo_user = peticion.get("nuevo_usuario")
                    nuevo_pass = peticion.get("password")
                    nombre = peticion.get("nombre")
                    perfil = peticion.get("perfil_id", 2) # 2 = Usuario normal por defecto

                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    try:
                        cursor.execute("INSERT INTO Usuarios (nombre, usuario, password, perfil_id) VALUES (?, ?, ?, ?)", 
                                    (nombre, nuevo_user, nuevo_pass, perfil))
                        db_conn.commit()
                        notificar_cambio_estado()
                        respuesta = {"accion": "INFO", "mensaje": f"Usuario {nuevo_user} creado con éxito."}
                        registrar_auditoria(usuario_actual, addr[0], f"CREO_USUARIO: {nuevo_user}")
                    except sqlite3.IntegrityError:
                        respuesta = {"accion": "ERROR", "mensaje": "El nombre de usuario ya existe."}
                    finally:
                        db_conn.close()
                    
                    conn.send(json.dumps(respuesta).encode('utf-8'))

                elif accion == "CREAR_GRUPO":
                    # Módulo ABM Grupos (Alta)
                    nombre_grupo = peticion.get("nombre_grupo")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    cursor.execute("INSERT INTO Grupos (nombre) VALUES (?)", (nombre_grupo,))
                    grupo_id = cursor.lastrowid
                    # El creador se añade automáticamente como gestor
                    cursor.execute("INSERT INTO Grupo_Miembros (grupo_id, usuario_id, es_gestor) VALUES (?, (SELECT id FROM Usuarios WHERE usuario=?), 1)", 
                                (grupo_id, usuario_actual))
                    db_conn.commit()
                    notificar_cambio_estado()
                    db_conn.close()
                    
                    respuesta = {"accion": "INFO", "mensaje": f"Grupo '{nombre_grupo}' creado."}
                    conn.send(json.dumps(respuesta).encode('utf-8'))

                elif accion == "CONSULTAR_AUDITORIA":
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    cursor.execute("SELECT fecha, ip, usuario, accion FROM Auditoria_Login ORDER BY id DESC LIMIT 500") # <-- Aumentado a 500
                    registros = cursor.fetchall()
                    db_conn.close()

                    respuesta = {
                        "accion": "RESULTADO_AUDITORIA",
                        "datos": registros
                    }
                    conn.send(json.dumps(respuesta).encode('utf-8'))

                elif accion == "ENVIAR_MENSAJE_GRUPO":
                    # Módulo de Chat Grupal
                    grupo_id = peticion.get("grupo_id")
                    mensaje = peticion.get("mensaje")
                    
                    # 1. Guardar en BD (Tabla Mensajes_Grupos) - Omitido por brevedad, similar a Mensajes_Directos
                    # 2. Obtener todos los miembros del grupo
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    cursor.execute("SELECT Usuarios.usuario FROM Grupo_Miembros JOIN Usuarios ON Grupo_Miembros.usuario_id = Usuarios.id WHERE grupo_id=?", (grupo_id,))
                    miembros = [row[0] for row in cursor.fetchall()]
                    db_conn.close()

                    # 3. Enviar a los miembros conectados
                    msg_data = {
                        "accion": "NUEVO_MENSAJE",
                        "remitente": f"{usuario_actual} (Grupo {grupo_id})",
                        "mensaje": mensaje
                    }
                    for miembro in miembros:
                        if miembro in clientes_conectados and miembro != usuario_actual:
                            try:
                                clientes_conectados[miembro].send(json.dumps(msg_data).encode('utf-8'))
                            except:
                                pass

                elif accion == "INICIO_ARCHIVO":
                    # 1. Preparamos el servidor para recibir múltiples pedazos
                    transfer_id = uuid.uuid4().hex
                    nombre_archivo = peticion.get("nombre_archivo")
                    destinatario = peticion.get("destinatario")
                    
                    nombre_unico = f"{transfer_id}_{nombre_archivo}"
                    ruta_guardado = os.path.join("archivos_servidor", nombre_unico)
                    
                    # Guardamos el estado de esta transferencia
                    transferencias_activas[transfer_id] = {
                        "ruta": ruta_guardado,
                        "destinatario": destinatario,
                        "nombre_original": nombre_archivo,
                        "remitente": usuario_actual,
                        "hash_original": peticion.get("hash_original") # GUARDAMOS EL HASH
                    }
                    
                    # Le damos permiso al cliente para que empiece a disparar los pedazos
                    conn.send(json.dumps({"accion": "PERMISO_ENVIO_CHUNKS", "transfer_id": transfer_id}).encode('utf-8'))

                elif accion == "CHUNK_ARCHIVO":
                    # 2. Recibimos un pedacito (512 KB) y lo sumamos al archivo físico en el disco
                    transfer_id = peticion.get("transfer_id")
                    datos_b64 = peticion.get("datos_base64")
                    
                    if transfer_id in transferencias_activas:
                        ruta = transferencias_activas[transfer_id]["ruta"]
                        # 'ab' significa Append Binary (agrega al final del archivo sin borrar lo anterior)
                        with open(ruta, "ab") as f:
                            f.write(base64.b64decode(datos_b64))

                elif accion == "FIN_ARCHIVO":
                    # 3. El cliente avisa que terminó. Registramos en BD y notificamos en el chat.
                    transfer_id = peticion.get("transfer_id")
                    if transfer_id in transferencias_activas:
                        info = transferencias_activas.pop(transfer_id) # Saca y borra la memoria temporal
                        destinatario = info["destinatario"]
                        nombre_archivo = info["nombre_original"]
                        ruta_final = info["ruta"]
                        nombre_unico = os.path.basename(ruta_final)

                        # --- NUEVO: VERIFICACIÓN DE CONTROL ---
                        with open(ruta_final, "rb") as f:
                            huella_recibida = hashlib.sha256(f.read()).hexdigest()
                            
                        if huella_recibida != info["hash_original"]:
                            os.remove(ruta_final) # Lo borramos porque llegó mal
                            conn.send(json.dumps({"accion": "ERROR", "mensaje": "Corrupción detectada en el archivo. Subida abortada."}).encode('utf-8'))
                            continue # Detenemos el proceso aquí
                        # ----------------------------------------
                        
                        fecha_actual = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        db_conn = sqlite3.connect('chat_app.db')
                        
                        try:
                            cursor = db_conn.cursor()
                            destino_db = destinatario[1:] if destinatario.startswith("#") else destinatario
                            # Insertamos en la tabla Archivos
                            cursor.execute("INSERT INTO Archivos (remitente, destino, nombre_original, nombre_servidor) VALUES (?, ?, ?, ?)", 
                                        (info["remitente"], destino_db, nombre_archivo, nombre_unico))
                            id_archivo = cursor.lastrowid 
                            
                            mensaje_chat = f"📎 [ARCHIVO:{id_archivo}] {nombre_archivo}"
                            
                            # Lógica de notificaciones
                            if destinatario.startswith("#"):
                                cursor.execute("INSERT INTO Mensajes_Grupos (grupo, remitente, mensaje, fecha, reply_to) VALUES (?, ?, ?, ?, ?)", (destino_db, info["remitente"], mensaje_chat, fecha_actual, None))
                                db_conn.commit()
                                
                                cursor.execute("SELECT es_gestor FROM Grupo_Miembros WHERE usuario_id=(SELECT id FROM Usuarios WHERE usuario=?) AND grupo_id=(SELECT id FROM Grupos WHERE nombre=?)", (info["remitente"], destino_db))
                                es_gest_db = cursor.fetchone()
                                pref_gestor = "[Gestor]-" if es_gest_db and es_gest_db[0] == 1 else ""

                                cursor.execute("SELECT Usuarios.usuario FROM Grupo_Miembros JOIN Usuarios ON Grupo_Miembros.usuario_id = Usuarios.id JOIN Grupos ON Grupos.id = Grupo_Miembros.grupo_id WHERE Grupos.nombre=?", (destino_db,))
                                miembros = [row[0] for row in cursor.fetchall()]
                                
                                paquete_vivo = json.dumps({"accion": "NUEVO_MENSAJE", "remitente": f"{pref_gestor}{info['remitente']} (#{destino_db})", "mensaje": mensaje_chat, "reply_to": None}).encode('utf-8')
                                
                                for miembro in miembros:
                                    if miembro in clientes_conectados and miembro != info["remitente"]:
                                        try: clientes_conectados[miembro].send(paquete_vivo)
                                        except: pass
                            else:
                                cursor.execute("INSERT INTO Mensajes_Directos (remitente, destinatario, mensaje, fecha, reply_to) VALUES (?, ?, ?, ?, ?)", (info["remitente"], destinatario, mensaje_chat, fecha_actual, None))
                                db_conn.commit()
                                
                                if destinatario in clientes_conectados:
                                    try: clientes_conectados[destinatario].send(json.dumps({"accion": "NUEVO_MENSAJE", "remitente": info["remitente"], "mensaje": mensaje_chat, "reply_to": None}).encode('utf-8'))
                                    except: pass
                                    
                        finally:
                            db_conn.close()

                        registrar_auditoria(info["remitente"], addr[0], f"SUBIÓ ARCHIVO: {nombre_archivo} a {destinatario}")
                        conn.send(json.dumps({"accion": "CONFIRMACION_ARCHIVO", "destinatario": destinatario, "mensaje": mensaje_chat}).encode('utf-8'))

                elif accion == "ELIMINAR_ARCHIVO":
                    try:
                        id_archivo = peticion.get("id_archivo")
                        db_conn = sqlite3.connect('chat_app.db')
                        cursor = db_conn.cursor()
                        
                        cursor.execute("SELECT remitente, destino, nombre_servidor, nombre_original FROM Archivos WHERE id=?", (id_archivo,))
                        arch = cursor.fetchone()
                        
                        if arch:
                            remitente, destino, nombre_servidor, nombre_original = arch
                            permitido = False
                            
                            # Lógica de permisos
                            cursor.execute("SELECT id FROM Grupos WHERE nombre=?", (destino,))
                            es_grupo = cursor.fetchone()
                            
                            if es_grupo: # Es un grupo, requiere ser Gestor
                                cursor.execute("SELECT es_gestor FROM Grupo_Miembros WHERE grupo_id=? AND usuario_id=(SELECT id FROM Usuarios WHERE usuario=?)", (es_grupo[0], usuario_actual))
                                auth = cursor.fetchone()
                                if auth and auth[0] == 1: permitido = True
                            else: # Es chat directo, cualquiera de los dos puede
                                if usuario_actual == remitente or usuario_actual == destino: permitido = True
                                
                            if permitido:
                                cursor.execute("DELETE FROM Archivos WHERE id=?", (id_archivo,))
                                db_conn.commit()
                                
                                ruta = os.path.join("archivos_servidor", nombre_servidor)
                                if os.path.exists(ruta): os.remove(ruta)
                                    
                                registrar_auditoria(usuario_actual, addr[0], f"ELIMINÓ ARCHIVO FÍSICO: {nombre_original} (ID: {id_archivo})")
                                conn.send(json.dumps({"accion": "INFO", "mensaje": "Archivo eliminado permanentemente."}).encode('utf-8'))
                            else:
                                conn.send(json.dumps({"accion": "ERROR", "mensaje": "No tienes permiso (Sólo Gestores pueden borrar en grupos)."}).encode('utf-8'))
                        else:
                            conn.send(json.dumps({"accion": "ERROR", "mensaje": "El archivo ya no existe."}).encode('utf-8'))
                            
                        db_conn.close()
                    except Exception as e:
                        conn.send(json.dumps({"accion": "ERROR", "mensaje": f"Error BD: {str(e)}"}).encode('utf-8'))

                elif accion == "LISTAR_ARCHIVOS_CHAT":
                    contacto = peticion.get("contacto")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    
                    # Seleccionamos también el nombre_servidor para poder buscarlo en el disco
                    if contacto.startswith("#"):
                        destino_db = contacto[1:]
                        cursor.execute("SELECT id, remitente, nombre_original, fecha, nombre_servidor FROM Archivos WHERE destino=? ORDER BY fecha DESC", (destino_db,))
                    else:
                        cursor.execute("SELECT id, remitente, nombre_original, fecha, nombre_servidor FROM Archivos WHERE (remitente=? AND destino=?) OR (remitente=? AND destino=?) ORDER BY fecha DESC", (usuario_actual, contacto, contacto, usuario_actual))
                    
                    archivos_db = cursor.fetchall()
                    db_conn.close()
                    
                    # --- NUEVO: Calcular el peso de los archivos en tiempo real ---
                    archivos_formateados = []
                    for arch in archivos_db:
                        id_arch, rem, nom_orig, fecha, nom_serv = arch
                        ruta = os.path.join("archivos_servidor", nom_serv)
                        
                        peso_str = "0 KB"
                        if os.path.exists(ruta):
                            peso_bytes = os.path.getsize(ruta)
                            # Convertir a KB o MB para que sea legible
                            if peso_bytes < 1024 * 1024:
                                peso_str = f"{peso_bytes / 1024:.1f} KB"
                            else:
                                peso_str = f"{peso_bytes / (1024 * 1024):.1f} MB"
                        else:
                            peso_str = "Archivo Perdido"
                            
                        # Empaquetamos todo (sin el nombre_servidor que es secreto)
                        archivos_formateados.append((id_arch, rem, nom_orig, peso_str, fecha))
                        
                    conn.send(json.dumps({"accion": "RESULTADO_ARCHIVOS_CHAT", "datos": archivos_formateados}).encode('utf-8'))

                elif accion == "DESCARGAR_ARCHIVO":
                    id_archivo = peticion.get("id_archivo")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    cursor.execute("SELECT nombre_original, nombre_servidor FROM Archivos WHERE id=?", (id_archivo,))
                    archivo_data = cursor.fetchone()
                    db_conn.close()
                    
                    if archivo_data:
                        nombre_original, nombre_servidor = archivo_data
                        ruta = os.path.join("archivos_servidor", nombre_servidor)
                        
                        if os.path.exists(ruta):
                            # Iniciar hilo de descarga para no bloquear la recepción de mensajes del usuario
                            def enviar_descarga_chunks():
                                transfer_id = uuid.uuid4().hex
                                # 1. Avisamos que inicia la descarga
                                conn.send(json.dumps({
                                    "accion": "INICIO_DESCARGA", 
                                    "transfer_id": transfer_id, 
                                    "nombre_archivo": nombre_original
                                }).encode('utf-8'))
                                
                                import time
                                time.sleep(0.1) # Breve pausa para que el cliente prepare la ruta
                                
                                try:
                                    with open(ruta, "rb") as f:
                                        while True:
                                            # 2. Leemos en pedazos seguros de 256 KB
                                            pedazo = f.read(1024 * 256) 
                                            if not pedazo:
                                                break
                                            
                                            datos_b64 = base64.b64encode(pedazo).decode('utf-8')
                                            conn.send(json.dumps({
                                                "accion": "CHUNK_DESCARGA", 
                                                "transfer_id": transfer_id, 
                                                "datos_base64": datos_b64
                                            }).encode('utf-8'))
                                            
                                            time.sleep(0.01) # Micro-pausa para evitar saturar el buffer TCP
                                            
                                    # 3. Avisamos que finalizó la transmisión
                                    conn.send(json.dumps({
                                        "accion": "FIN_DESCARGA", 
                                        "transfer_id": transfer_id, 
                                        "nombre_archivo": nombre_original
                                    }).encode('utf-8'))
                                    
                                    registrar_auditoria(usuario_actual, addr[0], f"DESCARGÓ ARCHIVO: {nombre_original}")
                                except Exception as e:
                                    print(f"Error en transferencia de descarga: {e}")

                            # Arrancamos la descarga en segundo plano
                            threading.Thread(target=enviar_descarga_chunks, daemon=True).start()
                        else:
                            conn.send(json.dumps({"accion": "ERROR", "mensaje": "El archivo físico ya no existe en el servidor."}).encode('utf-8'))

                elif accion == "OBTENER_HISTORIAL":
                    contacto = peticion.get("con_usuario")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    
                    respuesta = None # <-- FIX: Limpiamos la variable en cada petición
                    
                    if contacto.startswith("#"):
                        nombre_grupo = contacto[1:]
                        
                        # 1. Obtener quiénes son los gestores de este grupo
                        cursor.execute("SELECT Usuarios.usuario FROM Grupo_Miembros JOIN Usuarios ON Grupo_Miembros.usuario_id = Usuarios.id WHERE Grupo_Miembros.grupo_id=(SELECT id FROM Grupos WHERE nombre=?) AND Grupo_Miembros.es_gestor=1", (nombre_grupo,))
                        lista_gestores = [row[0] for row in cursor.fetchall()]

                        # 2. Permisos del usuario actual
                        cursor.execute("SELECT Grupos.solo_gestores, Grupo_Miembros.es_gestor FROM Grupos JOIN Grupo_Miembros ON Grupos.id = Grupo_Miembros.grupo_id WHERE Grupos.nombre=? AND usuario_id=(SELECT id FROM Usuarios WHERE usuario=?)", (nombre_grupo, usuario_actual))
                        grupo_data = cursor.fetchone()
                        
                        if grupo_data:
                            solo_gestores, es_gestor = grupo_data
                            cursor.execute("SELECT remitente, mensaje, reply_to FROM Mensajes_Grupos WHERE grupo=? ORDER BY fecha ASC", (nombre_grupo,))
                            historial_crudo = cursor.fetchall()
                            
                            historial_final = []
                            for msj in historial_crudo:
                                rem, texto, reply = msj
                                if rem in lista_gestores:
                                    rem = f"[Gestor]-{rem}"
                                historial_final.append((rem, texto, reply))
                                
                            # FIX: En vez de hacer conn.send aquí, se lo asignamos a la variable
                            respuesta = {"accion": "HISTORIAL_RECIBIDO", "mensajes": historial_final, "es_grupo": True, "es_gestor": bool(es_gestor), "solo_gestores": bool(solo_gestores)}
                    else:
                        cursor.execute('''SELECT remitente, mensaje, reply_to FROM Mensajes_Directos 
                                        WHERE (remitente=? AND destinatario=?) OR (remitente=? AND destinatario=?) ORDER BY fecha ASC''', (usuario_actual, contacto, contacto, usuario_actual))
                        historial = cursor.fetchall()
                        respuesta = {"accion": "HISTORIAL_RECIBIDO", "contacto": contacto, "mensajes": historial, "es_grupo": False}
                        
                    db_conn.close()
                    
                    # FIX: Hacemos UN SOLO ENVÍO, siempre y cuando 'respuesta' contenga datos
                    if respuesta:
                        conn.send(json.dumps(respuesta).encode('utf-8'))

                elif accion == "VACIAR_CHAT_GRUPO":
                    nombre_grupo = peticion.get("nombre_grupo")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    
                    # Verificar si es Gestor
                    cursor.execute("SELECT es_gestor FROM Grupo_Miembros JOIN Grupos ON Grupos.id = Grupo_Miembros.grupo_id WHERE Grupos.nombre=? AND usuario_id=(SELECT id FROM Usuarios WHERE usuario=?)", (nombre_grupo, usuario_actual))
                    auth = cursor.fetchone()
                    
                    if auth and auth[0] == 1:
                        cursor.execute("DELETE FROM Mensajes_Grupos WHERE grupo=?", (nombre_grupo,))
                        db_conn.commit()
                        registrar_auditoria(usuario_actual, addr[0], f"VACIÓ HISTORIAL DE GRUPO: #{nombre_grupo}") # <-- NUEVO
                        respuesta = {"accion": "INFO", "mensaje": f"Historial del grupo #{nombre_grupo} ha sido vaciado para todos."}
                    else:
                        respuesta = {"accion": "ERROR", "mensaje": "Permiso denegado. Solo los gestores pueden vaciar este chat."}
                    db_conn.close()
                    registrar_auditoria(usuario_actual, addr[0], f"VACIÓ CHAT PRIVADO CON: {contacto}") # <-- NUEVO
                    conn.send(json.dumps(respuesta).encode('utf-8'))

                elif accion == "IMPERSONAR":
                    objetivo = peticion.get("usuario_objetivo")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    
                    # 1. Verificar que el usuario actual es Admin (Perfil 1)
                    cursor.execute("SELECT perfil_id FROM Usuarios WHERE usuario=?", (usuario_actual,))
                    perfil = cursor.fetchone()
                    
                    if perfil and perfil[0] == 1:
                        # 2. Verificar que el usuario objetivo realmente existe en la BD
                        cursor.execute("SELECT id FROM Usuarios WHERE usuario=?", (objetivo,))
                        if cursor.fetchone():
                            
                            # 3. Cambiar la identidad en el diccionario de sockets
                            if usuario_actual in clientes_conectados:
                                del clientes_conectados[usuario_actual]
                                
                            # Guardamos la identidad original del Admin para poder volver
                            usuario_real = usuario_actual 
                            usuario_actual = objetivo
                            clientes_conectados[usuario_actual] = conn
                            
                            registrar_auditoria(usuario_real, addr[0], f"INICIO_IMPERSONAR: {objetivo}")
                            respuesta = {"accion": "IMPERSONACION_EXITOSA", "nuevo_usuario": objetivo, "mensaje": f"Ahora controlas la cuenta '{objetivo}'."}
                        else:
                            # Si llega aquí, es porque el SELECT del objetivo no encontró nada
                            respuesta = {"accion": "ERROR", "mensaje": f"El usuario '{objetivo}' no existe en la base de datos."}
                    else:
                        respuesta = {"accion": "ERROR", "mensaje": "Seguridad: Solo el Administrador puede impersonar."}
                        
                    db_conn.close()
                    conn.send(json.dumps(respuesta).encode('utf-8'))

                elif accion == "DEJAR_IMPERSONAR":
                    # Validamos que realmente estuviera impersonando a alguien
                    if usuario_real:
                        if usuario_actual in clientes_conectados:
                            del clientes_conectados[usuario_actual]
                            
                        registrar_auditoria(usuario_real, addr[0], f"FIN_IMPERSONAR: {usuario_actual}")
                        
                        # Devolvemos la identidad a la normalidad
                        usuario_actual = usuario_real
                        usuario_real = None
                        clientes_conectados[usuario_actual] = conn
                        
                        respuesta = {"accion": "FIN_IMPERSONACION", "usuario": usuario_actual, "mensaje": "Has vuelto a tu cuenta de Administrador."}
                        conn.send(json.dumps(respuesta).encode('utf-8'))

                elif accion == "LISTAR_GESTORES":
                    grupo = peticion.get("grupo")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    cursor.execute("SELECT Usuarios.usuario FROM Grupo_Miembros JOIN Usuarios ON Grupo_Miembros.usuario_id = Usuarios.id WHERE Grupo_Miembros.grupo_id=(SELECT id FROM Grupos WHERE nombre=?) AND Grupo_Miembros.es_gestor=1", (grupo,))
                    gestores = [row[0] for row in cursor.fetchall()]
                    db_conn.close()
                    conn.send(json.dumps({"accion": "RESULTADO_GESTORES", "datos": gestores}).encode('utf-8'))

                elif accion == "LISTAR_MIEMBROS_CHAT":
                    grupo = peticion.get("grupo")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    # Buscamos a todos los miembros y su rol
                    cursor.execute("SELECT Usuarios.usuario, Grupo_Miembros.es_gestor FROM Grupo_Miembros JOIN Usuarios ON Grupo_Miembros.usuario_id = Usuarios.id JOIN Grupos ON Grupos.id = Grupo_Miembros.grupo_id WHERE Grupos.nombre=?", (grupo,))
                    miembros = cursor.fetchall()
                    db_conn.close()
                    conn.send(json.dumps({"accion": "RESULTADO_MIEMBROS_CHAT", "datos": miembros}).encode('utf-8'))

                # --- ¡AQUÍ ESTÁ LA MAGIA CORREGIDA! ---
                elif accion == "OBTENER_PANEL":
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    
                    # 1. Obtener todos los usuarios y sus perfiles
                    cursor.execute("SELECT usuario, perfil_id FROM Usuarios")
                    todos_usuarios = cursor.fetchall()
                    
                    lista_usuarios = []
                    for usr, perfil in todos_usuarios:
                        estado_texto = " [🟢 Online]" if usr in clientes_conectados else " [🔴 Offline]"
                        prefijo = "[Admin] " if int(perfil) == 1 else ""
                        lista_usuarios.append(f"{prefijo}{usr}{estado_texto}")
                    
                    # 2. Obtener grupos a los que pertenece
                    cursor.execute("SELECT Grupos.nombre FROM Grupo_Miembros JOIN Grupos ON Grupos.id = Grupo_Miembros.grupo_id WHERE usuario_id=(SELECT id FROM Usuarios WHERE usuario=?)", (usuario_actual,))
                    mis_grupos = [f"#{row[0]}" for row in cursor.fetchall()]
                    
                    db_conn.close()
                    respuesta = {"accion": "ACTUALIZAR_PANEL", "usuarios": lista_usuarios, "grupos": mis_grupos}
                    conn.send(json.dumps(respuesta).encode('utf-8'))
                # --------------------------------------

                elif accion == "VACIAR_CHAT":
                    contacto = peticion.get("con_usuario")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    
                    # Eliminamos los registros de la base de datos entre estos dos usuarios
                    cursor.execute('''DELETE FROM Mensajes_Directos 
                                    WHERE (remitente=? AND destinatario=?) OR (remitente=? AND destinatario=?)''', 
                                (usuario_actual, contacto, contacto, usuario_actual))
                    db_conn.commit()
                    db_conn.close()
                    
                    respuesta = {"accion": "INFO", "mensaje": f"Chat con {contacto} eliminado del servidor."}
                    conn.send(json.dumps(respuesta).encode('utf-8'))
                    
                    # Opcional: Avisar al otro usuario en tiempo real si está conectado
                    if contacto in clientes_conectados:
                        aviso = {"accion": "INFO", "mensaje": f"{usuario_actual} ha vaciado el historial de chat contigo."}
                        clientes_conectados[contacto].send(json.dumps(aviso).encode('utf-8'))

                elif accion == "CAMBIAR_PASSWORD":
                    pass_actual = peticion.get("password_actual")
                    pass_nueva = peticion.get("password_nueva")
                    
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    
                    # Verificar si la contraseña actual es correcta
                    cursor.execute("SELECT id FROM Usuarios WHERE usuario=? AND password=?", (usuario_actual, pass_actual))
                    if cursor.fetchone():
                        # Si coincide, actualizamos a la nueva
                        cursor.execute("UPDATE Usuarios SET password=? WHERE usuario=?", (pass_nueva, usuario_actual))
                        db_conn.commit()
                        respuesta = {"accion": "INFO", "mensaje": "Contraseña actualizada correctamente."}
                        
                        # Dejamos registro en la auditoría
                        registrar_auditoria(usuario_actual, addr[0], "CAMBIO_PASSWORD")
                    else:
                        respuesta = {"accion": "ERROR", "mensaje": "La contraseña actual es incorrecta."}
                        
                    db_conn.close()
                    conn.send(json.dumps(respuesta).encode('utf-8'))

                # --- ABM CUENTAS ---
                elif accion == "LISTAR_CUENTAS":
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    cursor.execute("SELECT id, nombre, usuario, perfil_id FROM Usuarios")
                    cuentas = cursor.fetchall()
                    db_conn.close()
                    conn.send(json.dumps({"accion": "RESULTADO_CUENTAS", "datos": cuentas}).encode('utf-8'))

                # --- ABM CUENTAS ---
                elif accion == "CAMBIAR_ROL_ADMIN":
                    try:
                        usuarios = peticion.get("usuarios", [])
                        es_admin = peticion.get("es_admin")
                        nuevo_perfil = 1 if es_admin else 2
                        
                        # 1. Modificamos la base de datos
                        db_conn = sqlite3.connect('chat_app.db')
                        cursor = db_conn.cursor()
                        for usr in usuarios:
                            cursor.execute("UPDATE Usuarios SET perfil_id=? WHERE usuario=?", (nuevo_perfil, usr))
                        db_conn.commit()
                        db_conn.close() # <-- CERRAMOS LA CONEXIÓN PRIMERO
                        
                        # 2. Registramos la auditoría de forma segura (sin bloquear la BD)
                        for usr in usuarios:
                            registrar_auditoria(usuario_actual, addr[0], f"ABM CUENTAS: Cambió rol admin a '{usr}' -> {es_admin}")
                            forzar_recarga_cliente(usr, nuevo_perfil)
                            
                        notificar_cambio_estado(excluir_usuario=usuario_actual)
                        conn.send(json.dumps({"accion": "INFO", "mensaje": "Roles actualizados exitosamente."}).encode('utf-8'))
                    except Exception as e:
                        # Si algo falla, el servidor NO muere, te avisa en pantalla.
                        conn.send(json.dumps({"accion": "ERROR", "mensaje": f"Error BD: {str(e)}"}).encode('utf-8'))

                elif accion == "ELIMINAR_CUENTAS":
                    try:
                        usuarios = peticion.get("usuarios", [])
                        db_conn = sqlite3.connect('chat_app.db')
                        cursor = db_conn.cursor()
                        for usr in usuarios:
                            cursor.execute("DELETE FROM Usuarios WHERE usuario=?", (usr,))
                        db_conn.commit()
                        db_conn.close() # <-- CERRAMOS
                        
                        for usr in usuarios:
                            registrar_auditoria(usuario_actual, addr[0], f"ABM CUENTAS: Eliminó la cuenta '{usr}'")
                            
                        notificar_cambio_estado(excluir_usuario=usuario_actual)
                        conn.send(json.dumps({"accion": "INFO", "mensaje": f"{len(usuarios)} cuentas eliminadas."}).encode('utf-8'))
                    except Exception as e:
                        conn.send(json.dumps({"accion": "ERROR", "mensaje": f"Error BD: {str(e)}"}).encode('utf-8'))

                elif accion == "EDITAR_CUENTA":
                    id_usuario = peticion.get("id_usuario")
                    nombre = peticion.get("nombre")
                    usr = peticion.get("usuario")
                    pwd = peticion.get("password")
                    perfil = peticion.get("perfil_id")
                    
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    if pwd: 
                        cursor.execute("UPDATE Usuarios SET nombre=?, usuario=?, password=?, perfil_id=? WHERE id=?", (nombre, usr, pwd, perfil, id_usuario))
                    else:
                        cursor.execute("UPDATE Usuarios SET nombre=?, usuario=?, perfil_id=? WHERE id=?", (nombre, usr, perfil, id_usuario))
                    db_conn.commit()
                    db_conn.close()
                    registrar_auditoria(usuario_actual, addr[0], f"EDITÓ CUENTA: {usr} (Perfil: {perfil})") # <-- NUEVO
                    forzar_recarga_cliente(usr, perfil)

                    notificar_cambio_estado() 
                    conn.send(json.dumps({"accion": "INFO", "mensaje": "Cuenta editada."}).encode('utf-8'))

                elif accion == "ELIMINAR_CUENTA":
                    usr = peticion.get("usuario")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    cursor.execute("DELETE FROM Usuarios WHERE usuario=?", (usr,))
                    db_conn.commit()
                    db_conn.close()
                    registrar_auditoria(usuario_actual, addr[0], f"ELIMINÓ CUENTA: {usr}") # <-- NUEVO
                    notificar_cambio_estado()
                    conn.send(json.dumps({"accion": "INFO", "mensaje": f"Cuenta {usr} eliminada."}).encode('utf-8'))

                # --- ABM GRUPOS ---
                elif accion == "LISTAR_GRUPOS_ABM":
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    cursor.execute("SELECT id, perfil_id FROM Usuarios WHERE usuario=?", (usuario_actual,))
                    usr_data = cursor.fetchone()
                    
                    if usr_data:
                        usr_id, perfil = usr_data
                        if perfil == 1:
                            # Administrador: Ve todos los grupos y cuenta todos sus miembros
                            cursor.execute("""
                                SELECT g.nombre, g.solo_gestores, COUNT(m.usuario_id)
                                FROM Grupos g
                                LEFT JOIN Grupo_Miembros m ON g.id = m.grupo_id
                                GROUP BY g.id
                            """)
                        else:
                            # Gestor: Ve solo los que administra y cuenta sus miembros
                            cursor.execute("""
                                SELECT g.nombre, g.solo_gestores, 
                                    (SELECT COUNT(*) FROM Grupo_Miembros WHERE grupo_id = g.id)
                                FROM Grupos g
                                JOIN Grupo_Miembros gm ON g.id = gm.grupo_id
                                WHERE gm.usuario_id = ? AND gm.es_gestor = 1
                            """, (usr_id,))
                        
                        grupos = cursor.fetchall()
                        db_conn.close()
                        conn.send(json.dumps({"accion": "RESULTADO_GRUPOS_ABM", "datos": grupos}).encode('utf-8'))
                
                elif accion == "ABM_BLOQUEAR_GRUPO":
                    try:
                        grupo = peticion.get("grupo")
                        bloquear = peticion.get("bloquear")
                        
                        db_conn = sqlite3.connect('chat_app.db')
                        cursor = db_conn.cursor()
                        cursor.execute("UPDATE Grupos SET solo_gestores=? WHERE nombre=?", (bloquear, grupo))
                        db_conn.commit()
                        
                        cursor.execute("SELECT Usuarios.usuario FROM Grupo_Miembros JOIN Usuarios ON Grupo_Miembros.usuario_id = Usuarios.id JOIN Grupos ON Grupos.id = Grupo_Miembros.grupo_id WHERE Grupos.nombre=?", (grupo,))
                        miembros = [row[0] for row in cursor.fetchall()]
                        db_conn.close() # <-- CERRAMOS LA BD AQUÍ
                        
                        for miembro in miembros:
                            forzar_recarga_cliente(miembro)
                            
                        registrar_auditoria(usuario_actual, addr[0], f"ABM GRUPOS: Privacidad de #{grupo} -> Solo Gestores: {bool(bloquear)}")
                        notificar_cambio_estado(excluir_usuario=usuario_actual)
                        
                        conn.send(json.dumps({"accion": "INFO", "mensaje": f"Privacidad de #{grupo} actualizada."}).encode('utf-8'))
                    except Exception as e:
                        # Si algo falla, NO crasheamos, le avisamos al cliente.
                        try: conn.send(json.dumps({"accion": "ERROR", "mensaje": f"Error BD: {str(e)}"}).encode('utf-8'))
                        except: pass

                elif accion == "ELIMINAR_GRUPO":
                    grupo = peticion.get("grupo")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    cursor.execute("DELETE FROM Grupo_Miembros WHERE grupo_id=(SELECT id FROM Grupos WHERE nombre=?)", (grupo,))
                    cursor.execute("DELETE FROM Mensajes_Grupos WHERE grupo=?", (grupo,))
                    cursor.execute("DELETE FROM Grupos WHERE nombre=?", (grupo,))
                    db_conn.commit()
                    db_conn.close()
                    registrar_auditoria(usuario_actual, addr[0], f"ELIMINÓ GRUPO: #{grupo}") # <-- NUEVO
                    notificar_cambio_estado()
                    conn.send(json.dumps({"accion": "INFO", "mensaje": f"Grupo #{grupo} eliminado."}).encode('utf-8'))

                # --- ABM MIEMBROS DE GRUPO ---
                elif accion == "LISTAR_MIEMBROS":
                    grupo = peticion.get("grupo")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    cursor.execute("SELECT Usuarios.usuario, Grupo_Miembros.es_gestor FROM Grupo_Miembros JOIN Usuarios ON Grupo_Miembros.usuario_id = Usuarios.id JOIN Grupos ON Grupos.id = Grupo_Miembros.grupo_id WHERE Grupos.nombre=?", (grupo,))
                    miembros = cursor.fetchall()
                    db_conn.close()
                    conn.send(json.dumps({"accion": "RESULTADO_MIEMBROS", "datos": miembros}).encode('utf-8'))

                elif accion == "CAMBIAR_ROL_GESTOR":
                    grupo = peticion.get("grupo")
                    usr_obj = peticion.get("usuario")
                    nuevo_rol = peticion.get("es_gestor")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    cursor.execute("UPDATE Grupo_Miembros SET es_gestor=? WHERE usuario_id=(SELECT id FROM Usuarios WHERE usuario=?) AND grupo_id=(SELECT id FROM Grupos WHERE nombre=?)", (nuevo_rol, usr_obj, grupo))
                    db_conn.commit()
                    db_conn.close()
                    registrar_auditoria(usuario_actual, addr[0], f"CAMBIÓ ROL EN #{grupo}: {usr_obj} a Gestor={nuevo_rol}") # <-- NUEVO
                    forzar_recarga_cliente(usr_obj) # Le forzamos a recargar la UI para que le aparezca la papelera
                    conn.send(json.dumps({"accion": "INFO", "mensaje": f"Rol de {usr_obj} actualizado."}).encode('utf-8'))

                elif accion == "ELIMINAR_MIEMBRO":
                    grupo = peticion.get("grupo")
                    usr_obj = peticion.get("usuario")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    cursor.execute("DELETE FROM Grupo_Miembros WHERE usuario_id=(SELECT id FROM Usuarios WHERE usuario=?) AND grupo_id=(SELECT id FROM Grupos WHERE nombre=?)", (usr_obj, grupo))
                    db_conn.commit()
                    db_conn.close()
                    registrar_auditoria(usuario_actual, addr[0], f"EXPULSÓ DE #{grupo}: {usr_obj}") # <-- NUEVO
                    notificar_cambio_estado()
                    forzar_recarga_cliente(usr_obj)
                    conn.send(json.dumps({"accion": "INFO", "mensaje": f"Usuario {usr_obj} expulsado."}).encode('utf-8'))

                # --- ABM GRUPOS Y MIEMBROS (Mejorado para Múltiple) ---
                elif accion == "LISTAR_NO_MIEMBROS":
                    grupo = peticion.get("grupo")
                    db_conn = sqlite3.connect('chat_app.db')
                    cursor = db_conn.cursor()
                    # Traemos a los usuarios que NO están en este grupo
                    cursor.execute("""
                        SELECT usuario FROM Usuarios 
                        WHERE id NOT IN (
                            SELECT usuario_id FROM Grupo_Miembros 
                            WHERE grupo_id=(SELECT id FROM Grupos WHERE nombre=?)
                        )
                    """, (grupo,))
                    no_miembros = [row[0] for row in cursor.fetchall()]
                    db_conn.close()
                    
                    # FIX: Le devolvemos al cliente la lista Y el nombre del grupo
                    conn.send(json.dumps({"accion": "RESULTADO_NO_MIEMBROS", "grupo": grupo, "datos": no_miembros}).encode('utf-8'))

                elif accion == "AGREGAR_MIEMBROS_MULTI":
                    try:
                        grupo = peticion.get("grupo")
                        usuarios = peticion.get("usuarios", [])
                        
                        db_conn = sqlite3.connect('chat_app.db')
                        cursor = db_conn.cursor()
                        cursor.execute("SELECT id FROM Grupos WHERE nombre=?", (grupo,))
                        g_id = cursor.fetchone()[0]
                        
                        for usr in usuarios:
                            cursor.execute("SELECT id FROM Usuarios WHERE usuario=?", (usr,))
                            u_id = cursor.fetchone()[0]
                            cursor.execute("INSERT INTO Grupo_Miembros (grupo_id, usuario_id, es_gestor) VALUES (?, ?, 0)", (g_id, u_id))
                        
                        db_conn.commit()
                        db_conn.close() # <-- CERRAMOS
                        
                        for usr in usuarios:
                            registrar_auditoria(usuario_actual, addr[0], f"ABM GRUPOS: Añadió a {usr} al grupo #{grupo}")
                            forzar_recarga_cliente(usr) # Para que le aparezca el grupo

                        notificar_cambio_estado()
                        conn.send(json.dumps({"accion": "INFO", "mensaje": f"{len(usuarios)} miembros añadidos."}).encode('utf-8'))
                    except Exception as e:
                        conn.send(json.dumps({"accion": "ERROR", "mensaje": f"Error BD: {str(e)}"}).encode('utf-8'))

                elif accion == "CAMBIAR_ROL_GESTOR_MULTI":
                    try:
                        grupo = peticion.get("grupo")
                        usuarios = peticion.get("usuarios", [])
                        nuevo_rol = peticion.get("es_gestor")
                        
                        db_conn = sqlite3.connect('chat_app.db')
                        cursor = db_conn.cursor()
                        for usr in usuarios:
                            cursor.execute("UPDATE Grupo_Miembros SET es_gestor=? WHERE usuario_id=(SELECT id FROM Usuarios WHERE usuario=?) AND grupo_id=(SELECT id FROM Grupos WHERE nombre=?)", (nuevo_rol, usr, grupo))
                        db_conn.commit()
                        db_conn.close()
                        
                        for usr in usuarios:
                            registrar_auditoria(usuario_actual, addr[0], f"ABM GRUPOS: Rol gestor de {usr} en #{grupo} -> {bool(nuevo_rol)}")
                            forzar_recarga_cliente(usr)
                            
                        conn.send(json.dumps({"accion": "INFO", "mensaje": "Roles de gestor actualizados."}).encode('utf-8'))
                    except Exception as e:
                        conn.send(json.dumps({"accion": "ERROR", "mensaje": f"Error BD: {str(e)}"}).encode('utf-8'))

                elif accion == "ELIMINAR_MIEMBROS_MULTI":
                    try:
                        grupo = peticion.get("grupo")
                        usuarios = peticion.get("usuarios", [])
                        
                        db_conn = sqlite3.connect('chat_app.db')
                        cursor = db_conn.cursor()
                        for usr in usuarios:
                            cursor.execute("DELETE FROM Grupo_Miembros WHERE usuario_id=(SELECT id FROM Usuarios WHERE usuario=?) AND grupo_id=(SELECT id FROM Grupos WHERE nombre=?)", (usr, grupo))
                        db_conn.commit()
                        db_conn.close()
                        
                        for usr in usuarios:
                            registrar_auditoria(usuario_actual, addr[0], f"ABM GRUPOS: Expulsó a {usr} del grupo #{grupo}")
                            forzar_recarga_cliente(usr)

                        notificar_cambio_estado()
                        conn.send(json.dumps({"accion": "INFO", "mensaje": f"{len(usuarios)} usuarios expulsados."}).encode('utf-8'))
                    except Exception as e:
                        conn.send(json.dumps({"accion": "ERROR", "mensaje": f"Error BD: {str(e)}"}).encode('utf-8'))

                elif accion == "EDITAR_GRUPO":
                    try:
                        grupo_viejo = peticion.get("grupo_viejo")
                        grupo_nuevo = peticion.get("grupo_nuevo")
                        
                        db_conn = sqlite3.connect('chat_app.db')
                        cursor = db_conn.cursor()
                        # Actualizamos el nombre en la tabla de Grupos y en el historial de mensajes
                        cursor.execute("UPDATE Grupos SET nombre=? WHERE nombre=?", (grupo_nuevo, grupo_viejo))
                        cursor.execute("UPDATE Mensajes_Grupos SET grupo=? WHERE grupo=?", (grupo_nuevo, grupo_viejo))
                        db_conn.commit()
                        db_conn.close()
                        
                        registrar_auditoria(usuario_actual, addr[0], f"ABM GRUPOS: Renombró #{grupo_viejo} a #{grupo_nuevo}")
                        notificar_cambio_estado() # Avisamos a todos
                        conn.send(json.dumps({"accion": "INFO", "mensaje": f"Grupo renombrado a #{grupo_nuevo}."}).encode('utf-8'))
                    except sqlite3.IntegrityError:
                        conn.send(json.dumps({"accion": "ERROR", "mensaje": "Ya existe un grupo con ese nombre."}).encode('utf-8'))
                    except Exception as e:
                        conn.send(json.dumps({"accion": "ERROR", "mensaje": f"Error BD: {str(e)}"}).encode('utf-8'))

    except ConnectionResetError:
        # El cliente cerró la aplicación bruscamente (Típico de Windows). Lo ignoramos en silencio.
        pass
    except Exception as e:
        # Si el error es el 10054, no lo imprimimos. Si es otra cosa rara, sí.
        if "10054" not in str(e) and "10038" not in str(e):
            print(f"Error con el cliente {addr}: {e}")
    finally:
        # --- LIMPIEZA FINAL Y LOGOUT ---
        if usuario_actual:
            print(f"[{usuario_actual}] se ha desconectado.")
            if usuario_actual in clientes_conectados:
                del clientes_conectados[usuario_actual]
            
            db_conn = sqlite3.connect('chat_app.db')
            cursor = db_conn.cursor()
            fecha = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Aquí se registra el LOGOUT en la auditoría sin importar cómo se desconectó
            cursor.execute("INSERT INTO Auditoria_Login (fecha, ip, usuario, accion) VALUES (?, ?, ?, ?)", (fecha, addr[0], usuario_actual, "LOGOUT"))
            db_conn.commit()
            db_conn.close()
            
            notificar_cambio_estado()

        try:
            conn.close()
        except:
            pass

def iniciar_servidor():
    inicializar_bd()
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen(5)
    print(f"Servidor escuchando en {HOST}:{PORT}")
    
    while True:
        conn, addr = server.accept()
        thread = threading.Thread(target=manejar_cliente, args=(conn, addr))
        thread.start()

if __name__ == "__main__":
    iniciar_servidor()