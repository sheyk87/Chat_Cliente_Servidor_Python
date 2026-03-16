import tkinter as tk
from tkinter import messagebox, simpledialog, scrolledtext, filedialog
from tkinter import ttk
import socket
import threading
import json
import base64
import os
import re
import csv
import hashlib

HOST = '127.0.0.1'
PORT = 65432

class AppChat:
    def __init__(self, root):
        self.root = root
        self.root.title("Chat App Empresarial")
        self.root.geometry("500x550") 

        # # --- INICIO DEL LIFTING VISUAL ---
        # self.style = ttk.Style()
        # # Usamos 'clam' porque es el tema nativo más moderno y personalizable
        # if 'clam' in self.style.theme_names():
        #     self.style.theme_use('clam')
            
        # # Configurar las tablas (Treeviews) para que parezcan de una app moderna
        # self.style.configure("Treeview", 
        #                      background="#ffffff",
        #                      foreground="#333333",
        #                      rowheight=28, # Filas más anchas y cómodas de leer
        #                      fieldbackground="#ffffff",
        #                      font=("Segoe UI", 10))
        
        # # Color azul al seleccionar una fila (Estilo Windows 10/11)
        # self.style.map('Treeview', background=[('selected', '#0078D7')], foreground=[('selected', 'white')])
        
        # # Cabeceras de las tablas más elegantes
        # self.style.configure("Treeview.Heading", 
        #                      font=("Segoe UI", 10, "bold"), 
        #                      background="#e1e1e1", 
        #                      foreground="#333333", 
        #                      relief="flat")
        # # --- FIN DEL LIFTING VISUAL ---

        self.root.protocol("WM_DELETE_WINDOW", self.al_cerrar)
        
        self.cliente = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.conectado = False
        self.usuario_actual = None
        self.perfil_usuario = None

        self.construir_ui_login()

    def hashear_password(self, password):
        if not password: # Útil para cuando editamos una cuenta y dejamos la clave en blanco
            return ""
        # Añadimos una "Sal" para que sea imposible usar tablas Rainbow (diccionarios de hashes)
        salt = "ChatAppEmpresarial_Secreto!"
        return hashlib.sha256((password + salt).encode('utf-8')).hexdigest()

    def hacer_modal(self, ventana, parent=None):
        parent_window = parent if parent else self.root
        ventana.transient(parent_window) 
        ventana.grab_set() 
        ventana.focus_set()

    def conectar_servidor(self):
        if not self.conectado:
            try:
                self.cliente.connect((HOST, PORT))
                self.conectado = True
                
                hilo_escucha = threading.Thread(target=self.escuchar_servidor)
                hilo_escucha.daemon = True
                hilo_escucha.start()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo conectar al servidor: {e}")
                return False
        return True

    def construir_ui_login(self):
        self.frame_login = tk.Frame(self.root)
        self.frame_login.pack(pady=50)

        tk.Label(self.frame_login, text="Usuario:").pack()
        self.entry_usuario = tk.Entry(self.frame_login)
        self.entry_usuario.pack(pady=5)

        tk.Label(self.frame_login, text="Contraseña:").pack()
        self.entry_password = tk.Entry(self.frame_login, show="*")
        self.entry_password.pack(pady=5)

        tk.Button(self.frame_login, text="Entrar", command=self.hacer_login, width=15).pack(pady=15)

    def hacer_login(self):
        usuario = self.entry_usuario.get()
        password = self.entry_password.get()
        password_segura = self.hashear_password(password) # <-- NUEVO

        if self.conectar_servidor():
            peticion = {"accion": "LOGIN", "usuario": usuario, "password": password_segura} # <-- ENVIAMOS LA SEGURA
            self.cliente.send(json.dumps(peticion).encode('utf-8'))

    def construir_ui_chat(self):
        if hasattr(self, 'frame_login') and self.frame_login.winfo_exists():
            self.frame_login.destroy()

        self.root.geometry("850x600")
        self.renderizar_menus() 

        self.paned_window = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED)
        self.paned_window.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.frame_lateral = tk.Frame(self.paned_window, width=200, bg="#f4f4f4")
        self.paned_window.add(self.frame_lateral, minsize=180)

        tk.Label(self.frame_lateral, text="🔎 Buscar chat:", bg="#f4f4f4").pack(anchor="w", padx=5, pady=2)
        self.entry_buscar_panel = tk.Entry(self.frame_lateral)
        self.entry_buscar_panel.pack(fill=tk.X, padx=5, pady=2)
        self.entry_buscar_panel.bind("<KeyRelease>", self.filtrar_panel) 

        # --- LISTA DE GRUPOS ---
        tk.Label(self.frame_lateral, text="Mis Grupos", bg="#f4f4f4", font=("Arial", 10, "bold")).pack(anchor="w", padx=5, pady=2)
        self.lista_grupos = ttk.Treeview(self.frame_lateral, show="tree", selectmode="browse", height=6)
        self.lista_grupos.pack(fill=tk.X, padx=5, pady=2)
        # FIX: Evento oficial con identificador
        self.lista_grupos.bind("<<TreeviewSelect>>", lambda e: self.seleccionar_chat_desde_lista(e, "grupos"))
        # -----------------------------------------------------------

        self.lbl_titulo_usuarios = tk.Label(self.frame_lateral, text="Usuarios (0 Online)", bg="#f4f4f4", font=("Arial", 9, "bold"))
        self.lbl_titulo_usuarios.pack(anchor="w", padx=5, pady=2)

        # --- LISTA DE USUARIOS ---
        self.lista_usuarios = ttk.Treeview(self.frame_lateral, show="tree", selectmode="browse")
        self.lista_usuarios.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)
        # FIX: Evento oficial con identificador
        self.lista_usuarios.bind("<<TreeviewSelect>>", lambda e: self.seleccionar_chat_desde_lista(e, "usuarios"))
        self.lista_usuarios.tag_configure("admin_tag", font=("Arial", 9, "bold"))

        tk.Button(self.frame_lateral, text="↻ Actualizar", command=self.pedir_panel_lateral).pack(fill=tk.X, padx=5, pady=5)

        self.frame_chat = tk.Frame(self.paned_window)
        self.paned_window.add(self.frame_chat, minsize=400)

        self.lbl_chat_actual = tk.Label(self.frame_chat, text="Selecciona un chat del panel lateral", font=("Arial", 12, "bold"), bg="#e9ecef")
        self.lbl_chat_actual.pack(fill=tk.X, pady=2)

        self.frame_herramientas = tk.Frame(self.frame_chat)
        self.frame_herramientas.pack(fill=tk.X, pady=2)

        self.btn_gestores = tk.Button(self.frame_herramientas, text="👥 Miembros", command=self.ver_miembros_chat, bg="#e2e3e5")

        self.btn_vaciar = tk.Button(self.frame_herramientas, text="🗑️ Vaciar Chat", command=self.pedir_vaciar_chat, bg="#f8d7da")
        self.btn_vaciar.pack(side=tk.RIGHT, padx=5)

        self.btn_archivos_chat = tk.Button(self.frame_herramientas, text="📂 Archivos del Chat", command=self.abrir_archivos_chat, bg="#d9edf7")
        self.btn_archivos_chat.pack(side=tk.RIGHT, padx=5)

        self.mensaje_a_responder = None
        self.lbl_reply = tk.Label(self.frame_chat, text="", bg="#e2e3e5", anchor="w")

        self.chat_area = scrolledtext.ScrolledText(self.frame_chat, state='disabled', height=20)
        self.chat_area.pack(fill=tk.BOTH, expand=True)

        self.menu_contextual = tk.Menu(self.root, tearoff=0)
        self.menu_contextual.add_command(label="Responder a este mensaje", command=self.fijar_respuesta)
        self.chat_area.bind("<Button-3>", self.mostrar_menu_contextual) 

        self.chat_destino_actual = None 
        frame_envio = tk.Frame(self.frame_chat)
        frame_envio.pack(fill=tk.X, pady=5)

        self.entry_mensaje = tk.Entry(frame_envio)
        self.entry_mensaje.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

        self.btn_enviar = tk.Button(frame_envio, text="Enviar", command=self.enviar_mensaje)
        self.btn_enviar.pack(side=tk.RIGHT)
        self.btn_adjuntar = tk.Button(frame_envio, text="Adjuntar", command=self.enviar_archivo)
        self.btn_adjuntar.pack(side=tk.RIGHT, padx=5)

        self.pedir_panel_lateral()

    def renderizar_menus(self):
        if hasattr(self, 'menubar') and self.menubar.winfo_exists():
            self.menubar.destroy()
            
        self.menubar = tk.Menu(self.root)
        self.root.config(menu=self.menubar)

        if hasattr(self, 'menu_cuenta') and self.menu_cuenta.winfo_exists(): self.menu_cuenta.destroy()
        if hasattr(self, 'menu_admin') and self.menu_admin.winfo_exists(): self.menu_admin.destroy()

        self.menu_cuenta = tk.Menu(self.menubar, tearoff=0)
        self.menu_cuenta.add_command(label="Cambiar Contraseña", command=self.abrir_cambiar_password)
        self.menubar.add_cascade(label="Mi Cuenta", menu=self.menu_cuenta)

        estoy_imp = getattr(self, 'estoy_impersonando', False)
        es_admin_real = int(getattr(self, 'perfil_usuario', 2)) == 1 

        if es_admin_real or estoy_imp:
            self.menu_admin = tk.Menu(self.menubar, tearoff=0)
            
            if not estoy_imp:
                self.menu_admin.add_command(label="ABM Cuentas", command=self.abrir_abm_cuentas)
                self.menu_admin.add_command(label="ABM Grupos", command=self.abrir_abm_grupos) 
                self.menu_admin.add_command(label="Auditoría de Sistema", command=self.solicitar_auditoria)
                self.menu_admin.add_separator()
                self.menu_admin.add_command(label="Impersonar Usuario", command=self.impersonar_usuario)
            else:
                self.menu_admin.add_command(label="❌ Dejar de Impersonar", command=self.dejar_impersonar)
                
            self.menubar.add_cascade(label="Administración", menu=self.menu_admin)

    # --- NUEVAS FUNCIONES PARA EL PANEL ---

    def abrir_abm_cuentas(self):
        vent = tk.Toplevel(self.root)
        self.hacer_modal(vent) 
        vent.title("ABM de Cuentas")
        vent.geometry("700x450")
        
        frame_busqueda = tk.Frame(vent)
        frame_busqueda.pack(fill=tk.X, padx=5, pady=5)
        tk.Label(frame_busqueda, text="🔎 Buscar Usuario:").pack(side=tk.LEFT)
        self.entry_buscar_cuentas = tk.Entry(frame_busqueda)
        self.entry_buscar_cuentas.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.entry_buscar_cuentas.bind("<KeyRelease>", self.filtrar_cuentas)

        self.tree_cuentas = ttk.Treeview(vent, columns=("ID", "Nombre", "Usuario", "Perfil"), show="headings", selectmode="extended")
        self.tree_cuentas.heading("ID", text="ID", command=lambda: self.ordenar_por_columna(self.tree_cuentas, "ID", False))
        self.tree_cuentas.heading("Nombre", text="Nombre", command=lambda: self.ordenar_por_columna(self.tree_cuentas, "Nombre", False))
        self.tree_cuentas.heading("Usuario", text="Usuario", command=lambda: self.ordenar_por_columna(self.tree_cuentas, "Usuario", False))
        self.tree_cuentas.heading("Perfil", text="Perfil (1=Admin)", command=lambda: self.ordenar_por_columna(self.tree_cuentas, "Perfil", False))
        self.tree_cuentas.pack(fill=tk.BOTH, expand=True, pady=5)
        
        def refrescar():
            self.cliente.send(json.dumps({"accion": "LISTAR_CUENTAS"}).encode('utf-8'))
            self.pedir_panel_lateral() 
        
        self.root.after(100, refrescar)

        frame_btn = tk.Frame(vent)
        frame_btn.pack(fill=tk.X, pady=5)
        
        def asignar_admin_multi(es_admin):
            seleccion = self.tree_cuentas.selection()
            if not seleccion: return
            usuarios = [self.tree_cuentas.item(sel)['values'][2] for sel in seleccion]
            self.cliente.send(json.dumps({"accion": "CAMBIAR_ROL_ADMIN", "usuarios": usuarios, "es_admin": es_admin}).encode('utf-8'))
            self.root.after(500, refrescar)

        def eliminar_multi():
            seleccion = self.tree_cuentas.selection()
            if not seleccion: return
            usuarios = [self.tree_cuentas.item(sel)['values'][2] for sel in seleccion]
            if messagebox.askyesno("Confirmar", f"¿Eliminar {len(usuarios)} cuentas seleccionadas?"):
                self.cliente.send(json.dumps({"accion": "ELIMINAR_CUENTAS", "usuarios": usuarios}).encode('utf-8'))
                self.root.after(500, refrescar)

        def editar_cuenta():
            seleccion = self.tree_cuentas.selection()
            if not seleccion: return
            if len(seleccion) > 1:
                messagebox.showwarning("Atención", "Selecciona solo 1 cuenta para editar.")
                return
            
            item = self.tree_cuentas.item(seleccion[0])['values']
            
            vent_ed = tk.Toplevel(vent)
            self.hacer_modal(vent_ed, parent=vent) 
            vent_ed.title("Editar Cuenta")
            vent_ed.geometry("250x250")

            tk.Label(vent_ed, text="Nombre:").pack()
            e_nom = tk.Entry(vent_ed); e_nom.insert(0, item[1]); e_nom.pack()

            tk.Label(vent_ed, text="Usuario:").pack()
            e_usr = tk.Entry(vent_ed); e_usr.insert(0, item[2]); e_usr.pack()

            tk.Label(vent_ed, text="Nueva Contraseña (Vacío = no cambiar):").pack()
            e_pwd = tk.Entry(vent_ed, show="*"); e_pwd.pack()

            def guardar_edicion():
                self.cliente.send(json.dumps({
                    "accion": "EDITAR_CUENTA", "id_usuario": item[0],
                    "nombre": e_nom.get(), "usuario": e_usr.get(),
                    "password": self.hashear_password(e_pwd.get()), # <-- NUEVO
                    "perfil_id": item[3]
                }).encode('utf-8'))
                vent_ed.destroy()
                self.root.after(500, refrescar)

            tk.Button(vent_ed, text="Guardar Cambios", command=guardar_edicion, bg="#d4edda").pack(pady=10)

        tk.Button(frame_btn, text="➕ Crear", command=self.abrir_crear_usuario).pack(side=tk.LEFT, padx=2)
        tk.Button(frame_btn, text="✏️ Editar", command=editar_cuenta, bg="#d9edf7").pack(side=tk.LEFT, padx=2)
        tk.Button(frame_btn, text="👑 Hacer Admin", command=lambda: asignar_admin_multi(True), bg="#d4edda").pack(side=tk.LEFT, padx=2)
        tk.Button(frame_btn, text="👤 Quitar Admin", command=lambda: asignar_admin_multi(False), bg="#fff3cd").pack(side=tk.LEFT, padx=2)
        tk.Button(frame_btn, text="❌ Eliminar", command=eliminar_multi, bg="#f8d7da").pack(side=tk.RIGHT, padx=2)

    def abrir_abm_grupos(self):
        vent = tk.Toplevel(self.root)
        self.hacer_modal(vent) 
        vent.title("ABM de Grupos")
        vent.geometry("600x300")

        frame_busqueda = tk.Frame(vent)
        frame_busqueda.pack(fill=tk.X, padx=5, pady=5)
        tk.Label(frame_busqueda, text="🔎 Buscar Grupo:").pack(side=tk.LEFT)
        self.entry_buscar_grupos = tk.Entry(frame_busqueda)
        self.entry_buscar_grupos.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.entry_buscar_grupos.bind("<KeyRelease>", self.filtrar_grupos)
        
        self.tree_grupos = ttk.Treeview(vent, columns=("Grupo", "Privacidad", "Miembros"), show="headings", selectmode="extended")
        self.tree_grupos.heading("Grupo", text="Nombre del Grupo", command=lambda: self.ordenar_por_columna(self.tree_grupos, "Grupo", False))
        self.tree_grupos.heading("Privacidad", text="Privacidad", command=lambda: self.ordenar_por_columna(self.tree_grupos, "Privacidad", False))
        self.tree_grupos.heading("Miembros", text="Total Miembros", command=lambda: self.ordenar_por_columna(self.tree_grupos, "Miembros", False))
        self.tree_grupos.column("Miembros", width=80)
        self.tree_grupos.pack(fill=tk.BOTH, expand=True, pady=5)
        
        def refrescar():
            self.cliente.send(json.dumps({"accion": "LISTAR_GRUPOS_ABM"}).encode('utf-8'))
            self.pedir_panel_lateral()
            
        self.root.after(100, refrescar)

        frame_btn = tk.Frame(vent)
        frame_btn.pack(fill=tk.X, pady=5)

        def ver_miembros():
            sel = self.tree_grupos.selection()
            if sel: self.abrir_config_miembros(self.tree_grupos.item(sel[0])['values'][0], parent_window=vent)
            
        def toggle_bloqueo(bloquear):
            sel = self.tree_grupos.selection()
            if not sel: return
            grupos = [self.tree_grupos.item(s)['values'][0] for s in sel]
            for g in grupos:
                self.cliente.send(json.dumps({"accion": "ABM_BLOQUEAR_GRUPO", "grupo": g, "bloquear": 1 if bloquear else 0}).encode('utf-8'))
            self.root.after(500, refrescar)

        def editar_grupo():
            sel = self.tree_grupos.selection()
            if not sel: return
            if len(sel) > 1: return
            
            grupo_viejo = self.tree_grupos.item(sel[0])['values'][0]
            nuevo_nombre = simpledialog.askstring("Editar Grupo", "Nuevo nombre del grupo (sin #):", initialvalue=grupo_viejo)
            
            if nuevo_nombre and nuevo_nombre != grupo_viejo:
                self.cliente.send(json.dumps({
                    "accion": "EDITAR_GRUPO",
                    "grupo_viejo": grupo_viejo,
                    "grupo_nuevo": nuevo_nombre
                }).encode('utf-8'))
                self.root.after(500, refrescar)

        def eliminar_grupo():
            sel = self.tree_grupos.selection()
            if not sel: return
            grupo = self.tree_grupos.item(sel[0])['values'][0]
            if messagebox.askyesno("Confirmar", f"¿Eliminar grupo #{grupo}?"):
                self.cliente.send(json.dumps({"accion": "ELIMINAR_GRUPO", "grupo": grupo}).encode('utf-8'))
                self.root.after(500, refrescar)

        tk.Button(frame_btn, text="➕ Crear", command=self.abrir_crear_grupo, bg="#d4edda").pack(side=tk.LEFT, padx=2)
        tk.Button(frame_btn, text="✏️ Editar", command=editar_grupo, bg="#e2e3e5").pack(side=tk.LEFT, padx=2)
        tk.Button(frame_btn, text="👥 Miembros", command=ver_miembros, bg="#d9edf7").pack(side=tk.LEFT, padx=2)
        tk.Button(frame_btn, text="🔒 Bloquear", command=lambda: toggle_bloqueo(True), bg="#f8d7da").pack(side=tk.LEFT, padx=2)
        tk.Button(frame_btn, text="🔓 Desbloquear", command=lambda: toggle_bloqueo(False), bg="#fff3cd").pack(side=tk.LEFT, padx=2)
        tk.Button(frame_btn, text="❌ Eliminar", command=eliminar_grupo, bg="#f8d7da").pack(side=tk.RIGHT, padx=2)

    def abrir_config_miembros(self, grupo, parent_window=None):
        vent = tk.Toplevel(parent_window if parent_window else self.root)
        self.hacer_modal(vent, parent=parent_window) 
        vent.title(f"Miembros de #{grupo}")
        vent.geometry("450x350")
        
        self.tree_miembros = ttk.Treeview(vent, columns=("Usuario", "Rol"), show="headings", selectmode="extended")
        self.tree_miembros.heading("Usuario", text="Usuario", command=lambda: self.ordenar_por_columna(self.tree_miembros, "Usuario", False))
        self.tree_miembros.heading("Rol", text="Rol", command=lambda: self.ordenar_por_columna(self.tree_miembros, "Rol", False))
        self.tree_miembros.pack(fill=tk.BOTH, expand=True, pady=5)
        
        def refrescar():
            self.cliente.send(json.dumps({"accion": "LISTAR_MIEMBROS", "grupo": grupo}).encode('utf-8'))
            
        self.root.after(100, refrescar)

        frame_btn = tk.Frame(vent)
        frame_btn.pack(fill=tk.X, pady=5)

        def cambiar_rol_multi(es_gestor):
            seleccion = self.tree_miembros.selection()
            if not seleccion: return
            usuarios = [self.tree_miembros.item(sel)['values'][0] for sel in seleccion]
            self.cliente.send(json.dumps({"accion": "CAMBIAR_ROL_GESTOR_MULTI", "grupo": grupo, "usuarios": usuarios, "es_gestor": 1 if es_gestor else 0}).encode('utf-8'))
            self.root.after(500, refrescar)

        def expulsar_multi():
            seleccion = self.tree_miembros.selection()
            if not seleccion: return
            usuarios = [self.tree_miembros.item(sel)['values'][0] for sel in seleccion]
            if messagebox.askyesno("Confirmar", f"¿Expulsar {len(usuarios)} miembros?"):
                self.cliente.send(json.dumps({"accion": "ELIMINAR_MIEMBROS_MULTI", "grupo": grupo, "usuarios": usuarios}).encode('utf-8'))
                self.root.after(500, refrescar)
                self.root.after(500, lambda: self.cliente.send(json.dumps({"accion": "LISTAR_GRUPOS_ABM"}).encode('utf-8')))

        def abrir_add_no_miembros():
            self.cliente.send(json.dumps({"accion": "LISTAR_NO_MIEMBROS", "grupo": grupo}).encode('utf-8'))

        tk.Button(frame_btn, text="➕ Añadir", command=abrir_add_no_miembros, bg="#e2e3e5").pack(side=tk.LEFT, padx=2)
        tk.Button(frame_btn, text="👑 Hacer Gestor", command=lambda: cambiar_rol_multi(True), bg="#d4edda").pack(side=tk.LEFT, padx=2)
        tk.Button(frame_btn, text="👤 Quitar Gestor", command=lambda: cambiar_rol_multi(False), bg="#fff3cd").pack(side=tk.LEFT, padx=2)
        tk.Button(frame_btn, text="❌ Expulsar", command=expulsar_multi, bg="#f8d7da").pack(side=tk.RIGHT, padx=2)

    def pedir_panel_lateral(self):
        self.cliente.send(json.dumps({"accion": "OBTENER_PANEL"}).encode('utf-8'))

    # --- FIX DEFINITIVO: SELECCIÓN LÁSER ---
    # --- FIX DEFINITIVO: SELECCIÓN CRUZADA SEGURA ---
    def seleccionar_chat_desde_lista(self, event, origen):
        widget = event.widget
        sel = widget.selection()
        
        # Si la selección está vacía (porque nosotros la limpiamos por código), no hacemos nada
        if not sel: 
            return 
            
        seleccion = widget.item(sel[0])['text']
        
        # Desmarcamos la *otra* lista para evitar que Tkinter se confunda con el foco
        if origen == "usuarios" and hasattr(self, 'lista_grupos'):
            self.lista_grupos.selection_remove(self.lista_grupos.selection())
        elif origen == "grupos" and hasattr(self, 'lista_usuarios'):
            self.lista_usuarios.selection_remove(self.lista_usuarios.selection())
            
        # Limpiamos los adornos visuales para obtener el nombre real de la base de datos
        contacto = seleccion.replace("[Admin] ", "").replace(" [🟢 Online]", "").replace(" [🔴 Offline]", "")
        
        # Si tocamos el chat en el que ya estamos, no recargamos para evitar parpadeos
        if getattr(self, 'chat_destino_actual', None) == contacto:
            return
            
        self.chat_destino_actual = contacto
        self.root.title(f"Chat App Empresarial - Hablando con {contacto}")
        
        # Pedimos el historial al servidor
        peticion = {"accion": "OBTENER_HISTORIAL", "con_usuario": contacto}
        self.cliente.send(json.dumps(peticion).encode('utf-8'))

    def enviar_mensaje(self):
        destinatario = getattr(self, 'chat_destino_actual', None)
        mensaje = self.entry_mensaje.get()
        
        if not destinatario:
            messagebox.showwarning("Atención", "Por favor, selecciona un usuario o grupo del panel lateral primero.")
            return

        if mensaje:
            reply = getattr(self, 'mensaje_a_responder', None) 
            
            peticion = {
                "accion": "ENVIAR_MENSAJE",
                "destinatario": destinatario,
                "mensaje": mensaje,
                "reply_to": reply
            }
            self.cliente.send(json.dumps(peticion).encode('utf-8'))
            
            self.mostrar_mensaje("Yo", mensaje, reply)
            
            self.entry_mensaje.delete(0, tk.END)
            self.mensaje_a_responder = None
            if hasattr(self, 'lbl_reply') and self.lbl_reply.winfo_exists():
                self.lbl_reply.config(text="")
                self.lbl_reply.pack_forget()

    def enviar_archivo(self):
        destinatario = getattr(self, 'chat_destino_actual', None)
        if not destinatario:
            messagebox.showwarning("Atención", "Selecciona un chat del panel lateral antes de adjuntar.")
            return

        ruta_archivo = filedialog.askopenfilename(title="Seleccionar archivo a enviar")
        if ruta_archivo:
            nombre_archivo = os.path.basename(ruta_archivo)
            self.archivo_en_proceso = ruta_archivo 
            
            # NUEVO: Calculamos la huella digital del archivo
            with open(ruta_archivo, "rb") as f:
                huella_sha256 = hashlib.sha256(f.read()).hexdigest()
            
            peticion = {
                "accion": "INICIO_ARCHIVO", 
                "destinatario": destinatario, 
                "nombre_archivo": nombre_archivo,
                "hash_original": huella_sha256 # Mandamos la huella al servidor
            }
            self.cliente.send(json.dumps(peticion).encode('utf-8'))
            
            # Bloqueamos el botón y avisamos al usuario visualmente
            self.btn_adjuntar.config(state='disabled', text="⏳ Subiendo...")
    
    def subir_archivo_en_chunks(self, transfer_id, ruta_archivo):
        try:
            tamano_chunk = 1024 * 512 # Lee el archivo en pedazos de 512 KB
            with open(ruta_archivo, "rb") as f:
                while True:
                    pedazo = f.read(tamano_chunk)
                    if not pedazo:
                        break # Llegamos al final del archivo
                    
                    datos_b64 = base64.b64encode(pedazo).decode('utf-8')
                    peticion_chunk = {
                        "accion": "CHUNK_ARCHIVO",
                        "transfer_id": transfer_id,
                        "datos_base64": datos_b64
                    }
                    self.cliente.send(json.dumps(peticion_chunk).encode('utf-8'))
            
            # Cuando termina de leer todo, manda la señal de finalización
            self.cliente.send(json.dumps({"accion": "FIN_ARCHIVO", "transfer_id": transfer_id}).encode('utf-8'))
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", f"Fallo al subir archivo: {e}"))
            self.root.after(0, lambda: self.btn_adjuntar.config(state='normal', text="Adjuntar"))

    def pedir_historial(self):
        destinatario = self.entry_destinatario.get()
        if destinatario:
            peticion = {"accion": "OBTENER_HISTORIAL", "con_usuario": destinatario}
            self.cliente.send(json.dumps(peticion).encode('utf-8'))
            
            self.chat_area.config(state='normal')
            self.chat_area.delete(1.0, tk.END) 
            self.chat_area.config(state='disabled')
            self.mostrar_mensaje(f"--- Historial con {destinatario} ---")
        else:
            messagebox.showwarning("Atención", "Escribe el destinatario (Para:) antes de cargar el historial.")

    def pedir_vaciar_chat(self):
        destinatario = getattr(self, 'chat_destino_actual', None)
        
        if destinatario:
            if destinatario.startswith("#"):
                nombre_g = destinatario[1:]
                if messagebox.askyesno("Confirmar", f"¿Vaciar historial del grupo #{nombre_g}? (Requiere permiso de Gestor)"):
                    peticion = {"accion": "VACIAR_CHAT_GRUPO", "nombre_grupo": nombre_g}
                    self.cliente.send(json.dumps(peticion).encode('utf-8'))
                    self.chat_area.config(state='normal')
                    self.chat_area.delete(1.0, tk.END) 
                    self.chat_area.config(state='disabled')
            else:
                if messagebox.askyesno("Confirmar", f"¿Seguro que deseas vaciar el chat con {destinatario}?"):
                    peticion = {"accion": "VACIAR_CHAT", "con_usuario": destinatario}
                    self.cliente.send(json.dumps(peticion).encode('utf-8'))
                    self.chat_area.config(state='normal')
                    self.chat_area.delete(1.0, tk.END) 
                    self.chat_area.config(state='disabled')
        else:
            messagebox.showwarning("Atención", "Selecciona un usuario o grupo del panel lateral primero.")

    def abrir_crear_grupo(self):
        nombre_grupo = simpledialog.askstring("Crear Grupo", "Nombre del grupo (sin el #):")
        if nombre_grupo:
            peticion = {"accion": "CREAR_GRUPO", "nombre_grupo": nombre_grupo}
            self.cliente.send(json.dumps(peticion).encode('utf-8'))
            
            if hasattr(self, 'tree_grupos') and self.tree_grupos.winfo_exists():
                self.root.after(500, lambda: self.cliente.send(json.dumps({"accion": "LISTAR_GRUPOS_ABM"}).encode('utf-8')))
            
            self.root.after(500, self.pedir_panel_lateral)

    def escuchar_servidor(self):
        buffer_texto = ""
        decoder = json.JSONDecoder()
        
        while True:
            try:
                datos_crudos = self.cliente.recv(1024 * 64).decode('utf-8')
                if not datos_crudos:
                    break
                    
                buffer_texto += datos_crudos
                
                while buffer_texto:
                    buffer_texto = buffer_texto.lstrip()
                    if not buffer_texto:
                        break
                        
                    try:
                        respuesta, indice = decoder.raw_decode(buffer_texto)
                        buffer_texto = buffer_texto[indice:]
                    except json.JSONDecodeError:
                        break # Faltan datos por llegar, esperamos al siguiente ciclo 
                        
                    if "status" in respuesta and not self.usuario_actual:
                        if respuesta["status"] == "OK":
                            self.usuario_actual = self.entry_usuario.get()
                            self.perfil_usuario = respuesta.get("perfil")

                            self.carpeta_descargas = f"descargas_{self.usuario_actual}"
                            if not os.path.exists(self.carpeta_descargas):
                                os.makedirs(self.carpeta_descargas)

                            self.root.after(0, self.construir_ui_chat)
                        else:
                            self.root.after(0, lambda r=respuesta: messagebox.showerror("Error", r["mensaje"]))
                    
                    elif respuesta.get("accion") == "NUEVO_MENSAJE":
                        rem = respuesta.get("remitente")
                        msg = respuesta.get("mensaje")
                        reply = respuesta.get("reply_to")
                        
                        def procesar_nuevo_mensaje(r, m, rep):
                            if " (#" in r:
                                chat_origen = "#" + r.split(" (#")[1].replace(")", "")
                            else:
                                chat_origen = r
                                
                            if getattr(self, 'chat_destino_actual', None) == chat_origen:
                                self.mostrar_mensaje(r, m, rep)
                            else:
                                self.root.bell()
                                self.root.title(f"💬 ¡Nuevo mensaje en {chat_origen}! - Chat App")

                        self.root.after(0, lambda r=rem, m=msg, rep=reply: procesar_nuevo_mensaje(r, m, rep))

                    elif respuesta.get("accion") == "PERMISO_ENVIO_CHUNKS":
                        transfer_id = respuesta.get("transfer_id")
                        ruta_archivo = getattr(self, 'archivo_en_proceso', None)
                        
                        if ruta_archivo:
                            # ¡MAGIA! Iniciamos un hilo separado para que la UI de Tkinter no se congele
                            hilo_subida = threading.Thread(target=self.subir_archivo_en_chunks, args=(transfer_id, ruta_archivo))
                            hilo_subida.daemon = True
                            hilo_subida.start()

                    elif respuesta.get("accion") == "CONFIRMACION_ARCHIVO":
                        dest = respuesta.get("destinatario")
                        msg = respuesta.get("mensaje")
                        if getattr(self, 'chat_destino_actual', None) == dest:
                            self.root.after(0, lambda: self.btn_adjuntar.config(state='normal', text="Adjuntar"))

                    elif respuesta.get("accion") == "INFO":
                        msg = respuesta.get("mensaje")
                        self.root.after(0, lambda m=msg: messagebox.showinfo("Información", m))
                        
                    elif respuesta.get("accion") == "ERROR":
                        msg = respuesta.get("mensaje")
                        self.root.after(0, lambda m=msg: messagebox.showerror("Error", m))
                        
                    elif respuesta.get("accion") == "RESULTADO_AUDITORIA":
                        datos_auditoria = respuesta.get("datos")
                        self.root.after(0, lambda d=datos_auditoria: self.mostrar_ventana_auditoria(d))

                    elif respuesta.get("accion") == "RESULTADO_ARCHIVOS_CHAT":
                        datos = respuesta.get("datos")
                        def dibujar_archivos():
                            if hasattr(self, 'tree_archivos') and self.tree_archivos.winfo_exists():
                                self.tree_archivos.delete(*self.tree_archivos.get_children())
                                for d in datos: self.tree_archivos.insert("", tk.END, values=d)
                        self.root.after(0, dibujar_archivos)

                    elif respuesta.get("accion") == "INICIO_DESCARGA":
                        transfer_id = respuesta.get("transfer_id")
                        nombre_arch = respuesta.get("nombre_archivo")
                        
                        if not hasattr(self, 'descargas_activas'):
                            self.descargas_activas = {}
                            
                        if not os.path.exists(self.carpeta_descargas):
                            os.makedirs(self.carpeta_descargas)
                        
                        ruta_temp = os.path.join(self.carpeta_descargas, f"temp_{transfer_id}_{nombre_arch}")
                        open(ruta_temp, 'wb').close() # Crea un archivo vacío temporal
                        
                        self.descargas_activas[transfer_id] = {
                            "ruta": ruta_temp,
                            "nombre": nombre_arch
                        }

                    elif respuesta.get("accion") == "CHUNK_DESCARGA":
                        transfer_id = respuesta.get("transfer_id")
                        datos_b64 = respuesta.get("datos_base64")
                        
                        if hasattr(self, 'descargas_activas') and transfer_id in self.descargas_activas:
                            ruta_temp = self.descargas_activas[transfer_id]["ruta"]
                            # Append Binary ("ab") va pegando los pedazos al final del archivo temporal
                            with open(ruta_temp, "ab") as f:
                                f.write(base64.b64decode(datos_b64))

                    elif respuesta.get("accion") == "FIN_DESCARGA":
                        transfer_id = respuesta.get("transfer_id")
                        if hasattr(self, 'descargas_activas') and transfer_id in self.descargas_activas:
                            info = self.descargas_activas.pop(transfer_id) # Saca y limpia de la memoria
                            ruta_temp = info["ruta"]
                            nombre_arch = info["nombre"]
                            
                            # Buscar un nombre final que no sobreescriba existentes
                            ruta_final = os.path.join(self.carpeta_descargas, nombre_arch)
                            base, ext = os.path.splitext(ruta_final)
                            contador = 1
                            while os.path.exists(ruta_final):
                                ruta_final = f"{base}({contador}){ext}"
                                contador += 1
                                
                            try:
                                os.rename(ruta_temp, ruta_final) # Le quita el "temp_"
                                self.root.after(0, lambda r=ruta_final: messagebox.showinfo("Éxito", f"Descarga completada:\n{r}"))
                            except Exception as e:
                                self.root.after(0, lambda err=str(e): messagebox.showerror("Error", f"Error al guardar: {err}"))

                    elif respuesta.get("accion") == "HISTORIAL_RECIBIDO":
                        mensajes = respuesta.get("mensajes")
                        es_grupo = respuesta.get("es_grupo", False)
                        es_gestor = respuesta.get("es_gestor", False)
                        solo_gestores = respuesta.get("solo_gestores", False)
                        
                        def procesar_historial_y_ui():
                            if not hasattr(self, 'entry_mensaje'): return
                            
                            self.es_grupo_actual = es_grupo
                            self.soy_gestor_actual = es_gestor
                            
                            self.entry_mensaje.config(state='normal')
                            self.entry_mensaje.delete(0, tk.END)
                            
                            self.chat_area.config(state='normal')
                            self.chat_area.delete(1.0, tk.END)
                            self.chat_area.config(state='disabled')
                            
                            if es_grupo:
                                if hasattr(self, 'btn_gestores'): 
                                    self.btn_gestores.pack(side=tk.RIGHT, padx=5)
                                    
                                if not es_gestor: self.btn_vaciar.pack_forget()
                                else: self.btn_vaciar.pack(side=tk.RIGHT, padx=5)
                                
                                if solo_gestores and not es_gestor:
                                    self.entry_mensaje.insert(0, "🔒 Sólo los Gestores pueden escribir")
                                    self.entry_mensaje.config(state='disabled')
                                    self.btn_enviar.config(state='disabled')
                                    self.btn_adjuntar.config(state='disabled')
                                else:
                                    self.btn_enviar.config(state='normal')
                                    self.btn_adjuntar.config(state='normal')
                            else:
                                if hasattr(self, 'btn_gestores'): 
                                    self.btn_gestores.pack_forget()
                                    
                                self.btn_vaciar.pack(side=tk.RIGHT, padx=5)
                                self.btn_enviar.config(state='normal')
                                self.btn_adjuntar.config(state='normal')

                            for msj in mensajes:
                                rem = msj[0]
                                texto = msj[1]
                                reply = msj[2] if len(msj) > 2 else None
                                pref = "Yo" if rem == self.usuario_actual else rem
                                self.mostrar_mensaje(pref, texto, reply)

                        self.root.after(0, procesar_historial_y_ui)

                    elif respuesta.get("accion") == "RECARGAR_INTERFAZ":
                        nuevo_perfil = respuesta.get("nuevo_perfil")
                        if nuevo_perfil is not None:
                            self.perfil_usuario = nuevo_perfil
                            self.root.after(0, self.renderizar_menus)
                        self.root.after(0, self.pedir_panel_lateral)
                        dest = getattr(self, 'chat_destino_actual', None)
                        if dest:
                            peticion = {"accion": "OBTENER_HISTORIAL", "con_usuario": dest}
                            self.cliente.send(json.dumps(peticion).encode('utf-8'))

                    elif respuesta.get("accion") == "ACTUALIZAR_PANEL":
                        self.panel_usuarios_completos = respuesta.get("usuarios")
                        self.panel_grupos_completos = respuesta.get("grupos")
                        self.root.after(0, self.filtrar_panel)

                    elif respuesta.get("accion") == "REFRESCAR_PANEL":
                        self.root.after(0, self.pedir_panel_lateral)

                    elif respuesta.get("accion") == "IMPERSONACION_EXITOSA":
                        nuevo_usr = respuesta.get("nuevo_usuario")
                        msg = respuesta.get("mensaje")
                        self.usuario_actual = nuevo_usr
                        self.estoy_impersonando = True
                        
                        def aplicar_cambio():
                            self.renderizar_menus()
                            self.root.title(f"Chat App - Modo Impersonación: {self.usuario_actual}")
                            self.pedir_panel_lateral() 
                            messagebox.showwarning("Modo Dios", msg)
                        self.root.after(0, aplicar_cambio)
                        
                    elif respuesta.get("accion") == "FIN_IMPERSONACION":
                        usr = respuesta.get("usuario")
                        msg = respuesta.get("mensaje")
                        self.usuario_actual = usr
                        self.estoy_impersonando = False
                        
                        def aplicar_fin():
                            self.renderizar_menus()
                            self.root.title("Chat App Empresarial")
                            self.pedir_panel_lateral()
                            messagebox.showinfo("Info", msg)
                        self.root.after(0, aplicar_fin)

                    elif respuesta.get("accion") == "RESULTADO_CUENTAS":
                        self.datos_cuentas_completos = respuesta.get("datos")
                        self.root.after(0, self.filtrar_cuentas)

                    elif respuesta.get("accion") == "RESULTADO_GRUPOS_ABM":
                        self.datos_grupos_completos = respuesta.get("datos")
                        self.root.after(0, self.filtrar_grupos)

                    elif respuesta.get("accion") == "RESULTADO_MIEMBROS":
                        datos = respuesta.get("datos")
                        def dibujar_miembros():
                            if hasattr(self, 'tree_miembros') and self.tree_miembros.winfo_exists():
                                self.tree_miembros.delete(*self.tree_miembros.get_children())
                                for d in datos:
                                    rol = "👑 Gestor" if d[1] else "👤 Miembro"
                                    self.tree_miembros.insert("", tk.END, values=(d[0], rol))
                        self.root.after(0, dibujar_miembros)
                        
                    elif respuesta.get("accion") == "RESULTADO_NO_MIEMBROS":
                        datos = respuesta.get("datos")
                        grupo_objetivo = respuesta.get("grupo")
                        
                        def dibujar_ventana_agregar():
                            v = tk.Toplevel(self.root)
                            self.hacer_modal(v) 
                            v.title(f"Añadir Miembros a #{grupo_objetivo}")
                            v.geometry("300x400")
                            
                            tk.Label(v, text="🔍 Buscar usuario:").pack(pady=(10, 0), padx=10, anchor="w")
                            entry_buscar = tk.Entry(v)
                            entry_buscar.pack(fill=tk.X, padx=10, pady=2)
                            
                            lista_no_miembros = tk.Listbox(v, selectmode=tk.MULTIPLE, font=("Arial", 10))
                            lista_no_miembros.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
                            
                            def filtrar_usuarios(event=None):
                                query = entry_buscar.get().lower()
                                lista_no_miembros.delete(0, tk.END) 
                                for u in datos:
                                    if query in u.lower():
                                        lista_no_miembros.insert(tk.END, u)
                                        
                            entry_buscar.bind("<KeyRelease>", filtrar_usuarios)
                            filtrar_usuarios()
                            
                            def confirmar():
                                seleccionados = [lista_no_miembros.get(i) for i in lista_no_miembros.curselection()]
                                if not seleccionados: 
                                    return
                                
                                peticion = {
                                    "accion": "AGREGAR_MIEMBROS_MULTI",
                                    "grupo": grupo_objetivo,
                                    "usuarios": seleccionados
                                }
                                self.cliente.send(json.dumps(peticion).encode('utf-8'))
                                v.destroy()

                                self.root.after(500, lambda: self.cliente.send(json.dumps({"accion": "LISTAR_MIEMBROS", "grupo": grupo_objetivo}).encode('utf-8')))
                                self.root.after(500, lambda: self.cliente.send(json.dumps({"accion": "LISTAR_GRUPOS_ABM"}).encode('utf-8')))
                                
                            tk.Button(v, text="➕ Añadir Seleccionados", command=confirmar, bg="#d4edda").pack(pady=10)
                            
                        self.root.after(0, dibujar_ventana_agregar)

                    elif respuesta.get("accion") == "RESULTADO_MIEMBROS_CHAT":
                        datos = respuesta.get("datos")
                        
                        def mostrar_ventana_miembros_chat():
                            v = tk.Toplevel(self.root)
                            self.hacer_modal(v) 
                            v.title("Miembros del Grupo")
                            v.geometry("300x350")
                            tk.Label(v, text="👥 Lista de Miembros", font=("Arial", 11, "bold")).pack(pady=10)
                            
                            columnas = ("Usuario", "Rol")
                            tree = ttk.Treeview(v, columns=columnas, show="headings", height=10)
                            tree.heading("Usuario", text="Usuario")
                            tree.heading("Rol", text="Rol")
                            tree.column("Usuario", width=150)
                            tree.column("Rol", width=100)
                            tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
                            
                            datos_ordenados = sorted(datos, key=lambda x: x[1], reverse=True)
                            
                            for d in datos_ordenados:
                                rol = "👑 Gestor" if d[1] else "👤 Miembro"
                                tree.insert("", tk.END, values=(d[0], rol))
                                
                            tk.Button(v, text="Cerrar", command=v.destroy).pack(pady=5)
                            
                        self.root.after(0, mostrar_ventana_miembros_chat)

            except Exception as e:
                if "10053" not in str(e) and "10054" not in str(e) and "10038" not in str(e):
                    print("Desconectado del servidor:", e)
                break

    # --- FUNCIONES DE BÚSQUEDA Y FILTRADO LOCAL ---
    def filtrar_panel(self, event=None):
        # Si el usuario sigue escribiendo, cancelamos la búsqueda anterior
        if hasattr(self, 'timer_busqueda_panel') and self.timer_busqueda_panel:
            self.root.after_cancel(self.timer_busqueda_panel)
        
        # Programamos la búsqueda real para que ocurra 300ms DESPUÉS de la última tecla pulsada
        self.timer_busqueda_panel = self.root.after(300, self._ejecutar_filtro_panel)

    def _ejecutar_filtro_panel(self):
        # --- AQUÍ VA TODO EL CÓDIGO QUE ANTES TENÍAS EN filtrar_panel ---
        query = self.entry_buscar_panel.get().lower() if hasattr(self, 'entry_buscar_panel') else ""
        
        if hasattr(self, 'lista_usuarios') and self.lista_usuarios.winfo_exists():
            self.lista_usuarios.delete(*self.lista_usuarios.get_children())
            online_count = 0
            yo_contado = False
            
            for u in getattr(self, 'panel_usuarios_completos', []):
                if "[🟢 Online]" in u: online_count += 1
                nombre_limpio = u.replace("[Admin] ", "").replace(" [🟢 Online]", "").replace(" [🔴 Offline]", "")
                
                if hasattr(self, 'usuario_actual') and self.usuario_actual == nombre_limpio:
                    yo_contado = True
                    continue 
                        
                if query in nombre_limpio.lower() or query in u.lower(): 
                    etiqueta = ("admin_tag",) if "[Admin]" in u else ("normal_tag",)
                    self.lista_usuarios.insert("", tk.END, text=u, tags=etiqueta)
                    
            if not yo_contado and hasattr(self, 'usuario_actual') and self.usuario_actual:
                online_count += 1
                
            if hasattr(self, 'lbl_titulo_usuarios'):
                self.lbl_titulo_usuarios.config(text=f"Usuarios ({online_count} Online)")
                
        if hasattr(self, 'lista_grupos') and self.lista_grupos.winfo_exists():
            self.lista_grupos.delete(*self.lista_grupos.get_children())
            for g in getattr(self, 'panel_grupos_completos', []):
                if query in g.lower(): 
                    self.lista_grupos.insert("", tk.END, text=g)

    def filtrar_cuentas(self, event=None):
        query = self.entry_buscar_cuentas.get().lower() if hasattr(self, 'entry_buscar_cuentas') else ""
        if hasattr(self, 'tree_cuentas') and self.tree_cuentas.winfo_exists():
            self.tree_cuentas.delete(*self.tree_cuentas.get_children())
            for d in getattr(self, 'datos_cuentas_completos', []):
                if query in str(d[0]).lower() or query in str(d[1]).lower() or query in str(d[2]).lower():
                    self.tree_cuentas.insert("", tk.END, values=d)

    def filtrar_grupos(self, event=None):
        query = self.entry_buscar_grupos.get().lower() if hasattr(self, 'entry_buscar_grupos') else ""
        if hasattr(self, 'tree_grupos') and self.tree_grupos.winfo_exists():
            self.tree_grupos.delete(*self.tree_grupos.get_children())
            for d in getattr(self, 'datos_grupos_completos', []):
                if query in str(d[0]).lower():
                    estado = "🔒 Bloqueado" if d[1] else "🔓 Abierto"
                    miembros_str = f"{d[2]} usuarios" if len(d) > 2 else "0" 
                    self.tree_grupos.insert("", tk.END, values=(d[0], estado, miembros_str))

    def ordenar_por_columna(self, tree, col, reverse):
        l = [(tree.set(k, col), k) for k in tree.get_children('')]
        try:
            l.sort(key=lambda t: float(t[0].split()[0] if 'KB' in t[0] or 'MB' in t[0] else t[0]), reverse=reverse)
        except ValueError:
            l.sort(reverse=reverse)
        for index, (val, k) in enumerate(l):
            tree.move(k, '', index)
        tree.heading(col, command=lambda: self.ordenar_por_columna(tree, col, not reverse))

    def mostrar_mensaje(self, remitente, mensaje, reply_to=None):
        self.chat_area.config(state='normal')
        
        if reply_to:
            self.chat_area.insert(tk.END, f"  ↳ Respondiendo a: {reply_to[:50]}...\n", "reply_tag")
            self.chat_area.tag_config("reply_tag", foreground="#6c757d", font=("Arial", 9, "italic"))
            
        color = self.obtener_color_usuario(remitente)
        tag_user = f"color_{remitente}"
        self.chat_area.tag_config(tag_user, foreground=color, font=("Arial", 10, "bold"))
        
        usuario_limpio = remitente.split(" (")[0] 
        self.chat_area.insert(tk.END, f"[{usuario_limpio}] ", tag_user)
        self.chat_area.insert(tk.END, f"{mensaje}\n")
        
        self.chat_area.yview(tk.END)
        self.chat_area.config(state='disabled')

    def abrir_archivos_chat(self):
        destino = getattr(self, 'chat_destino_actual', None)
        if not destino:
            messagebox.showwarning("Atención", "Selecciona un chat primero.")
            return

        vent = tk.Toplevel(self.root)
        self.hacer_modal(vent) 
        vent.title(f"Archivos en {destino}")
        vent.geometry("650x300") 
        
        self.tree_archivos = ttk.Treeview(vent, columns=("ID", "Remitente", "Archivo", "Tamaño", "Fecha"), show="headings", selectmode="browse")
        self.tree_archivos.heading("ID", text="ID", command=lambda: self.ordenar_por_columna(self.tree_archivos, "ID", False))
        self.tree_archivos.heading("Remitente", text="Subido por", command=lambda: self.ordenar_por_columna(self.tree_archivos, "Remitente", False))
        self.tree_archivos.heading("Archivo", text="Nombre del Archivo", command=lambda: self.ordenar_por_columna(self.tree_archivos, "Archivo", False))
        self.tree_archivos.heading("Tamaño", text="Tamaño", command=lambda: self.ordenar_por_columna(self.tree_archivos, "Tamaño", False))
        self.tree_archivos.heading("Fecha", text="Fecha", command=lambda: self.ordenar_por_columna(self.tree_archivos, "Fecha", False))
        self.tree_archivos.pack(fill=tk.BOTH, expand=True, pady=5)
        
        self.cliente.send(json.dumps({"accion": "LISTAR_ARCHIVOS_CHAT", "contacto": destino}).encode('utf-8'))

        frame_btn = tk.Frame(vent)
        frame_btn.pack(fill=tk.X, pady=5)

        def descargar():
            sel = self.tree_archivos.selection()
            if not sel: return
            id_arch = self.tree_archivos.item(sel[0])['values'][0]
            self.cliente.send(json.dumps({"accion": "DESCARGAR_ARCHIVO", "id_archivo": id_arch}).encode('utf-8'))
            messagebox.showinfo("Descargando...", "Revisa tu carpeta local en unos segundos.")

        def abrir_carpeta():
            os.startfile(self.carpeta_descargas)
            
        def eliminar_archivo():
            sel = self.tree_archivos.selection()
            if not sel: return
            id_arch = self.tree_archivos.item(sel[0])['values'][0]
            if messagebox.askyesno("Confirmar", "¿Eliminar este archivo del servidor definitivamente?"):
                self.cliente.send(json.dumps({"accion": "ELIMINAR_ARCHIVO", "id_archivo": id_arch}).encode('utf-8'))
                self.root.after(500, lambda: self.cliente.send(json.dumps({"accion": "LISTAR_ARCHIVOS_CHAT", "contacto": destino}).encode('utf-8')))

        tk.Button(frame_btn, text="⬇️ Descargar", command=descargar, bg="#d4edda").pack(side=tk.LEFT, padx=5)
        
        es_grupo = getattr(self, 'es_grupo_actual', False)
        es_gestor = getattr(self, 'soy_gestor_actual', False)
        
        if not es_grupo or es_gestor:
            tk.Button(frame_btn, text="🗑️ Eliminar", command=eliminar_archivo, bg="#f8d7da").pack(side=tk.LEFT, padx=5)
            
        tk.Button(frame_btn, text="📁 Abrir Carpeta", command=abrir_carpeta, bg="#e2e3e5").pack(side=tk.RIGHT, padx=5)

    def obtener_color_usuario(self, usuario):
        if usuario == "Yo": return "#0056b3"
        colores = ["#e6194b", "#3cb44b", "#e58e00", "#4363d8", "#f58231", 
                   "#911eb4", "#008080", "#f032e6", "#bcf60c", "#fabebe", 
                   "#000075", "#e6beff", "#9a6324", "#fffac8", "#800000"]
                   
        usuario_limpio = usuario.split(" (")[0].replace("[Gestor]-", "")
        indice = sum(ord(c) for c in usuario_limpio) % len(colores)
        return colores[indice]

    def mostrar_menu_contextual(self, event):
        index = self.chat_area.index(f"@{event.x},{event.y}")
        linea = self.chat_area.get(f"{index} linestart", f"{index} lineend")
        
        if "↳ Respondiendo" in linea: return 
        
        if linea.strip():
            self.linea_seleccionada = linea.strip()
            self.menu_contextual.delete(0, tk.END)
            self.menu_contextual.add_command(label="Responder a este mensaje", command=self.fijar_respuesta)
            
            match = re.search(r"\[ARCHIVO:(\d+)\]", linea)
            if match:
                id_archivo = match.group(1)
                def descargar_desde_chat():
                    self.cliente.send(json.dumps({"accion": "DESCARGAR_ARCHIVO", "id_archivo": int(id_archivo)}).encode('utf-8'))
                    messagebox.showinfo("Descargando...", "El archivo se está descargando en tu carpeta local.")
                self.menu_contextual.add_separator()
                self.menu_contextual.add_command(label="⬇️ Descargar este archivo", command=descargar_desde_chat)

            self.menu_contextual.tk_popup(event.x_root, event.y_root)

    def fijar_respuesta(self):
        self.mensaje_a_responder = self.linea_seleccionada
        texto_corto = self.mensaje_a_responder[:40] + "..." if len(self.mensaje_a_responder) > 40 else self.mensaje_a_responder
        self.lbl_reply.config(text=f"  ↳ Respondiendo a: {texto_corto}")
        self.lbl_reply.pack(before=self.chat_area, fill=tk.X)

    def abrir_crear_usuario(self):
        ventana_alta = tk.Toplevel(self.root)
        self.hacer_modal(ventana_alta) 
        ventana_alta.title("Crear Usuario")
        ventana_alta.geometry("250x200")

        tk.Label(ventana_alta, text="Nombre Completo:").pack()
        entry_nombre = tk.Entry(ventana_alta)
        entry_nombre.pack()

        tk.Label(ventana_alta, text="Usuario:").pack()
        entry_user = tk.Entry(ventana_alta)
        entry_user.pack()

        tk.Label(ventana_alta, text="Contraseña:").pack()
        entry_pass = tk.Entry(ventana_alta, show="*")
        entry_pass.pack()

        def guardar():
            peticion = {
                "accion": "CREAR_USUARIO",
                "nombre": entry_nombre.get(),
                "nuevo_usuario": entry_user.get(),
                "password": self.hashear_password(entry_pass.get()), # <-- NUEVO
                "perfil_id": 2
            }
            self.cliente.send(json.dumps(peticion).encode('utf-8'))
            ventana_alta.destroy()
            
            if hasattr(self, 'tree_cuentas') and self.tree_cuentas.winfo_exists():
                self.root.after(500, lambda: self.cliente.send(json.dumps({"accion": "LISTAR_CUENTAS"}).encode('utf-8')))
            self.root.after(500, self.pedir_panel_lateral) 

        tk.Button(ventana_alta, text="Guardar", command=guardar).pack(pady=10)

    # --- NUEVA AUDITORÍA CON FILTROS Y CSV ---
    def solicitar_auditoria(self):
        if hasattr(self, 'vent_auditoria') and self.vent_auditoria.winfo_exists():
            self.vent_auditoria.lift()
            return
            
        peticion = {"accion": "CONSULTAR_AUDITORIA"}
        self.cliente.send(json.dumps(peticion).encode('utf-8'))

    def mostrar_ventana_auditoria(self, datos):
        self.vent_auditoria = tk.Toplevel(self.root)
        self.hacer_modal(self.vent_auditoria) 
        self.vent_auditoria.title("Auditoría del Sistema")
        self.vent_auditoria.geometry("900x500")

        frame_filtros = tk.Frame(self.vent_auditoria)
        frame_filtros.pack(fill=tk.X, padx=10, pady=5)
        
        tk.Label(frame_filtros, text="Fecha:").grid(row=0, column=0, padx=2)
        e_fecha = tk.Entry(frame_filtros, width=12)
        e_fecha.grid(row=0, column=1, padx=2)
        
        tk.Label(frame_filtros, text="IP:").grid(row=0, column=2, padx=2)
        e_ip = tk.Entry(frame_filtros, width=12)
        e_ip.grid(row=0, column=3, padx=2)
        
        tk.Label(frame_filtros, text="Usuario:").grid(row=0, column=4, padx=2)
        e_usr = tk.Entry(frame_filtros, width=12)
        e_usr.grid(row=0, column=5, padx=2)
        
        tk.Label(frame_filtros, text="Acción:").grid(row=0, column=6, padx=2)
        e_acc = tk.Entry(frame_filtros, width=18)
        e_acc.grid(row=0, column=7, padx=2)

        columnas = ("Fecha", "IP", "Usuario", "Acción")
        tree = ttk.Treeview(self.vent_auditoria, columns=columnas, show="headings")
        for col in columnas:
            tree.heading(col, text=col, command=lambda c=col: self.ordenar_por_columna(tree, c, False))
            tree.column(col, width=120 if col != "Acción" else 400)
        tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)

        def aplicar_filtros(*args):
            f_f = e_fecha.get().lower()
            f_i = e_ip.get().lower()
            f_u = e_usr.get().lower()
            f_a = e_acc.get().lower()
            
            tree.delete(*tree.get_children())
            for fila in datos: 
                if (f_f in str(fila[0]).lower() and 
                    f_i in str(fila[1]).lower() and 
                    f_u in str(fila[2]).lower() and 
                    f_a in str(fila[3]).lower()):
                    tree.insert("", tk.END, values=fila)
                    
        e_fecha.bind("<KeyRelease>", aplicar_filtros)
        e_ip.bind("<KeyRelease>", aplicar_filtros)
        e_usr.bind("<KeyRelease>", aplicar_filtros)
        e_acc.bind("<KeyRelease>", aplicar_filtros)
        
        aplicar_filtros() 
        
        def exportar_csv():
            ruta = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("Archivos CSV", "*.csv")], title="Guardar Auditoría")
            if ruta:
                try:
                    with open(ruta, mode='w', newline='', encoding='utf-8-sig') as f:
                        writer = csv.writer(f)
                        writer.writerow(columnas) 
                        for item in tree.get_children():
                            writer.writerow(tree.item(item)['values'])
                    messagebox.showinfo("Éxito", f"Registros guardados correctamente en:\n{ruta}")
                except Exception as e:
                    messagebox.showerror("Error", f"No se pudo guardar el archivo: {e}")

        tk.Button(self.vent_auditoria, text="📥 Descargar Registros Visibles (CSV)", command=exportar_csv, bg="#d4edda").pack(pady=10)

    def impersonar_usuario(self):
        target = simpledialog.askstring("Impersonar", "Ingrese el nombre de usuario que desea controlar:")
        if target:
            peticion = {"accion": "IMPERSONAR", "usuario_objetivo": target}
            self.cliente.send(json.dumps(peticion).encode('utf-8'))

    def dejar_impersonar(self):
        if messagebox.askyesno("Confirmar", "¿Deseas terminar la impersonación y volver a tu cuenta de Administrador?"):
            peticion = {"accion": "DEJAR_IMPERSONAR"}
            self.cliente.send(json.dumps(peticion).encode('utf-8'))
            
            self.chat_destino_actual = None
            self.lbl_chat_actual.config(text="Selecciona un chat del panel lateral")
            self.chat_area.config(state='normal')
            self.chat_area.delete(1.0, tk.END) 
            self.chat_area.config(state='disabled')
            self.pedir_panel_lateral() 

    def ver_miembros_chat(self):
        destino = getattr(self, 'chat_destino_actual', None)
        if not destino or not destino.startswith("#"): return
        self.cliente.send(json.dumps({"accion": "LISTAR_MIEMBROS_CHAT", "grupo": destino[1:]}).encode('utf-8'))

    def abrir_cambiar_password(self):
        ventana_pass = tk.Toplevel(self.root)
        self.hacer_modal(ventana_pass) 
        ventana_pass.title("Cambiar Contraseña")
        ventana_pass.geometry("250x250")

        tk.Label(ventana_pass, text="Contraseña Actual:").pack(pady=5)
        entry_actual = tk.Entry(ventana_pass, show="*")
        entry_actual.pack()

        tk.Label(ventana_pass, text="Nueva Contraseña:").pack(pady=5)
        entry_nueva = tk.Entry(ventana_pass, show="*")
        entry_nueva.pack()
        
        tk.Label(ventana_pass, text="Confirmar Nueva:").pack(pady=5)
        entry_conf = tk.Entry(ventana_pass, show="*")
        entry_conf.pack()

        def guardar_pass():
            actual = entry_actual.get()
            nueva = entry_nueva.get()
            conf = entry_conf.get()
            
            if not actual or not nueva or not conf:
                messagebox.showwarning("Atención", "Todos los campos son obligatorios.")
                return
            if nueva != conf:
                messagebox.showerror("Error", "Las contraseñas nuevas no coinciden.")
                return
                
            peticion = {
                "accion": "CAMBIAR_PASSWORD",
                "password_actual": self.hashear_password(actual), # <-- NUEVO
                "password_nueva": self.hashear_password(nueva)    # <-- NUEVO
            }
            self.cliente.send(json.dumps(peticion).encode('utf-8'))
            ventana_pass.destroy()

        tk.Button(ventana_pass, text="Actualizar", command=guardar_pass, bg="#d4edda").pack(pady=15)

    def al_cerrar(self):
        if messagebox.askyesno("Confirmar Salida", "¿Estás seguro que deseas cerrar la aplicación?"):
            try:
                self.cliente.send(json.dumps({"accion": "LOGOUT"}).encode('utf-8'))
                self.cliente.close()
            except:
                pass
            
            self.root.destroy()
            os._exit(0)

if __name__ == "__main__":
    root = tk.Tk()
    app = AppChat(root)
    root.mainloop()